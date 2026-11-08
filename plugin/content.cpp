// EchoCombatContent: serves EchoCombat's content pack to the game, so players need nothing but
// EchoCombat (no NvrContentOverlay). Same job, same pack format (evrtool pack, content.json):
//
//   <root>\content\echocombat\   the manifests the pack changes (stock ones with our resources
//                                added), the extra packages they name, the script DLLs it replaces
//                                or adds, and content.json (every file's sha256, and the sha256 of
//                                each stock manifest the pack was built from)
//
// <root> is the folder above the plugins folder this DLL loads from (nEVR's root,
// %LOCALAPPDATA%\nevr\echovr). Once the pack checks out:
//   - an open of <data dir>\manifests\<pkg> gets the pack's manifest,
//   - an open of <data dir>\packages\<pkg>_<n> the pack ships gets the pack's file,
//   - the game's module loader (echovr.exe+0xEB0F0, LoadLibraryA of bin\win10\scripts\<hash>.dll:
//     Echo runs script code from there, not from the package) gets the pack's copy of a script.
// Nothing in the game folder changes. If anything doesn't check out (a stock manifest that isn't
// the one the pack was built from, a pack file missing or changed, loaded after the game opened
// its data) it hooks nothing and the game runs stock; DroneFix / PowerBoost / VeilNet then stay
// off too (content_gate.h asks EchoCombatContent_Served).
//
// It must load before the game reads its manifests: nEVR's early pass (config.yaml `early: true`).
// When NvrContentOverlay is loaded as well (the Echo VR launcher installs it for content packs),
// that one serves the pack and this one does nothing.

#include <windows.h>
#include <bcrypt.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <map>
#include <string>
#include <vector>
#include "detours.h"
#include "nevr_plugin.h"
#include "nevr/plugin_logger.h"
#include "nlohmann/json.hpp"
#include "content_gate.h"

#pragma comment(lib, "bcrypt.lib")

namespace {

NEVR_DEFINE_PLUGIN_LOG("[EchoCombatContent]")

using json = nlohmann::json;
constexpr const char *kPackId = "echocombat";

// echovr.exe 631547 (rad15_live) and its module loader: void *LoadModule(const char *path,
// void *arg, int call_main, int reuse_loaded): LoadLibraryA(path), then RadPluginMain(arg).
constexpr DWORD kLiveBuild = 0x6452DFF6;
constexpr uintptr_t kLoadModuleRva = 0xEB0F0;
constexpr uint8_t kLoadModuleHead[] = {0x48, 0x89, 0x5C, 0x24, 0x08, 0x48, 0x89, 0x74,
                                       0x24, 0x10, 0x57, 0x48, 0x81, 0xEC, 0xA0, 0x04};

using create_w_fn = HANDLE(WINAPI *)(LPCWSTR, DWORD, DWORD, LPSECURITY_ATTRIBUTES, DWORD, DWORD, HANDLE);
using create_a_fn = HANDLE(WINAPI *)(LPCSTR, DWORD, DWORD, LPSECURITY_ATTRIBUTES, DWORD, DWORD, HANDLE);
using load_module_fn = void *(__fastcall *)(const char *, void *, int, int);
create_w_fn Real_CreateFileW = CreateFileW;
create_a_fn Real_CreateFileA = CreateFileA;
load_module_fn Real_LoadModule = nullptr;
bool g_hooked = false;
volatile bool g_served = false;

// Filled before the hooks go in, only read afterwards.
std::map<std::wstring, std::wstring> g_files;   // stock path (full, lower case) -> pack file
std::map<std::string, std::string> g_scripts;   // "<hash>.dll" (lower case) -> pack file (ANSI)
std::vector<std::wstring> g_first_packages;     // <data dir>\packages\<pkg>_0 of each manifest
volatile LONG g_file_hits = 0, g_script_hits = 0;
thread_local bool t_in_hook = false;

std::wstring ExeDir() {
    wchar_t path[MAX_PATH];
    DWORD n = GetModuleFileNameW(nullptr, path, MAX_PATH);
    if (n == 0 || n >= MAX_PATH) return L"";
    if (wchar_t *slash = wcsrchr(path, L'\\')) *slash = 0;
    return path;
}

// The folder above the "plugins" folder this DLL was loaded from (nEVR's root).
std::wstring PluginRoot() {
    HMODULE self = nullptr;
    wchar_t path[MAX_PATH];
    if (!GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                            (LPCWSTR)&PluginRoot, &self))
        return ExeDir();
    DWORD n = GetModuleFileNameW(self, path, MAX_PATH);
    if (n == 0 || n >= MAX_PATH) return ExeDir();
    wchar_t *slash = wcsrchr(path, L'\\');
    if (!slash) return ExeDir();
    *slash = 0;
    slash = wcsrchr(path, L'\\');
    if (!slash || _wcsicmp(slash + 1, L"plugins") != 0) return ExeDir();
    *slash = 0;
    return path;
}

