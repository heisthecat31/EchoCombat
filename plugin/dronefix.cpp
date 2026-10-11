// DroneFix: keeps the cut DRONE ordnance from crashing Echo VR.
//
// The drone's actor carries a CR15NetFollowPlayerCS component (it orbits its owner). That system
// follows ONE player, held on the system itself: a body-system pointer at +0x140 and the player's
// index at +0x190, filled in when a script runs R15FollowPlayerSetOrbitNode. Its update
//   +0xd65cb0  CR15NetFollowPlayerCS::Update(cs)
// walks every enabled follow component and reads that player's transform through +0x140 with no
// check. Once the drone runs the shared magazine script (fix_drone_script.py) its components are
// enabled as soon as it spawns in the pouch -- before any orbit target exists -- and the update
// dereferences a null +0x140 (crash at echovr+0x742aaa, GetCurrentTransform).
//
// The hook skips the update until a target is set, and contains an access violation inside it
// rather than letting it take the game down. The prologue is verified first; on a mismatch
// nothing is hooked (and nEVR unloads the plugin). A nEVR plugin (nevr_plugin.h): hooked from
// NvrPluginInitEx, unhooked in NvrPluginShutdown. Log (built with ECHOCOMBAT_LOG):
// plugin_logs\DroneFix\DroneFix.log.
//
// It also fires the drone's bullets from its gun. CR15NetAutoTargetCS aims by turning the
// drone's ROOT transform toward the target (+Z at it) and spawns each bullet at that root:
//   +0xce2550  CR15NetAutoTargetCS::FireBulletLocal(cs, handle, velocity, remote)
//   +0xce27e3    call CTransformCS::get(transforms, &out, root)   -> the bullet's spawn pose
// which is the middle of the drone, not the gun on its top (tools/fix_drone_model.py). That
// one call is redirected to MuzzleTransform, which moves the pose by MUZZLE, the gun's
// muzzle in the drone, turned the way AttackTarget turns the drone for this shot: +Z along
// the bullet's velocity, +Y as near world up as it can be. (Not the root's rotation: that
// is set through a deferred queue, so at the shot it can still be the last one, and differ
// between the server and the clients.) FireBulletLocal is hooked only to hand its velocity
// to MuzzleTransform. Every auto-target component is the drone's, and both the server's and
// the clients' shots go through it. Each bullet starts a frame's travel behind the muzzle,
// so it is first drawn there (see TickFrame). The first SHOT_LOG shots are logged.

#include <windows.h>
#include <stdint.h>
#include <stdio.h>
#include <math.h>
#include <string.h>
#include "detours.h"
#include "nevr_plugin.h"

