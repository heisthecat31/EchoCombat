package main

// evrtool doctor <gameDir>: why does Echo start on one PC and not another with
// the same files? Checks what differs between machines:
//
//   - every DLL in bin/win10 that EchoCombat touches (dbgcore.dll, plugins/*.dll):
//     can Windows find each DLL it imports? The plugin loader needs the Visual C++
//     2015-2022 x64 runtime; without it the loader cannot load.
//   - is echovr.exe the build the plugins were made for (their hook sites)?
//   - what is in plugins/ (a dbgcore.dll moved there from another mod, a second
//     loader, a stray copy of a plugin)
//   - the end of PowerBoost.log / DroneFix.log
import (
	"bytes"
	"crypto/sha256"
	"debug/pe"
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

type hookSite struct {
	dll, name string
	rva       uint32
	want      []byte
}

var hookSites = []hookSite{
	{"PowerBoost.dll", "HealServer", 0xcecc40, []byte{0x48, 0x89, 0x5c, 0x24, 0x18, 0x56, 0x57, 0x41, 0x56, 0x48, 0x83, 0xec, 0x70}},
	{"PowerBoost.dll", "ProcessDamageServer", 0xd29770, []byte{0x4c, 0x8b, 0xdc, 0x4d, 0x89, 0x4b, 0x20, 0x55, 0x53, 0x56, 0x57, 0x41, 0x54}},
	{"PowerBoost.dll", "SendDamageDealt", 0xcc0670, []byte{0x48, 0x89, 0x5c, 0x24, 0x10, 0x57, 0x48, 0x83, 0xec, 0x60, 0x33, 0xc0}},
	{"PowerBoost.dll", "heal bubble radius check", 0xd6dcc6, []byte{0x4c, 0x8b, 0x7d, 0xc8, 0xf3, 0x41, 0x0f, 0x10, 0x47, 0x38}},
	{"DroneFix.dll", "CR15NetFollowPlayerCS::Update", 0xd65cb0, []byte{0x48, 0x89, 0x5c, 0x24, 0x10, 0x57, 0x48, 0x83, 0xec, 0x20, 0x48, 0x8b, 0xd9}},
}

// readRVA reads n bytes of the image at rva from the file.
func readRVA(f *pe.File, rva uint32, n int) []byte {
	for _, s := range f.Sections {
		if rva >= s.VirtualAddress && rva+uint32(n) <= s.VirtualAddress+s.VirtualSize {
			data, err := s.Data()
			if err != nil {
				return nil
			}
			off := rva - s.VirtualAddress
			if int(off)+n > len(data) {
				return nil
			}
			return data[off : int(off)+n]
		}
	}
	return nil
}

func checkImports(path string) (bad int) {
	f, err := pe.Open(path)
	if err != nil {
		fmt.Printf("  %s: NOT A VALID DLL (%v) -- damaged or blocked\n", path, err)
		return 1
	}
	defer f.Close()
	// ImportedLibraries is a stub in debug/pe; ImportedSymbols gives "sym:DLL".
	syms, _ := f.ImportedSymbols()
	var libs []string
	seen := map[string]bool{}
	for _, s := range syms {
		if i := strings.LastIndex(s, ":"); i >= 0 && !seen[strings.ToLower(s[i+1:])] {
			seen[strings.ToLower(s[i+1:])] = true
			libs = append(libs, s[i+1:])
		}
	}
	var missing []string
	for _, lib := range libs {
		if !dllFindable(lib, filepath.Dir(path)) {
			missing = append(missing, lib)
		}
	}
	if len(missing) > 0 {
		fmt.Printf("  %s: CANNOT LOAD, missing %s\n", filepath.Base(path), strings.Join(missing, ", "))
		if strings.Contains(strings.ToUpper(strings.Join(missing, " ")), "140") {
			fmt.Println("    -> install the Visual C++ 2015-2022 Redistributable (x64): https://aka.ms/vs/17/release/vc_redist.x64.exe")
		}
		return 1
	}
	fmt.Printf("  %s: ok (imports %s)\n", filepath.Base(path), strings.Join(libs, ", "))
	return 0
}

func tail(path string, n int) {
	data, err := os.ReadFile(path)
	if err != nil {
		fmt.Printf("  %s: none (the plugin never ran here)\n", filepath.Base(path))
		return
	}
	lines := strings.Split(strings.TrimRight(string(data), "\r\n"), "\n")
	if len(lines) > n {
		lines = lines[len(lines)-n:]
	}
	fmt.Printf("  %s, last %d lines:\n", filepath.Base(path), len(lines))
	for _, l := range lines {
		fmt.Println("    " + strings.TrimRight(l, "\r"))
	}
}

func doctor(game, bundleDir string) {
	bin := filepath.Join(game, "bin", "win10")
	exe := filepath.Join(bin, "echovr.exe")
	problems := 0

	fmt.Println("== echovr.exe")
	data, err := os.ReadFile(exe)
	if err != nil {
		die("no %s", exe)
	}
	fmt.Printf("  sha256 %x\n", sha256.Sum256(data))
	f, err := pe.NewFile(bytes.NewReader(data))
	if err != nil {
		die("echovr.exe: %v", err)
	}
	for _, h := range hookSites {
		got := readRVA(f, h.rva, len(h.want))
		if !bytes.Equal(got, h.want) {
			fmt.Printf("  %s: %s at +%x does not match -- a different echovr build, %s will not hook\n", h.dll, h.name, h.rva, h.dll)
			problems++
		}
	}
	if problems == 0 {
		fmt.Println("  the build the plugins were made for")
	}

	fmt.Println("== plugin loader and plugins (can each one load on this PC?)")
	loader := filepath.Join(bin, "dbgcore.dll")
	if _, err := os.Stat(loader); err != nil {
		fmt.Println("  bin\\win10\\dbgcore.dll: MISSING -- nothing loads the plugins")
		problems++
	} else {
		ld, _ := os.ReadFile(loader)
		if bundleDir != "" {
			if ours, err := os.ReadFile(filepath.Join(bundleDir, "bin", "win10", "dbgcore.dll")); err == nil && !bytes.Equal(ours, ld) {
				fmt.Println("  bin\\win10\\dbgcore.dll is NOT EchoCombat's plugin loader")
			}
		}
		if !isPluginLoader(ld) {
			fmt.Println("  bin\\win10\\dbgcore.dll does not look like a plugin loader")
		}
		problems += checkImports(loader)
	}
	plugins := filepath.Join(bin, "plugins")
	entries, _ := os.ReadDir(plugins)
	loaders := 0
	for _, e := range entries {
		p := filepath.Join(plugins, e.Name())
		if !strings.EqualFold(filepath.Ext(e.Name()), ".dll") {
			continue
		}
		problems += checkImports(p)
		if d, err := os.ReadFile(p); err == nil && isPluginLoader(d) {
			loaders++
			fmt.Printf("    %s is itself a plugin loader: every plugin gets loaded TWICE (hooks installed twice)\n", e.Name())
		}
		if strings.EqualFold(e.Name(), "dbgcore.dll") || strings.EqualFold(e.Name(), "dbgcore_previous.dll") {
			fmt.Printf("    %s was moved here from bin\\win10 by the installer (another mod's dbgcore.dll). If the server\n"+
				"    needs it to be the real bin\\win10\\dbgcore.dll, that mod breaks: try the server with it removed.\n", e.Name())
		}
	}
	problems += loaders
	if len(entries) == 0 {
		fmt.Println("  plugins\\ is empty or missing")
	}

	fmt.Println("== logs")
	tail(filepath.Join(plugins, "PowerBoost.log"), 8)
	tail(filepath.Join(plugins, "DroneFix.log"), 4)

	fmt.Println("== scripts")
	created := readCreated(filepath.Join(bin, "scripts"))
	fmt.Printf("  %d script DLL(s) added by EchoCombat\n", len(created))

	fmt.Println()
	if problems == 0 {
		fmt.Println("no problems found in the files EchoCombat installs")
	} else {
		fmt.Printf("%d problem(s) found, see above\n", problems)
	}
}
