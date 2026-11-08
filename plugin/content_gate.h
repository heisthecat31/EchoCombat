// Whether DroneFix / PowerBoost / VeilNet should run at all (each asks from its NvrPluginInitEx,
// before any hook or byte patch):
//
// 1. EchoCombat's content pack has to be the game's data. The plugins patch code that only makes
//    sense with EchoCombat's scripts and tables; with the stock game under them they break every
//    tac mod. Served = EchoCombatContent.dll (content.cpp, loaded early) says so, or
//    NvrContentOverlay.dll is loaded (the Echo VR launcher's way of serving a pack).
// 2. nEVR builds from 6.17 carry EchoCombat's plugins built in ([NEVR.COMBAT] module=dronefix /
//    veilnet / powerboost). When the runtime has hooked a plugin's functions already, a second
//    copy on top half-installs (prologue checks fail) and the two fight over the same tac mod
//    controller and packets. So a plugin whose functions jump into nevr-runtime.dll stays off and
//    leaves them to the runtime.
#pragma once

#include <windows.h>
#include <stdint.h>
#include <string.h>

// Where a hook at `p` ends up: follows a jmp rel32 (E9), a jmp [rip+0] / abs64 (FF 25 00000000)
// and a jmp [rip+disp32] (FF 25), a few hops deep (MinHook: E9 to a relay, then FF 25 to the detour).
inline const uint8_t *EchoCombatHookTarget(const uint8_t *p) {
    __try {
        for (int hop = 0; hop < 4 && p; ++hop) {
            if (p[0] == 0xE9) p = p + 5 + *(const int32_t *)(p + 1);
            else if (p[0] == 0xFF && p[1] == 0x25) p = *(const uint8_t *const *)(p + 6 + *(const int32_t *)(p + 2));
            else if (p[0] == 0x48 && p[1] == 0xFF && p[2] == 0x25) p = *(const uint8_t *const *)(p + 7 + *(const int32_t *)(p + 3));
            else if (p[0] == 0xEB) p = p + 2 + *(const int8_t *)(p + 1);                              // jmp rel8
            else if (p[0] == 0x48 && p[1] == 0xB8 && p[10] == 0xFF && p[11] == 0xE0) p = *(const uint8_t *const *)(p + 2);   // mov rax, imm64; jmp rax
            else if (p[0] == 0x49 && p[1] == 0xBB && p[10] == 0x41 && p[11] == 0xFF && p[12] == 0xE3) p = *(const uint8_t *const *)(p + 2);   // mov r11, imm64; jmp r11
            else if (p[0] == 0x68 && p[5] == 0xC7 && p[6] == 0x44 && p[7] == 0x24 && p[8] == 0x04 && p[13] == 0xC3)          // push lo; mov [rsp+4], hi; ret
                p = (const uint8_t *)(uintptr_t)(*(const uint32_t *)(p + 1) | (uint64_t)*(const uint32_t *)(p + 9) << 32);
            else return p;
        }
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        return nullptr;
    }
    return p;
}

inline bool EchoCombatInModule(const uint8_t *p, const wchar_t *module) {
    HMODULE m = GetModuleHandleW(module);
    if (!m || !p) return false;
    const uint8_t *base = (const uint8_t *)m;
    auto nt = (const IMAGE_NT_HEADERS64 *)(base + ((const IMAGE_DOS_HEADER *)base)->e_lfanew);
    return p >= base && p < base + nt->OptionalHeader.SizeOfImage;
}

// Whether a function entry in echovr.exe is somebody's hook: it jumps (in any of the forms above)
// to code outside echovr.exe's image (nEVR's runtime, a MinHook / HookGuard relay, another plugin).
// Detours on such an entry goes on top of that hook: both run.
inline bool EchoCombatEntryHooked(const uint8_t *at) {
    const uint8_t *to = EchoCombatHookTarget(at);
    if (!to || to == at) return false;
    const uint8_t *exe = (const uint8_t *)GetModuleHandleW(nullptr);
    auto nt = (const IMAGE_NT_HEADERS64 *)(exe + ((const IMAGE_DOS_HEADER *)exe)->e_lfanew);
    return to < exe || to >= exe + nt->OptionalHeader.SizeOfImage;
}

// The first of `rvas` (echovr.exe) that nEVR's runtime has hooked, or 0.
inline uintptr_t EchoCombatRuntimeHooked(const uintptr_t *rvas, size_t n) {
    const uint8_t *exe = (const uint8_t *)GetModuleHandleW(nullptr);
    for (size_t i = 0; i < n; ++i) {
        const uint8_t *at = exe + rvas[i];
        const uint8_t *to = EchoCombatHookTarget(at);
        if (to && to != at && (EchoCombatInModule(to, L"nevr-runtime.dll") || EchoCombatInModule(to, L"BugSplat64.dll")))
            return rvas[i];
    }
    return 0;
}

inline bool EchoCombatContentServed(const char **how) {
    using served_fn = int(__cdecl *)();
    if (HMODULE c = GetModuleHandleW(L"EchoCombatContent.dll")) {
        auto served = (served_fn)GetProcAddress(c, "EchoCombatContent_Served");
        if (served && served()) { *how = "EchoCombatContent"; return true; }
    }
    if (GetModuleHandleW(L"NvrContentOverlay.dll")) { *how = "NvrContentOverlay"; return true; }
    *how = nullptr;
    return false;
}

// 0: run. Otherwise why not, one line for the log ("... : <plugin> off, ...").
inline const char *EchoCombatGate(const uintptr_t *rvas, size_t n, char *buf, size_t size) {
    const char *how = nullptr;
    if (!EchoCombatContentServed(&how)) {
        return "EchoCombat's content isn't served (EchoCombatContent.dll didn't load early or refused the pack; "
               "see its lines above): plugin off, the game stays stock";
    }
    if (uintptr_t rva = EchoCombatRuntimeHooked(rvas, n)) {
        _snprintf_s(buf, size, _TRUNCATE,
                    "nEVR's built-in EchoCombat already hooks echovr+0x%llx: plugin off, the runtime's copy runs it",
                    (unsigned long long)rva);
        return buf;
    }
    return nullptr;
}