namespace {

constexpr uintptr_t FOLLOW_UPDATE_RVA = 0xd65cb0;
constexpr uint8_t FOLLOW_UPDATE_BYTES[] = { 0x48, 0x89, 0x5c, 0x24, 0x10, 0x57, 0x48, 0x83, 0xec, 0x20, 0x48, 0x8b, 0xd9 };
constexpr uintptr_t TARGET_BODY_SYSTEM = 0x140;

using follow_update_fn = void(__fastcall *)(uintptr_t);
follow_update_fn Real_FollowUpdate = nullptr;

constexpr uintptr_t FIRE_GET_CALL_RVA = 0xce27e3;           // in FireBulletLocal
constexpr uintptr_t TRANSFORM_GET_RVA = 0x3c4470;           // CTransformCS::get
constexpr uint8_t FIRE_GET_CALL_BYTES[] = { 0xe8, 0x88, 0x1c, 0x6e, 0xff, 0x0f, 0x10, 0x45, 0x40 };
// the gun's muzzle in the drone (x, y, z; metres): fix_drone_model.py's MUZZLE
constexpr float MUZZLE[3] = { 0.000024f, 0.075634f, 0.147283f };

constexpr uintptr_t FIRE_LOCAL_RVA = 0xce2550;              // CR15NetAutoTargetCS::FireBulletLocal
constexpr uint8_t FIRE_LOCAL_BYTES[] = { 0x44, 0x89, 0x4c, 0x24, 0x20, 0x55, 0x53, 0x57, 0x41, 0x54 };
constexpr LONG SHOT_LOG = 40;

// The drone's script shows / hides its gun with an EnableComponentNode on (ncaModel, GUN),
// but nothing hides the satellite (another model component, fix_drone_model.py), so it
// outlived the gun. Every such node on GUN is repeated for SATELLITE.
//   +0x12478d0  CEnableComponentNode::Enter(node, data): data = { actor, scope, system,
//               component, enable }
constexpr uintptr_t ENABLE_ENTER_RVA = 0x12478d0;
constexpr uint8_t ENABLE_ENTER_BYTES[] = { 0x40, 0x55, 0x56, 0x57, 0x48, 0x83, 0xec, 0x30, 0x48, 0x8b, 0x01 };
constexpr uint64_t NCA_MODEL = 0x38EE951A26FB816Aull;       // CSymbol64("ncaModel")
constexpr uint64_t GUN = 0x72F91FFFA17C3C8Cull;
constexpr uint64_t SATELLITE = 0x106C63A2927B7A4Dull;
// the port on the body's front (fix_drone_model.py's PORT_COMP: a detonator part the drone's
// script shows once deployed; 0xA977.. is the one it shows only in the hand)
constexpr uint64_t PORT = 0x45B09F0FA9F7FA33ull;
using enable_enter_fn = void(__fastcall *)(void *, const uint64_t *);
enable_enter_fn Real_EnableEnter = nullptr;
volatile LONG g_mirrored = 0;

// CTransformCS::get's output: rotation (x, y, z, w), then position
struct Pose { float q[4]; float p[3]; float s; };
using transform_get_fn = Pose *(__fastcall *)(void *, Pose *, uint32_t);
transform_get_fn Real_TransformGet = nullptr;
using fire_local_fn = void(__fastcall *)(void *, uint32_t, const float *, int);
fire_local_fn Real_FireLocal = nullptr;
thread_local const float *t_velocity = nullptr;             // the shot FireBulletLocal is making
thread_local int t_remote = 0;

char g_log_path[MAX_PATH];
volatile LONG g_muzzle_shots = 0;
volatile LONG g_skipped = 0;
volatile LONG g_faults = 0;

void Log(const char *fmt, ...) {
    // Off unless built with ECHOCOMBAT_LOG: a release writes no log, so slow PCs pay
    // nothing for it.
#ifdef ECHOCOMBAT_LOG
    FILE *f = nullptr;
    if (fopen_s(&f, g_log_path, "a") != 0 || !f) return;
    SYSTEMTIME t;
    GetLocalTime(&t);
    fprintf(f, "[%02d:%02d:%02d] ", t.wHour, t.wMinute, t.wSecond);
    va_list args;
    va_start(args, fmt);
    vfprintf(f, fmt, args);
    va_end(args);
    fputc('\n', f);
    fclose(f);
#else
    (void)fmt;
#endif
}

bool CallGuarded(uintptr_t cs) {
    __try {
        Real_FollowUpdate(cs);
        return true;
    } __except (GetExceptionCode() == EXCEPTION_ACCESS_VIOLATION ? EXCEPTION_EXECUTE_HANDLER : EXCEPTION_CONTINUE_SEARCH) {
        return false;
    }
}

// The game's frame time, from the follow-player update (once a frame): a bullet is first
// drawn after its first step, a frame's travel from where it is spawned (at 120 m/s and
// 45-90 fps, 1.3-2.7 m out), so it is spawned a frame behind the muzzle.
LARGE_INTEGER g_qpf, g_last_frame;
volatile float g_frame_dt = 1.0f / 90.0f;

void TickFrame() {
    LARGE_INTEGER now;
    QueryPerformanceCounter(&now);
    if (g_last_frame.QuadPart) {
        float dt = (float)(now.QuadPart - g_last_frame.QuadPart) / (float)g_qpf.QuadPart;
        if (dt > 1.0f / 240.0f && dt < 0.1f)
            g_frame_dt = g_frame_dt * 0.9f + dt * 0.1f;
    }
    g_last_frame = now;
}

// shared by the death and grab rules below
constexpr uint64_t DRONE_ACTOR = 0x10E40287A9BF5A13ull;
using disable_fn = void(__fastcall *)(void *system, uint32_t index, uint16_t flag);
disable_fn Real_Disable = nullptr;

// --- the drone dies when its health runs out --------------------------------------------
// fix_drone_health.py gives the drone's damageable real health, and ProcessDamageServer kills
// it at 0 (the dead flag, then the death routine DEATH_RVA), but for anything that is not a
// player nothing happens after that. So: at each release, every component the drone's script
// turns on (CEnableComponentNode::Enter -> ENABLE_COMP_RVA (component system, index)) goes
// into that drone's group, its damageable first (a new life: health back to full and the dead
// flag off, as nothing else ever revives an ordnance). When that damageable's death routine
// runs (on the server; VeilNet.dll then tells the clients, DroneFix_Killed), the group's
// components are turned off, and kept off whatever the script does, until the next release:
// the drone is gone, and its life and cooldown run out as they would.
constexpr uintptr_t ENABLE_COMP_RVA = 0x160070;                  // (component system, index, flag): enable
constexpr uint8_t ENABLE_COMP_BYTES[] = { 0x48, 0x89, 0x5c, 0x24, 0x20, 0x55, 0x56, 0x41, 0x56 };
constexpr uintptr_t DEATH_RVA = 0xccf3a0;                        // CR15NetDamageableCS death (cs, index)
constexpr uint8_t DEATH_BYTES[] = { 0x48, 0x89, 0x5c, 0x24, 0x08, 0x48, 0x89, 0x6c, 0x24, 0x10 };
constexpr uint64_t R14_DAMAGEABLE = 0xC9DC08CFC2F5920Full;      // CSymbol64("R14NetDamageable")
//: the drone death token (fix_drone_fx.py's DEATH_TOKEN_RVA): +00 count, +08 expiry, +10 shown
constexpr uintptr_t DEATH_TOKEN_RVA = 0x2104D60;
//: the system the drone's script turns off first when its lifetime ends (all of it): its sound
constexpr uint64_t DRONE_SOUND = 0x5B8CC538E22AD937ull;
// (test) each deployed drone killed on the server this long after release, as a hit to 0
// health does (own-team bullets can't hit own ordnance, so it can't be shot alone); 0 = off
constexpr ULONGLONG KILL_TEST_MS = 0;
using enable_comp_fn = void(__fastcall *)(void *system, uint32_t index, uint16_t flag);
using death_fn = void(__fastcall *)(void *cs, uint32_t index);
enable_comp_fn Real_EnableComp = nullptr;
death_fn Real_Death = nullptr;
death_fn Death = nullptr;                                         // the hooked routine (test kill)
thread_local int t_drone_enable = 0;                              // 1: a drone component on, 2: its damageable
bool g_is_server = false;
struct Comp { void *system; uint32_t index; };

// Explosions due, run on the follow update (the game thread, outside any script node: run
// from inside one -- the drone script's own disable node, as the expiry first did -- a
// node's Execute overwrites the running node's per-thread storage, and every client in a
// match crashed when a drone's lifetime ran out). An expiry also holds back the drone's
// sound system going off (`sound`) until its explosion's sound has played.
struct DeathFx { void *ctx; ULONGLONG at; bool spawned; int nsound; Comp sound[8]; };
DeathFx g_fx[8];
SRWLOCK g_fx_lock = SRWLOCK_INIT;
constexpr ULONGLONG FX_SOUND_HOLD_MS = 2500;                      // the explosion's sound, then the sound system off

void QueueDeathFx(void *ctx, const Comp *sound, int nsound) {
    AcquireSRWLockExclusive(&g_fx_lock);
    DeathFx *f = nullptr;
    for (auto &x : g_fx) if (!x.ctx) { f = &x; break; }
    if (f) {
        *f = {};
        f->ctx = ctx;
        f->at = GetTickCount64();
        f->nsound = nsound < 8 ? nsound : 8;
        memcpy(f->sound, sound, sizeof(Comp) * f->nsound);
    }
    ReleaseSRWLockExclusive(&g_fx_lock);
    if (!f) {                                                     // (8 at once: no explosion, sound off now)
        for (int i = 0; i < nsound; ++i) Real_Disable(sound[i].system, sound[i].index, 1);
        Log("drone explosion queue full: skipped");
    }
}

// fix_drone_fx.py's spawn and sound stubs (their addresses left by the drone script) with a
// dead drone's node context: the detonator's explosion and POINT's sound on that drone. Its
// node state kept round each, as the translocator's dispatcher hook does.
void SpawnDeathFx(void *ctx) {
    using stub_fn = void(__fastcall *)(void *);
    auto slots = (stub_fn volatile *)((uint8_t *)GetModuleHandleW(nullptr) + DEATH_TOKEN_RVA + 0x28);
    if (!slots[0]) { Log("drone explosion: no spawn stub (drone script unpatched?)"); return; }
    __try {
        auto state = (uint64_t *)((uint8_t *)ctx + 0x18);
        uint64_t saved = *state;
        for (int i = 0; i < 2; ++i)
            if (stub_fn stub = slots[i]) { *state = 0; stub(ctx); }
        *state = saved;
        Log("drone explosion spawned (ctx %p)", ctx);
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        Log("drone explosion faulted and was contained (ctx %p)", ctx);
    }
}

void DeathFxDue() {
    void *spawn[8];
    int nspawn = 0;
    Comp off[64];
    int noff = 0;
    ULONGLONG now = GetTickCount64();
    AcquireSRWLockExclusive(&g_fx_lock);
    for (auto &f : g_fx) {
        if (!f.ctx) continue;
        if (!f.spawned) {
            spawn[nspawn++] = f.ctx;
            f.spawned = true;
            f.at = now;
        }
        if (now - f.at >= FX_SOUND_HOLD_MS || !f.nsound) {
            for (int i = 0; i < f.nsound && noff < 64; ++i) off[noff++] = f.sound[i];
            f = {};
        }
    }
    ReleaseSRWLockExclusive(&g_fx_lock);
    for (int i = 0; i < nspawn; ++i) SpawnDeathFx(spawn[i]);
    for (int i = 0; i < noff; ++i) Real_Disable(off[i].system, off[i].index, 1);
}
struct DroneGroup { uint8_t *dcs; uint32_t didx; ULONGLONG opened; bool dead; bool test_killed; int n; Comp comps[20];
                    void *ctx; };                              // ctx: a node context of its script (its explosion)
DroneGroup g_drones[8];
SRWLOCK g_drones_lock = SRWLOCK_INIT;
// drone components the script turns on just before its damageable (the models): no group yet
struct Pending { Comp c; ULONGLONG at; };
Pending g_pending[16];
int g_npending = 0;

uint8_t *DamageRecord(uint8_t *cs, uint32_t index) {
    uint16_t slot = *(uint16_t *)(*(uint8_t **)(cs + 0xd0) + (uint64_t)(index & 0xffff) * 4);
    return *(uint8_t **)(cs + 0x100) + slot * 0xb8ull;
}

void Revive(uint8_t *cs, uint32_t index) {                        // health back to full, not dead
    __try {
        uint8_t *rec = DamageRecord(cs, index);
        uint8_t *cd = **(uint8_t ***)(cs + 0xc0) + *(uint16_t *)rec * 0x38ull;
        *(float *)(rec + 0x20) = *(float *)(cd + 0x24);
        rec[2] &= ~4;
        Log("drone %u deployed: health %.0f", index & 0xffff, *(float *)(rec + 0x20));
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        Log("drone %u deployed: its damageable record is unreadable", index & 0xffff);
    }
}

DroneGroup *Newest() {                                            // (under the lock)
    DroneGroup *g = nullptr;
    for (auto &d : g_drones)
        if (d.dcs && !d.dead && GetTickCount64() - d.opened < 5000 && (!g || d.opened > g->opened)) g = &d;
    return g;
}

void AddComp(DroneGroup *g, void *system, uint32_t index) {      // (under the lock)
    for (int i = 0; i < g->n; ++i)
        if (g->comps[i].system == system && g->comps[i].index == index) return;
    if (g->n < 20) g->comps[g->n++] = { system, index };
}

// how long after its release a dead drone's script can still try to turn its parts on (the
// stock lifetime is 20 s); the next one is out no sooner (cooldown 30 s)
constexpr ULONGLONG DEAD_SWALLOW_MS = 25000;

bool InDeadGroup(void *system, uint32_t index) {                  // (under the lock)
    for (auto &d : g_drones) {
        if (!d.dcs || !d.dead || GetTickCount64() - d.opened > DEAD_SWALLOW_MS) continue;
        for (int i = 0; i < d.n; ++i)
            if (d.comps[i].system == system && d.comps[i].index == index) return true;
    }
    return false;
}

void __fastcall Hooked_EnableComp(void *system, uint32_t index, uint16_t flag) {
    int what = t_drone_enable;
    AcquireSRWLockExclusive(&g_drones_lock);
    bool swallow = false;
    if (what == 2) {                                              // a release: this drone's new life
        DroneGroup *g = nullptr;
        for (auto &d : g_drones) if (d.dcs == system && d.didx == index) g = &d;
        if (!g) for (auto &d : g_drones) if (!d.dcs) { g = &d; break; }
        if (!g) { g = &g_drones[0]; for (auto &d : g_drones) if (d.opened < g->opened) g = &d; }
        *g = {};
        g->dcs = (uint8_t *)system;
        g->didx = index;
        g->opened = GetTickCount64();
        g->comps[g->n++] = { system, index };
        // this enable is the drone script's own node: the context the dispatcher just left
        g->ctx = *(void *volatile *)((uint8_t *)GetModuleHandleW(nullptr) + DEATH_TOKEN_RVA + 0x20);
        for (int i = 0; i < g_npending; ++i)                      // the models, turned on first
            if (g->opened - g_pending[i].at < 3000) AddComp(g, g_pending[i].c.system, g_pending[i].c.index);
        g_npending = 0;
    } else {
        swallow = InDeadGroup(system, index);                     // dead: the script can't bring it back
        if (!swallow && what == 1) {
            if (DroneGroup *g = Newest()) AddComp(g, system, index);
            else {
                if (g_npending == 16) g_npending = 0;
                g_pending[g_npending++] = { { system, index }, GetTickCount64() };
            }
        }
    }
    ReleaseSRWLockExclusive(&g_drones_lock);
    if (what == 2) Revive((uint8_t *)system, index);
    if (!swallow) Real_EnableComp(system, index, flag);
}

// a touch interact the grab rule held back: part of the newest drone too
void AddTouch(void *system, uint32_t index) {
    AcquireSRWLockExclusive(&g_drones_lock);
    if (DroneGroup *g = Newest()) AddComp(g, system, index);
    ReleaseSRWLockExclusive(&g_drones_lock);
}

void SetGun(uint64_t actor, uint32_t shown);

// Turns the drone whose damageable is (dcs, didx) off; dcs null: the one whose damageable
// index is didx (a client told by the server).
void Shutdown(uint8_t *dcs, uint32_t didx, const char *why) {
    Comp comps[20];
    int n = 0;
    void *ctx = nullptr;
    AcquireSRWLockExclusive(&g_drones_lock);
    for (auto &d : g_drones) {
        if (!d.dcs || d.dead) continue;
        if (dcs ? (d.dcs == dcs && d.didx == didx) : ((d.didx & 0xffff) == (didx & 0xffff))) {
            d.dead = true;
            n = d.n;
            ctx = d.ctx;
            memcpy(comps, d.comps, sizeof(Comp) * n);
            break;
        }
    }
    ReleaseSRWLockExclusive(&g_drones_lock);
    if (!n || !Real_Disable) return;                              // (unhooked: VeilNet's 'K' after shutdown)
    SetGun(DRONE_ACTOR, 0);                                       // the port's override: hidden
    for (int i = 0; i < n; ++i) Real_Disable(comps[i].system, comps[i].index, 1);
    // the explosion, on the next follow update (the game thread). Clients only: a particle
    // spawn on the headless server crashed it.
    if (!g_is_server && ctx) QueueDeathFx(ctx, nullptr, 0);
    Log("drone %u %s: shut down (%d components off)%s", didx & 0xffff, why, n,
        !g_is_server && ctx ? ", explosion" : "");
}

// The drone's own end (its lifetime, 20 s): its script turns off its sound system
// (DRONE_SOUND) first, then its damageable and the rest, on the script's thread. The sound
// system's disables are held back (t_expiry, Hooked_Disable); the damageable's names the
// drone (ExpiredDamageable): still alive -> its explosion is queued, with the held-back
// sound system to go off after it; already dead (shot down: its explosion was then) -> the
// sound system goes off now. Every client runs the script; the server gets no explosion.
struct Expiry { void *ctx; int nsound; Comp sound[8]; bool open; };
thread_local Expiry t_expiry = {};
thread_local int t_expiry_step = 0;                               // 1: sound system going off, 2: damageable

void ExpiryHold(void *system, uint32_t index) {                   // (Hooked_Disable, t_expiry_step 1)
    if (t_expiry.nsound < 8) t_expiry.sound[t_expiry.nsound++] = { system, index };
    else Real_Disable(system, index, 1);
}

void ExpiredDamageable(void *system, uint32_t index) {            // (Hooked_Disable, t_expiry_step 2)
    bool alive = false;
    ULONGLONG age = 0;
    AcquireSRWLockExclusive(&g_drones_lock);
    for (auto &d : g_drones)
        if (d.dcs == system && d.didx == index) {
            alive = !d.dead;
            d.dead = true;
            age = GetTickCount64() - d.opened;
            break;
        }
    ReleaseSRWLockExclusive(&g_drones_lock);
    Expiry e = t_expiry;
    t_expiry = {};
    if (alive && !g_is_server && e.open && e.ctx) {
        QueueDeathFx(e.ctx, e.sound, e.nsound);
        Log("drone %u expired after %.1f s, explosion", index & 0xffff, age / 1000.0);
    } else {
        for (int i = 0; i < e.nsound; ++i) Real_Disable(e.sound[i].system, e.sound[i].index, 1);
        if (alive) Log("drone %u expired after %.1f s", index & 0xffff, age / 1000.0);
    }
}

void __fastcall Hooked_Death(void *cs, uint32_t index) {
    Real_Death(cs, index);
    bool mine = false;
    AcquireSRWLockShared(&g_drones_lock);
    for (auto &d : g_drones) if (d.dcs == cs && d.didx == index && !d.dead) mine = true;
    ReleaseSRWLockShared(&g_drones_lock);
    if (!mine) return;
    Shutdown((uint8_t *)cs, index, "destroyed");
    if (g_is_server) {
        using killed_fn = void(__cdecl *)(uint32_t);
        static killed_fn tell = nullptr;
        if (!tell)
            if (HMODULE veilnet = GetModuleHandleW(L"VeilNet.dll"))
                tell = (killed_fn)GetProcAddress(veilnet, "VeilNet_DroneKilled");
        if (tell) tell(index & 0xffff);
        else Log("drone %u: no VeilNet.dll, the clients won't see it go", index & 0xffff);
    }
}

extern "C" __declspec(dllexport) void __cdecl DroneFix_Killed(uint32_t index) {   // VeilNet: the server says
    if (Real_Disable) Shutdown(nullptr, index, "destroyed on the server");
}

void KillTestDue() {                                              // (test) kill as a 0-health hit does
    if (!KILL_TEST_MS || !g_is_server || !Death) return;
    uint8_t *cs = nullptr;
    uint32_t index = 0;
    AcquireSRWLockExclusive(&g_drones_lock);
    for (auto &d : g_drones)
        if (d.dcs && !d.dead && !d.test_killed && GetTickCount64() - d.opened >= KILL_TEST_MS) {
            d.test_killed = true;
            cs = d.dcs;
            index = d.didx;
            break;
        }
    ReleaseSRWLockExclusive(&g_drones_lock);
    if (!cs) return;
    __try {
        uint8_t *rec = DamageRecord(cs, index);
        if (rec[2] & 4) return;
        *(float *)(rec + 0x20) = 0.0f;
        rec[2] |= 4;
        Log("[test] drone %u: health 0, killing it", index & 0xffff);
        Death(cs, index);
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        Log("[test] killing drone %u faulted", index & 0xffff);
    }
}

void __fastcall Hooked_FollowUpdate(uintptr_t cs) {
    TickFrame();
    KillTestDue();
    DeathFxDue();
    if (*(uintptr_t *)(cs + TARGET_BODY_SYSTEM) == 0) {
        if (InterlockedIncrement(&g_skipped) == 1)
            Log("follow update skipped: no orbit target set yet (cs %p)", (void *)cs);
        return;
    }
    if (!CallGuarded(cs) && InterlockedIncrement(&g_faults) <= 5)
        Log("follow update faulted and was contained (cs %p, target system %p, index %u)", (void *)cs,
            *(void **)(cs + TARGET_BODY_SYSTEM), *(uint16_t *)(cs + 0x190));
}

// Each drone's last gun state (by actor), so the port follows it whatever the drone's
// script does with the port's component: that script is the detonator's, and shows / hides
// its parts on its own (the part PORT is on is one it shows once the drone is deployed).
struct GunState { uint64_t actor; uint32_t shown; };
GunState g_guns[32];
SRWLOCK g_guns_lock = SRWLOCK_INIT;

void SetGun(uint64_t actor, uint32_t shown) {
    AcquireSRWLockExclusive(&g_guns_lock);
    int slot = -1;
    for (int i = 0; i < 32 && slot < 0; ++i)
        if (g_guns[i].actor == actor) slot = i;
    for (int i = 0; i < 32 && slot < 0; ++i)
        if (!g_guns[i].actor) slot = i;
    if (slot < 0) {                                         // full: forget the oldest
        memmove(g_guns, g_guns + 1, sizeof(g_guns) - sizeof(g_guns[0]));
        slot = 31;
    }
    g_guns[slot] = { actor, shown };
    ReleaseSRWLockExclusive(&g_guns_lock);
}

bool GunShown(uint64_t actor, uint32_t *shown) {
    AcquireSRWLockShared(&g_guns_lock);
    bool found = false;
    for (int i = 0; i < 32 && !found; ++i)
        if (g_guns[i].actor == actor) { *shown = g_guns[i].shown; found = true; }
    ReleaseSRWLockShared(&g_guns_lock);
    return found;
}

// --- the drone stays grabbable until it locks on ------------------------------------------
// A moment after release the drone's script turns its R14TouchInteract component off, which
// is what stops it being grabbed. CEnableComponentNode::Enter resolves the component and asks
// for that through DISABLE_RVA (component system, component index); while capturing (the
// drone's touch interact, from the hook below) that call is held back and the component kept,
// with this drone's record reset (a new life). At the drone's first shot, the drone that has
// not fired yet and was deployed last is the one shooting: its touch interact is turned off
// then, so a drone that has locked onto someone can't be grabbed. The next release starts again.
constexpr uint64_t R14_TOUCH_INTERACT = 0x2E40131422F7B1FCull;   // CSymbol64("R14TouchInteract")
constexpr uintptr_t DISABLE_RVA = 0x9cb780;                      // (component system, index, flag): disable
constexpr uint8_t DISABLE_BYTES[] = { 0x48, 0x83, 0xec, 0x78, 0x48, 0x8b, 0xc1 };
thread_local bool t_capture = false;

struct TouchRec { void *system; uint32_t index; uint32_t handle; ULONGLONG deployed; bool locked; };
TouchRec g_touch[16];
SRWLOCK g_touch_lock = SRWLOCK_INIT;

void ExpiryHold(void *system, uint32_t index);
void ExpiredDamageable(void *system, uint32_t index);

void __fastcall Hooked_Disable(void *system, uint32_t index, uint16_t flag) {
    if (t_expiry_step == 1 && !g_is_server) { ExpiryHold(system, index); return; }
    if (t_expiry_step == 2) {
        Real_Disable(system, index, flag);
        ExpiredDamageable(system, index);
        return;
    }
    if (!t_capture) {
        Real_Disable(system, index, flag);
        return;
    }
    AcquireSRWLockExclusive(&g_touch_lock);
    int slot = -1, oldest = 0;
    for (int i = 0; i < 16 && slot < 0; ++i)
        if (g_touch[i].system == system && g_touch[i].index == index) slot = i;
    for (int i = 0; i < 16 && slot < 0; ++i)
        if (!g_touch[i].system) slot = i;
    for (int i = 1; i < 16; ++i)
        if (g_touch[i].deployed < g_touch[oldest].deployed) oldest = i;
    if (slot < 0) slot = oldest;
    g_touch[slot] = { system, index, 0, GetTickCount64(), false };   // deployed, not locked on
    ReleaseSRWLockExclusive(&g_touch_lock);
    AddTouch(system, index);                                 // goes when the drone does
    Log("drone deployed: stays grabbable until it locks on (touch interact %p #%u)", system, index);
}

// At a drone's shot: the first one locks that drone on, and turns its touch interact off.
void LockedOn(uint32_t handle) {
    if (!Real_Disable) return;
    void *system = nullptr;
    uint32_t index = 0;
    AcquireSRWLockExclusive(&g_touch_lock);
    int mine = -1, newest = -1;
    for (int i = 0; i < 16; ++i) {
        if (!g_touch[i].system) continue;
        if (g_touch[i].handle == handle) mine = i;
        else if (!g_touch[i].handle && !g_touch[i].locked
                 && GetTickCount64() - g_touch[i].deployed < 120000
                 && (newest < 0 || g_touch[i].deployed > g_touch[newest].deployed)) newest = i;
    }
    if (mine < 0 && newest >= 0) {
        mine = newest;
        g_touch[mine].handle = handle;
    }
    if (mine >= 0 && !g_touch[mine].locked) {
        g_touch[mine].locked = true;
        system = g_touch[mine].system;
        index = g_touch[mine].index;
    }
    ReleaseSRWLockExclusive(&g_touch_lock);
    if (system) {
        Real_Disable(system, index, 1);
        Log("drone %u locked on: no longer grabbable (touch interact %p #%u)", handle, system, index);
    }
}

// For Hooked_EnableComp: what the drone's script is turning on in this call (restored after).
struct EnableTag {
    int saved;
    explicit EnableTag(int v) : saved(t_drone_enable) { t_drone_enable = v; }
    ~EnableTag() { t_drone_enable = saved; }
};

#ifdef ECHOCOMBAT_LOG
volatile LONG g_dbg_enables = 0;
#endif

void __fastcall Hooked_EnableEnter(void *node, const uint64_t *data) {
#ifdef ECHOCOMBAT_LOG
    if (data[0] == DRONE_ACTOR && InterlockedIncrement(&g_dbg_enables) <= 400)
        Log("[test] drone script: %s %016llx/%016llx", (uint32_t)data[4] ? "on " : "off", data[2], data[3]);
#endif
    if (data[0] == DRONE_ACTOR && !(uint32_t)data[4] && Real_EnableComp && Real_Disable
        && (data[2] == DRONE_SOUND || data[2] == R14_DAMAGEABLE)) {
        if (data[2] == DRONE_SOUND) {                       // the end begins: this node's context
            for (int i = 0; i < t_expiry.nsound; ++i)        // (an unfinished one before: let it go)
                Real_Disable(t_expiry.sound[i].system, t_expiry.sound[i].index, 1);
            t_expiry = {};
            t_expiry.open = true;
            t_expiry.ctx = *(void *volatile *)((uint8_t *)GetModuleHandleW(nullptr) + DEATH_TOKEN_RVA + 0x20);
        }
        t_expiry_step = data[2] == DRONE_SOUND ? 1 : 2;
        Real_EnableEnter(node, data);
        t_expiry_step = 0;
        return;
    }
    EnableTag tag(data[0] == DRONE_ACTOR && (uint32_t)data[4] ? (data[2] == R14_DAMAGEABLE ? 2 : 1) : 0);
    if (data[0] == DRONE_ACTOR && data[2] == R14_TOUCH_INTERACT && !(uint32_t)data[4] && Real_Disable) {
        t_capture = true;                                   // the engine resolves it; Hooked_Disable keeps it
        Real_EnableEnter(node, data);
        t_capture = false;
        return;
    }
    if (data[2] == NCA_MODEL && data[3] == PORT) {          // the script's own say: the gun's instead
        uint32_t shown;
        if (GunShown(data[0], &shown) && shown != (uint32_t)data[4]) {
            uint64_t copy[5];
            memcpy(copy, data, sizeof copy);
            copy[4] = shown;
            Real_EnableEnter(node, copy);
            return;
        }
    }
    Real_EnableEnter(node, data);
    if (data[2] == NCA_MODEL && data[3] == GUN) {
        SetGun(data[0], (uint32_t)data[4]);
        uint64_t copy[5];                                   // actor, scope, system, component, enable
        memcpy(copy, data, sizeof copy);
        copy[3] = SATELLITE;
        Real_EnableEnter(node, copy);
        copy[3] = PORT;
        Real_EnableEnter(node, copy);
        if (InterlockedIncrement(&g_mirrored) <= 5)
            Log("drone gun %s: body and port too", (uint32_t)data[4] ? "shown" : "hidden");
    }
}

void __fastcall Hooked_FireLocal(void *cs, uint32_t handle, const float *velocity, int remote) {
    LockedOn(handle);
    t_velocity = velocity;
    t_remote = remote;
    Real_FireLocal(cs, handle, velocity, remote);
    t_velocity = nullptr;
}

Pose *__fastcall MuzzleTransform(void *transforms, Pose *out, uint32_t index) {
    Real_TransformGet(transforms, out, index);
    const float *v = t_velocity;
    if (!v) return out;
    float len = sqrtf(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]);
    if (len < 1e-4f) return out;
    // AttackTarget's basis: Z = aim, X = (z, 0, -x) / |..|, Y = Z x X
    float z[3] = { v[0] / len, v[1] / len, v[2] / len };
    float xl = sqrtf(z[2] * z[2] + z[0] * z[0]);
    float x[3] = { xl > 1e-4f ? z[2] / xl : 1.0f, 0.0f, xl > 1e-4f ? -z[0] / xl : 0.0f };
    float y[3] = { z[1] * x[2] - z[2] * x[1], z[2] * x[0] - z[0] * x[2], z[0] * x[1] - z[1] * x[0] };
    float root[3] = { out->p[0], out->p[1], out->p[2] };
    float dt = g_frame_dt;
    dt = dt < 1.0f / 120.0f ? 1.0f / 120.0f : dt > 1.0f / 30.0f ? 1.0f / 30.0f : dt;
    for (int i = 0; i < 3; ++i)
        out->p[i] += MUZZLE[0] * x[i] + MUZZLE[1] * y[i] + MUZZLE[2] * z[i] - v[i] * dt;
    LONG n = InterlockedIncrement(&g_muzzle_shots);
    if (n <= SHOT_LOG)
        Log("[pid %lu] shot %ld%s: root (%.3f %.3f %.3f) spawn (%.3f %.3f %.3f) velocity (%.2f %.2f %.2f) "
            "frame %.1f ms", GetCurrentProcessId(), n, t_remote ? " (remote)" : "", root[0], root[1], root[2],
            out->p[0], out->p[1], out->p[2], v[0], v[1], v[2], dt * 1000.0f);
    return out;
}

