// PowerBoost: the engine side of POWER BOOST (the cut `buff` tac mod).
//
// ability_properties.buff gives a linked teammate `dr` damage reduction for
// `dr_duration` seconds. The engine has no such buff, so this plugin adds it on
// the server, where damage is decided:
//
//   +0xcecc40  HealServer(cs, index, amount, ...)          CR15NetDamageableCS: heal one damageable
//   +0xd29770  ProcessDamageServer(cs, index, damage, ...)  CR15NetDamageableCS: damage one damageable
//
// The POWER BOOST script tells the plugin whom to buff through the engine's own heal
// node: a heal of a "marker" amount, 1,000,000 + dr_permille * 1000 + seconds
// (e.g. 1,020,010 = dr 0.020 for 10 s; every such value is exact in a float). The
// HealServer hook recognises it, remembers that damageable (component system +
// index) as buffed until then, and swallows it. While buffed, ProcessDamageServer
// gets damage * (1 - dr) before any shield or health is taken off.
//
// Both prologues are checked first; on a mismatch nothing is hooked. Server only in
// effect (clients never run these). Log: PowerBoost.log next to the DLL.

#include <windows.h>
#include <stdint.h>
#include <stdio.h>
#include "detours.h"

namespace {

constexpr uintptr_t HEAL_RVA = 0xcecc40;
constexpr uint8_t HEAL_BYTES[] = { 0x48, 0x89, 0x5c, 0x24, 0x18, 0x56, 0x57, 0x41, 0x56, 0x48, 0x83, 0xec, 0x70 };
constexpr uintptr_t DAMAGE_RVA = 0xd29770;
constexpr uint8_t DAMAGE_BYTES[] = { 0x4c, 0x8b, 0xdc, 0x4d, 0x89, 0x4b, 0x20, 0x55, 0x53, 0x56, 0x57, 0x41, 0x54 };

constexpr float MARKER_BASE = 1000000.0f;
constexpr float MARKER_END = 2000000.0f;

using heal_fn = void(__fastcall *)(void *cs, uint32_t index, float amount, uint64_t a4, uint64_t a5);
using damage_fn = void(__fastcall *)(void *cs, uint32_t index, float damage, void *info, uint64_t a5, uint64_t a6);
heal_fn Real_Heal = nullptr;
damage_fn Real_Damage = nullptr;

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

bool Check(uint8_t *at, const uint8_t *bytes, size_t n, const char *name) {
    if (memcmp(at, bytes, n) == 0) return true;
    Log("prologue mismatch at %s -- wrong echovr build, not hooking", name);
    return false;
}

void Install() {
    auto base = (uint8_t *)GetModuleHandleW(nullptr);
    if (!Check(base + HEAL_RVA, HEAL_BYTES, sizeof(HEAL_BYTES), "HealServer") ||
        !Check(base + DAMAGE_RVA, DAMAGE_BYTES, sizeof(DAMAGE_BYTES), "ProcessDamageServer"))
        return;
    Real_Heal = (heal_fn)(base + HEAL_RVA);
    Real_Damage = (damage_fn)(base + DAMAGE_RVA);
    DetourTransactionBegin();
    DetourUpdateThread(GetCurrentThread());
    DetourAttach(&(PVOID &)Real_Heal, Hooked_Heal);
    DetourAttach(&(PVOID &)Real_Damage, Hooked_Damage);
    LONG rc = DetourTransactionCommit();
    Log(rc == NO_ERROR ? "hooked HealServer and ProcessDamageServer" : "hook failed (%ld)", rc);
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
