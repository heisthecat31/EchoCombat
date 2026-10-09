// CombatBots: brains for the bots (-bots N) on Echo Combat servers.
//
// Bots are CR15NetBotCS components. Everything a bot does is driven by its record in
// that component system, and the engine's own "methods" (MoveToPoint, HoldFire,
// SetLookDir, ...) are plain writes into it (Quest build libr15.so, via ReVault; the
// PC build uses the same layout, see docs/bots_phase2.md):
//
//   record = *(cs + 0x100) + i * 0x1B0     i = 0 .. *(u16 *)(cs + 0xFC) - 1 (enabled bots)
//   +0x08 u32  user id                     (UserId)
//   +0x60 u32  moving                      (MoveToPoint / StopMovement)
//   +0x74 f32x3 target point               (MoveToPoint)
//   +0xB4 f32  turn rate                   (SetLookDir: 0.2)
//   +0xB8 f32x4 look rotation (x y z w)    (SetLookDir)
//   +0xC8 u32  fire held                   (HoldFire / ReleaseFire; acts when cs+0x168 != 0)
//   +0x12C u32 boost                       (BoostToTransform / StopMovement)
//
// The plugin hooks CR15NetBotCS::Update (+0xd625c0, the per-frame update on the game
// thread, `this` = the bot system) and, with brain=1 in CombatBots.ini, writes each
// bot's move target, look rotation and trigger before the engine's update runs.
//
// World state comes from the server's own session API (the HTTP listener it binds on
// 127.0.0.1, "/session"): every player's team, head position and facing, polled on a
// thread of its own.
//
// Phase 1 of the plugin (brain=0, the default) only LOGS: each bot's record and the
// session API's players, so the bot <-> player mapping and the coordinate conventions
// can be checked in CombatBots.log before the brain drives anything. brain=1 turns on
// the first behaviour: go for the nearest enemy, aim at them, fire within range.
//
// Server only ("-server"); on a prologue mismatch nothing is hooked.

#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#include <iphlpapi.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <string>
#include <vector>
#include <array>
#include <queue>
#include "detours.h"

#pragma comment(lib, "ws2_32.lib")
#pragma comment(lib, "iphlpapi.lib")

