// VeilNet: carries UMBRAL VEIL (and POINT) to every machine.
//
// The veil (the smoke tac mod) runs its script only on the client that used it. The
// one networked thing it does is create a barrier wall, which every machine gets.
// Nothing the script can send travels with the wall in a form the wall script can
// read back, so this plugin sends the news itself:
//
//   client that used the veil --"V id"--> server --"V id"--> every other client
//
// It uses the game's own connection: no ports of its own. echovr.exe talks to its
// server with plain sendto / recvfrom on one UDP socket; VeilNet hooks both. A client
// sends its packets from the game's socket to the server address and port the game
// itself sends to; on every machine, recvfrom takes VeilNet's packets out before
// the game sees them. The server answers through the socket each client's packets
// came in on, so replies go back the way the game's own do (same port forwarding,
// same NAT mapping).
//
// Every machine that hears of a veil (the user's client too) gets a "veil token" for
// TOKEN_LIFE. The barrier wall script (tools/veil_fx.py, network_wall) waits a moment
// at its spawn nodes for a token; a wall that takes one becomes the veil (no model, no
// collision, smoke clouds and the veil sound); a wall that finds none is a barrier.
//
//   echovr.exe +0x2104cc0 (spare bytes past .data, also used by the wall script):
//     +00 u32 tokens   +08 u64 expiry (interrupt time, 100 ns)
//     +10 u32 walls that became the veil   +14 u32 walls that stayed barriers
//   echovr.exe +0x2104f00: the veil's custom-param node (smoke script, mark_param)
//     bumps the u32 there each time the veil is used on this machine.
//
// Clients say hello every 2 s; the server relays only to clients that have (so a
// player without VeilNet never gets a packet the game would not understand), and answers
// each hello with an 'A'. A client that has had no answer for SERVER_TIMEOUT is on a
// server without EchoCombat: it hides the three new tac mods (UMBRAL VEIL, OVERCHARGE,
// POINT) from the tac mod list until one comes (TacModsFor).
// A nEVR plugin (nevr_plugin.h): set up from NvrPluginInitEx, taken down in
// NvrPluginShutdown; the host says whether this is the server. Its lines go to nEVR's host
// log, tagged plugin=VeilNet; the per-packet and per-tick lines are Debug.
//
// POINT goes the same way as 'P' packets: its script (also a barrier-script copy) bumps
// the u32 at +0x2104f80, every machine gets a "point token" (+0x2104ce0, same layout as
// the veil's), and a wall that takes one goes off as POINT's stun field instead.
//
// TRANSLOCATOR goes as 'T' packets: each teleport bumps the u32 at +0x2104d40 (the
// translocator script, tools/fix_loc_fx.py); the server only relays them, and every
// other client gets a "translocator token" (+0x2104d20) that the next translocator puck
// node to run there takes, showing the teleport effect and sound on its puck. The
// teleporting machine shows its own and holds no token.
//
// OVERCHARGE goes as 'O' packets: each use bumps the u32 at +0x2104ca4 (the buff
// script, tools/fix_buff.py), every machine gets an "overcharge token" (+0x2104ca8),
// and the next heal bubble in Repair Matrix's script to take one shows OVERCHARGE's
// purple look (tools/oc_switch.py).
//
// MEDIGUN goes as 'M' packets: PowerBoost.dll on the client holding it calls
// VeilNet_Medigun(id) (owner key, on / off, a sequence); the server relays it and every
// machine, the server too, hands it to PowerBoost_MedigunRemote, which ends that owner's
// heal bubble when the beam goes off.

#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stdarg.h>
#include "detours.h"
#include "nevr_plugin.h"
#include "nevr/plugin_logger.h"

#pragma comment(lib, "ws2_32.lib")

// Lines go to nEVR's host log, tagged plugin=<config.yaml name> (docs/standards/logging.md, Rule 15).
NEVR_DEFINE_PLUGIN_LOG("[VeilNet]")

constexpr const char *kLogName = "VeilNet";   // names the plugin in its log-cap Warning