// The call's rel32 has to reach MuzzleTransform: through a jump stub allocated within 2 GB.
void *StubNear(uintptr_t site, void *target) {
    SYSTEM_INFO si;
    GetSystemInfo(&si);
    uintptr_t gran = si.dwAllocationGranularity;
    for (uintptr_t at = (site & ~(gran - 1)) - gran; at > site - 0x7ff00000; at -= gran) {
        auto stub = (uint8_t *)VirtualAlloc((void *)at, 16, MEM_RESERVE | MEM_COMMIT, PAGE_EXECUTE_READWRITE);
        if (!stub) continue;
        const uint8_t jmp[] = { 0xff, 0x25, 0, 0, 0, 0 };     // jmp [rip+0]
        memcpy(stub, jmp, sizeof jmp);
        memcpy(stub + sizeof jmp, &target, sizeof target);
        return stub;
    }
    return nullptr;
}

bool g_hooked = false;
bool g_fire_hooked = false;
bool g_enable_hooked = false;
uint8_t *g_fire_site = nullptr;

void InstallMuzzle(uintptr_t base) {
    auto site = (uint8_t *)(base + FIRE_GET_CALL_RVA);
    if (memcmp(site, FIRE_GET_CALL_BYTES, sizeof(FIRE_GET_CALL_BYTES)) != 0) {
        Log("FireBulletLocal call mismatch at +0x%llx -- wrong echovr build, bullets stay at the root",
            (unsigned long long)FIRE_GET_CALL_RVA);
        return;
    }
    auto fire = (uint8_t *)(base + FIRE_LOCAL_RVA);
    if (memcmp(fire, FIRE_LOCAL_BYTES, sizeof(FIRE_LOCAL_BYTES)) != 0) {
        Log("FireBulletLocal prologue mismatch at +0x%llx -- bullets stay at the root", (unsigned long long)FIRE_LOCAL_RVA);
        return;
    }
    Real_FireLocal = (fire_local_fn)fire;
    DetourTransactionBegin();
    DetourUpdateThread(GetCurrentThread());
    DetourAttach(&(PVOID &)Real_FireLocal, Hooked_FireLocal);
    if (DetourTransactionCommit() != NO_ERROR) {
        Log("FireBulletLocal hook failed; bullets stay at the root");
        return;
    }
    g_fire_hooked = true;
    Real_TransformGet = (transform_get_fn)(base + TRANSFORM_GET_RVA);
    void *stub = StubNear((uintptr_t)site, (void *)MuzzleTransform);
    if (!stub) {
        Log("no memory near echovr for the muzzle stub; bullets stay at the root");
        return;
    }
    int32_t rel = (int32_t)((uintptr_t)stub - ((uintptr_t)site + 5));
    DWORD old;
    VirtualProtect(site + 1, 4, PAGE_EXECUTE_READWRITE, &old);
    memcpy(site + 1, &rel, 4);
    VirtualProtect(site + 1, 4, old, &old);
    FlushInstructionCache(GetCurrentProcess(), site, 5);
    g_fire_site = site;
    Log("drone bullets fire from the muzzle (%.4f %.4f %.4f) (+0x%llx)", MUZZLE[0], MUZZLE[1], MUZZLE[2],
        (unsigned long long)FIRE_GET_CALL_RVA);
}

