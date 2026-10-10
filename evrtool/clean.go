package main

// clean takes out an EchoCombat install made the old way (install.bat / `evrtool setup`,
// which repacked the game's own files) so the install is stock again: the content pack
// is served beside stock files only (NvrContentOverlay checks the stock manifests' sha256).
//
//	evrtool clean <gameDir>
//
//	_data/.../manifests/<pkg>   the stock manifest back from <pkg>.bak, delta packages removed
//	                            (main and side package; other mods' repacks go too)
//	bin/win10/scripts/          each <hash>.dll.orig back over EchoCombat's copy, the DLLs
//	                            it added (echocombat_created.txt) removed
//	bin/win10/dbgcore.dll       removed when it is a plugin loader (EchoCombat's or another
//	                            mod's): nEVR does not start beside one
//	bin/win10/plugins/          the old loader's and plugins' logs (*.log beside the DLLs)

import (
	"bytes"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/EchoTools/cosmetic-editor/EvrFile/manifest"
)

// scriptsType: StreamingScriptWin10, the script assets (a 20-byte header, then the DLL).
const scriptsType = "6eace9f64204fd0"

func gameDataDir(game string) string {
	return filepath.Join(game, "_data", "5932408047", "rad15", "win10")
}

// isPluginLoader: a dbgcore.dll that loads a plugins folder.
func isPluginLoader(data []byte) bool {
	return bytes.Contains(data, []byte("plugins\x00")) && bytes.Contains(data, []byte("LoadLibrary"))
}

// restorePackage puts name's stock manifest back from its .bak and removes the delta
// packages a repack added. False when the package was never repacked.
func restorePackage(dataDir, name string) bool {
	mp := filepath.Join(dataDir, "manifests", name)
	orig, err := manifest.ReadFile(mp + ".bak")
	if err != nil {
		return false
	}
	data, err := os.ReadFile(mp + ".bak")
	if err != nil {
		die("read .bak: %v", err)
	}
	if err := os.WriteFile(mp, data, 0644); err != nil {
		die("write manifest: %v", err)
	}
	for _, leftover := range []string{".bak", ".echocombat", ".echocombat.live", ".bak.echocombat-tmp"} {
		os.Remove(mp + leftover)
	}
	for i := orig.Header.PackageCount; ; i++ {
		p := filepath.Join(dataDir, "packages", fmt.Sprintf("%s_%d", name, i))
		if _, err := os.Stat(p); err != nil {
			break
		}
		if err := os.Remove(p); err != nil {
			die("remove %s: %v", p, err)
		}
		fmt.Println("removed", p)
	}
	fmt.Println("restored the stock manifest of", name)
	return true
}

func clean(game string) {
	data := gameDataDir(game)
	if _, err := os.Stat(filepath.Join(data, "manifests", pkg)); err != nil {
		die("no Echo VR package under %s", data)
	}
	for _, name := range []string{pkg, sidePackage} {
		restorePackage(data, name)
	}

	scripts := filepath.Join(game, "bin", "win10", "scripts")
	created := map[string]bool{}
	if list, err := os.ReadFile(filepath.Join(scripts, "echocombat_created.txt")); err == nil {
		for _, n := range strings.Fields(string(list)) {
			created[n] = true
		}
	}
	entries, _ := os.ReadDir(scripts)
	for _, e := range entries {
		name := e.Name()
		if !strings.HasSuffix(name, ".dll.orig") {
			continue
		}
		dst := filepath.Join(scripts, strings.TrimSuffix(name, ".orig"))
		os.Remove(dst)
		if err := os.Rename(filepath.Join(scripts, name), dst); err != nil {
			die("restore %s: %v", dst, err)
		}
		fmt.Println("restored", dst)
	}
	for n := range created {
		if err := os.Remove(filepath.Join(scripts, n+".dll")); err == nil {
			fmt.Println("removed", filepath.Join(scripts, n+".dll"))
		}
	}
	os.Remove(filepath.Join(scripts, "echocombat_created.txt"))

	bin := filepath.Join(game, "bin", "win10")
	if ld, err := os.ReadFile(filepath.Join(bin, "dbgcore.dll")); err == nil && isPluginLoader(ld) {
		if err := os.Remove(filepath.Join(bin, "dbgcore.dll")); err != nil {
			die("remove the old plugin loader: %v", err)
		}
		os.Remove(filepath.Join(bin, "dbgcore.dll.bak"))
		fmt.Println("removed the old plugin loader", filepath.Join(bin, "dbgcore.dll"))
	}
	for _, log := range []string{"loader.log", "PowerBoost.log", "DroneFix.log", "VeilNet.log", "CombatBots.log"} {
		os.Remove(filepath.Join(bin, "plugins", log))
	}
	fmt.Println("the install is stock again")
}
