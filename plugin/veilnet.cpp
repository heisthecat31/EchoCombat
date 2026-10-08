// VeilNet: carries UMBRAL VEIL to every machine.
//
// The veil (the smoke tac mod) runs its script only on the client that used it. The
// one networked thing it does is create a barrier wall, which every machine gets.
// Nothing the script can send travels with the wall in a form the wall script can
// read back, so this plugin sends the news itself, over its own UDP socket:
//
//   client that used the veil --"V id"--> server --"V id"--> every other client
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
// Server ("-server" on the command line): listens on the first free UDP port in
// [veil] port .. port+7 (PowerBoost.ini-style VeilNet.ini, default 6970), remembers
// every client that says hello, and relays each veil to all of them but the sender.
// Several servers on one PC take one port each.
//
// Client: says hello to every port in that range on the server every 2 s (which also
// keeps a NAT mapping open for the relays), and sends each use of the veil there. The
// server's address is VeilNet.ini [veil] server=, or else the address this game
// sends most of its UDP to (sendto / WSASendTo / connected send are watched).
//
// Log: VeilNet.log next to the DLL.

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
constexpr ULONGLONG TOKEN_LIFE = 15000000;      // 1.5 s, in 100 ns
constexpr int PORTS = 8;
constexpr uint32_t MAGIC = 0x4c564345;          // "ECVL"

struct Shared {
    volatile LONG tokens;
    LONG pad;
    volatile ULONGLONG expiry;
    volatile LONG veils, barriers;
};

struct Packet {
    uint32_t magic;
    uint8_t type;                               // 'H' hello, 'V' veil
    uint8_t pad[3];
    uint32_t id;
};

uint8_t *g_base;
Shared *g_shared;
bool g_server;
int g_port_base = 6970;
SOCKET g_sock = INVALID_SOCKET;
char g_log_path[MAX_PATH];
volatile LONG g_logged = 0;

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

void AddToken() {
    ULONGLONG now = InterruptTime();
    if (now >= g_shared->expiry) InterlockedExchange(&g_shared->tokens, 0);
    InterlockedIncrement(&g_shared->tokens);
    g_shared->expiry = now + TOKEN_LIFE;
}

// The last ids seen, so a veil that arrives twice (several servers on one PC, a resend)
// gives one token.
uint32_t g_seen[32];
int g_seen_next = 0;
SRWLOCK g_lock = SRWLOCK_INIT;

bool FirstTime(uint32_t id) {
    AcquireSRWLockExclusive(&g_lock);
    bool seen = false;
    for (uint32_t s : g_seen) seen |= s == id;
    if (!seen) g_seen[g_seen_next++ % 32] = id;
    ReleaseSRWLockExclusive(&g_lock);
    return !seen;
}

// --- the server's address, as the game itself uses it -----------------------------
using sendto_fn = int(WSAAPI *)(SOCKET, const char *, int, int, const sockaddr *, int);
using wsasendto_fn = int(WSAAPI *)(SOCKET, LPWSABUF, DWORD, LPDWORD, DWORD, const sockaddr *, int,
                                   LPWSAOVERLAPPED, LPWSAOVERLAPPED_COMPLETION_ROUTINE);
using send_fn = int(WSAAPI *)(SOCKET, const char *, int, int);
using wsasend_fn = int(WSAAPI *)(SOCKET, LPWSABUF, DWORD, LPDWORD, DWORD, LPWSAOVERLAPPED,
                                 LPWSAOVERLAPPED_COMPLETION_ROUTINE);
sendto_fn Real_sendto = sendto;
wsasendto_fn Real_WSASendTo = WSASendTo;
send_fn Real_send = send;
wsasend_fn Real_WSASend = WSASend;

struct Dest { uint32_t ip; volatile LONG count; };
Dest g_dests[16];
volatile uint32_t g_server_ip = 0;              // network order; 0 = not known yet
bool g_server_fixed = false;                    // from VeilNet.ini

void Saw(const sockaddr *to) {
    if (g_server_fixed || !to || to->sa_family != AF_INET) return;
    uint32_t ip = ((const sockaddr_in *)to)->sin_addr.s_addr;
    int free_slot = -1;
    for (int i = 0; i < 16; ++i) {
        if (g_dests[i].ip == ip) {
            LONG c = InterlockedIncrement(&g_dests[i].count);
            if (g_server_ip != ip) {
                LONG best = 0;
                for (const Dest &d : g_dests) if (d.ip == g_server_ip) best = d.count;
                if (c > best + 50) g_server_ip = ip;
            }
            return;
        }
        if (!g_dests[i].ip && free_slot < 0) free_slot = i;
    }
    if (free_slot >= 0) g_dests[free_slot].ip = ip;
}