void InstallEnableMirror(uintptr_t base) {
    auto enter = (uint8_t *)(base + ENABLE_ENTER_RVA);
    if (memcmp(enter, ENABLE_ENTER_BYTES, sizeof(ENABLE_ENTER_BYTES)) != 0) {
        Log("EnableComponentNode prologue mismatch at +0x%llx -- the satellite won't hide with the gun",
            (unsigned long long)ENABLE_ENTER_RVA);
        return;
    }
    Real_EnableEnter = (enable_enter_fn)enter;
    DetourTransactionBegin();
    DetourUpdateThread(GetCurrentThread());
    DetourAttach(&(PVOID &)Real_EnableEnter, Hooked_EnableEnter);
    LONG rc = DetourTransactionCommit();
    g_enable_hooked = rc == NO_ERROR;
    Log(rc == NO_ERROR ? "hooked EnableComponentNode: the satellite shows / hides with the gun (+0x%llx)"
                       : "EnableComponentNode hook failed (+0x%llx)", (unsigned long long)ENABLE_ENTER_RVA);
}

void InstallGrabRule(uintptr_t base) {
    auto target = (uint8_t *)(base + DISABLE_RVA);
    if (memcmp(target, DISABLE_BYTES, sizeof(DISABLE_BYTES)) != 0) {
        Log("component disable prologue mismatch at +0x%llx -- the drone can't be grabbed after release, as stock",
            (unsigned long long)DISABLE_RVA);
        return;
    }
    disable_fn real = (disable_fn)target;
    DetourTransactionBegin();
    DetourUpdateThread(GetCurrentThread());
    DetourAttach(&(PVOID &)real, Hooked_Disable);
    LONG rc = DetourTransactionCommit();
    if (rc == NO_ERROR) Real_Disable = real;
    Log(rc == NO_ERROR ? "hooked component disable: a drone stays grabbable until it locks on (+0x%llx)"
                       : "component disable hook failed (+0x%llx)", (unsigned long long)DISABLE_RVA);
}

