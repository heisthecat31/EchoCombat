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
// Phase 2, the link. POWER BOOST's bubble is Repair Matrix's heal bubble, and the
// bubble already links to and heals every target within its radius:
//
//   +0xd6d1d0  CR15NetHealBubbleCS::UpdateActiveHealBubble(handle, dt)
//   +0xd6dcc6    radius check: |target - owner|^2 >= radius^2 -> unlink
//
// fix_buff.py gives POWER BOOST's bubble radius len + init_angle / 100000 (12.00037
// = 12 m, 37 deg). The radius check is patched to call ConeFilter first: for such a
// bubble, a target also needs to be within that angle of the owner's aim, and a
// target that passes gets the dr buff. The bubble's targeting runs on clients only,
// so the client that used POWER BOOST sends each link to the server as a link marker
// (2,000,000 + the same encoding), the way it sends the use marker (see LinkMade). Repair Matrix (a whole radius) is untouched. The owner is
// looked up the way the function does it (+0x44cc40, +0x638830): position at +8F8h,
// orientation quaternion (x, y, z, w) at +BD0h. Which local axis is "aim" is set by
// axis= in PowerBoost.ini ([cone], default +z); the log shows the angle to each
// target along all six axes so the right one can be picked.
//
// All prologues are checked first; on a mismatch nothing is hooked. "-server" on the
// command line picks the server role. Log: PowerBoost.log next to the DLL.

#include <windows.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <math.h>
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
constexpr float LINK_BASE = 2000000.0f;   // link marker: the client's "I linked this one" (same encoding)
constexpr float LINK_END = 3000000.0f;

using heal_fn = void(__fastcall *)(void *cs, uint32_t index, float amount, uint64_t a4, uint64_t a5);
using damage_fn = void(__fastcall *)(void *cs, uint32_t index, float damage, void *info, uint64_t a5, uint64_t a6);
heal_fn Real_Heal = nullptr;
damage_fn Real_Damage = nullptr;
using send_fn = void(__fastcall *)(void *cs, uint32_t index, float amount, uint8_t type, uint64_t info);
send_fn SendDamageDealt = nullptr;
bool g_server = false;

constexpr uintptr_t RADIUS_RVA = 0xd6dcc6;
constexpr uint8_t RADIUS_BYTES[] = { 0x4c, 0x8b, 0x7d, 0xc8,                    // mov r15, [rbp-38h]
                                     0xf3, 0x41, 0x0f, 0x10, 0x47, 0x38,        // movss xmm0, [r15+38h]
                                     0xf3, 0x0f, 0x59, 0xc0,                    // mulss xmm0, xmm0
                                     0x0f, 0x2f, 0xc8 };                        // comiss xmm1, xmm0
constexpr uintptr_t OWNER_HANDLE_RVA = 0x44cc40;
constexpr uint8_t OWNER_HANDLE_BYTES[] = { 0x40, 0x53, 0x48, 0x83, 0xec, 0x20, 0x48, 0x8b, 0x81, 0xc8, 0x00, 0x00, 0x00 };
constexpr uintptr_t OWNER_OBJECT_RVA = 0x638830;
constexpr uint8_t OWNER_OBJECT_BYTES[] = { 0x44, 0x8b, 0x49, 0x08, 0x41, 0x83, 0xf9, 0xff };
using handle_fn = void *(__fastcall *)(void *cs, void *out, uint32_t index);
using object_fn = uint8_t *(__fastcall *)(void *handle);
handle_fn OwnerHandle = nullptr;
object_fn OwnerObject = nullptr;

volatile float g_dr = 0.09f;               // from the latest marker
volatile unsigned g_dr_seconds = 10;
volatile ULONGLONG g_used_at = 0;         // when this client last used POWER BOOST
float g_axis[3] = { 0, 0, 1 };            // owner-local aim axis (PowerBoost.ini [cone] axis=)

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

