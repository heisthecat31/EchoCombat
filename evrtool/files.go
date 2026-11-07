package main

// The loose files of a player install, next to the package merge:
//
//	bin/win10/scripts/<hash>.dll  Echo loads script code from here, not from the package.
//	                              Written from the stage's script assets (6eace9f64204fd0,
//	                              a 20-byte header before the PE); each original is kept
//	                              once as <hash>.dll.orig.
//	bin/win10/plugins/*.dll       PowerBoost.dll, DroneFix.dll, VeilNet.dll
//	bin/win10/dbgcore.dll         the plugin loader, which loads plugins/. A dbgcore.dll
//	                              already there from another mod is moved into plugins/
//	                              so the loader still loads it; an older plugin loader
//	                              is replaced instead (kept as dbgcore.dll.bak), so the
//	                              plugins are not loaded twice.
//
// Every write is read back.

import (
	"bytes"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

const scriptsType = "6eace9f64204fd0"

// bundle is the extracted zip: stage/ and bin/win10/.
type bundle struct{ dir string }

func (b bundle) stage() string { return filepath.Join(b.dir, "stage") }
func (b bundle) bin(p ...string) string {
	return filepath.Join(append([]string{b.dir, "bin", "win10"}, p...)...)
}

func gameDataDir(game string) string {
	return filepath.Join(game, "_data", "5932408047", "rad15", "win10")
}

// plugins lists the bundle's plugin files: the DLLs and their .ini settings
// (PowerBoost.ini, written from config/mp_weapon_settings.json).
func (b bundle) plugins() []string {
	entries, _ := os.ReadDir(b.bin("plugins"))
	var out []string
	for _, e := range entries {
		if ext := filepath.Ext(e.Name()); strings.EqualFold(ext, ".dll") || strings.EqualFold(ext, ".ini") {
			out = append(out, e.Name())
		}
	}
	return out
}

// preflight fails before anything is changed when the bundle is incomplete,
// which is what antivirus quarantining a DLL looks like.
func (b bundle) preflight() {
	var missing []string
	for _, p := range []string{b.stage(), filepath.Join(b.stage(), scriptsType), b.bin("dbgcore.dll"),
		b.bin("plugins", "PowerBoost.dll"), b.bin("plugins", "DroneFix.dll"), b.bin("plugins", "VeilNet.dll")} {
		if _, err := os.Stat(p); err != nil {
			missing = append(missing, p)
		}
	}
	if len(missing) > 0 {
		die("these files from the zip are missing (nothing was changed):\n  %s\n"+
			"Extract the whole zip again. If they disappear again, your antivirus removed them: "+
			"restore them from Windows Security > Protection history, or allow the folder.",
			strings.Join(missing, "\n  "))
	}
}

func writeChecked(path string, data []byte) {
	if err := os.WriteFile(path, data, 0644); err != nil {
		die("write %s: %v", path, err)
	}
	got, err := os.ReadFile(path)
	if err != nil || !bytes.Equal(got, data) {
		die("%s did not keep what was written (antivirus?): %v", path, err)
	}
}

func copyChecked(src, dst string) {
	data, err := os.ReadFile(src)
	if err != nil {
		die("read %s: %v", src, err)
	}
	writeChecked(dst, data)
}

func installScripts(game string, b bundle) {
	dir := filepath.Join(game, "bin", "win10", "scripts")
	if err := os.MkdirAll(dir, 0755); err != nil {
		die("create %s: %v", dir, err)
	}
	entries, err := os.ReadDir(filepath.Join(b.stage(), scriptsType))
	if err != nil {
		die("read staged scripts: %v", err)
	}
	created := readCreated(dir)
	defer writeCreated(dir, created)
	// What an earlier EchoCombat wrote and this one no longer ships goes back to stock first,
	// so no old script stays behind (the party-gun Pulsar script did, 2026-11-07).
	staged := map[string]bool{}
	for _, e := range entries {
		staged[e.Name()] = true
	}
	for _, name := range ourScripts(dir, created) {
		if !staged[name] {
			restoreScript(dir, name, created)
		}
	}
	writeList(dir, scriptsList, staged)
	for _, e := range entries {
		asset, err := os.ReadFile(filepath.Join(b.stage(), scriptsType, e.Name()))
		if err != nil {
			die("read script %s: %v", e.Name(), err)
		}
		mz := bytes.Index(asset, []byte("MZ"))
		if mz < 0 || mz > 64 {
			die("staged script %s holds no PE image", e.Name())
		}
		dst := filepath.Join(dir, e.Name()+".dll")
		if _, err := os.Stat(dst); err != nil {
			created[e.Name()] = true
		} else if _, err := os.Stat(dst + ".orig"); err != nil && !created[e.Name()] {
			copyChecked(dst, dst+".orig")
		}
		writeChecked(dst, asset[mz:])
		fmt.Println("wrote", dst)
	}
}

// createdList names the script DLLs EchoCombat added (no original to keep), so
// a reinstall does not take its own DLL for an original.
const createdList = "echocombat_created.txt"

// scriptsList names every script DLL the last install wrote; pluginsList (in plugins\) every
// plugin file. A reinstall takes back what the new build no longer ships.
const scriptsList = "echocombat_scripts.txt"
const pluginsList = "echocombat_plugins.txt"

func readList(dir, name string) map[string]bool {
	m := map[string]bool{}
	data, _ := os.ReadFile(filepath.Join(dir, name))
	for _, n := range strings.Fields(string(data)) {
		m[n] = true
	}
	return m
}

func writeList(dir, name string, m map[string]bool) {
	var names []string
	for n := range m {
		names = append(names, n)
	}
	sort.Strings(names)
	writeChecked(filepath.Join(dir, name), []byte(strings.Join(names, "\n")+"\n"))
}

func readCreated(dir string) map[string]bool     { return readList(dir, createdList) }
func writeCreated(dir string, m map[string]bool) { writeList(dir, createdList, m) }

// ourScripts: every script DLL an EchoCombat install has touched: the last install's list,
// the ones it added, and (installs from before the list) every <hash>.dll with a .orig beside
// it, which only an EchoCombat install makes.
func ourScripts(dir string, created map[string]bool) []string {
	set := readList(dir, scriptsList)
	for n := range created {
		set[n] = true
	}
	entries, _ := os.ReadDir(dir)
	for _, e := range entries {
		if n, ok := strings.CutSuffix(e.Name(), ".dll.orig"); ok {
			set[n] = true
		}
	}
	var out []string
	for n := range set {
		out = append(out, n)
	}
	sort.Strings(out)
	return out
}

// restoreScript puts script `name` back to stock: its .orig, or no file when EchoCombat added it.
func restoreScript(dir, name string, created map[string]bool) {
	dst := filepath.Join(dir, name+".dll")
	if _, err := os.Stat(dst + ".orig"); err == nil && !created[name] {
		os.Remove(dst)
		if err := os.Rename(dst+".orig", dst); err != nil {
			die("restore %s: %v", dst, err)
		}
		fmt.Println("restored stock", dst)
	} else if err := os.Remove(dst); err == nil {
		fmt.Println("removed", dst)
	}
	delete(created, name)
}

// isPluginLoader: a dbgcore.dll that loads a plugins folder.
func isPluginLoader(data []byte) bool {
	return bytes.Contains(data, []byte("plugins\x00")) && bytes.Contains(data, []byte("LoadLibrary"))
}

func installPlugins(game string, b bundle) {
	bin := filepath.Join(game, "bin", "win10")
	plugins := filepath.Join(bin, "plugins")
	if err := os.MkdirAll(plugins, 0755); err != nil {
		die("create %s: %v", plugins, err)
	}
	loader, err := os.ReadFile(b.bin("dbgcore.dll"))
	if err != nil {
		die("read plugin loader: %v", err)
	}
	dst := filepath.Join(bin, "dbgcore.dll")
	if old, err := os.ReadFile(dst); err == nil && !bytes.Equal(old, loader) {
		if isPluginLoader(old) {
			copyChecked(dst, dst+".bak")
			fmt.Println("replacing an older plugin loader (kept as dbgcore.dll.bak)")
		} else {
			moved := filepath.Join(plugins, "dbgcore.dll")
			if prev, err := os.ReadFile(moved); err == nil && !bytes.Equal(prev, old) {
				moved = filepath.Join(plugins, "dbgcore_previous.dll")
			}
			writeChecked(moved, old)
			fmt.Println("moved the existing dbgcore.dll to", moved, "so the plugin loader still loads it")
		}
	}
	writeChecked(dst, loader)
	fmt.Println("wrote", dst, "(plugin loader)")
	if checkImports(dst) > 0 {
		fmt.Println("  WARNING: the plugin loader cannot load on this PC until that is installed; " +
			"Echo may fail to start (run doctor.bat to check again)")
	}
	shipped := map[string]bool{}
	for _, name := range b.plugins() {
		shipped[name] = true
	}
	for name := range readList(plugins, pluginsList) { // an older EchoCombat's, not shipped now
		if !shipped[name] {
			if err := os.Remove(filepath.Join(plugins, name)); err == nil {
				fmt.Println("removed", filepath.Join(plugins, name), "(no longer part of EchoCombat)")
			}
		}
	}
	for _, name := range b.plugins() {
		copyChecked(b.bin("plugins", name), filepath.Join(plugins, name))
		fmt.Println("wrote", filepath.Join(plugins, name))
	}
	writeList(plugins, pluginsList, shipped)
}

// setup is the whole player install: merge the packages, then the loose files.
func setup(game, dir string) {
	b := bundle{dir}
	if clean, ok := b.cleanCopy(); ok { // only this release's files, checked
		defer os.RemoveAll(clean.dir)
		b = clean
	}
	b.preflight()
	data := gameDataDir(game)
	if _, err := os.Stat(manifestPath(data)); err != nil {
		die("no Echo VR package under %s", data)
	}
	install(data, b.stage())
	installScripts(game, b)
	installPlugins(game, b)
}

// remove takes EchoCombat out again and leaves other mods, and the plugin
// loader (other plugins may use it), in place.
func remove(game, dir string) {
	b := bundle{dir}
	data := gameDataDir(game)
	unmerge(data)
	mainPkg := pkg
	pkg = sidePackage
	if _, err := os.Stat(manifestPath(data)); err == nil {
		unmerge(data)
	}
	pkg = mainPkg
	scripts := filepath.Join(game, "bin", "win10", "scripts")
	created := readCreated(scripts)
	names := map[string]bool{} // everything EchoCombat touched, any version
	for _, n := range ourScripts(scripts, created) {
		names[n] = true
	}
	entries, _ := os.ReadDir(filepath.Join(b.stage(), scriptsType))
	for _, e := range entries {
		names[e.Name()] = true
	}
	for n := range names {
		restoreScript(scripts, n, created)
	}
	os.Remove(filepath.Join(scripts, createdList))
	os.Remove(filepath.Join(scripts, scriptsList))
	plugins := filepath.Join(game, "bin", "win10", "plugins")
	ours := readList(plugins, pluginsList)
	for _, name := range b.plugins() {
		ours[name] = true
	}
	for name := range ours {
		p := filepath.Join(plugins, name)
		if err := os.Remove(p); err == nil {
			fmt.Println("removed", p)
		}
	}
	os.Remove(filepath.Join(plugins, pluginsList))
}
