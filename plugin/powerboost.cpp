// PowerBoost: the engine side of POWER BOOST (the cut `buff` tac mod).
//
// ability_properties.buff gives a linked teammate `dr` damage reduction for
// `dr_duration` seconds. The engine has no such buff, so this plugin adds it on
// the server, where damage is decided:
//
//   +0xcecc40  HealServer(cs, index, amount, ...)          CR15NetDamageableCS: heal one damageable
//   +0xd29770  ProcessDamageServer(cs, index, damage, ...)  CR15NetDamageableCS: damage one damageable
//
//   +0xcc0670  SendDamageDealt(cs, index, amount, type, info)  client -> server
//                                         R15NetDamageableDamageDealt message
//
// The POWER BOOST script tells the plugin whom to buff through the engine's own heal
// node: a heal of a "marker" amount, 1,000,000 + dr_permille * 1000 + seconds
// (e.g. 1,020,010 = dr 0.020 for 10 s; every such value is exact in a float).
//
// That heal node runs on the client that used the tac mod, so the marker first shows
// up in the client's HealServer. The client swallows it and sends it on as a
// DamageDealt of -marker: the server's handler for that message turns any amount <= 0
// into HealServer(-amount), so the server's HealServer sees the marker too. There it
// is swallowed again and remembered: that damageable (component system + index) is
// buffed until then, and ProcessDamageServer gets damage * (1 - dr) before any shield
// or health is taken off.
//
// All prologues are checked first; on a mismatch nothing is hooked. "-server" on the
// command line picks the server role. Log: PowerBoost.log next to the DLL.

#include <windows.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "detours.h"