void SawSocket(SOCKET s) {
    if (s == g_sock) return;
    int type = 0, n = sizeof(type);
    if (getsockopt(s, SOL_SOCKET, SO_TYPE, (char *)&type, &n) != 0 || type != SOCK_DGRAM) return;
    sockaddr_storage peer;
    int len = sizeof(peer);
    if (getpeername(s, (sockaddr *)&peer, &len) == 0) Saw((sockaddr *)&peer);
}

int WSAAPI Hooked_sendto(SOCKET s, const char *buf, int len, int flags, const sockaddr *to, int tolen) {
    if (s != g_sock) Saw(to);
    return Real_sendto(s, buf, len, flags, to, tolen);
}
int WSAAPI Hooked_WSASendTo(SOCKET s, LPWSABUF b, DWORD n, LPDWORD sent, DWORD flags, const sockaddr *to,
                            int tolen, LPWSAOVERLAPPED o, LPWSAOVERLAPPED_COMPLETION_ROUTINE c) {
    if (s != g_sock) Saw(to);
    return Real_WSASendTo(s, b, n, sent, flags, to, tolen, o, c);
}
int WSAAPI Hooked_send(SOCKET s, const char *buf, int len, int flags) {
    SawSocket(s);
    return Real_send(s, buf, len, flags);
}
int WSAAPI Hooked_WSASend(SOCKET s, LPWSABUF b, DWORD n, LPDWORD sent, DWORD flags, LPWSAOVERLAPPED o,
                          LPWSAOVERLAPPED_COMPLETION_ROUTINE c) {
    SawSocket(s);
    return Real_WSASend(s, b, n, sent, flags, o, c);
}

void Send(const sockaddr_in &to, uint8_t type, uint32_t id) {
    Packet p = { MAGIC, type, {}, id };
    Real_sendto(g_sock, (const char *)&p, sizeof(p), 0, (const sockaddr *)&to, sizeof(to));
}

void SendToServer(uint8_t type, uint32_t id) {
    uint32_t ip = g_server_ip;
    if (!ip) return;
    sockaddr_in to = {};
    to.sin_family = AF_INET;
    to.sin_addr.s_addr = ip;
    for (int i = 0; i < PORTS; ++i) {
        to.sin_port = htons((u_short)(g_port_base + i));
        Send(to, type, id);
    }
}

// --- server: the clients it relays to -----------------------------------------------
struct Client { sockaddr_in addr; ULONGLONG last; };
Client g_clients[64];

void Remember(const sockaddr_in &a) {
    ULONGLONG now = GetTickCount64();
    int slot = -1, oldest = 0;
    for (int i = 0; i < 64; ++i) {
        Client &c = g_clients[i];
        if (c.addr.sin_addr.s_addr == a.sin_addr.s_addr && c.addr.sin_port == a.sin_port) { c.last = now; return; }
        if (!c.last && slot < 0) slot = i;
        if (c.last < g_clients[oldest].last) oldest = i;
    }
    if (slot < 0) slot = oldest;
    g_clients[slot] = { a, now };
    char buf[48];
    Log("client %s says hello", Addr(a, buf, sizeof(buf)));
}

DWORD WINAPI Receive(LPVOID) {
    for (;;) {
        Packet p;
        sockaddr_in from;
        int flen = sizeof(from);
        int n = recvfrom(g_sock, (char *)&p, sizeof(p), 0, (sockaddr *)&from, &flen);
        if (n == SOCKET_ERROR) {
            if (WSAGetLastError() == WSAECONNRESET) continue;    // an earlier send hit a closed port
            Sleep(100);
            continue;
        }
        if (n != sizeof(p) || p.magic != MAGIC) continue;
        char buf[48];
        if (g_server) {
            Remember(from);
            if (p.type != 'V' || !FirstTime(p.id)) continue;
            AddToken();
            ULONGLONG now = GetTickCount64();
            int relayed = 0;
            for (const Client &c : g_clients)
                if (c.last && now - c.last < 30000 &&
                    !(c.addr.sin_addr.s_addr == from.sin_addr.s_addr && c.addr.sin_port == from.sin_port)) {
                    Send(c.addr, 'V', p.id);
                    ++relayed;
                }
            Log("veil %08x from %s: token here, relayed to %d client(s)", p.id, Addr(from, buf, sizeof(buf)), relayed);
        } else if (p.type == 'V' && FirstTime(p.id)) {
            AddToken();
            Log("veil %08x from %s: token here", p.id, Addr(from, buf, sizeof(buf)));
        }
    }
}