// Buffs (cs, index) for `seconds`. Unless `refresh`, a buff still running is left as is.
void AddBuff(void *cs, uint16_t index, float dr, unsigned seconds, bool refresh = true) {
    ULONGLONG now = GetTickCount64(), until = now + seconds * 1000ull;
    AcquireSRWLockExclusive(&g_lock);
    int slot = -1;
    for (int i = 0; i < MAX_BUFFS; ++i) {
        if (g_buffs[i].cs == cs && g_buffs[i].index == index) {
            if (!refresh && g_buffs[i].until > now) { ReleaseSRWLockExclusive(&g_lock); return; }
            slot = i;
            break;
        }
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
        g_dr = (v / 1000) / 1000.0f;              // what the link hands out (see ConeFilter)
        g_dr_seconds = v % 1000;
        if (!g_server) {                          // used here: hand it to the server
            g_used_at = GetTickCount64();
            Log("marker %.0f for %p/%u -> server", amount, cs, index & 0xffff);
            SendDamageDealt(cs, index, -amount, 0, 0);
            return;
        }
        Log("POWER BOOST used by %p/%u: links give x%.3f damage for %u s", cs, index & 0xffff,
            1.0f - g_dr, (unsigned)g_dr_seconds);
        return;                                   // a marker, not a heal
    }
    if (amount >= LINK_BASE && amount < LINK_END) {
        if (g_server) {                           // a client linked this damageable
            unsigned v = (unsigned)(amount - LINK_BASE + 0.5f);
            AddBuff(cs, (uint16_t)index, (v / 1000) / 1000.0f, v % 1000, false);
        }
        return;
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

// q (x, y, z, w) applied to v.
void Rotate(const float *q, const float *v, float *out) {
    float t[3] = { 2 * (q[1] * v[2] - q[2] * v[1]), 2 * (q[2] * v[0] - q[0] * v[2]), 2 * (q[0] * v[1] - q[1] * v[0]) };
    out[0] = v[0] + q[3] * t[0] + (q[1] * t[2] - q[2] * t[1]);
    out[1] = v[1] + q[3] * t[1] + (q[2] * t[0] - q[0] * t[2]);
    out[2] = v[2] + q[3] * t[2] + (q[0] * t[1] - q[1] * t[0]);
}

float AngleTo(const float *q, const float *axis, const float *d, float dist) {
    float f[3];
    Rotate(q, axis, f);
    float len = sqrtf(f[0] * f[0] + f[1] * f[1] + f[2] * f[2]);
    float c = (f[0] * d[0] + f[1] * d[1] + f[2] * d[2]) / (len * dist);
    return acosf(c < -1 ? -1 : c > 1 ? 1 : c) * 57.29578f;
}

// A link to (dcs, index). The bubble's targeting only runs on clients, so the client
// that used POWER BOOST (it sent a marker within the last 30 s) tells the server, at
// most once a second per target: a DamageDealt of -(link marker), which the server's
// handler turns into a heal of the marker, where Hooked_Heal buffs that damageable
// (a buff still running is left as is). Other clients see the same link and stay quiet.
void LinkMade(void *dcs, uint32_t index) {
    ULONGLONG now = GetTickCount64();
    if (g_server) { AddBuff(dcs, (uint16_t)index, g_dr, g_dr_seconds, false); return; }
    if (g_used_at == 0 || now - g_used_at > 30000) return;
    static struct { void *cs; uint16_t index; ULONGLONG at; } sent[16];
    int slot = 0;
    for (int i = 0; i < 16; ++i) {
        if (sent[i].cs == dcs && sent[i].index == (uint16_t)index) { slot = i; break; }
        if (sent[i].at < sent[slot].at) slot = i;
    }
    if (sent[slot].cs == dcs && sent[slot].index == (uint16_t)index && now - sent[slot].at < 1000) return;
    sent[slot] = { dcs, (uint16_t)index, now };
    float marker = LINK_BASE + (float)((unsigned)(g_dr * 1000.0f + 0.5f) * 1000 + g_dr_seconds);
    Log("link to %p/%u -> server (marker %.0f)", dcs, index & 0xffff, marker);
    SendDamageDealt(dcs, index, -marker, 0, 0);
}

// Called from the bubble's radius check (see InstallCone). Returns 0 to treat the
// target as out of range. bubble: the bubble's record; target: its position;
// dcs/index: the target's damageable.
int __fastcall ConeFilter(uint8_t *bubble, const float *target, void *dcs, uint32_t index) {
    float radius = *(float *)(bubble + 0x38);
    int angle = (int)((radius - floorf(radius)) * 100000.0f + 0.5f);
    if (angle < 1 || angle > 180) return 1;               // not POWER BOOST's bubble
    uint8_t handle[64] = {};
    void *h = OwnerHandle(*(void **)bubble, handle, *(uint32_t *)(bubble + 8));
    uint8_t *owner = h ? OwnerObject(h) : nullptr;
    if (!owner) return 0;
    const float *pos = (const float *)(owner + 0x8f8), *q = (const float *)(owner + 0xbd0);
    float d[3] = { target[0] - pos[0], target[1] - pos[1], target[2] - pos[2] };
    float dist = sqrtf(d[0] * d[0] + d[1] * d[1] + d[2] * d[2]);
    if (dist < 0.3f) return 0;                            // the owner: never self-linked
    float off = AngleTo(q, g_axis, d, dist);
    bool ok = off <= (float)angle;

    static ULONGLONG last;                                // diagnostics, twice a second
    ULONGLONG now = GetTickCount64();
    if (now - last >= 500) {
        last = now;
        static const float axes[6][3] = { {1,0,0}, {-1,0,0}, {0,1,0}, {0,-1,0}, {0,0,1}, {0,0,-1} };
        float a[6];
        for (int i = 0; i < 6; ++i) a[i] = AngleTo(q, axes[i], d, dist);
        Log("cone: target %p/%u at %.1f m, %.0f deg off aim (max %d) -> %s | +x %.0f -x %.0f +y %.0f -y %.0f "
            "+z %.0f -z %.0f | q %.2f %.2f %.2f %.2f", dcs, index & 0xffff, dist, off, angle,
            ok ? "LINK" : "no", a[0], a[1], a[2], a[3], a[4], a[5], q[0], q[1], q[2], q[3]);
    }
    if (ok) LinkMade(dcs, index);
    return ok;
}

// The radius check, 14 bytes at +0xd6dcc6, becomes an absolute jump to this stub:
// the original three instructions, then ConeFilter (volatile registers saved); a
// rejected target gets radius^2 = 0, so the check that follows unlinks it.
bool InstallCone(uint8_t *base) {
    uint8_t *site = base + RADIUS_RVA;
    uint8_t *stub = (uint8_t *)VirtualAlloc(nullptr, 256, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE);
    if (!stub) return false;
    uint8_t code[] = {
        0x4c, 0x8b, 0x7d, 0xc8,                         // mov r15, [rbp-38h]
        0xf3, 0x41, 0x0f, 0x10, 0x47, 0x38,             // movss xmm0, [r15+38h]
        0xf3, 0x0f, 0x59, 0xc0,                         // mulss xmm0, xmm0
        0x50, 0x51, 0x52, 0x41, 0x50, 0x41, 0x51, 0x41, 0x52, 0x41, 0x53,   // push rax rcx rdx r8-r11
        0x48, 0x81, 0xec, 0x88, 0x00, 0x00, 0x00,       // sub rsp, 88h (aligned again)
        0xf3, 0x0f, 0x7f, 0x44, 0x24, 0x20,             // movdqu [rsp+20h], xmm0
        0xf3, 0x0f, 0x7f, 0x4c, 0x24, 0x30,             // movdqu [rsp+30h], xmm1
        0xf3, 0x0f, 0x7f, 0x54, 0x24, 0x40,             // movdqu [rsp+40h], xmm2
        0xf3, 0x0f, 0x7f, 0x5c, 0x24, 0x50,             // movdqu [rsp+50h], xmm3
        0xf3, 0x0f, 0x7f, 0x64, 0x24, 0x60,             // movdqu [rsp+60h], xmm4
        0xf3, 0x0f, 0x7f, 0x6c, 0x24, 0x70,             // movdqu [rsp+70h], xmm5
        0x4c, 0x89, 0xf9,                               // mov rcx, r15      bubble
        0x48, 0x8d, 0x95, 0x10, 0x01, 0x00, 0x00,       // lea rdx, [rbp+110h] target position
        0x4d, 0x89, 0xe8,                               // mov r8, r13       target damageable cs
        0x41, 0x89, 0xd9,                               // mov r9d, ebx      ... and index
        0x48, 0xb8, 0, 0, 0, 0, 0, 0, 0, 0,             // mov rax, ConeFilter
        0xff, 0xd0,                                     // call rax
        0x85, 0xc0,                                     // test eax, eax
        0x75, 0x08,                                     // jnz keep
        0xc7, 0x44, 0x24, 0x20, 0x00, 0x00, 0x00, 0x00, // mov dword [rsp+20h], 0 (radius^2 = 0)
        0xf3, 0x0f, 0x6f, 0x44, 0x24, 0x20,             // keep: movdqu xmm0, [rsp+20h]
        0xf3, 0x0f, 0x6f, 0x4c, 0x24, 0x30,
        0xf3, 0x0f, 0x6f, 0x54, 0x24, 0x40,
        0xf3, 0x0f, 0x6f, 0x5c, 0x24, 0x50,
        0xf3, 0x0f, 0x6f, 0x64, 0x24, 0x60,
        0xf3, 0x0f, 0x6f, 0x6c, 0x24, 0x70,
        0x48, 0x81, 0xc4, 0x88, 0x00, 0x00, 0x00,       // add rsp, 88h
        0x41, 0x5b, 0x41, 0x5a, 0x41, 0x59, 0x41, 0x58, 0x5a, 0x59, 0x58,   // pop r11-r8 rdx rcx rax
        0xff, 0x25, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, // jmp [rip+0] -> the comiss after the site
    };
    uint64_t fn = (uint64_t)&ConeFilter, back = (uint64_t)(site + 14);
    size_t at_fn = 0, at_back = sizeof(code) - 8;
    for (size_t i = 0; i + 1 < sizeof(code); ++i)
        if (code[i] == 0x48 && code[i + 1] == 0xb8) { at_fn = i + 2; break; }
    memcpy(code + at_fn, &fn, 8);
    memcpy(code + at_back, &back, 8);
    memcpy(stub, code, sizeof(code));
    uint8_t jump[14] = { 0xff, 0x25, 0, 0, 0, 0 };      // jmp [rip+0] -> stub
    uint64_t to = (uint64_t)stub;
    memcpy(jump + 6, &to, 8);
    DWORD old;
    if (!VirtualProtect(site, sizeof(jump), PAGE_EXECUTE_READWRITE, &old)) return false;
    memcpy(site, jump, sizeof(jump));
    VirtualProtect(site, sizeof(jump), old, &old);
    FlushInstructionCache(GetCurrentProcess(), site, sizeof(jump));
    return true;
}

void ReadIni() {
    char ini[MAX_PATH], axis[16];
    strcpy_s(ini, g_log_path);
    if (char *dot = strrchr(ini, '.')) strcpy_s(dot, MAX_PATH - (dot - ini), ".ini");
    GetPrivateProfileStringA("cone", "axis", "+z", axis, sizeof(axis), ini);
    int i = axis[1] == 'x' || axis[1] == 'X' ? 0 : axis[1] == 'y' || axis[1] == 'Y' ? 1 : 2;
    g_axis[0] = g_axis[1] = g_axis[2] = 0;
    g_axis[i] = axis[0] == '-' ? -1.0f : 1.0f;
    Log("cone aim axis %s", axis);
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
    if (Check(base + RADIUS_RVA, RADIUS_BYTES, sizeof(RADIUS_BYTES), "heal bubble radius check") &&
        Check(base + OWNER_HANDLE_RVA, OWNER_HANDLE_BYTES, sizeof(OWNER_HANDLE_BYTES), "owner handle") &&
        Check(base + OWNER_OBJECT_RVA, OWNER_OBJECT_BYTES, sizeof(OWNER_OBJECT_BYTES), "owner object")) {
        OwnerHandle = (handle_fn)(base + OWNER_HANDLE_RVA);
        OwnerObject = (object_fn)(base + OWNER_OBJECT_RVA);
        ReadIni();
        Log(InstallCone(base) ? "POWER BOOST link: cone on the heal bubble radius check" : "cone patch failed");
    }
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
