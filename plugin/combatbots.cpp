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
#include "detours.h"

#pragma comment(lib, "ws2_32.lib")
#pragma comment(lib, "iphlpapi.lib")

namespace {

constexpr uintptr_t BOT_UPDATE_RVA = 0xd625c0;
constexpr uint8_t BOT_UPDATE_BYTES[] = { 0x40, 0x55, 0x56, 0x41, 0x54, 0x48, 0x8d, 0xac, 0x24, 0x50, 0xfe, 0xff, 0xff };

constexpr size_t RECORD = 0x1b0;
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
    g_cfg.log_every_ms = GetPrivateProfileIntA("bots", "log_every_ms", 5000, g_ini_path);
    Log("settings: brain=%d forward=%s keep_distance=%.1f fire_range=%.1f turn_rate=%.2f",
        g_cfg.brain, axis, g_cfg.keep_distance, g_cfg.fire_range, g_cfg.turn_rate);
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
    float pos[3] = {}, fwd[3] = {};
    bool has_pos = false;
};

SRWLOCK g_world_lock = SRWLOCK_INIT;
std::vector<Player> g_players;
std::string g_last_json;
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
                    players.push_back(p);
                }
        }
    AcquireSRWLockExclusive(&g_world_lock);
    g_players.swap(players);
    g_last_json = body.substr(0, 6000);
    g_world_at = GetTickCount64();
    ReleaseSRWLockExclusive(&g_world_lock);
}

DWORD WINAPI Poller(LPVOID) {
    WSADATA wsa;
    WSAStartup(MAKEWORD(2, 2), &wsa);
    ULONGLONG next_scan = 0;
    for (;;) {
        Sleep(100);
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
    ReleaseSRWLockShared(&g_world_lock);
    if (players.empty() || age > 2000) return;
    for (uint16_t i = 0; i < n; ++i) {
        uint8_t *r = records + i * RECORD;
        const Player *me = FindBotPlayer(players, *(uint32_t *)(r + R_USER));
        if (!me || !me->has_pos) continue;
        const Player *target = nullptr;
        float best = 1e9f;
        for (const Player &p : players) {
            if (&p == me || !p.has_pos || p.team == me->team) continue;
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
        // move: to keep_distance short of the target
        float stop = best > g_cfg.keep_distance ? best - g_cfg.keep_distance : 0;
        float *t = (float *)(r + R_TARGET);
        for (int k = 0; k < 3; ++k) t[k] = me->pos[k] + dir[k] * stop;
        *(uint32_t *)(r + R_MOVING) = stop > 0.5f ? 1 : 0;
        // look and fire
        float q[4];
        FromTo(g_cfg.forward, dir, q);
        memcpy(r + R_LOOK, q, sizeof(q));
        *(float *)(r + R_TURN) = g_cfg.turn_rate;
        *(uint32_t *)(r + R_FIRE) = best <= g_cfg.fire_range ? 1 : 0;
    }
}

// --- diagnostics ---------------------------------------------------------------------
void Report(uint8_t *cs) {
    static ULONGLONG next = 0;
    ULONGLONG now = GetTickCount64();
    if (now < next) return;
    next = now + g_cfg.log_every_ms;
    uint16_t n = *(uint16_t *)(cs + 0xfc);
    uint8_t *records = *(uint8_t **)(cs + 0x100);
    Log("bot system %p: %u enabled bot(s), authority %u", cs, n, *(uint32_t *)(cs + 0x168));
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