namespace {

constexpr uintptr_t BOT_UPDATE_RVA = 0xd625c0;
constexpr uint8_t BOT_UPDATE_BYTES[] = { 0x40, 0x55, 0x56, 0x41, 0x54, 0x48, 0x8d, 0xac, 0x24, 0x50, 0xfe, 0xff, 0xff };

// CR15NetDamageableCS::NetworkRespawn(SMsg<SR15NetDamageablePlayerRespawn>) (Quest 0x2138eb4).
constexpr uintptr_t RESPAWN_RVA = 0xd14080;
constexpr uint8_t RESPAWN_BYTES[] = { 0x4c, 0x8b, 0xdc, 0x55, 0x41, 0x55, 0x41, 0x56, 0x48, 0x8b, 0xec, 0x48, 0x83, 0xec, 0x60, 0x48 };

constexpr size_t RECORD = 0x1b0;
constexpr size_t R_ACTOR = 0x0c;                  // the bot's actor (= its damageable record +08h)
constexpr size_t DAMAGEABLE = 0xb8;               // damageable record: +02h flags (4 = dead), +08h actor,
constexpr size_t D_FLAGS = 0x02, D_ACTOR = 0x08,  // +0Ch player slot (index | generation << 16),
                 D_SLOT = 0x0c, D_SHIELD = 0x1c, D_HEALTH = 0x20;   // +1Ch shield, +20h health
constexpr size_t R_USER = 0x08, R_MOVING = 0x60, R_TARGET = 0x74, R_TURN = 0xb4, R_LOOK = 0xb8,
                 R_FIRE = 0xc8, R_BOOST = 0x12c;

char g_log_path[MAX_PATH], g_ini_path[MAX_PATH];
volatile LONG g_logged = 0;

void Log(const char *fmt, ...) {
    if (InterlockedIncrement(&g_logged) > 20000) return;
    FILE *f = nullptr;
    if (fopen_s(&f, g_log_path, "a") != 0 || !f) return;
    SYSTEMTIME t;
    GetLocalTime(&t);
    fprintf(f, "[%02d:%02d:%02d.%03d] ", t.wHour, t.wMinute, t.wSecond, t.wMilliseconds);
    va_list args;
    va_start(args, fmt);
    vfprintf(f, fmt, args);
    va_end(args);
    fputc('\n', f);
    fclose(f);
}

// --- settings (CombatBots.ini) --------------------------------------------------------
struct Settings {
    bool brain = false;
    float forward[3] = { 0, 0, 1 };      // the look rotation's local forward axis
    float keep_distance = 8.0f;          // how close a bot closes in on its target
    float fire_range = 35.0f;
    float turn_rate = 0.3f;
    float aim_up = 0.15f;                // aim this far above the target's head position
    float bullet_speed = 80.0f;          // for leading a moving target (0: no lead)
    unsigned respawn_ms = 6000;          // a dead bot respawns this long after dying (0: never)
    float war_room_radius = 30.0f;       // within this of an orb: in the war room
    float orb_reach = 1.2f;              // this close to an orb takes it
    float node_reach = 1.5f;             // this close to a route node moves on to the next
    float link_distance = 1.75f;         // route nodes this close join different routes
    unsigned log_every_ms = 5000;
} g_cfg;

float IniFloat(const char *sec, const char *key, float def) {
    char buf[64], d[32];
    sprintf_s(d, "%g", def);
    GetPrivateProfileStringA(sec, key, d, buf, sizeof(buf), g_ini_path);
    return (float)atof(buf);
}

void ReadIni() {
    g_cfg.brain = GetPrivateProfileIntA("bots", "brain", 0, g_ini_path) != 0;
    char axis[16];
    GetPrivateProfileStringA("bots", "forward", "+z", axis, sizeof(axis), g_ini_path);
    int i = axis[1] == 'x' || axis[1] == 'X' ? 0 : axis[1] == 'y' || axis[1] == 'Y' ? 1 : 2;
    g_cfg.forward[0] = g_cfg.forward[1] = g_cfg.forward[2] = 0;
    g_cfg.forward[i] = axis[0] == '-' ? -1.0f : 1.0f;
    g_cfg.keep_distance = IniFloat("bots", "keep_distance", 8.0f);
    g_cfg.fire_range = IniFloat("bots", "fire_range", 35.0f);
    g_cfg.turn_rate = IniFloat("bots", "turn_rate", 0.3f);
    g_cfg.aim_up = IniFloat("bots", "aim_up", 0.15f);
    g_cfg.bullet_speed = IniFloat("bots", "bullet_speed", 80.0f);
    g_cfg.respawn_ms = GetPrivateProfileIntA("bots", "respawn_ms", 6000, g_ini_path);
    g_cfg.war_room_radius = IniFloat("bots", "war_room_radius", 30.0f);
    g_cfg.orb_reach = IniFloat("bots", "orb_reach", 1.2f);
    g_cfg.node_reach = IniFloat("bots", "node_reach", 1.5f);
    g_cfg.link_distance = IniFloat("bots", "link_distance", 1.75f);
    g_cfg.log_every_ms = GetPrivateProfileIntA("bots", "log_every_ms", 5000, g_ini_path);
    Log("settings: brain=%d forward=%s keep_distance=%.1f fire_range=%.1f turn_rate=%.2f aim_up=%.2f bullet_speed=%.0f",
        g_cfg.brain, axis, g_cfg.keep_distance, g_cfg.fire_range, g_cfg.turn_rate, g_cfg.aim_up, g_cfg.bullet_speed);
}

// --- a small JSON reader (enough for the session API) ---------------------------------
struct Json {
    enum Kind { Null, Bool, Num, Str, Arr, Obj } kind = Null;
    double num = 0;
    bool b = false;
    std::string str;
    std::vector<Json> items;                         // Arr, or Obj values
    std::vector<std::string> keys;                   // Obj keys
    const Json *get(const char *k) const {
        for (size_t i = 0; i < keys.size(); ++i) if (keys[i] == k) return &items[i];
        return nullptr;
    }
};

struct Parser {
    const char *p, *end;
    void ws() { while (p < end && (*p == ' ' || *p == '\n' || *p == '\r' || *p == '\t')) ++p; }
    bool str(std::string &out) {
        if (p >= end || *p != '"') return false;
        ++p;
        while (p < end && *p != '"') {
            if (*p == '\\' && p + 1 < end) { ++p; out += *p == 'n' ? '\n' : *p; ++p; }
            else out += *p++;
        }
        if (p >= end) return false;
        ++p;
        return true;
    }
    bool value(Json &j, int depth = 0) {
        if (depth > 32) return false;
        ws();
        if (p >= end) return false;
        if (*p == '{') {
            j.kind = Json::Obj; ++p; ws();
            if (p < end && *p == '}') { ++p; return true; }
            for (;;) {
                ws();
                std::string k;
                if (!str(k)) return false;
                ws();
                if (p >= end || *p != ':') return false;
                ++p;
                Json v;
                if (!value(v, depth + 1)) return false;
                j.keys.push_back(k);
                j.items.push_back(std::move(v));
                ws();
                if (p < end && *p == ',') { ++p; continue; }
                if (p < end && *p == '}') { ++p; return true; }
                return false;
            }
        }
        if (*p == '[') {
            j.kind = Json::Arr; ++p; ws();
            if (p < end && *p == ']') { ++p; return true; }
            for (;;) {
                Json v;
                if (!value(v, depth + 1)) return false;
                j.items.push_back(std::move(v));
                ws();
                if (p < end && *p == ',') { ++p; continue; }
                if (p < end && *p == ']') { ++p; return true; }
                return false;
            }
        }
        if (*p == '"') { j.kind = Json::Str; return str(j.str); }
        if (!strncmp(p, "true", 4)) { j.kind = Json::Bool; j.b = true; p += 4; return true; }
        if (!strncmp(p, "false", 5)) { j.kind = Json::Bool; p += 5; return true; }
        if (!strncmp(p, "null", 4)) { p += 4; return true; }
        char *e = nullptr;
        j.num = strtod(p, &e);
        if (e == p) return false;
        j.kind = Json::Num;
        p = e;
        return true;
    }
};

// --- the session API -------------------------------------------------------------------
struct Player {
    std::string name, team;
    uint64_t userid = 0;
    int playerid = -1;
    float pos[3] = {}, fwd[3] = {}, hand[3] = {}, vel[3] = {};
    bool has_pos = false, has_hand = false;
};

SRWLOCK g_world_lock = SRWLOCK_INIT;
std::vector<Player> g_players;
std::string g_last_json;
std::string g_map;                               // map_name from the session API
volatile LONG g_orbs_live = 0;                   // the round has started: war room orbs work
ULONGLONG g_world_at = 0;
uint16_t g_api_port = 0;

bool HttpGet(uint16_t port, const char *path, std::string &body) {
    SOCKET s = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    if (s == INVALID_SOCKET) return false;
    DWORD to = 500;
    setsockopt(s, SOL_SOCKET, SO_RCVTIMEO, (const char *)&to, sizeof(to));
    setsockopt(s, SOL_SOCKET, SO_SNDTIMEO, (const char *)&to, sizeof(to));
    sockaddr_in a = {};
    a.sin_family = AF_INET;
    a.sin_port = htons(port);
    a.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    bool ok = false;
    if (connect(s, (sockaddr *)&a, sizeof(a)) == 0) {
        char req[256];
        int n = sprintf_s(req, "GET %s HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n", path);
        if (send(s, req, n, 0) == n) {
            std::string all;
            char buf[16384];
            int got;
            while ((got = recv(s, buf, sizeof(buf), 0)) > 0) all.append(buf, got);
            size_t at = all.find("\r\n\r\n");
            bool status_ok = all.compare(0, 12, "HTTP/1.1 200") == 0 || all.compare(0, 12, "HTTP/1.0 200") == 0;
            if (at != std::string::npos && status_ok) {
                body = all.substr(at + 4);
                ok = true;
            }
        }
    }
    closesocket(s);
    return ok;
}

// The TCP ports this process listens on: one of them is the session API.
std::vector<uint16_t> OwnListeningPorts() {
    std::vector<uint16_t> ports;
    DWORD size = 0;
    GetExtendedTcpTable(nullptr, &size, FALSE, AF_INET, TCP_TABLE_OWNER_PID_LISTENER, 0);
    std::vector<uint8_t> buf(size + 1024);
    size = (DWORD)buf.size();
    if (GetExtendedTcpTable(buf.data(), &size, FALSE, AF_INET, TCP_TABLE_OWNER_PID_LISTENER, 0) != NO_ERROR) return ports;
    auto *t = (MIB_TCPTABLE_OWNER_PID *)buf.data();
    DWORD pid = GetCurrentProcessId();
    for (DWORD i = 0; i < t->dwNumEntries; ++i)
        if (t->table[i].dwOwningPid == pid) ports.push_back(ntohs((uint16_t)t->table[i].dwLocalPort));
    return ports;
}

bool Vec3(const Json *j, float *out) {
    if (!j || j->kind != Json::Arr || j->items.size() < 3) return false;
    for (int i = 0; i < 3; ++i) out[i] = (float)j->items[i].num;
    return true;
}

void ParseSession(const std::string &body) {
    Json root;
    Parser ps{ body.data(), body.data() + body.size() };
    if (!ps.value(root) || root.kind != Json::Obj) return;
    std::vector<Player> players;
    if (const Json *teams = root.get("teams"))
        for (const Json &team : teams->items) {
            const Json *tname = team.get("team");
            if (const Json *list = team.get("players"))
                for (const Json &pl : list->items) {
                    Player p;
                    if (const Json *n = pl.get("name")) p.name = n->str;
                    if (tname) p.team = tname->str;
                    if (const Json *u = pl.get("userid")) p.userid = (uint64_t)u->num;
                    if (const Json *pid = pl.get("playerid")) p.playerid = (int)pid->num;
                    const Json *head = pl.get("head");
                    const Json *body_ = pl.get("body");
                    if (head) {
                        p.has_pos = Vec3(head->get("position"), p.pos);
                        Vec3(head->get("forward"), p.fwd);
                    }
                    if (!p.has_pos && body_) p.has_pos = Vec3(body_->get("position"), p.pos);
                    if (!p.has_pos) p.has_pos = Vec3(pl.get("position"), p.pos);
                    if (const Json *rh = pl.get("rhand")) p.has_hand = Vec3(rh->get("pos"), p.hand);
                    Vec3(pl.get("velocity"), p.vel);
                    players.push_back(p);
                }
        }
    std::string map;
    if (const Json *m = root.get("map_name")) map = m->str;
    AcquireSRWLockExclusive(&g_world_lock);
    g_players.swap(players);
    g_map = map;
    g_last_json = body.substr(0, 6000);
    g_world_at = GetTickCount64();
    ReleaseSRWLockExclusive(&g_world_lock);
}

// --- round state, from this server's own log (_local/r14logs/*_<pid>.log) -------------
// The war room orbs work from "OnRoundStartCB" on; the team room / pre-match / round
// countdown states come before it.
struct LogTail {
    std::string path;
    LONGLONG offset = 0;
    std::string partial;
    ULONGLONG next_find = 0;
} g_tail;

void FindOwnLog() {
    char exe[MAX_PATH];
    GetModuleFileNameA(nullptr, exe, MAX_PATH);
    std::string dir = exe;
    for (int up = 0; up < 3; ++up) dir = dir.substr(0, dir.find_last_of('\\'));   // ...\bin\win10\echovr.exe -> install
    char pattern[MAX_PATH];
    sprintf_s(pattern, "%s\\_local\\r14logs\\*_%lu.log", dir.c_str(), GetCurrentProcessId());
    WIN32_FIND_DATAA fd;
    HANDLE h = FindFirstFileA(pattern, &fd);
    if (h == INVALID_HANDLE_VALUE) return;
    FindClose(h);
    g_tail.path = dir + "\\_local\\r14logs\\" + fd.cFileName;
    Log("watching %s for the round state", g_tail.path.c_str());
}

void ReadRoundState() {
    if (g_tail.path.empty()) {
        if (GetTickCount64() < g_tail.next_find) return;
        g_tail.next_find = GetTickCount64() + 5000;
        FindOwnLog();
        if (g_tail.path.empty()) return;
    }
    HANDLE f = CreateFileA(g_tail.path.c_str(), GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
                           nullptr, OPEN_EXISTING, 0, nullptr);
    if (f == INVALID_HANDLE_VALUE) return;
    LARGE_INTEGER size;
    if (GetFileSizeEx(f, &size) && size.QuadPart > g_tail.offset) {
        LARGE_INTEGER at;
        at.QuadPart = g_tail.offset;
        SetFilePointerEx(f, at, nullptr, FILE_BEGIN);
        std::string chunk((size_t)min(size.QuadPart - g_tail.offset, (LONGLONG)(1 << 20)), '\0');
        DWORD got = 0;
        if (ReadFile(f, &chunk[0], (DWORD)chunk.size(), &got, nullptr)) {
            g_tail.offset += got;
            chunk.resize(got);
            g_tail.partial += chunk;
            size_t nl;
            while ((nl = g_tail.partial.find('\n')) != std::string::npos) {
                std::string line = g_tail.partial.substr(0, nl);
                g_tail.partial.erase(0, nl + 1);
                LONG live = -1;
                if (line.find("OnRoundStartCB") != std::string::npos) live = 1;
                else if (line.find("enter state 'round_start'") != std::string::npos ||
                         line.find("enter state 'team_room_wait_enter'") != std::string::npos ||
                         line.find("enter state 'pre_match") != std::string::npos)
                    live = 0;
                if (live >= 0 && InterlockedExchange(&g_orbs_live, live) != live)
                    Log("round state: orbs %s", live ? "LIVE" : "off (team room / countdown)");
            }
        }
    }
    CloseHandle(f);
}

DWORD WINAPI Poller(LPVOID) {
    WSADATA wsa;
    WSAStartup(MAKEWORD(2, 2), &wsa);
    ULONGLONG next_scan = 0;
    for (;;) {
        Sleep(100);
        ReadRoundState();
        std::string body;
        if (g_api_port && HttpGet(g_api_port, "/session", body)) { ParseSession(body); continue; }
        if (GetTickCount64() < next_scan) continue;
        next_scan = GetTickCount64() + 5000;
        for (uint16_t port : OwnListeningPorts())
            if (HttpGet(port, "/session", body) && !body.empty() && body[0] == '{') {
                if (g_api_port != port) Log("session API found on 127.0.0.1:%u", port);
                g_api_port = port;
                ParseSession(body);
                break;
            }
    }
}

// --- the brain -----------------------------------------------------------------------
void Normalize(float *v) {
    float l = sqrtf(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]);
    if (l > 1e-6f) { v[0] /= l; v[1] /= l; v[2] /= l; }
}

