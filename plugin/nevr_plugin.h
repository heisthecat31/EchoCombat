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
#include <stdio.h>
#include <string.h>

#include "nevr_plugin_interface.h"

#define ECHOCOMBAT_VERSION_MAJOR 1
#define ECHOCOMBAT_VERSION_MINOR 1
#define ECHOCOMBAT_VERSION_PATCH 2

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
// launcher's "Upload logs" picks them up); the folders are made here, and only in a build
// that logs (ECHOCOMBAT_LOG).
inline void EchoCombatLogPath(char *out, size_t size, const char *name) {
#ifndef ECHOCOMBAT_LOG
    (void)size; (void)name;
    out[0] = 0;
#else
    char dir[MAX_PATH];
    DWORD n = GetModuleFileNameA(nullptr, dir, MAX_PATH);
    if (n == 0 || n >= MAX_PATH) { out[0] = 0; return; }
    if (char *slash = strrchr(dir, '\\')) *slash = 0;
    char path[MAX_PATH];
    sprintf_s(path, "%s\\plugin_logs", dir);
    CreateDirectoryA(path, nullptr);
    sprintf_s(path, "%s\\plugin_logs\\%s", dir, name);
    CreateDirectoryA(path, nullptr);
    sprintf_s(out, size, "%s\\%s.log", path, name);
#endif
}

// A file next to this plugin's DLL in plugins\ (its .ini).
inline void EchoCombatBesideDll(HMODULE self, char *out, size_t size, const char *file) {
    if (!GetModuleFileNameA(self, out, (DWORD)size)) { out[0] = 0; return; }
    if (char *slash = strrchr(out, '\\')) strcpy_s(slash + 1, size - (slash + 1 - out), file);
}