namespace {

constexpr uintptr_t TOKEN_RVA = 0x2104cc0;
constexpr uintptr_t USE_COUNTER_RVA = 0x2104f00;
constexpr uintptr_t POINT_TOKEN_RVA = 0x2104ce0;
constexpr uintptr_t POINT_COUNTER_RVA = 0x2104f80;
constexpr uintptr_t LOC_TOKEN_RVA = 0x2104d20;
constexpr uintptr_t LOC_COUNTER_RVA = 0x2104d40;
constexpr uintptr_t OC_TOKEN_RVA = 0x2104ca8;
constexpr uintptr_t OC_COUNTER_RVA = 0x2104ca4;
constexpr uintptr_t EQUIP_RVA = 0x2104e80;          // tools/equip_guard.py: +00 equipped, +08 writer, +10 skips
constexpr uintptr_t POINT_FIRED_RVA = 0x2104d44;    // POINTs whose stun went off here
constexpr ULONGLONG TOKEN_LIFE = 15000000;      // 1.5 s, in 100 ns
constexpr uint32_t MAGIC = 0x4c564345;          // "ECVL"
constexpr uint32_t MAGIC2 = 0x4c494556;         // "VEIL"
//: The gear registry's tac mod list (filled from gear_table.tacmods, InitAndLoadGearTables
//: +0xc4eba0): a pointer to { allocator, entries, count, capacity }, entries 0x88 bytes
//: with the name (char[64]) first. Ours are the table's last three (fix_smoke.py,
//: fix_buff.py, fix_point.py append them in this order).
constexpr uintptr_t TACMOD_LIST_RVA = 0x20d3430;
constexpr size_t TACMOD_ENTRY = 0x88;
const char *const kNewTacMods[3] = {"smoke", "buff", "point"};
constexpr ULONGLONG SERVER_TIMEOUT = 6000;      // ms without an answer to the hello
//: MEDIGUN is off unless the server turns it on: PowerBoost.ini [server] medigun=1 next to this
//: DLL on the server. Its answer to each hello carries ANSWER_MEDIGUN when it does; a client
//: shows MEDIGUN (the weapon list's last entry, fix_medigun.py appends it) only while its current
//: server's answers say so, and PowerBoost.dll (VeilNet_MedigunAllowed) keeps it a plain COMET
//: otherwise. The weapon list sits just before the tac mod list (gear_table order: weapons,
//: ordnances, tac mods; each filled by +0xc4e410 from InitAndLoadGearTables).
constexpr uintptr_t WEAPON_LIST_RVA = 0x20d3420;
constexpr uint32_t ANSWER_MEDIGUN = 1;
bool g_medigun_on_server = false;               // server: [server] medigun

struct Shared {
    volatile LONG tokens;
    LONG pad;
    volatile ULONGLONG expiry;
    volatile LONG veils, barriers;
};

struct Packet {
    uint32_t magic;
    uint8_t type;                               // 'H' hello, 'A' its answer, 'V' veil, 'P' point, 'T' teleport, 'O' overcharge, 'K' a drone killed (server -> clients)
    uint8_t pad[3];
    uint32_t id;
    uint32_t magic2;
};

uint8_t *g_base;
Shared *g_shared;
Shared *g_point;                                // POINT's tokens (+10: walls that went off)
Shared *g_loc;                                  // TRANSLOCATOR's tokens (+10: teleports shown)
Shared *g_oc;                                   // OVERCHARGE's tokens (+10: bubbles shown purple)
bool g_server;
SRWLOCK g_lock = SRWLOCK_INIT;
volatile bool g_stop = false;                   // NvrPluginShutdown: the tick thread ends
HANDLE g_tick = nullptr;

// One line through nEVR's host log. Debug and Info are counted apart, so a burst of Debug lines
// never takes Info's room: Debug stops after kDebugCap lines and Info after kInfoCap, and the
// first line past either cap writes one Warning that says so. A Warning or an Error is always
// written.
constexpr LONG kDebugCap = 5000;
constexpr LONG kInfoCap = 20000;
volatile LONG g_logged_debug = 0;
volatile LONG g_logged_info = 0;

void LogLine(uint32_t level, const char *fmt, va_list args) {
    if (level < NEVR_LOG_WARNING) {
        bool debug = level == NEVR_LOG_DEBUG;
        LONG cap = debug ? kDebugCap : kInfoCap;
        LONG n = InterlockedIncrement(debug ? &g_logged_debug : &g_logged_info);
        if (n > cap) {
            if (n == cap + 1) {
                char note[160];
                snprintf(note, sizeof(note), "%s log cap reached: further %s lines are dropped (cap %ld)",
                         kLogName, debug ? "Debug" : "Info", static_cast<long>(cap));
                PluginLogFields(NEVR_LOG_WARNING, note, {});
            }
            return;
        }
    }
    char line[1024];
    vsnprintf(line, sizeof(line), fmt, args);
    PluginLogFields(level, line, {});
}

void Log(const char *fmt, ...) {
    va_list args;
    va_start(args, fmt);
    LogLine(NEVR_LOG_INFO, fmt, args);
    va_end(args);
}

void LogDebug(const char *fmt, ...) {
    va_list args;
    va_start(args, fmt);
    LogLine(NEVR_LOG_DEBUG, fmt, args);
    va_end(args);
}

void LogWarning(const char *fmt, ...) {
    va_list args;
    va_start(args, fmt);
    LogLine(NEVR_LOG_WARNING, fmt, args);
    va_end(args);
}

void LogError(const char *fmt, ...) {
    va_list args;
    va_start(args, fmt);
    LogLine(NEVR_LOG_ERROR, fmt, args);
    va_end(args);
}

ULONGLONG InterruptTime() { return *(volatile ULONGLONG *)0x7ffe0008; }

const char *Addr(const sockaddr_in &a, char *buf, size_t n) {
    char ip[32];
    inet_ntop(AF_INET, &a.sin_addr, ip, sizeof(ip));
    sprintf_s(buf, n, "%s:%u", ip, ntohs(a.sin_port));
    return buf;
}

bool Same(const sockaddr_in &a, const sockaddr_in &b) {
    return a.sin_addr.s_addr == b.sin_addr.s_addr && a.sin_port == b.sin_port;
}

void AddToken(Shared *t) {
    ULONGLONG now = InterruptTime();
    if (now >= t->expiry) InterlockedExchange(&t->tokens, 0);
    InterlockedIncrement(&t->tokens);
    t->expiry = now + TOKEN_LIFE;
}

Shared *Tokens(uint8_t type) {
    return type == 'P' ? g_point : type == 'T' ? g_loc : type == 'O' ? g_oc : g_shared;
}
const char *What(uint8_t type) {
    return type == 'P' ? "point" : type == 'T' ? "teleport" : type == 'O' ? "overcharge" : "veil";
}
bool Carried(uint8_t type) { return type == 'V' || type == 'P' || type == 'T' || type == 'O'; }

const char *TacMod(uint64_t s) {
    switch (s) {
    case 0xe32dc7c9d4804fb5ull: return "UMBRAL VEIL (smoke)";
    case 0xe32dc7cad6864aa4ull: return "POINT (point)";
    case 0xc8c33e48386618b6ull: return "OVERCHARGE (buff)";
    case 0xc8c33e4832761fbcull: return "Repair Matrix (heal)";
    case 0x41d2d43513260b1aull: return "barrier (shield)";
    case 0x41d2d4381430080cull: return "sensor";
    case 0x41d2d02f1b2a1316ull: return "wraith";
    default: return "?";
    }
}

// The last ids seen, so a veil that arrives twice (the resend) gives one token.
uint32_t g_seen[32];
int g_seen_next = 0;

bool FirstTime(uint32_t id) {
    AcquireSRWLockExclusive(&g_lock);
    bool seen = false;
    for (uint32_t s : g_seen) seen |= s == id;
    if (!seen) g_seen[g_seen_next++ % 32] = id;
    ReleaseSRWLockExclusive(&g_lock);
    return !seen;
}

using sendto_fn = int(WSAAPI *)(SOCKET, const char *, int, int, const sockaddr *, int);
using recvfrom_fn = int(WSAAPI *)(SOCKET, char *, int, int, sockaddr *, int *);
sendto_fn Real_sendto = sendto;
recvfrom_fn Real_recvfrom = recvfrom;

void Send(SOCKET s, const sockaddr_in &to, uint8_t type, uint32_t id) {
    Packet p = { MAGIC, type, {}, id, MAGIC2 };
    Real_sendto(s, (const char *)&p, sizeof(p), 0, (const sockaddr *)&to, sizeof(to));
}

// --- client: the game's connection to its server ------------------------------------
// The destination (socket + address) the game sent the most packets to in the last
// second. Every game server on a PC has its own port (6792, 6793, ...): when the
// game moves to another one (lobby -> match), this follows within a second.
struct Dest { SOCKET sock; sockaddr_in addr; LONG count; };
Dest g_dests[16];
int g_best = -1;

// Once a second (Tick): the busiest destination of the last second becomes the
// server, and the counts start again.
void PickServer() {
    AcquireSRWLockExclusive(&g_lock);
    int best = -1;
    for (int i = 0; i < 16; ++i)
        if (g_dests[i].count && (best < 0 || g_dests[i].count > g_dests[best].count)) best = i;
    if (best >= 0) g_best = best;
    for (int i = 0; i < 16; ++i)
        if (i != g_best) g_dests[i].count = 0;
        else g_dests[i].count = 1;               // keeps its slot while quiet
    ReleaseSRWLockExclusive(&g_lock);
}

void SawSend(SOCKET s, const sockaddr *to) {
    if (!to || to->sa_family != AF_INET) return;
    const sockaddr_in &a = *(const sockaddr_in *)to;
    AcquireSRWLockExclusive(&g_lock);
    int i = 0, free_slot = -1, low = 0;
    for (; i < 16; ++i) {
        if (g_dests[i].count && g_dests[i].sock == s && Same(g_dests[i].addr, a)) break;
        if (!g_dests[i].count && free_slot < 0) free_slot = i;
        if (g_dests[i].count < g_dests[low].count) low = i;
    }
    if (i == 16) {                              // new destination
        i = free_slot >= 0 ? free_slot : low;
        if (i == g_best) g_best = -1;
        g_dests[i] = { s, a, 0 };
    }
    ++g_dests[i].count;
    if (g_best < 0) g_best = i;
    ReleaseSRWLockExclusive(&g_lock);
}

bool ServerDest(Dest &out) {
    AcquireSRWLockShared(&g_lock);
    bool ok = g_best >= 0;
    if (ok) out = g_dests[g_best];
    ReleaseSRWLockShared(&g_lock);
    return ok;
}

void SendToServer(uint8_t type, uint32_t id) {
    Dest d;
    if (ServerDest(d)) Send(d.sock, d.addr, type, id);
}

// --- server: the clients it relays to -----------------------------------------------
struct Client { SOCKET sock; sockaddr_in addr; ULONGLONG last; };
Client g_clients[64];

void Remember(SOCKET s, const sockaddr_in &a) {
    ULONGLONG now = GetTickCount64();
    AcquireSRWLockExclusive(&g_lock);
    int slot = -1, oldest = 0;
    bool known = false;
    for (int i = 0; i < 64 && !known; ++i) {
        Client &c = g_clients[i];
        if (c.last && Same(c.addr, a)) { c.last = now; c.sock = s; known = true; }
        else {
            if (!c.last && slot < 0) slot = i;
            if (c.last < g_clients[oldest].last) oldest = i;
        }
    }
    if (!known) g_clients[slot < 0 ? oldest : slot] = { s, a, now };
    ReleaseSRWLockExclusive(&g_lock);
    char buf[48];
    if (!known) Log("client %s has VeilNet", Addr(a, buf, sizeof(buf)));
}

int Relay(const sockaddr_in &from, uint8_t type, uint32_t id) {
    Client list[64];
    AcquireSRWLockShared(&g_lock);
    memcpy(list, g_clients, sizeof(list));
    ReleaseSRWLockShared(&g_lock);
    ULONGLONG now = GetTickCount64();
    int n = 0;
    for (const Client &c : list)
        if (c.last && now - c.last < 30000 && !Same(c.addr, from)) {
            Send(c.sock, c.addr, type, id);
            Send(c.sock, c.addr, type, id);                     // once more, against loss
            ++n;
        }
    return n;
}

// DroneFix.dll on the server, when a drone's health runs out: every client shuts that drone
// down too ('K', the drone's damageable index in the low 16 bits of the id).
volatile LONG g_kills = 0;
extern "C" __declspec(dllexport) void __cdecl VeilNet_DroneKilled(uint32_t index) {
    if (!g_server) return;
    uint32_t id = ((uint32_t)InterlockedIncrement(&g_kills) << 16) | (index & 0xffff);
    FirstTime(id);
    sockaddr_in nobody = {};
    int n = Relay(nobody, 'K', id);
    Log("drone %u killed: told %d client(s)", index & 0xffff, n);
}

// PowerBoost.dll on the client with a MEDIGUN: its beam on / off, to the server and on to everyone.
extern "C" __declspec(dllexport) void __cdecl VeilNet_Medigun(uint32_t id) {
    if (g_server) return;
    FirstTime(id);
    SendToServer('M', id);
    SendToServer('M', id);                                  // once more, against loss
}

void MedigunHere(uint32_t id) {
    using remote_fn = void(__cdecl *)(uint32_t);
    static remote_fn remote = nullptr;
    if (!remote)
        if (HMODULE pb = GetModuleHandleW(L"PowerBoost.dll"))
            remote = (remote_fn)GetProcAddress(pb, "PowerBoost_MedigunRemote");
    if (remote) remote(id);
}

volatile ULONGLONG g_last_answer = 0;           // client: when the server last answered a hello
volatile uint32_t g_last_answer_flags = 0;      // ... and what it said (ANSWER_MEDIGUN)

void Handle(SOCKET s, const Packet &p, const sockaddr_in &from) {
    char buf[48];
    if (g_server) {
        Remember(s, from);
        if (p.type == 'H') Send(s, from, 'A', g_medigun_on_server ? ANSWER_MEDIGUN : 0);   // "this server has EchoCombat"
        if (p.type == 'M' && g_medigun_on_server && FirstTime(p.id)) {
            MedigunHere(p.id);
            Relay(from, 'M', p.id);
        }
        if (Carried(p.type) && FirstTime(p.id)) {
            if (p.type != 'T') AddToken(Tokens(p.type));   // a teleport has nothing to show here
            int n = Relay(from, p.type, p.id);
            LogDebug("%s %08x from %s: %srelayed to %d client(s)", What(p.type), p.id,
                Addr(from, buf, sizeof(buf)), p.type != 'T' ? "token here, " : "", n);
        }
    } else if (p.type == 'A') {
        Dest d;                                          // only the current server's answer counts
        if (ServerDest(d) && Same(d.addr, from)) {
            g_last_answer = GetTickCount64();
            g_last_answer_flags = p.id;
        }
    } else if (p.type == 'M' && FirstTime(p.id)) {
        if (g_last_answer_flags & ANSWER_MEDIGUN) MedigunHere(p.id);
    } else if (p.type == 'K' && FirstTime(p.id)) {          // a drone the server killed: DroneFix shuts it down
        using killed_fn = void(__cdecl *)(uint32_t);
        static killed_fn killed = nullptr;
        if (!killed)
            if (HMODULE dronefix = GetModuleHandleW(L"DroneFix.dll"))
                killed = (killed_fn)GetProcAddress(dronefix, "DroneFix_Killed");
        if (killed) killed(p.id & 0xffff);
        if (killed)
            LogDebug("drone %u killed on the server: shut down here", p.id & 0xffff);
        else
            LogWarning("drone %u killed on the server: NOT shut down here (no DroneFix.dll)", p.id & 0xffff);
    } else if (Carried(p.type) && FirstTime(p.id)) {
        AddToken(Tokens(p.type));
        LogDebug("%s %08x from the server: token here", What(p.type), p.id);
    }
}

// --- the hooks ----------------------------------------------------------------------
int WSAAPI Hooked_sendto(SOCKET s, const char *buf, int len, int flags, const sockaddr *to, int tolen) {
    if (!g_server) SawSend(s, to);
    return Real_sendto(s, buf, len, flags, to, tolen);
}

// VeilNet's packets are taken out here; the game gets the next datagram, or "nothing
// waiting" (WSAEWOULDBLOCK) when there is none, instead of a packet it cannot read.
int WSAAPI Hooked_recvfrom(SOCKET s, char *buf, int len, int flags, sockaddr *from, int *fromlen) {
    for (;;) {
        sockaddr_storage own;
        int own_len = sizeof(own);
        sockaddr *f = from ? from : (sockaddr *)&own;
        int *fl = from ? fromlen : &own_len;
        int saved = fl ? *fl : 0;
        int n = Real_recvfrom(s, buf, len, flags, f, fl);
        if (n != (int)sizeof(Packet) || (flags & MSG_PEEK) || !fl) return n;
        Packet p;
        memcpy(&p, buf, sizeof(p));
        if (p.magic != MAGIC || p.magic2 != MAGIC2) return n;
        if (f->sa_family == AF_INET) Handle(s, p, *(const sockaddr_in *)f);
        *fl = saved;
        u_long waiting = 0;
        if (ioctlsocket(s, FIONREAD, &waiting) != 0 || waiting == 0) {
            WSASetLastError(WSAEWOULDBLOCK);
            return SOCKET_ERROR;
        }
    }
}

// The tac mod list as the server allows: all of it on a server with EchoCombat, without the
// last three (ours) on one without. The entries stay where they are; only the count
// changes. A rebuilt list (SettingsUpdateCB reloads the gear tables) has a new entries
// pointer and its full count again. Nothing is touched unless its last three are ours.
uint8_t *g_list_entries;
uint64_t g_list_full;

bool OursAtEnd(uint8_t *entries, uint64_t full) {
    for (int k = 0; k < 3; ++k)
        if (strncmp((const char *)entries + (full - 3 + k) * TACMOD_ENTRY, kNewTacMods[k], 64) != 0) return false;
    return true;
}

// The tac mod the player has selected (EQUIP_RVA, from their profile update) is one of ours.
bool OurSelected() {
    uint64_t sym = *(volatile uint64_t *)(g_base + EQUIP_RVA);
    return sym == 0xe32dc7c9d4804fb5ull || sym == 0xe32dc7cad6864aa4ull || sym == 0xc8c33e48386618b6ull;   // smoke, point, buff
}

// The list is rebuilt (and its old one freed) on the game's thread: everything here is
// guarded. 0: unchanged, 1: shown, 2: hidden.
int TacModsGuarded(bool server_has_it, uint64_t *now_count) {
    __try {
        uint8_t *list = *(uint8_t *volatile *)(g_base + TACMOD_LIST_RVA);
        if (!list) return 0;
        uint8_t *entries = *(uint8_t *volatile *)(list + 0x08);
        volatile uint64_t *count = (volatile uint64_t *)(list + 0x10);
        uint64_t capacity = *(volatile uint64_t *)(list + 0x18);
        if (!entries) return 0;
        // a new list is filled an entry at a time: its full count is the most it has had
        if (entries != g_list_entries) {
            g_list_entries = entries;
            g_list_full = 0;
        }
        if (*count > g_list_full) g_list_full = *count;
        uint64_t full = g_list_full;
        if (full < 3 || full > capacity || !OursAtEnd(entries, full)) return 0;
        uint64_t want = server_has_it ? full : full - 3;
        // One of ours selected: the list stays whole. Cut short, the selection pointed past
        // its end (a loading match hides them until its server answers): kept, it is only
        // an EchoCombat tac mod on a server without it, as before the gate.
        if (!server_has_it && OurSelected()) want = full;
        if (*count == want) return 0;
        *count = want;
        *now_count = want;
        return server_has_it ? 1 : 2;
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        return 0;
    }
}

// MEDIGUN in the weapon list as the server allows (see ANSWER_MEDIGUN): the list's last entry,
// cut off by the count as the tac mods are. While it is this player's weapon it stays (the
// selection would point past the list's end); PowerBoost.dll keeps it a COMET meanwhile.
uint8_t *g_weapon_entries;
uint64_t g_weapon_full;

bool MedigunSelected() {
    using weapon_fn = uint64_t(__cdecl *)();
    static weapon_fn weapon = nullptr;
    if (!weapon)
        if (HMODULE pb = GetModuleHandleW(L"PowerBoost.dll")) weapon = (weapon_fn)GetProcAddress(pb, "PowerBoost_LocalWeapon");
    return weapon && weapon() == 0x2fda8a9b57734284ull;     // CSymbol64("medigun")
}

int MedigunListGuarded(bool allowed, uint64_t *now_count) {
    __try {
        uint8_t *list = *(uint8_t *volatile *)(g_base + WEAPON_LIST_RVA);
        if (!list) return 0;
        uint8_t *entries = *(uint8_t *volatile *)(list + 0x08);
        volatile uint64_t *count = (volatile uint64_t *)(list + 0x10);
        uint64_t capacity = *(volatile uint64_t *)(list + 0x18);
        if (!entries) return 0;
        if (entries != g_weapon_entries) {
            g_weapon_entries = entries;
            g_weapon_full = 0;
        }
        if (*count > g_weapon_full) g_weapon_full = *count;
        uint64_t full = g_weapon_full;
        if (full < 1 || full > capacity || strncmp((const char *)entries + (full - 1) * TACMOD_ENTRY, "medigun", 64) != 0)
            return 0;
        uint64_t want = allowed || MedigunSelected() ? full : full - 1;
        if (*count == want) return 0;
        *count = want;
        *now_count = want;
        return want == full ? 1 : 2;
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        return 0;
    }
}

bool MedigunAllowedNow() {
    ULONGLONG now = GetTickCount64();
    return g_last_answer && now - g_last_answer < SERVER_TIMEOUT && (g_last_answer_flags & ANSWER_MEDIGUN);
}

void MedigunListFor(bool allowed) {
    uint64_t n = 0;
    int r = MedigunListGuarded(allowed, &n);
    if (r == 1) Log("MEDIGUN shown (%llu weapons)%s", n, allowed ? ": the server allows it" : ": selected, kept until changed");
    if (r == 2) Log("MEDIGUN hidden (%llu weapons): the server does not allow it", n);
}

void TacModsFor(bool server_has_it) {
    uint64_t n = 0;
    int r = TacModsGuarded(server_has_it, &n);
    if (r == 1) Log("the server has EchoCombat: UMBRAL VEIL, OVERCHARGE and POINT shown (%llu tac mods)", n);
    if (r == 2) Log("the server has no EchoCombat: UMBRAL VEIL, OVERCHARGE and POINT hidden (%llu tac mods)", n);
}

// Watches this machine's veil uses (client), says hello (client), shows / hides the new
// tac mods (client) and logs what the barrier walls decided (both).
void HookSelectionLogs();

// SawLog (in the platform module's logger hook) hands the selected tac mod to Tick here,
// so the hook itself never logs; Tick writes the "selected:" line. One producer, one consumer.
volatile LONG64 g_selected_pending = 0;

DWORD WINAPI Tick(LPVOID) {
    volatile LONG *uses = (volatile LONG *)(g_base + USE_COUNTER_RVA);
    volatile LONG *point_uses = (volatile LONG *)(g_base + POINT_COUNTER_RVA);
    volatile LONG *loc_uses = (volatile LONG *)(g_base + LOC_COUNTER_RVA);
    volatile LONG *oc_uses = (volatile LONG *)(g_base + OC_COUNTER_RVA);
    LONG seen_uses = *uses, seen_veils = g_shared->veils, seen_barriers = g_shared->barriers;
    LONG seen_point_uses = *point_uses, seen_points = g_point->veils;
    LONG seen_loc_uses = *loc_uses, seen_locs = g_loc->veils;
    LONG seen_oc_uses = *oc_uses, seen_ocs = g_oc->veils;
    volatile LONG *point_fired = (volatile LONG *)(g_base + POINT_FIRED_RVA);
    LONG seen_fired = *point_fired;
    volatile uint64_t *equip = (volatile uint64_t *)(g_base + EQUIP_RVA);
    volatile LONG *skips = (volatile LONG *)(g_base + EQUIP_RVA + 0x10);
    volatile LONG *reruns = (volatile LONG *)(g_base + EQUIP_RVA + 0x20);
    uint64_t seen_queried = equip[3], seen_writer = equip[1];
    LONG seen_skips = *skips, seen_reruns = *reruns;
    sockaddr_in logged_server = {};
    ULONGLONG next_hello = 0, next_pick = 0, next_hook = 0, next_tacmods = 0;
    while (!g_stop) {
        Sleep(10);                                       // (5 ms: 200 wakeups a second, for checks that need far fewer)
        if (!g_server && GetTickCount64() >= next_hook) {                // the selection is the client's own
            next_hook = GetTickCount64() + 1000;
            HookSelectionLogs();
        }
        if (!g_server) {
            for (int k = 0; k < 4; ++k) {
                uint8_t type = "VPTO"[k];
                LONG u = k == 3 ? *oc_uses : k == 2 ? *loc_uses : k ? *point_uses : *uses;
                LONG &seen = k == 3 ? seen_oc_uses : k == 2 ? seen_loc_uses : k ? seen_point_uses : seen_uses;
                if (u == seen) continue;
                seen = u;
                uint32_t id = GetTickCount() * 2654435761u ^ GetCurrentProcessId() << 16 ^ (uint32_t)u ^ k;
                FirstTime(id);
                if (type != 'T') AddToken(Tokens(type));     // a teleport is shown here already
                Dest d;
                bool ok = ServerDest(d);
                SendToServer(type, id);
                SendToServer(type, id);                          // once more, against loss
                if (ok)
                    Log("%s used here: token here, %08x sent to the server", What(type), id);
                else
                    LogWarning("%s used here: token here (%08x not sent: no game server connection seen yet)",
                        What(type), id);
            }
            ULONGLONG now = GetTickCount64();
            if (now >= next_pick) {
                next_pick = now + 1000;
                PickServer();
            }
            if (now >= next_tacmods) {
                next_tacmods = now + 250;
                TacModsFor(g_last_answer && now - g_last_answer < SERVER_TIMEOUT);
                MedigunListFor(MedigunAllowedNow());
            }
            if (now >= next_hello) {
                next_hello = now + 2000;
                SendToServer('H', 0);
                Dest d;
                if (ServerDest(d) && !Same(d.addr, logged_server)) {
                    logged_server = d.addr;
                    char buf[48];
                    Log("server %s (the game's own connection)", Addr(d.addr, buf, sizeof(buf)));
                }
            }
        }
        LONG64 selected = InterlockedExchange64(&g_selected_pending, 0);
        if (selected) Log("selected: %s", TacMod((uint64_t)selected));
        LONG v = g_shared->veils, b = g_shared->barriers;
        if (v != seen_veils) { seen_veils = v; Log("a barrier wall took a token: UMBRAL VEIL (%ld so far)", v); }
        if (b != seen_barriers) { seen_barriers = b; Log("a barrier wall found no token: energy barrier (%ld so far)", b); }
        LONG pt = g_point->veils;
        if (pt != seen_points) { seen_points = pt; Log("a barrier wall took a point token: POINT (%ld so far)", pt); }
        LONG pf = *point_fired;
        if (pf != seen_fired) { seen_fired = pf; Log("POINT went off here: stun explosion activated (%ld so far)", pf); }
        LONG lc = g_loc->veils;
        if (lc != seen_locs) { seen_locs = lc; Log("a translocator puck took a teleport token: effect and sound shown (%ld so far)", lc); }
        uint64_t eq = equip[0], qd = equip[3], wr = equip[1];
        if (qd != seen_queried || wr != seen_writer) {
            Log("controller enabled for: %s (controller %016llx%s; selected: %s)", TacMod(qd), wr,
                seen_writer && wr != seen_writer ? ", A DIFFERENT CONTROLLER" : "", TacMod(eq));
            seen_queried = qd;
            seen_writer = wr;
        }
        LONG rr = *reruns;
        if (rr != seen_reruns) {
            if (rr) Log("controller chain ended on %s, selected %s: re-run %ld", TacMod(qd), TacMod(eq), rr);
            seen_reruns = rr;
        }
        LONG sk = *skips;
        if (sk != seen_skips) {
            seen_skips = sk;
            Log("a tac mod that is not the selected one (%s) was used: skipped (%ld so far)", TacMod(eq), sk);
        }
        LONG oc = g_oc->veils;
        if (oc != seen_ocs) { seen_ocs = oc; Log("a heal bubble took an overcharge token: shown purple (%ld so far)", oc); }
    }
    return 0;
}

// The tac mod the player selected, as the client sends it ("[NSUSER] sent profile
// update: {"ability":"point"}"): stored at EQUIP_RVA for tools/equip_guard.py's checks
// and the controller's re-run. Read from the game's log the moment it is picked. The
// profile code is in the platform module (pnsovr.dll for Oculus, pnsrad.dll for the
// others), each with its own copy of the logger: in each, the logger is found from the
// code that logs that line (lea r8, <format>; ...; call WriteLog; WriteLog calls
// PrintfImpl(level, flags, fmt, va_list)) and hooked. echovr.exe has a copy too, but its
// logger is nEVR's: nEVR hooks it itself, and a second hook there breaks nEVR's log and
// stops a server (its hook guard), so that one is left alone. The hook does no logging (it
// runs inside the platform module's own logger); Tick writes the "selected:" line.
using printf_fn = void(*)(int, uint64_t, const char *, va_list);
constexpr char kProfileFmt[] = "[NSUSER] sent profile update: %s";
const wchar_t *const kLogModules[] = {L"pnsovr.dll", L"pnsrad.dll"};
constexpr int kLogHooks = 2;
printf_fn g_real_log[kLogHooks];
bool g_log_tried[kLogHooks];

uint64_t AbilitySymbol(const char *name, size_t n) {
    static const struct { const char *name; uint64_t sym; } k[] = {
        {"smoke", 0xe32dc7c9d4804fb5ull}, {"point", 0xe32dc7cad6864aa4ull}, {"buff", 0xc8c33e48386618b6ull},
        {"heal", 0xc8c33e4832761fbcull}, {"shield", 0x41d2d43513260b1aull}, {"sensor", 0x41d2d4381430080cull},
        {"wraith", 0x41d2d02f1b2a1316ull}};
    for (const auto &e : k)
        if (strlen(e.name) == n && memcmp(e.name, name, n) == 0) return e.sym;
    return 0;
}

void SawLog(const char *fmt, va_list args) {
    if (!fmt || strcmp(fmt, kProfileFmt) != 0) return;
    va_list copy = args;
    const char *json = va_arg(copy, const char *);
    const char *a = json ? strstr(json, "\"ability\":\"") : nullptr;
    if (!a) return;
    a += 11;
    const char *e = strchr(a, '"');
    uint64_t sym = e ? AbilitySymbol(a, e - a) : 0;
    if (!sym) return;
    *(volatile LONG *)(g_base + EQUIP_RVA + 0x20) = 0;                // a new selection: re-runs allowed
    *(volatile uint64_t *)(g_base + EQUIP_RVA) = sym;
    InterlockedExchange64(&g_selected_pending, (LONG64)sym);         // Tick logs it
}

template <int I> void HookedLog(int level, uint64_t flags, const char *fmt, va_list args) {
    SawLog(fmt, args);
    g_real_log[I](level, flags, fmt, args);
}
const printf_fn kHookedLog[kLogHooks] = {HookedLog<0>, HookedLog<1>};

// The PrintfImpl the module's profile update goes through, or nullptr.
printf_fn FindProfileLogger(uint8_t *m) {
    auto *dos = (IMAGE_DOS_HEADER *)m;
    auto *nt = (IMAGE_NT_HEADERS64 *)(m + dos->e_lfanew);
    size_t size = nt->OptionalHeader.SizeOfImage;
    const uint8_t *str = nullptr;
    auto *sec = IMAGE_FIRST_SECTION(nt);
    for (int i = 0; i < nt->FileHeader.NumberOfSections && !str; ++i, ++sec) {
        if (sec->Characteristics & IMAGE_SCN_MEM_EXECUTE) continue;
        uint8_t *p = m + sec->VirtualAddress;
        size_t n = sec->Misc.VirtualSize;
        for (size_t o = 0; o + sizeof(kProfileFmt) <= n; ++o)
            if (p[o] == '[' && memcmp(p + o, kProfileFmt, sizeof(kProfileFmt)) == 0) { str = p + o; break; }
    }
    if (!str) return nullptr;
    sec = IMAGE_FIRST_SECTION(nt);
    for (int i = 0; i < nt->FileHeader.NumberOfSections; ++i, ++sec) {
        if (!(sec->Characteristics & IMAGE_SCN_MEM_EXECUTE)) continue;
        uint8_t *p = m + sec->VirtualAddress;
        size_t n = sec->Misc.VirtualSize;
        for (size_t o = 0; o + 7 <= n; ++o) {
            if (p[o] != 0x4c || p[o + 1] != 0x8d || p[o + 2] != 0x05) continue;      // lea r8, [rip+x]
            if (p + o + 7 + *(int32_t *)(p + o + 3) != str) continue;
            for (size_t c = o + 7; c < o + 7 + 24 && c + 5 <= n; ++c) {               // the call after it
                if (p[c] != 0xe8) continue;
                uint8_t *wl = p + c + 5 + *(int32_t *)(p + c + 1);
                // WriteLog: mov [rsp+18h], r8; mov [rsp+20h], r9; sub rsp, 28h; lea r9, [rsp+48h]; call PrintfImpl
                static const uint8_t head[] = {0x4c, 0x89, 0x44, 0x24, 0x18, 0x4c, 0x89, 0x4c, 0x24, 0x20,
                                               0x48, 0x83, 0xec, 0x28, 0x4c, 0x8d, 0x4c, 0x24, 0x48, 0xe8};
                if (wl < m || wl + sizeof(head) + 4 > m + size || memcmp(wl, head, sizeof(head)) != 0) return nullptr;
                return (printf_fn)(wl + sizeof(head) + 4 + *(int32_t *)(wl + sizeof(head)));
            }
            return nullptr;
        }
    }
    return nullptr;
}

// Hooks each module's logger once it is loaded (the platform module can load late).
void HookSelectionLogs() {
    for (int i = 0; i < kLogHooks; ++i) {
        if (g_log_tried[i]) continue;
        HMODULE m = GetModuleHandleW(kLogModules[i]);
        if (!m) continue;
        g_log_tried[i] = true;
        printf_fn f = FindProfileLogger((uint8_t *)m);
        if (!f) continue;                                                  // no profile code in it
        g_real_log[i] = f;
        DetourTransactionBegin();
        DetourUpdateThread(GetCurrentThread());
        DetourAttach(&(PVOID &)g_real_log[i], (PVOID)kHookedLog[i]);
        LONG rc = DetourTransactionCommit();
        if (rc != NO_ERROR) g_real_log[i] = nullptr;
        if (rc == NO_ERROR)
            Log("watching tac mod selections in %ls", kLogModules[i]);
        else
            LogWarning("hooking the logger in %ls failed", kLogModules[i]);
    }
}

bool g_hooked = false;

bool Install(bool server) {
    if (g_hooked) return true;
    g_base = (uint8_t *)GetModuleHandleW(nullptr);
    g_shared = (Shared *)(g_base + TOKEN_RVA);
    g_point = (Shared *)(g_base + POINT_TOKEN_RVA);
    g_loc = (Shared *)(g_base + LOC_TOKEN_RVA);
    g_oc = (Shared *)(g_base + OC_TOKEN_RVA);
    g_server = server;
    if (g_server) *(volatile LONG *)(g_base + EQUIP_RVA + 0x14) = 1;   // equip_guard: a client's check only
    DetourTransactionBegin();
    DetourUpdateThread(GetCurrentThread());
    DetourAttach(&(PVOID &)Real_sendto, Hooked_sendto);
    DetourAttach(&(PVOID &)Real_recvfrom, Hooked_recvfrom);
    LONG rc = DetourTransactionCommit();
    if (rc != NO_ERROR) { LogWarning("hooking sendto / recvfrom failed (%ld): UMBRAL VEIL stays local", rc); return false; }
    g_hooked = true;
    Log(g_server ? "server: relaying UMBRAL VEIL over the game's own connection"
                 : "client: UMBRAL VEIL goes over the game's own connection");
    g_stop = false;
    g_tick = CreateThread(nullptr, 0, Tick, nullptr, 0, nullptr);
    return true;
}

void Uninstall() {
    g_stop = true;
    if (g_tick) {
        WaitForSingleObject(g_tick, 2000);
        CloseHandle(g_tick);
        g_tick = nullptr;
    }
    DetourTransactionBegin();
    DetourUpdateThread(GetCurrentThread());
    if (g_hooked) {
        DetourDetach(&(PVOID &)Real_sendto, Hooked_sendto);
        DetourDetach(&(PVOID &)Real_recvfrom, Hooked_recvfrom);
    }
    for (int i = 0; i < kLogHooks; ++i)
        if (g_real_log[i]) DetourDetach(&(PVOID &)g_real_log[i], (PVOID)kHookedLog[i]);
    DetourTransactionCommit();
    g_hooked = false;
    for (int i = 0; i < kLogHooks; ++i) { g_real_log[i] = nullptr; g_log_tried[i] = false; }
    Log("unhooked");
}

// A clean exit. CR15Game's shutdown (+0x1223a0, its vslot 7, run once by Main_ as the game
// quits) logs the player out, then hands over to the engine's own teardown (+0x512590, the
// call at +0x122755). That teardown frees every resource, and one GPU particle effect's
// instance list is broken by then (+0x633643 reads through -1), so nearly every close with
// EchoCombat's data ended in an access violation and a BugSplat report. The call ends the
// process there instead (the logout and everything before it has run). The stub calls
// TerminateProcess itself and is never freed, so it outlives this DLL: nothing to undo.
constexpr uintptr_t TEARDOWN_CALL_RVA = 0x122752;
constexpr uint8_t TEARDOWN_CALL_BYTES[] = { 0x48, 0x8b, 0xcf, 0xe8, 0x36, 0xfe, 0x3e, 0x00 };   // mov rcx, rdi; call +0x512590

void InstallQuickExit() {
    static bool done;
    if (done) return;
    uint8_t *base = (uint8_t *)GetModuleHandleW(nullptr);
    uint8_t *call = base + TEARDOWN_CALL_RVA + 3;
    if (memcmp(base + TEARDOWN_CALL_RVA, TEARDOWN_CALL_BYTES, sizeof TEARDOWN_CALL_BYTES) != 0) {
        LogWarning("shutdown call not found (another build?): the game exits as stock");
        return;
    }
    uint8_t *stub = nullptr;                              // a call rel32 reaches +-2 GB
    for (uintptr_t at = ((uintptr_t)base & ~0xffffull) - 0x10000; at > (uintptr_t)base - 0x70000000; at -= 0x10000)
        if ((stub = (uint8_t *)VirtualAlloc((void *)at, 0x1000, MEM_RESERVE | MEM_COMMIT, PAGE_EXECUTE_READWRITE))) break;
    if (!stub) {
        LogWarning("no room for the shutdown stub: the game exits as stock");
        return;
    }
    uint8_t code[] = {
        0x48, 0xc7, 0xc1, 0xff, 0xff, 0xff, 0xff,         // mov rcx, -1 (this process)
        0x31, 0xd2,                                       // xor edx, edx (exit code 0)
        0x48, 0xb8, 0, 0, 0, 0, 0, 0, 0, 0,               // mov rax, TerminateProcess
        0xff, 0xe0,                                       // jmp rax
    };
    uint64_t fn = (uint64_t)GetProcAddress(GetModuleHandleW(L"kernel32.dll"), "TerminateProcess");
    if (!fn) return;
    memcpy(code + 11, &fn, 8);
    memcpy(stub, code, sizeof code);
    int32_t rel = (int32_t)(stub - (call + 5));
    DWORD old;
    if (!VirtualProtect(call, 5, PAGE_EXECUTE_READWRITE, &old)) return;
    memcpy(call + 1, &rel, 4);
    VirtualProtect(call, 5, old, &old);
    FlushInstructionCache(GetCurrentProcess(), call, 5);
    done = true;
    Log("clean exit: the engine's teardown is skipped once the game has shut down");
}

} // namespace