// The rotation taking unit vector a onto unit vector b, as (x, y, z, w).
void FromTo(const float *a, const float *b, float *q) {
    float d = a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
    if (d < -0.9999f) {                                 // opposite: half a turn round y
        q[0] = 0; q[1] = 1; q[2] = 0; q[3] = 0;
        return;
    }
    q[0] = a[1] * b[2] - a[2] * b[1];
    q[1] = a[2] * b[0] - a[0] * b[2];
    q[2] = a[0] * b[1] - a[1] * b[0];
    q[3] = 1 + d;
    float l = sqrtf(q[0] * q[0] + q[1] * q[1] + q[2] * q[2] + q[3] * q[3]);
    for (int i = 0; i < 4; ++i) q[i] /= l;
}

// A look rotation with no roll: yaw round y, then pitch round x (forward +z).
void YawPitch(const float *dir, float *q) {
    float yaw = atan2f(dir[0], dir[2]);
    float pitch = -asinf(fmaxf(-1.0f, fminf(1.0f, dir[1])));
    float sy = sinf(yaw * 0.5f), cy = cosf(yaw * 0.5f), sp = sinf(pitch * 0.5f), cp = cosf(pitch * 0.5f);
    q[0] = cy * sp; q[1] = sy * cp; q[2] = -sy * sp; q[3] = cy * cp;
}

