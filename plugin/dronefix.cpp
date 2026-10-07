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

#include <windows.h>
#include <stdint.h>
#include <stdio.h>
#include "detours.h"

namespace {

constexpr uintptr_t FOLLOW_UPDATE_RVA = 0xd65cb0;
constexpr uint8_t FOLLOW_UPDATE_BYTES[] = { 0x48, 0x89, 0x5c, 0x24, 0x10, 0x57, 0x48, 0x83, 0xec, 0x20, 0x48, 0x8b, 0xd9 };
constexpr uintptr_t TARGET_BODY_SYSTEM = 0x140;

using follow_update_fn = void(__fastcall *)(uintptr_t);
follow_update_fn Real_FollowUpdate = nullptr;

char g_log_path[MAX_PATH];
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

void __fastcall Hooked_FollowUpdate(uintptr_t cs) {
    if (*(uintptr_t *)(cs + TARGET_BODY_SYSTEM) == 0) {
        if (InterlockedIncrement(&g_skipped) == 1)
            Log("follow update skipped: no orbit target set yet (cs %p)", (void *)cs);
        return;
    }
    if (!CallGuarded(cs) && InterlockedIncrement(&g_faults) <= 5)
        Log("follow update faulted and was contained (cs %p, target system %p, index %u)", (void *)cs,
            *(void **)(cs + TARGET_BODY_SYSTEM), *(uint16_t *)(cs + 0x190));
}

void Install() {
    auto base = (uintptr_t)GetModuleHandleW(nullptr);
    auto target = (uint8_t *)(base + FOLLOW_UPDATE_RVA);
    if (memcmp(target, FOLLOW_UPDATE_BYTES, sizeof(FOLLOW_UPDATE_BYTES)) != 0) {
        Log("prologue mismatch at +0x%llx -- wrong echovr build, not hooking", (unsigned long long)FOLLOW_UPDATE_RVA);
        return;
    }
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