// PowerBoost.dll (client): may this player's MEDIGUN work here? Only on a server that allows it.
extern "C" __declspec(dllexport) int __cdecl VeilNet_MedigunAllowed() {
    return g_server ? (g_medigun_on_server ? 1 : 0) : (MedigunAllowedNow() ? 1 : 0);
}

ECHOCOMBAT_EXPORT NvrPluginInfo NvrPluginGetInfo(void) {
    return EchoCombatPluginInfo("veil_net", "EchoCombat: UMBRAL VEIL, POINT, TRANSLOCATOR and OVERCHARGE between players");
}

ECHOCOMBAT_EXPORT uint32_t NvrPluginGetApiVersion(void) { return NEVR_PLUGIN_API_VERSION; }

ECHOCOMBAT_EXPORT uint32_t NvrPluginGetCapabilities(void) {
    return NEVR_PLUGIN_CAP_ALTERS_GAMEPLAY | NEVR_PLUGIN_CAP_NETWORK | NEVR_PLUGIN_CAP_HOOKS_ENGINE;
}

ECHOCOMBAT_EXPORT int NvrPluginInitEx(const NvrGameContext *ctx, const char *) {
    PluginLogBind(ctx);
    HMODULE self = nullptr;                              // MEDIGUN: PowerBoost.ini [server] medigun, beside the DLLs
    GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                       (LPCWSTR)&NvrPluginInitEx, &self);
    char ini[MAX_PATH];
    EchoCombatBesideDll(self, ini, sizeof(ini), "PowerBoost.ini");
    g_medigun_on_server = GetPrivateProfileIntA("server", "medigun", 0, ini) != 0;
    InstallQuickExit();
    return Install(EchoCombatIsServer(ctx)) ? 0 : 1;
}

ECHOCOMBAT_EXPORT int NvrPluginInit(const NvrGameContext *ctx) { return NvrPluginInitEx(ctx, "{}"); }

ECHOCOMBAT_EXPORT void NvrPluginShutdown(void) { Uninstall(); }

BOOL APIENTRY DllMain(HMODULE self, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) DisableThreadLibraryCalls(self);
    return TRUE;
}