// --- life: dead bots stop, then respawn through the game's own respawn handler ----------
uint8_t *DamageableCS();
using respawn_fn = void(__fastcall *)(uint8_t *dcs, void *msg);
respawn_fn g_respawn = nullptr;
uint8_t *g_player_dcs = nullptr;                 // the damageable system of the bots' game space
void *g_player_space = nullptr;
ULONGLONG g_dead_since[64];
ULONGLONG g_respawn_tried[64];

// The players' damageable system: the one PowerBoost saw that shares the bots' game space.
uint8_t *PlayerDamageables(uint8_t *cs) {
    void *space = *(void **)(cs + 0x80);
    if (g_player_space != space) { g_player_dcs = nullptr; g_player_space = space; }
    if (!g_player_dcs)
        if (uint8_t *d = DamageableCS())
            if (*(void **)(d + 0x80) == space) {
                g_player_dcs = d;
                Log("players' damageable system %p (game space %p)", d, space);
            }
    return g_player_dcs;
}

uint8_t *DamageableOf(uint8_t *dcs, uint32_t actor) {
    uint8_t *recs = *(uint8_t **)(dcs + 0x100);
    uint16_t n = *(uint16_t *)(dcs + 0xfc);
    for (uint16_t i = 0; recs && i < n && i < 64; ++i)
        if (*(uint32_t *)(recs + i * DAMAGEABLE + D_ACTOR) == actor) return recs + i * DAMAGEABLE;
    return nullptr;
}

bool IsDead(const uint8_t *d) { return (d[D_FLAGS] & 4) != 0; }

// Send the game's respawn message for this damageable, as a player's client would.
void Respawn(uint8_t *dcs, const uint8_t *d, unsigned bot) {
    uint32_t slot = *(const uint32_t *)(d + D_SLOT);
    uint8_t *game = *(uint8_t **)(dcs + 0xb8);
    uint16_t idx = (uint16_t)slot, gen = (uint16_t)(slot >> 16);
    // NetworkRespawn's own checks: slot < 16, its generation current, the slot in use.
    if (!g_respawn || !game || idx >= 16 || gen == 0xffff ||
        *(uint16_t *)(game + 0x13a + idx * 4) != gen || *(uint16_t *)(game + 0x138 + idx * 4) == 0xffff) {
        Log("bot %u: can't respawn (slot %08x, game %p)", bot, slot, game);
        return;
    }
    alignas(16) uint8_t payload[32] = {};
    *(uint64_t *)payload = *(uint64_t *)(*(uint8_t **)(dcs + 0x80) + 0x58);
    *(uint32_t *)(payload + 8) = slot;
    alignas(16) uint8_t msg[64] = {};
    *(void **)(msg + 0x10) = payload;
    g_respawn(dcs, msg);
    Log("bot %u: respawned (slot %08x)", bot, slot);
}

