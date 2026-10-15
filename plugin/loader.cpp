// dbgcore.dll: EchoCombat's plugin loader.
//
// echovr.exe loads <bin\win10>\dbgcore.dll itself at startup (its crash symbol
// handler: "Failed to initialize symbol handler: couldn't load dbgcore.dll").
// This stands in for it: it loads every DLL in <bin\win10>\plugins\, in name
// order, and passes the two real dbgcore exports through to the system copy
// (dbgcore.dll, else dbghelp.dll), so crash dumps still work.
//
// Built like the plugins (/MT): it imports KERNEL32 only, so it loads on a PC
// without the Visual C++ runtime -- the loader this replaces needed MSVCP140 /
// VCRUNTIME140(_1) and kept game servers from starting where those are missing.
//
// A DLL in plugins\ that is itself a plugin loader (another mod's dbgcore.dll,
// moved there by the installer) is skipped: it would load every plugin a second
// time and hook everything twice. Log (built with ECHOCOMBAT_LOG): <game>\_local\echoCombatBetaLogs\loader.log.

#include <windows.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "logdir.h"

// Marks this DLL as a plugin loader for the installer and for other copies of
// this loader (see IsLoader).
extern "C" __declspec(dllexport) const char EchoCombatPluginLoader[] = "plugins";

