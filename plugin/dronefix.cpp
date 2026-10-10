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
// nothing is hooked. Log: DroneFix.log next to the DLL.
//
// It also fires the drone's bullets from its gun. CR15NetAutoTargetCS aims by turning the
// drone's ROOT transform toward the target (+Z at it) and spawns each bullet at that root:
//   +0xce2550  CR15NetAutoTargetCS::FireBulletLocal(cs, handle, velocity, remote)
//   +0xce27e3    call CTransformCS::get(transforms, &out, root)   -> the bullet's spawn pose
// which is the middle of the drone, not the gun on its side (tools/fix_drone_model.py). That
// one call is redirected to MuzzleTransform, which moves the pose by MUZZLE, the muzzle's
// offset in the drone, turned the way AttackTarget turns the drone for this shot: +Z along
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
#include "detours.h"

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

void __fastcall Hooked_FollowUpdate(uintptr_t cs) {
    TickFrame();
    if (*(uintptr_t *)(cs + TARGET_BODY_SYSTEM) == 0) {
        if (InterlockedIncrement(&g_skipped) == 1)
            Log("follow update skipped: no orbit target set yet (cs %p)", (void *)cs);
        return;
    }
    if (!CallGuarded(cs) && InterlockedIncrement(&g_faults) <= 5)
        Log("follow update faulted and was contained (cs %p, target system %p, index %u)", (void *)cs,
            *(void **)(cs + TARGET_BODY_SYSTEM), *(uint16_t *)(cs + 0x190));
}

void __fastcall Hooked_EnableEnter(void *node, const uint64_t *data) {
    Real_EnableEnter(node, data);
    if (data[2] == NCA_MODEL && data[3] == GUN) {
        uint64_t copy[5];                                   // actor, scope, system, component, enable
        memcpy(copy, data, sizeof copy);
        copy[3] = SATELLITE;
        Real_EnableEnter(node, copy);
        if (InterlockedIncrement(&g_mirrored) <= 5)
            Log("drone gun %s: satellite too", (uint32_t)data[4] ? "shown" : "hidden");
    }
}

void __fastcall Hooked_FireLocal(void *cs, uint32_t handle, const float *velocity, int remote) {
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
    Log(rc == NO_ERROR ? "hooked EnableComponentNode: the satellite shows / hides with the gun (+0x%llx)"
                       : "EnableComponentNode hook failed (+0x%llx)", (unsigned long long)ENABLE_ENTER_RVA);
}

void Install() {
    auto base = (uintptr_t)GetModuleHandleW(nullptr);
    InstallMuzzle(base);
    InstallEnableMirror(base);
    auto target = (uint8_t *)(base + FOLLOW_UPDATE_RVA);
    if (memcmp(target, FOLLOW_UPDATE_BYTES, sizeof(FOLLOW_UPDATE_BYTES)) != 0) {
        Log("prologue mismatch at +0x%llx -- wrong echovr build, not hooking", (unsigned long long)FOLLOW_UPDATE_RVA);
        return;
    }
    QueryPerformanceFrequency(&g_qpf);
    Real_FollowUpdate = (follow_update_fn)target;
    DetourTransactionBegin();
    DetourUpdateThread(GetCurrentThread());
    DetourAttach(&(PVOID &)Real_FollowUpdate, Hooked_FollowUpdate);
    LONG rc = DetourTransactionCommit();
    Log(rc == NO_ERROR ? "hooked CR15NetFollowPlayerCS update (+0x%llx)" : "hook failed (+0x%llx)",
        (unsigned long long)FOLLOW_UPDATE_RVA);
}

} // namespace

BOOL APIENTRY DllMain(HMODULE self, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) {
        DisableThreadLibraryCalls(self);
        GetModuleFileNameA(self, g_log_path, MAX_PATH);
        if (char *slash = strrchr(g_log_path, '\\')) strcpy_s(slash + 1, MAX_PATH - (slash + 1 - g_log_path), "DroneFix.log");
        Install();
    }
    return TRUE;
}