// --- nav: war room orbs and walkable routes (CombatBots_<map>.json, tools/record_nav.py) --
// Bots can't see walls: MoveToPoint goes in a straight line through anything. So a bot
// only walks along routes a player has walked, and only leaves the war room by an orb.
struct Orb {
    std::string team;
    float at[3], to[3];                          // where the orb is, where it lands
};
struct Nav {
    std::string map;
    std::vector<Orb> orbs;
    std::vector<std::array<float, 3>> nodes;
    std::vector<std::vector<int>> links;
} g_nav;

float Dist(const float *a, const float *b) {
    float d[3] = { a[0] - b[0], a[1] - b[1], a[2] - b[2] };
    return sqrtf(d[0] * d[0] + d[1] * d[1] + d[2] * d[2]);
}
float FlatDist(const float *a, const float *b) {
    float x = a[0] - b[0], z = a[2] - b[2];
    return sqrtf(x * x + z * z);
}
float FlatLen(const float *a) { return sqrtf(a[0] * a[0] + a[2] * a[2]); }

void Link(int a, int b) {
    if (a == b) return;
    for (int x : g_nav.links[a]) if (x == b) return;
    g_nav.links[a].push_back(b);
    g_nav.links[b].push_back(a);
}

void LoadNav(const std::string &map) {
    g_nav = Nav();
    g_nav.map = map;
    std::string path = g_ini_path;
    path = path.substr(0, path.size() - 4) + "_" + map + ".json";     // CombatBots.ini -> CombatBots_<map>.json
    FILE *f = nullptr;
    if (fopen_s(&f, path.c_str(), "rb") != 0 || !f) {
        Log("no nav for %s (%s): bots stay in the war room", map.c_str(), path.c_str());
        return;
    }
    std::string text;
    char buf[65536];
    size_t got;
    while ((got = fread(buf, 1, sizeof(buf), f)) > 0) text.append(buf, got);
    fclose(f);
    Parser ps{ text.data(), text.data() + text.size() };
    Json root;
    if (!ps.value(root) || root.kind != Json::Obj) { Log("nav %s: bad JSON", path.c_str()); return; }
    if (const Json *orbs = root.get("orbs"))
        for (const Json &o : orbs->items) {
            Orb orb;
            if (const Json *t = o.get("team")) orb.team = t->str;
            if (!Vec3(o.get("orb"), orb.at) || !Vec3(o.get("to"), orb.to)) continue;
            // an orb takes you from the war room in towards the map; a death goes the other way
            if (FlatLen(orb.at) < FlatLen(orb.to) + 30.0f) continue;
            g_nav.orbs.push_back(orb);
        }
    if (const Json *routes = root.get("routes"))
        for (const Json &r : routes->items) {
            int prev = -1;
            for (const Json &pt : r.items) {
                std::array<float, 3> p;
                if (!Vec3(&pt, p.data())) continue;
                g_nav.nodes.push_back(p);
                g_nav.links.emplace_back();
                int at = (int)g_nav.nodes.size() - 1;
                if (prev >= 0) Link(prev, at);
                prev = at;
            }
        }
    // routes that pass close by each other join up
    for (size_t a = 0; a < g_nav.nodes.size(); ++a)
        for (size_t b = a + 1; b < g_nav.nodes.size(); ++b)
            if (Dist(g_nav.nodes[a].data(), g_nav.nodes[b].data()) < g_cfg.link_distance) Link((int)a, (int)b);
    Log("nav %s: %zu orb(s), %zu route node(s)", map.c_str(), g_nav.orbs.size(), g_nav.nodes.size());
    for (const Orb &o : g_nav.orbs)
        Log("  orb %s: %.1f %.1f %.1f -> %.1f %.1f %.1f", o.team.c_str(), o.at[0], o.at[1], o.at[2], o.to[0], o.to[1], o.to[2]);
}

int NearestNode(const float *p) {
    int best = -1;
    float bd = 1e9f;
    for (size_t i = 0; i < g_nav.nodes.size(); ++i) {
        float d = Dist(p, g_nav.nodes[i].data());
        if (d < bd) { bd = d; best = (int)i; }
    }
    return best;
}

// A* over the route graph.
bool FindPath(int from, int to, std::vector<int> &out) {
    out.clear();
    if (from < 0 || to < 0) return false;
    size_t n = g_nav.nodes.size();
    std::vector<float> cost(n, 1e30f);
    std::vector<int> came(n, -1);
    using Item = std::pair<float, int>;
    std::priority_queue<Item, std::vector<Item>, std::greater<Item>> open;
    cost[from] = 0;
    open.push({ Dist(g_nav.nodes[from].data(), g_nav.nodes[to].data()), from });
    while (!open.empty()) {
        int at = open.top().second;
        open.pop();
        if (at == to) break;
        for (int nb : g_nav.links[at]) {
            float c = cost[at] + Dist(g_nav.nodes[at].data(), g_nav.nodes[nb].data());
            if (c < cost[nb]) {
                cost[nb] = c;
                came[nb] = at;
                open.push({ c + Dist(g_nav.nodes[nb].data(), g_nav.nodes[to].data()), nb });
            }
        }
    }
    if (from != to && came[to] < 0) return false;
    for (int at = to; at >= 0; at = came[at]) out.insert(out.begin(), at);
    return true;
}