namespace {

wchar_t g_dir[MAX_PATH];      // ...\bin\win10\plugins
char g_log[MAX_PATH];

void Log(const char *fmt, ...) {
    // Off unless built with ECHOCOMBAT_LOG: a release writes no log, so slow PCs pay
    // nothing for it.
#ifdef ECHOCOMBAT_LOG
    FILE *f = nullptr;
    if (fopen_s(&f, g_log, "a") != 0 || !f) return;
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

// True when the file is a plugin loader: it names "plugins" and imports LoadLibrary.
bool IsLoader(const wchar_t *path) {
    HANDLE h = CreateFileW(path, GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING, 0, nullptr);
    if (h == INVALID_HANDLE_VALUE) return false;
    DWORD size = GetFileSize(h, nullptr);
    bool loader = false;
    if (size != INVALID_FILE_SIZE && size < (64u << 20)) {
        char *buf = (char *)HeapAlloc(GetProcessHeap(), 0, size);
        DWORD got = 0;
        if (buf && ReadFile(h, buf, size, &got, nullptr)) {
            bool names = false, loads = false;
            for (DWORD i = 0; i + 12 <= got && !(names && loads); ++i) {
                if (!names && memcmp(buf + i, "plugins\0", 8) == 0) names = true;
                if (!loads && memcmp(buf + i, "LoadLibrary", 11) == 0) loads = true;
            }
            loader = names && loads;
        }
        if (buf) HeapFree(GetProcessHeap(), 0, buf);
    }
    CloseHandle(h);
    return loader;
}

void LoadPlugins() {
    wchar_t pattern[MAX_PATH];
    swprintf_s(pattern, L"%s\\*.dll", g_dir);
    WIN32_FIND_DATAW fd;
    HANDLE find = FindFirstFileW(pattern, &fd);
    if (find == INVALID_HANDLE_VALUE) {
        Log("no plugins in %ls", g_dir);
        return;
    }
    // FindFirstFile on NTFS returns names sorted; that is the load order.
    int loaded = 0;
    do {
        if (fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) continue;
        wchar_t path[MAX_PATH];
        swprintf_s(path, L"%s\\%s", g_dir, fd.cFileName);
        if (IsLoader(path)) {
            Log("skipped %ls: it is a plugin loader itself (it would load every plugin again)", fd.cFileName);
            continue;
        }
        HMODULE m = LoadLibraryW(path);
        if (m) {
            Log("loaded %ls", fd.cFileName);
            ++loaded;
        } else {
            DWORD e = GetLastError();
            Log("FAILED to load %ls: error %lu%s", fd.cFileName, e,
                e == ERROR_MOD_NOT_FOUND ? " (a DLL it needs is missing)" :
                e == ERROR_BAD_EXE_FORMAT ? " (not a 64-bit DLL)" :
                e == ERROR_DLL_INIT_FAILED ? " (its DllMain failed)" : "");
        }
    } while (FindNextFileW(find, &fd));
    FindClose(find);
    Log("%d plugin(s) loaded", loaded);
}

// The system copy of an export: dbgcore.dll, else dbghelp.dll (which exports the
// same two functions; older Windows and Wine have no dbgcore.dll).
FARPROC Real(const char *name) {
    static const wchar_t *dlls[] = { L"\\dbgcore.dll", L"\\dbghelp.dll" };
    for (const wchar_t *dll : dlls) {
        wchar_t path[MAX_PATH];
        UINT n = GetSystemDirectoryW(path, MAX_PATH);
        if (n == 0 || n > MAX_PATH - 16) return nullptr;
        wcscat_s(path, dll);
        HMODULE m = LoadLibraryW(path);
        if (FARPROC p = m ? GetProcAddress(m, name) : nullptr) return p;
    }
    return nullptr;
}

} // namespace

// The two exports of the system dbgcore.dll, passed through. Every argument is
// pointer-sized or smaller and passed in a register or stack slot, so they are
// forwarded as integers without the dbghelp types.
extern "C" __declspec(dllexport) BOOL WINAPI MiniDumpWriteDump(uintptr_t process, uintptr_t pid, uintptr_t file,
                                                               uintptr_t type, uintptr_t exception,
                                                               uintptr_t user, uintptr_t callback) {
    using fn = BOOL(WINAPI *)(uintptr_t, uintptr_t, uintptr_t, uintptr_t, uintptr_t, uintptr_t, uintptr_t);
    fn real = (fn)Real("MiniDumpWriteDump");
    if (!real) { SetLastError(ERROR_PROC_NOT_FOUND); return FALSE; }
    return real(process, pid, file, type, exception, user, callback);
}

extern "C" __declspec(dllexport) BOOL WINAPI MiniDumpReadDumpStream(uintptr_t base, uintptr_t stream, uintptr_t dir,
                                                                    uintptr_t ptr, uintptr_t size) {
    using fn = BOOL(WINAPI *)(uintptr_t, uintptr_t, uintptr_t, uintptr_t, uintptr_t);
    fn real = (fn)Real("MiniDumpReadDumpStream");
    if (!real) { SetLastError(ERROR_PROC_NOT_FOUND); return FALSE; }
    return real(base, stream, dir, ptr, size);
}

// A clean exit. CR15Game's shutdown (+0x1223a0, its vslot 7, run once by Main_ as the game
// quits) logs the player out, then hands over to the engine's own teardown (+0x512590, the
// call at +0x122755). That teardown frees every resource, and one GPU particle effect's
// instance list is broken by then (+0x633643 reads through -1), so nearly every close since
// the modded data ended in an access violation and a BugSplat report. The process is on its
// way out at that point: the call ends it there instead (the logout and everything before it
// has run; Windows frees the rest).
constexpr uintptr_t TEARDOWN_CALL_RVA = 0x122752;
constexpr uint8_t TEARDOWN_CALL_BYTES[] = { 0x48, 0x8b, 0xcf, 0xe8, 0x36, 0xfe, 0x3e, 0x00 };   // mov rcx, rdi; call +0x512590

void __fastcall QuickExit(void *) {
    Log("game shut down: ending the process before the engine's teardown");
    TerminateProcess(GetCurrentProcess(), 0);
}

void InstallQuickExit() {
    uint8_t *base = (uint8_t *)GetModuleHandleW(nullptr);
    uint8_t *call = base + TEARDOWN_CALL_RVA + 3;
    if (memcmp(base + TEARDOWN_CALL_RVA, TEARDOWN_CALL_BYTES, sizeof TEARDOWN_CALL_BYTES) != 0) {
        Log("shutdown call not found (another build?): the game exits as stock");
        return;
    }
    // a call rel32 reaches +-2 GB: a stub just below the game's image jumps on to QuickExit
    uint8_t *stub = nullptr;
    for (uintptr_t at = ((uintptr_t)base & ~0xffffull) - 0x10000; at > (uintptr_t)base - 0x70000000; at -= 0x10000)
        if ((stub = (uint8_t *)VirtualAlloc((void *)at, 0x1000, MEM_RESERVE | MEM_COMMIT, PAGE_EXECUTE_READWRITE))) break;
    if (!stub) {
        Log("no room for the shutdown stub: the game exits as stock");
        return;
    }
    uint8_t code[] = { 0x48, 0xb8, 0, 0, 0, 0, 0, 0, 0, 0, 0xff, 0xe0 };   // mov rax, QuickExit; jmp rax
    uint64_t fn = (uint64_t)&QuickExit;
    memcpy(code + 2, &fn, 8);
    memcpy(stub, code, sizeof code);
    int32_t rel = (int32_t)(stub - (call + 5));
    DWORD old;
    if (!VirtualProtect(call, 5, PAGE_EXECUTE_READWRITE, &old)) return;
    memcpy(call + 1, &rel, 4);
    VirtualProtect(call, 5, old, &old);
    FlushInstructionCache(GetCurrentProcess(), call, 5);
    Log("clean exit: the engine's teardown is skipped once the game has shut down");
}

BOOL APIENTRY DllMain(HMODULE self, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) {
        DisableThreadLibraryCalls(self);
        DWORD n = GetModuleFileNameW(self, g_dir, MAX_PATH);
        if (n == 0 || n >= MAX_PATH) return TRUE;
        wchar_t *slash = wcsrchr(g_dir, L'\\');
        if (!slash || (slash - g_dir) + 9 >= MAX_PATH) return TRUE;
        // Only the game gets the plugins. Other programs next to it load this DLL too
        // (the crash reporter, BsSndRpt64.exe, when Echo crashes); for them it is just
        // dbgcore.dll. The game is echovr.exe or a patched copy of it named echovr*.exe:
        // EchoXR starts echovr_openxr.exe.
        wchar_t exe[MAX_PATH];
        DWORD en = GetModuleFileNameW(nullptr, exe, MAX_PATH);
        const wchar_t *exe_name = en ? wcsrchr(exe, L'\\') : nullptr;
        if (!exe_name) return TRUE;
        size_t len = wcslen(++exe_name);
        if (len < 10 || _wcsnicmp(exe_name, L"echovr", 6) != 0 || _wcsicmp(exe_name + len - 4, L".exe") != 0)
            return TRUE;
        wcscpy_s(slash + 1, MAX_PATH - (slash + 1 - g_dir), L"plugins");
        CreateDirectoryW(g_dir, nullptr);
        EchoCombatLogPath(self, 2, "loader.log", g_log, sizeof(g_log));
        Log("EchoCombat plugin loader (%s)", GetCommandLineA());
        InstallQuickExit();
        LoadPlugins();
    }
    return TRUE;
}