void InstallDeathRule(uintptr_t base) {
    g_is_server = strstr(GetCommandLineA(), "-server") != nullptr;
    auto en = (uint8_t *)(base + ENABLE_COMP_RVA), death = (uint8_t *)(base + DEATH_RVA);
    if (memcmp(en, ENABLE_COMP_BYTES, sizeof(ENABLE_COMP_BYTES)) || memcmp(death, DEATH_BYTES, sizeof(DEATH_BYTES))) {
        Log("component enable / death prologue mismatch -- the drone can't be shot down");
        return;
    }
    enable_comp_fn real_en = (enable_comp_fn)en;
    death_fn real_death = (death_fn)death;
    DetourTransactionBegin();
    DetourUpdateThread(GetCurrentThread());
    DetourAttach(&(PVOID &)real_en, Hooked_EnableComp);
    DetourAttach(&(PVOID &)real_death, Hooked_Death);
    LONG rc = DetourTransactionCommit();
    if (rc != NO_ERROR) {
        Log("component enable / death hook failed -- the drone can't be shot down");
        return;
    }
    Real_EnableComp = real_en;
    Real_Death = real_death;
    Death = (death_fn)death;                                // through the hook (the test kill)
    Log("hooked component enable and damageable death: a drone is destroyed when its health runs out (%s)",
        g_is_server ? "server" : "client");
    if (KILL_TEST_MS && g_is_server)
        Log("[test] each deployed drone is killed %llu ms after release", KILL_TEST_MS);
}