// --- the bot's body: its transform (CTransformCS at bot cs + 138h; Quest
// CR15NetBotCS::Transform -> CTransformCS::ComputeLocalToWorldTransfQ). Records of 118h,
// slot from the u32 table at +C8h; with no parent (+08h) the world position is at +F8h.
float *BodyPos(uint8_t *cs, uint32_t actor) {
    uint8_t *tcs = *(uint8_t **)(cs + 0x138);
    if (!tcs) return nullptr;
    uint16_t *slots = *(uint16_t **)(tcs + 0xc8);
    uint8_t *recs = *(uint8_t **)(tcs + 0xf8);
    if (!slots || !recs) return nullptr;
    uint8_t *r = recs + slots[(actor & 0xffff) * 2] * 0x118ull;
    if (*(void **)(r + 8)) return nullptr;
    return (float *)(r + 0xf8);
}
volatile LONG g_body_checks = 0;
bool g_body_ok = false;                          // BodyPos matched the API position: teleports allowed

struct BotState {
    int orb = -1;                                // the orb this bot is heading for
    std::vector<int> path;
    size_t step = 0;
    int goal = -1;
    ULONGLONG path_at = 0;
} g_bot[64];

const Player *FindBotPlayer(const std::vector<Player> &players, uint32_t user) {
    for (const Player &p : players)
        if ((uint32_t)p.userid == user || p.playerid == (int)user) return &p;
    return nullptr;
}

void Think(uint8_t *cs) {
    uint16_t n = *(uint16_t *)(cs + 0xfc);
    uint8_t *records = *(uint8_t **)(cs + 0x100);
    if (!records || !n) return;
    AcquireSRWLockShared(&g_world_lock);
    std::vector<Player> players = g_players;
    ULONGLONG age = GetTickCount64() - g_world_at;
    std::string map = g_map;
    ReleaseSRWLockShared(&g_world_lock);
    if (!map.empty() && map != g_nav.map) {
        LoadNav(map);
        for (BotState &b : g_bot) b = BotState();
    }
    uint8_t *dcs = PlayerDamageables(cs);
    ULONGLONG now = GetTickCount64();
    // which players are dead (bots only: the API doesn't say)
    std::vector<int> dead_ids;
    for (uint16_t i = 0; dcs && i < n; ++i) {
        uint8_t *r = records + i * RECORD;
        uint8_t *d = DamageableOf(dcs, *(uint32_t *)(r + R_ACTOR));
        if (!d || i >= 64) continue;
        if (!IsDead(d)) { g_dead_since[i] = 0; continue; }
        dead_ids.push_back((int)*(uint32_t *)(r + R_USER));
        if (!g_dead_since[i]) { g_dead_since[i] = now; Log("bot %u died", i); }
        if (g_cfg.respawn_ms && now - g_dead_since[i] >= g_cfg.respawn_ms && now - g_respawn_tried[i] >= 3000) {
            g_respawn_tried[i] = now;
            Respawn(dcs, d, i);
        }
    }
    auto is_dead = [&](int playerid) {
        for (int id : dead_ids) if (id == playerid) return true;
        return false;
    };
    if (players.empty() || age > 2000) return;
    for (uint16_t i = 0; i < n; ++i) {
        uint8_t *r = records + i * RECORD;
        if (is_dead((int)*(uint32_t *)(r + R_USER))) {      // dead: no moving, no shooting
            *(uint32_t *)(r + R_FIRE) = 0;
            *(uint32_t *)(r + R_MOVING) = 0;
            continue;
        }
        const Player *me = FindBotPlayer(players, *(uint32_t *)(r + R_USER));
        if (!me || !me->has_pos || i >= 64) continue;
        BotState &st = g_bot[i];
        uint32_t actor = *(uint32_t *)(r + R_ACTOR);
        float *body = BodyPos(cs, actor);
        if (body && !g_body_ok && g_body_checks < 20) {
            float d = Dist(body, me->pos);
            InterlockedIncrement(&g_body_checks);
            Log("bot %u body %.2f %.2f %.2f vs API %.2f %.2f %.2f (%.2f m)%s", i, body[0], body[1], body[2],
                me->pos[0], me->pos[1], me->pos[2], d, d < 1.5f ? ": body found, teleports on" : "");
            if (d < 1.5f) g_body_ok = true;
        }

        // war room: nothing until the orbs work, then walk to an orb and take it
        bool in_war_room = false;
        for (const Orb &o : g_nav.orbs)
            if (FlatDist(me->pos, o.at) < g_cfg.war_room_radius) in_war_room = true;
        if (in_war_room || g_nav.nodes.empty()) {
            *(uint32_t *)(r + R_FIRE) = 0;
            std::vector<int> mine;
            for (size_t k = 0; k < g_nav.orbs.size(); ++k)
                if (g_nav.orbs[k].team == me->team) mine.push_back((int)k);
            if (!g_orbs_live || mine.empty() || !in_war_room) {
                *(uint32_t *)(r + R_MOVING) = 0;
                st.orb = -1;
                continue;
            }
            if (st.orb < 0 || g_nav.orbs[st.orb].team != me->team) st.orb = mine[rand() % mine.size()];
            const Orb &o = g_nav.orbs[st.orb];
            float *t = (float *)(r + R_TARGET);
            if (FlatDist(me->pos, o.at) > g_cfg.orb_reach) {
                memcpy(t, o.at, sizeof(o.at));
                *(uint32_t *)(r + R_MOVING) = 1;
                float dir[3] = { o.at[0] - me->pos[0], 0, o.at[2] - me->pos[2] }, q[4];
                Normalize(dir);
                YawPitch(dir, q);
                memcpy(r + R_LOOK, q, sizeof(q));
                *(float *)(r + R_TURN) = g_cfg.turn_rate;
                continue;
            }
            // at the orb: land where it lands (spread a little so bots don't stack)
            *(uint32_t *)(r + R_MOVING) = 0;
            if (!g_body_ok || !body) {
                static ULONGLONG warned = 0;
                if (now > warned) { warned = now + 10000; Log("bot %u at its orb, but its body isn't found: can't teleport", i); }
                continue;
            }
            float land[3] = { o.to[0] + (rand() % 200 - 100) / 100.0f, o.to[1], o.to[2] + (rand() % 200 - 100) / 100.0f };
            memcpy(body, land, sizeof(land));
            memcpy(t, land, sizeof(land));
            Log("bot %u took the %s orb at %.1f %.1f %.1f -> %.1f %.1f %.1f", i, me->team.c_str(), o.at[0], o.at[1], o.at[2],
                land[0], land[1], land[2]);
            st.orb = -1;
            st.path.clear();
            continue;
        }
        st.orb = -1;

        const Player *target = nullptr;
        float best = 1e9f;
        for (const Player &p : players) {
            if (&p == me || !p.has_pos || p.team == me->team || p.team == "SPECTATORS" || is_dead(p.playerid)) continue;
            float d[3] = { p.pos[0] - me->pos[0], p.pos[1] - me->pos[1], p.pos[2] - me->pos[2] };
            float dist = sqrtf(d[0] * d[0] + d[1] * d[1] + d[2] * d[2]);
            if (dist < best) { best = dist; target = &p; }
        }
        if (!target) {
            *(uint32_t *)(r + R_FIRE) = 0;
            continue;
        }
        float dir[3] = { target->pos[0] - me->pos[0], target->pos[1] - me->pos[1], target->pos[2] - me->pos[2] };
        Normalize(dir);
        // move along the recorded routes towards the target, stopping keep_distance short
        float *t = (float *)(r + R_TARGET);
        if (best <= g_cfg.keep_distance) {
            *(uint32_t *)(r + R_MOVING) = 0;
        } else {
            int goal = NearestNode(target->pos);
            if (goal != st.goal || now - st.path_at > 1000 || st.step >= st.path.size()) {
                st.goal = goal;
                st.path_at = now;
                FindPath(NearestNode(me->pos), goal, st.path);
                st.step = 0;
            }
            while (st.step < st.path.size() && Dist(me->pos, g_nav.nodes[st.path[st.step]].data()) < g_cfg.node_reach)
                ++st.step;
            if (st.step < st.path.size()) {
                memcpy(t, g_nav.nodes[st.path[st.step]].data(), 3 * sizeof(float));
                *(uint32_t *)(r + R_MOVING) = 1;
            } else {
                *(uint32_t *)(r + R_MOVING) = 0;           // no route to them: hold and shoot if in range
            }
        }
        // look and fire: from the gun hand to the target's head (raised by aim_up), led by its velocity
        const float *from = me->has_hand ? me->hand : me->pos;
        float aim[3] = { target->pos[0], target->pos[1] + g_cfg.aim_up, target->pos[2] };
        if (g_cfg.bullet_speed > 0) {
            float lead = best / g_cfg.bullet_speed;
            for (int k = 0; k < 3; ++k) aim[k] += target->vel[k] * lead;
        }
        float adir[3] = { aim[0] - from[0], aim[1] - from[1], aim[2] - from[2] };
        Normalize(adir);
        float q[4];
        if (g_cfg.forward[2] > 0.5f) YawPitch(adir, q);
        else FromTo(g_cfg.forward, adir, q);
        memcpy(r + R_LOOK, q, sizeof(q));
        *(float *)(r + R_TURN) = g_cfg.turn_rate;
        *(uint32_t *)(r + R_FIRE) = best <= g_cfg.fire_range ? 1 : 0;
    }
}