std::wstring Widen(const std::string &s) {
    if (s.empty()) return L"";
    int n = MultiByteToWideChar(CP_UTF8, 0, s.data(), (int)s.size(), nullptr, 0);
    std::wstring out(n, L'\0');
    MultiByteToWideChar(CP_UTF8, 0, s.data(), (int)s.size(), &out[0], n);
    return out;
}

std::string Narrow(const std::wstring &s) {
    if (s.empty()) return "";
    int n = WideCharToMultiByte(CP_UTF8, 0, s.data(), (int)s.size(), nullptr, 0, nullptr, nullptr);
    std::string out(n, '\0');
    WideCharToMultiByte(CP_UTF8, 0, s.data(), (int)s.size(), &out[0], n, nullptr, nullptr);
    return out;
}

// A full path in one spelling: backslashes, no \\?\, no "." or "..", lower case.
std::wstring Canonical(const std::wstring &path) {
    std::wstring in = path;
    for (wchar_t &c : in) if (c == L'/') c = L'\\';
    if (in.compare(0, 4, L"\\\\?\\") == 0 && in.compare(0, 8, L"\\\\?\\UNC\\") != 0) in.erase(0, 4);
    wchar_t buf[MAX_PATH * 2];
    DWORD n = GetFullPathNameW(in.c_str(), MAX_PATH * 2, buf, nullptr);
    std::wstring out = (n == 0 || n >= MAX_PATH * 2) ? in : std::wstring(buf, n);
    if (!out.empty()) CharLowerBuffW(&out[0], (DWORD)out.size());
    return out;
}

DWORD ExeTimestamp() {
    const BYTE *base = (const BYTE *)GetModuleHandleW(nullptr);
    auto dos = (const IMAGE_DOS_HEADER *)base;
    return ((const IMAGE_NT_HEADERS64 *)(base + dos->e_lfanew))->FileHeader.TimeDateStamp;
}

// The file's sha256 in lower-case hex, "" when it can't be read.
std::string Sha256(const std::wstring &path) {
    HANDLE f = Real_CreateFileW(path.c_str(), GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING,
                                FILE_FLAG_SEQUENTIAL_SCAN, nullptr);
    if (f == INVALID_HANDLE_VALUE) return "";
    BCRYPT_ALG_HANDLE alg = nullptr;
    BCRYPT_HASH_HANDLE hash = nullptr;
    std::string out;
    if (BCryptOpenAlgorithmProvider(&alg, BCRYPT_SHA256_ALGORITHM, nullptr, 0) == 0 &&
        BCryptCreateHash(alg, &hash, nullptr, 0, nullptr, 0, 0) == 0) {
        std::vector<UCHAR> buf(1 << 20);
        DWORD got = 0;
        BOOL ok;
        while ((ok = ReadFile(f, buf.data(), (DWORD)buf.size(), &got, nullptr)) && got > 0)
            BCryptHashData(hash, buf.data(), got, 0);
        UCHAR digest[32];
        if (ok && BCryptFinishHash(hash, digest, sizeof(digest), 0) == 0) {
            static const char hex[] = "0123456789abcdef";
            for (UCHAR b : digest) { out += hex[b >> 4]; out += hex[b & 15]; }
        }
    }
    if (hash) BCryptDestroyHash(hash);
    if (alg) BCryptCloseAlgorithmProvider(alg, 0);
    CloseHandle(f);
    return out;
}

bool IsHex(const std::string &s, size_t len) {
    if (s.size() != len) return false;
    for (char c : s) if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'))) return false;
    return true;
}

