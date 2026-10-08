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
// player without VeilNet never gets a packet the game would not understand).
// "-server" on the command line picks the server role. Log: VeilNet.log next to the DLL.
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

#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "detours.h"

#pragma comment(lib, "ws2_32.lib")

namespace {

constexpr uintptr_t TOKEN_RVA = 0x2104cc0;
constexpr uintptr_t USE_COUNTER_RVA = 0x2104f00;
constexpr uintptr_t POINT_TOKEN_RVA = 0x2104ce0;
constexpr uintptr_t POINT_COUNTER_RVA = 0x2104f80;
constexpr uintptr_t LOC_TOKEN_RVA = 0x2104d20;
constexpr uintptr_t LOC_COUNTER_RVA = 0x2104d40;
constexpr ULONGLONG TOKEN_LIFE = 15000000;      // 1.5 s, in 100 ns
constexpr uint32_t MAGIC = 0x4c564345;          // "ECVL"
constexpr uint32_t MAGIC2 = 0x4c494556;         // "VEIL"

struct Shared {
    volatile LONG tokens;
    LONG pad;
    volatile ULONGLONG expiry;
    volatile LONG veils, barriers;
};

struct Packet {
    uint32_t magic;
    uint8_t type;                               // 'H' hello, 'V' veil, 'P' point, 'T' teleport
    uint8_t pad[3];
    uint32_t id;
    uint32_t magic2;
};

uint8_t *g_base;
Shared *g_shared;
Shared *g_point;                                // POINT's tokens (+10: walls that went off)
Shared *g_loc;                                  // TRANSLOCATOR's tokens (+10: teleports shown)
bool g_server;
char g_log_path[MAX_PATH];
volatile LONG g_logged = 0;
SRWLOCK g_lock = SRWLOCK_INIT;

void Log(const char *fmt, ...) {
    if (InterlockedIncrement(&g_logged) > 2000) return;
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

Shared *Tokens(uint8_t type) { return type == 'P' ? g_point : type == 'T' ? g_loc : g_shared; }
const char *What(uint8_t type) { return type == 'P' ? "point" : type == 'T' ? "teleport" : "veil"; }
bool Carried(uint8_t type) { return type == 'V' || type == 'P' || type == 'T'; }

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

void Handle(SOCKET s, const Packet &p, const sockaddr_in &from) {
    char buf[48];
    if (g_server) {
        Remember(s, from);
        if (Carried(p.type) && FirstTime(p.id)) {
            if (p.type != 'T') AddToken(Tokens(p.type));   // a teleport has nothing to show here
            int n = Relay(from, p.type, p.id);
            Log("%s %08x from %s: %srelayed to %d client(s)", What(p.type), p.id,
                Addr(from, buf, sizeof(buf)), p.type != 'T' ? "token here, " : "", n);
        }
    } else if (Carried(p.type) && FirstTime(p.id)) {
        AddToken(Tokens(p.type));
        Log("%s %08x from the server: token here", What(p.type), p.id);
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

// Watches this machine's veil uses (client), says hello (client) and logs what the
// barrier walls decided (both).
DWORD WINAPI Tick(LPVOID) {
    volatile LONG *uses = (volatile LONG *)(g_base + USE_COUNTER_RVA);
    volatile LONG *point_uses = (volatile LONG *)(g_base + POINT_COUNTER_RVA);
    volatile LONG *loc_uses = (volatile LONG *)(g_base + LOC_COUNTER_RVA);
    LONG seen_uses = *uses, seen_veils = g_shared->veils, seen_barriers = g_shared->barriers;
    LONG seen_point_uses = *point_uses, seen_points = g_point->veils;
    LONG seen_loc_uses = *loc_uses, seen_locs = g_loc->veils;
    sockaddr_in logged_server = {};
    ULONGLONG next_hello = 0, next_pick = 0;
    for (;;) {
        Sleep(5);
        if (!g_server) {
            for (int k = 0; k < 3; ++k) {
                uint8_t type = "VPT"[k];
                LONG u = k == 2 ? *loc_uses : k ? *point_uses : *uses;
                LONG &seen = k == 2 ? seen_loc_uses : k ? seen_point_uses : seen_uses;
                if (u == seen) continue;
                seen = u;
                uint32_t id = GetTickCount() * 2654435761u ^ GetCurrentProcessId() << 16 ^ (uint32_t)u ^ k;
                FirstTime(id);
                if (type != 'T') AddToken(Tokens(type));     // a teleport is shown here already
                Dest d;
                bool ok = ServerDest(d);
                SendToServer(type, id);
                SendToServer(type, id);                          // once more, against loss
                Log(ok ? "%s used here: token here, %08x sent to the server"
                       : "%s used here: token here (%08x not sent: no game server connection seen yet)",
                    What(type), id);
            }
            ULONGLONG now = GetTickCount64();
            if (now >= next_pick) {
                next_pick = now + 1000;
                PickServer();
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
        LONG v = g_shared->veils, b = g_shared->barriers;
        if (v != seen_veils) { seen_veils = v; Log("a barrier wall took a token: UMBRAL VEIL (%ld so far)", v); }
        if (b != seen_barriers) { seen_barriers = b; Log("a barrier wall found no token: energy barrier (%ld so far)", b); }
        LONG pt = g_point->veils;
        if (pt != seen_points) { seen_points = pt; Log("a barrier wall took a point token: POINT (%ld so far)", pt); }
        LONG lc = g_loc->veils;
        if (lc != seen_locs) { seen_locs = lc; Log("a translocator puck took a teleport token: effect and sound shown (%ld so far)", lc); }
    }
}

DWORD WINAPI Install(LPVOID) {
    g_base = (uint8_t *)GetModuleHandleW(nullptr);
    g_shared = (Shared *)(g_base + TOKEN_RVA);
    g_point = (Shared *)(g_base + POINT_TOKEN_RVA);
    g_loc = (Shared *)(g_base + LOC_TOKEN_RVA);
    g_server = strstr(GetCommandLineA(), " -server") != nullptr;
    DetourTransactionBegin();
    DetourUpdateThread(GetCurrentThread());
    DetourAttach(&(PVOID &)Real_sendto, Hooked_sendto);
    DetourAttach(&(PVOID &)Real_recvfrom, Hooked_recvfrom);
    LONG rc = DetourTransactionCommit();
    if (rc != NO_ERROR) { Log("hooking sendto / recvfrom failed (%ld): UMBRAL VEIL stays local", rc); return 0; }
    Log(g_server ? "server: relaying UMBRAL VEIL over the game's own connection"
                 : "client: UMBRAL VEIL goes over the game's own connection");
    if (HANDLE t = CreateThread(nullptr, 0, Tick, nullptr, 0, nullptr)) CloseHandle(t);
    return 0;
}

} // namespace

BOOL APIENTRY DllMain(HMODULE self, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) {
        DisableThreadLibraryCalls(self);
        GetModuleFileNameA(self, g_log_path, MAX_PATH);
        if (char *slash = strrchr(g_log_path, '\\')) strcpy_s(slash + 1, MAX_PATH - (slash + 1 - g_log_path), "VeilNet.log");
        // The hooks are set up off the loader lock.
        if (HANDLE t = CreateThread(nullptr, 0, Install, nullptr, 0, nullptr)) CloseHandle(t);
    }
    return TRUE;
}