// --- diagnostics ---------------------------------------------------------------------
// The damageable system (dead / health), from PowerBoost.dll once anything has been hit.
uint8_t *DamageableCS() {
    using get_fn = void *(*)();
    static get_fn get = nullptr;
    if (!get)
        if (HMODULE pb = GetModuleHandleA("PowerBoost.dll"))
            get = (get_fn)GetProcAddress(pb, "PowerBoost_DamageableCS");
    return get ? (uint8_t *)get() : nullptr;
}

void Hex(const char *what, const uint8_t *p, size_t n) {
    char line[16 * 3 + 1];
    for (size_t o = 0; o < n; o += 16) {
        size_t k = 0;
        for (size_t j = 0; j < 16 && o + j < n; ++j) k += sprintf_s(line + k, sizeof(line) - k, "%02x ", p[o + j]);
        Log("    %s +%03zx: %s", what, o, line);
    }
}

// Raw records, to find which damageable is which bot (and the bot's actor handle).
void DumpRecords(uint8_t *cs) {
    static int dumps = 0;
    if (dumps >= 3) return;
    uint8_t *dcs = DamageableCS();
    if (!dcs) return;
    ++dumps;
    uint16_t n = *(uint16_t *)(cs + 0xfc);
    uint8_t *records = *(uint8_t **)(cs + 0x100);
    Log("raw dump %d: bot cs %p (+80 %p), damageable cs %p (+80 %p, +fc %u)", dumps, cs, *(void **)(cs + 0x80),
        dcs, *(void **)(dcs + 0x80), *(uint16_t *)(dcs + 0xfc));
    for (uint16_t i = 0; records && i < n && i < 16; ++i) {
        Log("  bot record %u:", i);
        Hex("bot", records + i * RECORD, dumps == 1 ? RECORD : 0x40);
    }
    uint8_t *drec = *(uint8_t **)(dcs + 0x100);
    uint16_t dn = *(uint16_t *)(dcs + 0xfc);
    for (uint16_t i = 0; drec && i < dn && i < 48; ++i) {
        uint8_t *r = drec + i * 0xb8ull;
        Log("  damageable %u: flags %02x shield %.1f health %.1f", i, r[2], *(float *)(r + 0x1c), *(float *)(r + 0x20));
        Hex("dmg", r, dumps == 1 ? 0xb8 : 0x30);
    }
    uint16_t *slots = *(uint16_t **)(dcs + 0xd0);
    if (slots) Hex("dmg slots(u32)", (uint8_t *)slots, 4 * 32);
}

