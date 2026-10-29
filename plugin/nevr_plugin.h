// What EchoCombat's plugins share to run under nEVR (BugSplat64.dll), the Echo VR launcher's
// runtime: its plugin ABI (nevr/plugin_interface.h, from nevr-runtime's sdk/include), the
// version, and the helpers the three plugins use.
//
// nEVR loads a plugin from bin\win10\plugins\ only when _local\config.yaml lists it, then
// calls NvrPluginInitEx once -- that is where the hooks go in -- and NvrPluginShutdown
// before a clean unload. DllMain only records the module: it runs under the loader lock,
// and a DLL that fails nEVR's checks is unloaded right after it, so nothing may be hooked
// there. Whether this is a dedicated server comes from the host (ctx->flags), not from
// the command line.
//
// The plugins log through nEVR's host log (nevr/plugin_logger.h, docs/standards/logging.md
// Rule 15). They write no log file. The build finds the SDK header through NEVR_SDK_INCLUDE.
#pragma once

#include <windows.h>
#include <stdint.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>

#include "nevr/plugin_interface.h"

#define ECHOCOMBAT_VERSION_MAJOR 1
#define ECHOCOMBAT_VERSION_MINOR 1
#define ECHOCOMBAT_VERSION_PATCH 9

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

// True only if `len` bytes at `addr` are exactly `expected`. The same checks as nevr-runtime's
// nevr::ValidatePrologue (plugins/common/include/nevr_common.h): a null pointer or a length
// of 0 is "no match", never "match" (memcmp of 0 bytes returns 0). Call it right before
// writing to the game's code, and skip the patch when it is false.
inline bool EchoCombatBytesMatch(const void *addr, const uint8_t *expected, size_t len) {
    if (!addr || !expected || len == 0) return false;
    return memcmp(addr, expected, len) == 0;
}

// A file next to this plugin's DLL in plugins\ (its .ini).
inline void EchoCombatBesideDll(HMODULE self, char *out, size_t size, const char *file) {
    if (!GetModuleFileNameA(self, out, (DWORD)size)) { out[0] = 0; return; }
    if (char *slash = strrchr(out, '\\')) strcpy_s(slash + 1, size - (slash + 1 - out), file);
}