// A path inside the pack: forward slashes, plain names, nothing absolute or climbing out.
bool IsPackPath(const std::string &p) {
    if (p.empty() || p.size() > 200 || p.front() == '/' || p.back() == '/') return false;
    size_t start = 0;
    for (;;) {
        size_t end = p.find('/', start);
        std::string part = p.substr(start, end == std::string::npos ? std::string::npos : end - start);
        if (part.empty() || part == "." || part == "..") return false;
        for (char c : part)
            if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '.' ||
                  c == '_' || c == '-'))
                return false;
        if (end == std::string::npos) return true;
        start = end + 1;
    }
}

std::string BaseName(const std::string &p) {
    size_t at = p.find_last_of('/');
    return at == std::string::npos ? p : p.substr(at + 1);
}

std::wstring PackFile(const std::wstring &dir, const std::string &rel) {
    std::wstring out = dir + L"\\" + Widen(rel);
    for (wchar_t &c : out) if (c == L'/') c = L'\\';
    return out;
}

// Reads and checks content.json, the pack's files and the stock manifests; fills g_files and
// g_scripts. false (reason logged) leaves both empty.
bool LoadPack(const std::wstring &dir) {
    const std::wstring root = ExeDir() + L"\\..\\..";
    json pack;
    {
        FILE *f = nullptr;
        if (_wfopen_s(&f, (dir + L"\\content.json").c_str(), L"rb") != 0 || !f) { PluginLogError("no content.json in %s: the game runs stock", Narrow(dir).c_str()); return false; }
        std::string text;
        char buf[4096];
        size_t n;
        while ((n = fread(buf, 1, sizeof(buf), f)) > 0 && text.size() < (1u << 20)) text.append(buf, n);
        fclose(f);
        pack = json::parse(text, nullptr, false);
    }
    auto str = [](const json &o, const char *key) -> std::string {
        auto it = o.find(key);
        return it != o.end() && it->is_string() ? it->get<std::string>() : std::string();
    };
    if (!pack.is_object() || pack.value("format", 0) != 1 || str(pack, "id") != kPackId) {
        PluginLogError("content.json isn't a format 1 pack with id %s", kPackId);
        return false;
    }

    std::map<std::string, std::string> files;     // every pack file, checked against its sha256
    auto fit = pack.find("files");
    if (fit == pack.end() || !fit->is_object()) { PluginLogError("content.json lists no files"); return false; }
    for (auto &item : fit->items()) {
        const std::string &rel = item.key();
        std::string want = item.value().is_string() ? item.value().get<std::string>() : std::string();
        for (char &c : want) c = (char)tolower((unsigned char)c);
        if (!IsPackPath(rel) || !IsHex(want, 64)) { PluginLogError("bad file entry '%s'", rel.c_str()); return false; }
        std::string got = Sha256(PackFile(dir, rel));
        if (got != want) {
            PluginLogError("pack file %s is %s: reinstall EchoCombat", rel.c_str(), got.empty() ? "missing" : "changed");
            return false;
        }
        files[rel] = want;
    }

    std::string data_rel = str(pack, "data_dir");
    if (!IsPackPath(data_rel)) { PluginLogError("bad data_dir '%s'", data_rel.c_str()); return false; }
    const std::wstring data = PackFile(root, data_rel);

    std::map<std::wstring, std::wstring> mapped;
    auto mit = pack.find("manifests");
    if (mit == pack.end() || !mit->is_array()) { PluginLogError("content.json has no manifests"); return false; }
    for (const json &m : *mit) {
        std::string pkg = m.is_object() ? str(m, "package") : std::string();
        std::string stock = m.is_object() ? str(m, "stock_sha256") : std::string();
        std::string file = m.is_object() ? str(m, "file") : std::string();
        int count = m.is_object() ? m.value("stock_packages", 0) : 0;
        if (!IsHex(pkg, 16) || !IsHex(stock, 64) || count < 1 || !files.count(file)) {
            PluginLogError("bad manifest entry '%s'", pkg.c_str());
            return false;
        }
        const std::wstring stock_path = data + L"\\manifests\\" + Widen(pkg);
        std::string got = Sha256(stock_path);
        if (got != stock) {
            PluginLogError("the game's manifest %s is %s, not the one the pack was built from: the game runs stock "
                           "(restore the stock game files, e.g. verify them in the Oculus / Meta app)",
                           pkg.c_str(), got.empty() ? "missing" : "not stock");
            return false;
        }
        mapped[Canonical(stock_path)] = PackFile(dir, file);
        g_first_packages.push_back(data + L"\\packages\\" + Widen(pkg) + L"_0");
        auto pit = m.find("packages");
        if (pit != m.end() && !pit->is_array()) { PluginLogError("packages of %s isn't a list", pkg.c_str()); return false; }
        if (pit == m.end()) continue;
        for (const json &p : *pit) {
            std::string rel = p.is_string() ? p.get<std::string>() : std::string();
            std::string name = BaseName(rel);
            bool ours = files.count(rel) && name.size() > pkg.size() + 1 && name.compare(0, pkg.size(), pkg) == 0 &&
                        name[pkg.size()] == '_';
            int n = ours ? atoi(name.c_str() + pkg.size() + 1) : -1;
            if (!ours || n < count || std::to_string(n) != name.substr(pkg.size() + 1)) {
                PluginLogError("'%s' isn't one of %s's added packages", rel.c_str(), pkg.c_str());
                return false;
            }
            mapped[Canonical(data + L"\\packages\\" + Widen(name))] = PackFile(dir, rel);
        }
    }

    std::map<std::string, std::string> scripts;
    auto sit = pack.find("scripts");
    if (sit != pack.end() && !sit->is_array()) { PluginLogError("scripts isn't a list"); return false; }
    if (sit != pack.end() && !sit->empty()) {
        // The loader takes an ANSI path: the pack's folder needs one (else its 8.3 name).
        std::wstring wdir = dir;
        BOOL lossy = FALSE;
        int n = WideCharToMultiByte(CP_ACP, WC_NO_BEST_FIT_CHARS, wdir.c_str(), -1, nullptr, 0, nullptr, &lossy);
        if (lossy) {
            wchar_t short_path[MAX_PATH];
            DWORD sn = GetShortPathNameW(dir.c_str(), short_path, MAX_PATH);
            if (sn > 0 && sn < MAX_PATH) wdir = short_path;
            lossy = FALSE;
            n = WideCharToMultiByte(CP_ACP, WC_NO_BEST_FIT_CHARS, wdir.c_str(), -1, nullptr, 0, nullptr, &lossy);
        }
        if (lossy || n <= 0) { PluginLogError("the pack's folder has no ANSI path for the game's script loader"); return false; }
        std::string adir(n - 1, '\0');
        WideCharToMultiByte(CP_ACP, WC_NO_BEST_FIT_CHARS, wdir.c_str(), -1, &adir[0], n, nullptr, nullptr);
        for (const json &s : *sit) {
            std::string rel = s.is_string() ? s.get<std::string>() : std::string();
            std::string name = BaseName(rel);
            if (!files.count(rel) || rel != "scripts/" + name || name.size() != 20 || !IsHex(name.substr(0, 16), 16) ||
                name.compare(16, 4, ".dll") != 0) {
                PluginLogError("'%s' isn't a script (scripts/<16 hex>.dll)", rel.c_str());
                return false;
            }
            scripts[name] = adir + "\\scripts\\" + name;
        }
    }
    g_files.swap(mapped);
    g_scripts.swap(scripts);
    PluginLog("pack %s %s: %zu files checked, %zu stock files served from the pack, %zu scripts", kPackId,
              str(pack, "version").c_str(), files.size(), g_files.size(), g_scripts.size());
    return true;
}