// Watches this machine's veil uses (client), says hello (client) and logs what the
// barrier walls decided (both).
DWORD WINAPI Tick(LPVOID) {
    volatile LONG *uses = (volatile LONG *)(g_base + USE_COUNTER_RVA);
    LONG seen_uses = *uses, seen_veils = g_shared->veils, seen_barriers = g_shared->barriers;
    uint32_t logged_server = 0;
    ULONGLONG next_hello = 0;
    for (;;) {
        Sleep(5);
        if (!g_server) {
            LONG u = *uses;
            if (u != seen_uses) {
                seen_uses = u;
                uint32_t id = GetTickCount() * 2654435761u ^ GetCurrentProcessId() << 16 ^ (uint32_t)u;
                FirstTime(id);
                AddToken();
                SendToServer('V', id);
                SendToServer('V', id);                           // once more, against loss
                Log("veil used here: token here, veil %08x sent to the server", id);
            }
            ULONGLONG now = GetTickCount64();
            if (now >= next_hello) {
                next_hello = now + 2000;
                SendToServer('H', 0);
                if (g_server_ip != logged_server) {
                    logged_server = g_server_ip;
                    char ip[32];
                    in_addr a;
                    a.s_addr = logged_server;
                    inet_ntop(AF_INET, &a, ip, sizeof(ip));
                    Log("server %s (udp %d-%d)%s", ip, g_port_base, g_port_base + PORTS - 1,
                        g_server_fixed ? ", from VeilNet.ini" : "");
                }
            }
        }
        LONG v = g_shared->veils, b = g_shared->barriers;
        if (v != seen_veils) { seen_veils = v; Log("a barrier wall took a token: UMBRAL VEIL (%ld so far)", v); }
        if (b != seen_barriers) { seen_barriers = b; Log("a barrier wall found no token: energy barrier (%ld so far)", b); }
    }
}

DWORD WINAPI Install(LPVOID) {
    g_base = (uint8_t *)GetModuleHandleW(nullptr);
    g_shared = (Shared *)(g_base + TOKEN_RVA);
    const char *cmd = GetCommandLineA();
    g_server = strstr(cmd, " -server") != nullptr;

    char ini[MAX_PATH], server[64];
    strcpy_s(ini, g_log_path);
    if (char *dot = strrchr(ini, '.')) strcpy_s(dot, MAX_PATH - (dot - ini), ".ini");
    g_port_base = GetPrivateProfileIntA("veil", "port", 6970, ini);
    GetPrivateProfileStringA("veil", "server", "", server, sizeof(server), ini);

    WSADATA wsa;
    if (WSAStartup(MAKEWORD(2, 2), &wsa) != 0) { Log("WSAStartup failed"); return 0; }
    if (server[0]) {
        in_addr a;
        if (inet_pton(AF_INET, server, &a) == 1) { g_server_ip = a.s_addr; g_server_fixed = true; }
        else Log("VeilNet.ini server=%s is not an IPv4 address; finding the server from the game's traffic", server);
    }

    g_sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    if (g_sock == INVALID_SOCKET) { Log("socket failed (%d)", WSAGetLastError()); return 0; }
    sockaddr_in me = {};
    me.sin_family = AF_INET;
    me.sin_addr.s_addr = INADDR_ANY;
    int port = 0;
    if (g_server) {
        for (int i = 0; i < PORTS && !port; ++i) {
            me.sin_port = htons((u_short)(g_port_base + i));
            if (bind(g_sock, (sockaddr *)&me, sizeof(me)) == 0) port = g_port_base + i;
        }
        if (!port) { Log("server: no free udp port in %d-%d", g_port_base, g_port_base + PORTS - 1); return 0; }
        Log("server: listening on udp %d", port);
    } else if (bind(g_sock, (sockaddr *)&me, sizeof(me)) != 0) {
        Log("bind failed (%d)", WSAGetLastError());
        return 0;
    }

    if (!g_server) {
        DetourTransactionBegin();
        DetourUpdateThread(GetCurrentThread());
        DetourAttach(&(PVOID &)Real_sendto, Hooked_sendto);
        DetourAttach(&(PVOID &)Real_WSASendTo, Hooked_WSASendTo);
        DetourAttach(&(PVOID &)Real_send, Hooked_send);
        DetourAttach(&(PVOID &)Real_WSASend, Hooked_WSASend);
        LONG rc = DetourTransactionCommit();
        if (rc != NO_ERROR) Log("watching the game's sends failed (%ld): set [veil] server= in VeilNet.ini", rc);
        Log("client: veil uses go to the server on udp %d-%d", g_port_base, g_port_base + PORTS - 1);
    }
    if (HANDLE t = CreateThread(nullptr, 0, Receive, nullptr, 0, nullptr)) CloseHandle(t);
    if (HANDLE t = CreateThread(nullptr, 0, Tick, nullptr, 0, nullptr)) CloseHandle(t);
    return 0;
}

} // namespace

BOOL APIENTRY DllMain(HMODULE self, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) {
        DisableThreadLibraryCalls(self);
        GetModuleFileNameA(self, g_log_path, MAX_PATH);
        if (char *slash = strrchr(g_log_path, '\\')) strcpy_s(slash + 1, MAX_PATH - (slash + 1 - g_log_path), "VeilNet.log");
        // Winsock and the hooks are set up off the loader lock.
        if (HANDLE t = CreateThread(nullptr, 0, Install, nullptr, 0, nullptr)) CloseHandle(t);
    }
    return TRUE;
}
