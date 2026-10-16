// What EchoCombat's plugins share to run under nEVR (BugSplat64.dll), the Echo VR
// launcher's runtime: its plugin ABI (nevr_plugin_interface.h), the version, and where
// they log.
//
// nEVR loads a plugin from bin\win10\plugins\ only when _local\config.yaml lists it, then
// calls NvrPluginInitEx once -- that is where the hooks go in -- and NvrPluginShutdown
// before a clean unload. DllMain only records the module: it runs under the loader lock,
// and a DLL that fails nEVR's checks is unloaded right after it, so nothing may be hooked
// there. Whether this is a dedicated server comes from the host (ctx->flags), not from
// the command line.
#pragma once

#include <windows.h>
#include <stdint.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>

#include "nevr_plugin_interface.h"

#define ECHOCOMBAT_VERSION_MAJOR 1
#define ECHOCOMBAT_VERSION_MINOR 1
#define ECHOCOMBAT_VERSION_PATCH 8

#define ECHOCOMBAT_EXPORT extern "C" __declspec(dllexport)

inline NvrPluginInfo EchoCombatPluginInfo(const char *name, const char *description) {
    NvrPluginInfo info = {};
    info.name = name;
    info.description = description;
    info.version_major = ECHOCOMBAT_VERSION_MAJOR;
    info.version_minor = ECHOCOMBAT_VERSION_MINOR;
    info.version_patch = ECHOCOMBAT_VERSION_PATCH;
    return info;
}

// The host says whether this is a dedicated server; without a context (a host that
// calls the plain NvrPluginInit), "-server" on the command line decides.
inline bool EchoCombatIsServer(const NvrGameContext *ctx) {
    if (ctx) return (ctx->flags & NEVR_HOST_IS_SERVER) != 0;
    const char *cmd = GetCommandLineA();
    for (const char *p = cmd; p && *p; ++p)
        if ((p == cmd || p[-1] == ' ') && _strnicmp(p, "-server", 7) == 0 &&
            (p[7] == 0 || p[7] == ' ' || p[7] == '"'))
            return true;
    return false;
}

// <bin\win10>\plugin_logs\<name>\<name>.log, where the other plugins log (and where the
// launcher's "Upload logs" picks them up). Always made: the plugins' Log() functions write
// here in every build; ECHOCOMBAT_LOG only adds the extra diagnostic dumps. If the folder
// can't be made or the file can't be opened for append, say so once on stderr and in the
// debugger (nEVR's plugin log channel -- nevr plugin_logger.h; a plugin cannot call the
// host's own Log()), and leave out[0] empty so Log() writes nothing.
inline void EchoCombatLogFail(const char *name, const char *what, const char *path, DWORD err) {
    char line[MAX_PATH + 160];
    sprintf_s(line, "[%s] ERROR log not written: %s '%s' (Win32 error %lu)", name, what, path, err);
    fprintf(stderr, "%s\n", line);
    strcat_s(line, "\n");
    OutputDebugStringA(line);
}

inline bool EchoCombatMakeDir(const char *name, const char *path) {
    if (CreateDirectoryA(path, nullptr)) return true;
    DWORD err = GetLastError();
    if (err == ERROR_ALREADY_EXISTS) return true;
    EchoCombatLogFail(name, "cannot create folder", path, err);
    return false;
}

inline void EchoCombatLogPath(char *out, size_t size, const char *name) {
    out[0] = 0;
    char dir[MAX_PATH];
    DWORD n = GetModuleFileNameA(nullptr, dir, MAX_PATH);
    if (n == 0 || n >= MAX_PATH) { EchoCombatLogFail(name, "cannot find the game folder", "", GetLastError()); return; }
    if (char *slash = strrchr(dir, '\\')) *slash = 0;
    char path[MAX_PATH], file[MAX_PATH];
    sprintf_s(path, "%s\\plugin_logs", dir);
    if (!EchoCombatMakeDir(name, path)) return;
    sprintf_s(path, "%s\\plugin_logs\\%s", dir, name);
    if (!EchoCombatMakeDir(name, path)) return;
    sprintf_s(file, "%s\\%s.log", path, name);
    FILE *f = nullptr;
    if (fopen_s(&f, file, "a") != 0 || !f) { EchoCombatLogFail(name, "cannot open", file, GetLastError()); return; }
    fclose(f);
    sprintf_s(out, size, "%s", file);
}

// True only if `len` bytes at `addr` are exactly `expected`. The same checks as nevr-runtime's
// nevr::ValidatePrologue (plugins/common/include/nevr_common.h): a null pointer or a length
// of 0 is "no match", never "match" (memcmp of 0 bytes returns 0). Call it right before
// writing to the game's code, and skip the patch when it is false.
inline bool EchoCombatBytesMatch(const void *addr, const uint8_t *expected, size_t len) {
    if (!addr || !expected || len == 0) return false;
    return memcmp(addr, expected, len) == 0;
}

// The line format of nevr-runtime's plugin logger (plugins/common/include/plugin_logger.h,
// "[prefix] LEVEL message" on stderr, which is the only log channel it gives a plugin). The
// plugins' Log() calls carry no level, so they go out as INFO; failures are reported above
// with ERROR.
inline void EchoCombatToStderr(const char *fmt, va_list args) {
    char line[1024];
    vsnprintf(line, sizeof(line), fmt, args);
    fprintf(stderr, "[EchoCombat] INFO %s\n", line);
}

// A file next to this plugin's DLL in plugins\ (its .ini).
inline void EchoCombatBesideDll(HMODULE self, char *out, size_t size, const char *file) {
    if (!GetModuleFileNameA(self, out, (DWORD)size)) { out[0] = 0; return; }
    if (char *slash = strrchr(out, '\\')) strcpy_s(slash + 1, size - (slash + 1 - out), file);
}