// The game keeps its packages open from when it reads the manifests: a stock package that
// can't be opened without sharing means it has, and serving now would mix pack scripts with
// stock data.
bool DataAlreadyOpen() {
    for (const std::wstring &path : g_first_packages) {
        HANDLE h = Real_CreateFileW(path.c_str(), GENERIC_READ, 0, nullptr, OPEN_EXISTING, 0, nullptr);
        if (h != INVALID_HANDLE_VALUE) { CloseHandle(h); continue; }
        if (GetLastError() == ERROR_SHARING_VIOLATION) return true;
    }
    return false;
}

const std::wstring *PackFor(LPCWSTR name, DWORD access, DWORD disposition) {
    if (!g_served || disposition != OPEN_EXISTING ||
        (access & (GENERIC_WRITE | GENERIC_ALL | FILE_WRITE_DATA | FILE_APPEND_DATA | DELETE)))
        return nullptr;
    auto it = g_files.find(Canonical(name));
    return it == g_files.end() ? nullptr : &it->second;
}

HANDLE OpenW(LPCWSTR name, DWORD access, DWORD share, LPSECURITY_ATTRIBUTES sa, DWORD disposition, DWORD flags,
             HANDLE tmpl) {
    if (t_in_hook || !name) return Real_CreateFileW(name, access, share, sa, disposition, flags, tmpl);
    t_in_hook = true;
    HANDLE h;
    if (const std::wstring *pack = PackFor(name, access, disposition)) {
        h = Real_CreateFileW(pack->c_str(), access, share, sa, disposition, flags, tmpl);
        DWORD err = GetLastError();
        LONG n = InterlockedIncrement(&g_file_hits);
        if (h == INVALID_HANDLE_VALUE) PluginLogError("serving %ls from the pack FAILED (error %lu)", name, err);
        else if (n <= 8) PluginLogDebug("%ls -> %ls", name, pack->c_str());
        SetLastError(err);
    } else {
        h = Real_CreateFileW(name, access, share, sa, disposition, flags, tmpl);
    }
    t_in_hook = false;
    return h;
}