bool Install() {
    if (g_hooked) return true;
    auto base = (uintptr_t)GetModuleHandleW(nullptr);
    InstallDeathRule(base);
    InstallMuzzle(base);
    InstallEnableMirror(base);
    InstallGrabRule(base);
    auto target = (uint8_t *)(base + FOLLOW_UPDATE_RVA);
    if (memcmp(target, FOLLOW_UPDATE_BYTES, sizeof(FOLLOW_UPDATE_BYTES)) != 0) {
        Log("prologue mismatch at +0x%llx -- wrong echovr build, not hooking", (unsigned long long)FOLLOW_UPDATE_RVA);
        return false;
    }
    QueryPerformanceFrequency(&g_qpf);
    Real_FollowUpdate = (follow_update_fn)target;
    DetourTransactionBegin();
    DetourUpdateThread(GetCurrentThread());
    DetourAttach(&(PVOID &)Real_FollowUpdate, Hooked_FollowUpdate);
    LONG rc = DetourTransactionCommit();
    Log(rc == NO_ERROR ? "hooked CR15NetFollowPlayerCS update (+0x%llx)" : "hook failed (+0x%llx)",
        (unsigned long long)FOLLOW_UPDATE_RVA);
    g_hooked = rc == NO_ERROR;
    return g_hooked;
}

} // namespace

