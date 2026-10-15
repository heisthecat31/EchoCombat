// Where the plugins' logs go (built with ECHOCOMBAT_LOG): <game>\_local\echoCombatBetaLogs,
// beside the game's own logs, instead of next to the DLLs.
#pragma once
#include <windows.h>
#include <stdio.h>
#include <string.h>

// out = <game>\_local\echoCombatBetaLogs\<name>. `self` sits `depth` folders below the game
// folder: 3 for a plugin (bin\win10\plugins), 2 for the loader (bin\win10). A DLL with fewer
// folders above it logs next to itself.
inline void EchoCombatLogPath(HMODULE self, int depth, const char *name, char *out, size_t size) {
    char dir[MAX_PATH];
    DWORD n = GetModuleFileNameA(self, dir, MAX_PATH);
    if (n == 0 || n >= MAX_PATH) { out[0] = 0; return; }
    char *slash = strrchr(dir, '\\');
    if (!slash) { out[0] = 0; return; }
    *slash = 0;                                           // the DLL's folder
    char root[MAX_PATH];
    strcpy_s(root, dir);
    int up = 0;
    for (; up < depth; ++up) {
        char *s = strrchr(root, '\\');
        if (!s) break;
        *s = 0;
    }
    if (up < depth) { snprintf(out, size, "%s\\%s", dir, name); return; }
    char logs[MAX_PATH];
    snprintf(logs, sizeof(logs), "%s\\_local", root);
#ifdef ECHOCOMBAT_LOG
    CreateDirectoryA(logs, nullptr);
#endif
    strcat_s(logs, "\\echoCombatBetaLogs");
#ifdef ECHOCOMBAT_LOG
    CreateDirectoryA(logs, nullptr);
#endif
    snprintf(out, size, "%s\\%s", logs, name);
}