HANDLE WINAPI Hooked_CreateFileW(LPCWSTR name, DWORD access, DWORD share, LPSECURITY_ATTRIBUTES sa, DWORD disposition,
                                 DWORD flags, HANDLE tmpl) {
    return OpenW(name, access, share, sa, disposition, flags, tmpl);
}

HANDLE WINAPI Hooked_CreateFileA(LPCSTR name, DWORD access, DWORD share, LPSECURITY_ATTRIBUTES sa, DWORD disposition,
                                 DWORD flags, HANDLE tmpl) {
    if (t_in_hook || !name || !g_served) return Real_CreateFileA(name, access, share, sa, disposition, flags, tmpl);
    wchar_t wide[MAX_PATH * 2];
    if (!MultiByteToWideChar(CP_ACP, 0, name, -1, wide, MAX_PATH * 2))
        return Real_CreateFileA(name, access, share, sa, disposition, flags, tmpl);
    if (!PackFor(wide, access, disposition)) return Real_CreateFileA(name, access, share, sa, disposition, flags, tmpl);
    return OpenW(wide, access, share, sa, disposition, flags, tmpl);
}

// The pack's copy of a script the game loads from ...\scripts\<hash>.dll, or nullptr.
const std::string *ScriptFor(const char *path) {
    if (!g_served) return nullptr;
    size_t len = strlen(path);
    if (len < 28) return nullptr;                    // "scripts\" + 16 hex + ".dll"
    const char *name = path + len - 20;
    char sep = name[-1];
    if ((sep != '\\' && sep != '/') || _strnicmp(name - 8, "scripts", 7) != 0) return nullptr;
    if (len > 28 && name[-9] != '\\' && name[-9] != '/') return nullptr;
    std::string key(name, 20);
    for (char &c : key) c = (char)tolower((unsigned char)c);
    auto it = g_scripts.find(key);
    return it == g_scripts.end() ? nullptr : &it->second;
}

void *__fastcall Hooked_LoadModule(const char *path, void *arg, int call_main, int reuse) {
    if (path) {
        if (const std::string *pack = ScriptFor(path)) {
            void *h = Real_LoadModule(pack->c_str(), arg, call_main, reuse);
            LONG n = InterlockedIncrement(&g_script_hits);
            if (!h) PluginLogError("script %s from the pack FAILED to load", pack->c_str());
            else if (n <= 4) PluginLogDebug("script %s -> %s", path, pack->c_str());
            return h;
        }
    }
    return Real_LoadModule(path, arg, call_main, reuse);
}