namespace {

constexpr uintptr_t HEAL_RVA = 0xcecc40;
constexpr uint8_t HEAL_BYTES[] = { 0x48, 0x89, 0x5c, 0x24, 0x18, 0x56, 0x57, 0x41, 0x56, 0x48, 0x83, 0xec, 0x70 };
constexpr uintptr_t DAMAGE_RVA = 0xd29770;
constexpr uint8_t DAMAGE_BYTES[] = { 0x4c, 0x8b, 0xdc, 0x4d, 0x89, 0x4b, 0x20, 0x55, 0x53, 0x56, 0x57, 0x41, 0x54 };
constexpr uintptr_t SEND_RVA = 0xcc0670;
constexpr uint8_t SEND_BYTES[] = { 0x48, 0x89, 0x5c, 0x24, 0x10, 0x57, 0x48, 0x83, 0xec, 0x60, 0x33, 0xc0 };

constexpr float MARKER_BASE = 1000000.0f;
constexpr float MARKER_END = 2000000.0f;

using heal_fn = void(__fastcall *)(void *cs, uint32_t index, float amount, uint64_t a4, uint64_t a5);
using damage_fn = void(__fastcall *)(void *cs, uint32_t index, float damage, void *info, uint64_t a5, uint64_t a6);
heal_fn Real_Heal = nullptr;
damage_fn Real_Damage = nullptr;
using send_fn = void(__fastcall *)(void *cs, uint32_t index, float amount, uint8_t type, uint64_t info);
send_fn SendDamageDealt = nullptr;
bool g_server = false;

struct Buff {
    void *cs;
    uint16_t index;
    ULONGLONG until;      // GetTickCount64
    float mult;           // 1 - dr
};
constexpr int MAX_BUFFS = 64;
Buff g_buffs[MAX_BUFFS];
SRWLOCK g_lock = SRWLOCK_INIT;

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

void AddBuff(void *cs, uint16_t index, float dr, unsigned seconds) {
    ULONGLONG now = GetTickCount64(), until = now + seconds * 1000ull;
    AcquireSRWLockExclusive(&g_lock);
    int slot = -1;
    for (int i = 0; i < MAX_BUFFS; ++i) {
        if (g_buffs[i].cs == cs && g_buffs[i].index == index) { slot = i; break; }
        if (slot < 0 && (g_buffs[i].cs == nullptr || g_buffs[i].until <= now)) slot = i;
    }
    if (slot >= 0) g_buffs[slot] = { cs, index, until, 1.0f - dr };
    ReleaseSRWLockExclusive(&g_lock);
    Log("buff: damageable %p/%u takes x%.3f damage for %u s%s", cs, index, 1.0f - dr, seconds,
        slot < 0 ? " -- NO FREE SLOT, ignored" : "");
}

float BuffMult(void *cs, uint16_t index) {
    ULONGLONG now = GetTickCount64();
    float mult = 1.0f;
    AcquireSRWLockShared(&g_lock);
    for (int i = 0; i < MAX_BUFFS; ++i)
        if (g_buffs[i].cs == cs && g_buffs[i].index == index && g_buffs[i].until > now) { mult = g_buffs[i].mult; break; }
    ReleaseSRWLockShared(&g_lock);
    return mult;
}

void __fastcall Hooked_Heal(void *cs, uint32_t index, float amount, uint64_t a4, uint64_t a5) {
    if (amount >= MARKER_BASE && amount < MARKER_END) {
        if (!g_server) {                          // used here: hand it to the server
            Log("marker %.0f for %p/%u -> server", amount, cs, index & 0xffff);
            SendDamageDealt(cs, index, -amount, 0, 0);
            return;
        }
        unsigned v = (unsigned)(amount - MARKER_BASE + 0.5f);
        AddBuff(cs, (uint16_t)index, (v / 1000) / 1000.0f, v % 1000);
        return;                                   // a marker, not a heal
    }
    Real_Heal(cs, index, amount, a4, a5);
}

void __fastcall Hooked_Damage(void *cs, uint32_t index, float damage, void *info, uint64_t a5, uint64_t a6) {
    float mult = BuffMult(cs, (uint16_t)index);
    if (mult != 1.0f) {
        Log("damage to buffed %p/%u: %.2f -> %.2f", cs, index & 0xffff, damage, damage * mult);
        damage *= mult;
    }
    Real_Damage(cs, index, damage, info, a5, a6);
}

// True when the command line has `flag` as a whole argument (any case).
bool HasArg(const char *flag) {
    const char *cmd = GetCommandLineA();
    size_t n = strlen(flag);
    for (const char *p = cmd; p && *p; ++p)
        if ((p == cmd || p[-1] == ' ' || p[-1] == '\t') && _strnicmp(p, flag, n) == 0 &&
            (p[n] == 0 || p[n] == ' ' || p[n] == '\t' || p[n] == '"'))
            return true;
    return false;
}

bool Check(uint8_t *at, const uint8_t *bytes, size_t n, const char *name) {
    if (memcmp(at, bytes, n) == 0) return true;
    Log("prologue mismatch at %s -- wrong echovr build, not hooking", name);
    return false;
}

void Install() {
    auto base = (uint8_t *)GetModuleHandleW(nullptr);
    if (!Check(base + HEAL_RVA, HEAL_BYTES, sizeof(HEAL_BYTES), "HealServer") ||
        !Check(base + DAMAGE_RVA, DAMAGE_BYTES, sizeof(DAMAGE_BYTES), "ProcessDamageServer") ||
        !Check(base + SEND_RVA, SEND_BYTES, sizeof(SEND_BYTES), "SendDamageDealt"))
        return;
    SendDamageDealt = (send_fn)(base + SEND_RVA);
    g_server = HasArg("-server");
    Real_Heal = (heal_fn)(base + HEAL_RVA);
    Real_Damage = (damage_fn)(base + DAMAGE_RVA);
    DetourTransactionBegin();
    DetourUpdateThread(GetCurrentThread());
    DetourAttach(&(PVOID &)Real_Heal, Hooked_Heal);
    DetourAttach(&(PVOID &)Real_Damage, Hooked_Damage);
    LONG rc = DetourTransactionCommit();
    if (rc == NO_ERROR) Log("hooked HealServer and ProcessDamageServer (%s)", g_server ? "server" : "client");
    else Log("hook failed (%ld)", rc);
}

} // namespace

BOOL APIENTRY DllMain(HMODULE self, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) {
        DisableThreadLibraryCalls(self);
        GetModuleFileNameA(self, g_log_path, MAX_PATH);
        if (char *slash = strrchr(g_log_path, '\\')) strcpy_s(slash + 1, MAX_PATH - (slash + 1 - g_log_path), "PowerBoost.log");
        Install();
    }
    return TRUE;
}