void Report(uint8_t *cs) {
    static ULONGLONG next = 0;
    ULONGLONG now = GetTickCount64();
    if (now < next) return;
    next = now + g_cfg.log_every_ms;
    uint16_t n = *(uint16_t *)(cs + 0xfc);
    uint8_t *records = *(uint8_t **)(cs + 0x100);
    Log("bot system %p: %u enabled bot(s), authority %u", cs, n, *(uint32_t *)(cs + 0x168));
    DumpRecords(cs);
    for (uint16_t i = 0; records && i < n && i < 16; ++i) {
        uint8_t *r = records + i * RECORD;
        float *t = (float *)(r + R_TARGET), *q = (float *)(r + R_LOOK);
        Log("  bot %u: user %08x moving %u target %.2f %.2f %.2f look %.2f %.2f %.2f %.2f turn %.2f fire %u boost %u",
            i, *(uint32_t *)(r + R_USER), *(uint32_t *)(r + R_MOVING), t[0], t[1], t[2], q[0], q[1], q[2], q[3],
            *(float *)(r + R_TURN), *(uint32_t *)(r + R_FIRE), *(uint32_t *)(r + R_BOOST));
    }
    AcquireSRWLockShared(&g_world_lock);
    std::vector<Player> players = g_players;
    static bool dumped = false;
    std::string json = dumped ? std::string() : g_last_json;
    ReleaseSRWLockShared(&g_world_lock);
    for (const Player &p : players)
        Log("  player '%s' team '%s' userid %llu playerid %d pos %.2f %.2f %.2f fwd %.2f %.2f %.2f%s",
            p.name.c_str(), p.team.c_str(), (unsigned long long)p.userid, p.playerid, p.pos[0], p.pos[1], p.pos[2],
            p.fwd[0], p.fwd[1], p.fwd[2], p.has_pos ? "" : " (no position)");
    if (!json.empty()) {
        dumped = true;
        Log("session API (first 6000 chars): %s", json.c_str());
    }
}

// --- the hook --------------------------------------------------------------------------
using update_fn = void(__fastcall *)(uint8_t *cs);
update_fn Real_Update = nullptr;

void __fastcall Hooked_Update(uint8_t *cs) {
    __try {
        if (g_cfg.brain) Think(cs);
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        static volatile LONG faults = 0;
        if (InterlockedIncrement(&faults) <= 5) Log("brain fault 0x%08lx: skipped this frame", GetExceptionCode());
    }
    Real_Update(cs);
    __try {
        Report(cs);
    } __except (EXCEPTION_EXECUTE_HANDLER) {
    }
}

bool HasArg(const char *flag) {
    const char *cmd = GetCommandLineA();
    size_t n = strlen(flag);
    for (const char *p = cmd; p && *p; ++p)
        if ((p == cmd || p[-1] == ' ' || p[-1] == '\t') && _strnicmp(p, flag, n) == 0 &&
            (p[n] == 0 || p[n] == ' ' || p[n] == '\t' || p[n] == '"'))
            return true;
    return false;
}

DWORD WINAPI Install(LPVOID) {
    if (!HasArg("-server")) { Log("not a server: CombatBots stays off"); return 0; }
    ReadIni();
    auto base = (uint8_t *)GetModuleHandleW(nullptr);
    if (memcmp(base + BOT_UPDATE_RVA, BOT_UPDATE_BYTES, sizeof(BOT_UPDATE_BYTES)) != 0) {
        Log("prologue mismatch at CR15NetBotCS::Update -- wrong echovr build, not hooking");
        return 0;
    }
    if (memcmp(base + RESPAWN_RVA, RESPAWN_BYTES, sizeof(RESPAWN_BYTES)) == 0) g_respawn = (respawn_fn)(base + RESPAWN_RVA);
    else Log("prologue mismatch at NetworkRespawn: bots won't respawn");
    Real_Update = (update_fn)(base + BOT_UPDATE_RVA);
    DetourTransactionBegin();
    DetourUpdateThread(GetCurrentThread());
    DetourAttach(&(PVOID &)Real_Update, Hooked_Update);
    LONG rc = DetourTransactionCommit();
    if (rc != NO_ERROR) { Log("hook failed (%ld)", rc); return 0; }
    Log("hooked CR15NetBotCS::Update; brain %s", g_cfg.brain ? "ON" : "off (logging only)");
    if (HANDLE t = CreateThread(nullptr, 0, Poller, nullptr, 0, nullptr)) CloseHandle(t);
    return 0;
}

} // namespace

BOOL APIENTRY DllMain(HMODULE self, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) {
        DisableThreadLibraryCalls(self);
        GetModuleFileNameA(self, g_log_path, MAX_PATH);
        strcpy_s(g_ini_path, g_log_path);
        if (char *slash = strrchr(g_log_path, '\\')) strcpy_s(slash + 1, MAX_PATH - (slash + 1 - g_log_path), "CombatBots.log");
        if (char *dot = strrchr(g_ini_path, '.')) strcpy_s(dot, MAX_PATH - (dot - g_ini_path), ".ini");
        if (HANDLE t = CreateThread(nullptr, 0, Install, nullptr, 0, nullptr)) CloseHandle(t);
    }
    return TRUE;
}