bool Install() {
    if (g_hooked) return true;
    if (EchoCombatOverlayServing()) {
        PluginLog("NvrContentOverlay serves the pack: this plugin stays off");
        return false;
    }
    if (GetModuleHandleW(L"NvrContentOverlay.dll")) {
        char reason[700];
        EchoCombatOverlayReason(reason, sizeof(reason));
        PluginLogWarning("NvrContentOverlay is loaded but refused the pack (%s): trying to serve it here",
                         reason[0] ? reason : "its log says nothing");
    }
    const std::wstring dir = PluginRoot() + L"\\content\\" + Widen(kPackId);
    if (!LoadPack(dir)) return false;
    if (DataAlreadyOpen()) {
        PluginLogError("loaded too late: the game has opened its data already. It must be listed with `early: true` "
                       "in config.yaml (run install_nevr_local.bat again). The game runs stock");
        return false;
    }
    uint8_t *load = (uint8_t *)GetModuleHandleW(nullptr) + kLoadModuleRva;
    const bool loader_ok = ExeTimestamp() == kLiveBuild && EchoCombatBytesMatch(load, kLoadModuleHead, sizeof(kLoadModuleHead));
    if (!g_scripts.empty() && !loader_ok) {
        PluginLogError("this isn't echovr.exe 631547 (its script loader differs): the game runs stock");
        return false;
    }
    Real_LoadModule = (load_module_fn)load;
    DetourTransactionBegin();
    DetourUpdateThread(GetCurrentThread());
    DetourAttach(&(PVOID &)Real_CreateFileW, (PVOID)Hooked_CreateFileW);
    DetourAttach(&(PVOID &)Real_CreateFileA, (PVOID)Hooked_CreateFileA);
    if (!g_scripts.empty()) DetourAttach(&(PVOID &)Real_LoadModule, (PVOID)Hooked_LoadModule);
    LONG rc = DetourTransactionCommit();
    if (rc != NO_ERROR) {
        PluginLogError("hooking the file opens failed (%ld): the game runs stock", rc);
        Real_CreateFileW = CreateFileW;
        Real_CreateFileA = CreateFileA;
        return false;
    }
    g_hooked = true;
    g_served = true;
    PluginLog("serving the EchoCombat pack");
    return true;
}

void Uninstall() {
    g_served = false;
    if (!g_hooked) return;
    DetourTransactionBegin();
    DetourUpdateThread(GetCurrentThread());
    DetourDetach(&(PVOID &)Real_CreateFileW, (PVOID)Hooked_CreateFileW);
    DetourDetach(&(PVOID &)Real_CreateFileA, (PVOID)Hooked_CreateFileA);
    if (!g_scripts.empty()) DetourDetach(&(PVOID &)Real_LoadModule, (PVOID)Hooked_LoadModule);
    DetourTransactionCommit();
    g_hooked = false;
    PluginLog("shut down (%ld file opens and %ld scripts served from the pack)", g_file_hits, g_script_hits);
}

} // namespace

// DroneFix / PowerBoost / VeilNet (content_gate.h): is EchoCombat's pack the game's data?
extern "C" __declspec(dllexport) int __cdecl EchoCombatContent_Served() { return g_served ? 1 : 0; }

ECHOCOMBAT_EXPORT NvrPluginInfo NvrPluginGetInfo(void) {
    return EchoCombatPluginInfo("echocombat_content", "EchoCombat: serves EchoCombat's game data (load early)");
}

ECHOCOMBAT_EXPORT uint32_t NvrPluginGetApiVersion(void) { return NEVR_PLUGIN_API_VERSION; }

ECHOCOMBAT_EXPORT uint32_t NvrPluginGetCapabilities(void) {
    return NEVR_PLUGIN_CAP_ALTERS_GAMEPLAY | NEVR_PLUGIN_CAP_HOOKS_ENGINE;
}

// Nonzero (refused): nEVR unloads the DLL, the game runs stock and the other plugins see no pack.
ECHOCOMBAT_EXPORT int NvrPluginInitEx(const NvrGameContext *ctx, const char *) {
    PluginLogBind(ctx);
    return Install() ? 0 : 1;
}

ECHOCOMBAT_EXPORT int NvrPluginInit(const NvrGameContext *ctx) { return NvrPluginInitEx(ctx, "{}"); }

ECHOCOMBAT_EXPORT void NvrPluginShutdown(void) { Uninstall(); }

BOOL APIENTRY DllMain(HMODULE self, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) DisableThreadLibraryCalls(self);
    return TRUE;
}