ECHOCOMBAT_EXPORT NvrPluginInfo NvrPluginGetInfo(void) {
    return EchoCombatPluginInfo("drone_fix", "EchoCombat: keeps the DRONE from crashing Echo VR");
}

ECHOCOMBAT_EXPORT uint32_t NvrPluginGetApiVersion(void) { return NEVR_PLUGIN_API_VERSION; }

ECHOCOMBAT_EXPORT uint32_t NvrPluginGetCapabilities(void) {
    return NEVR_PLUGIN_CAP_ALTERS_GAMEPLAY | NEVR_PLUGIN_CAP_HOOKS_ENGINE;
}

ECHOCOMBAT_EXPORT int NvrPluginInitEx(const NvrGameContext *, const char *) {
    EchoCombatLogPath(g_log_path, sizeof(g_log_path), "DroneFix");
    return Install() ? 0 : 1;
}

ECHOCOMBAT_EXPORT int NvrPluginInit(const NvrGameContext *ctx) { return NvrPluginInitEx(ctx, "{}"); }

ECHOCOMBAT_EXPORT void NvrPluginShutdown(void) {
    if (g_fire_site) {                                      // the call back to CTransformCS::get
        DWORD old;
        VirtualProtect(g_fire_site + 1, 4, PAGE_EXECUTE_READWRITE, &old);
        memcpy(g_fire_site + 1, FIRE_GET_CALL_BYTES + 1, 4);
        VirtualProtect(g_fire_site + 1, 4, old, &old);
        FlushInstructionCache(GetCurrentProcess(), g_fire_site, 5);
        g_fire_site = nullptr;
    }
    if (!g_hooked && !g_fire_hooked && !g_enable_hooked && !Real_Disable && !Real_EnableComp) return;
    DetourTransactionBegin();
    DetourUpdateThread(GetCurrentThread());
    if (g_hooked) DetourDetach(&(PVOID &)Real_FollowUpdate, Hooked_FollowUpdate);
    if (g_fire_hooked) DetourDetach(&(PVOID &)Real_FireLocal, Hooked_FireLocal);
    if (g_enable_hooked) DetourDetach(&(PVOID &)Real_EnableEnter, Hooked_EnableEnter);
    if (Real_Disable) DetourDetach(&(PVOID &)Real_Disable, Hooked_Disable);       // the grab rule
    if (Real_EnableComp) {                                                       // the death rule
        DetourDetach(&(PVOID &)Real_EnableComp, Hooked_EnableComp);
        DetourDetach(&(PVOID &)Real_Death, Hooked_Death);
    }
    DetourTransactionCommit();
    g_hooked = g_fire_hooked = g_enable_hooked = false;
    Real_Disable = nullptr;
    Real_EnableComp = nullptr;
    Real_Death = nullptr;
    Log("unhooked (%ld updates skipped, %ld faults contained)", g_skipped, g_faults);
}

BOOL APIENTRY DllMain(HMODULE self, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) DisableThreadLibraryCalls(self);
    return TRUE;
}
