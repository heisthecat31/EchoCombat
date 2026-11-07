package main

import (
	"crypto/sha256"
	"encoding/hex"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func put(t *testing.T, path, data string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(data), 0644); err != nil {
		t.Fatal(err)
	}
}

func read(t *testing.T, path string) string {
	t.Helper()
	b, err := os.ReadFile(path)
	if err != nil {
		return "<missing>"
	}
	return string(b)
}

// A release folder with files.txt, plus a leftover from an older zip extracted over it.
func TestCleanCopyIgnoresLeftovers(t *testing.T) {
	dir := t.TempDir()
	files := map[string]string{
		"stage/" + scriptsType + "/aaaa": "hdr.MZnew-a",
		"bin/win10/plugins/VeilNet.dll":  "veilnet",
		"README.txt":                     "readme",
	}
	var list []string
	for p, d := range files {
		put(t, filepath.Join(dir, filepath.FromSlash(p)), d)
		sum := sha256.Sum256([]byte(d))
		list = append(list, hex.EncodeToString(sum[:])+"  "+p)
	}
	put(t, filepath.Join(dir, fileList), strings.Join(list, "\n")+"\n")
	put(t, filepath.Join(dir, "stage", scriptsType, "cff4557b7d2ce426"), "hdr.MZold-party-pulsar")

	clean, ok := bundle{dir}.cleanCopy()
	if !ok {
		t.Fatal("files.txt not used")
	}
	defer os.RemoveAll(clean.dir)
	if got := read(t, filepath.Join(clean.stage(), scriptsType, "aaaa")); got != "hdr.MZnew-a" {
		t.Errorf("listed script: %q", got)
	}
	if got := read(t, filepath.Join(clean.stage(), scriptsType, "cff4557b7d2ce426")); got != "<missing>" {
		t.Errorf("leftover made it into the clean copy: %q", got)
	}
	if got := read(t, clean.bin("plugins", "VeilNet.dll")); got != "veilnet" {
		t.Errorf("plugin: %q", got)
	}
}

func TestNoFileListUsesFolder(t *testing.T) {
	dir := t.TempDir()
	if b, ok := (bundle{dir}).cleanCopy(); ok || b.dir != dir {
		t.Fatal("a bundle without files.txt must be used as it is")
	}
}

// An install from an older build (party Pulsar script with its .orig, a script it added, an
// old plugin), then a newer build that ships neither: both scripts go back to stock.
func TestReinstallTakesBackDroppedScripts(t *testing.T) {
	game := t.TempDir()
	scripts := filepath.Join(game, "bin", "win10", "scripts")
	plugins := filepath.Join(game, "bin", "win10", "plugins")
	put(t, filepath.Join(scripts, "cff4557b7d2ce426.dll"), "party-pulsar")
	put(t, filepath.Join(scripts, "cff4557b7d2ce426.dll.orig"), "stock-pulsar")
	put(t, filepath.Join(scripts, "aaaa.dll"), "old-a")
	put(t, filepath.Join(scripts, "aaaa.dll.orig"), "stock-a")
	put(t, filepath.Join(scripts, "bbbb.dll"), "added-by-old")
	put(t, filepath.Join(scripts, createdList), "bbbb\n")
	put(t, filepath.Join(scripts, "unrelated.dll"), "someone-else")
	put(t, filepath.Join(scripts, "23819c478e9d7e22.dll"), "other-mod-patch") // another mod's, with a .orig
	put(t, filepath.Join(scripts, "23819c478e9d7e22.dll.orig"), "other-stock")
	put(t, filepath.Join(plugins, "OldThing.dll"), "old plugin")
	put(t, filepath.Join(plugins, pluginsList), "OldThing.dll\nVeilNet.dll\n")
	put(t, filepath.Join(plugins, "OtherMod.dll"), "other mod")

	rel := t.TempDir()
	put(t, filepath.Join(rel, "stage", scriptsType, "aaaa"), "hdr.MZnew-a")
	put(t, filepath.Join(rel, "bin", "win10", "dbgcore.dll"), "plugins\x00LoadLibrary loader")
	put(t, filepath.Join(rel, "bin", "win10", "plugins", "VeilNet.dll"), "new veilnet")
	b := bundle{rel}
	installScripts(game, b)
	for _, p := range b.plugins() {
		copyChecked(b.bin("plugins", p), filepath.Join(plugins, p))
	}
	// installPlugins' removal step (the loader and import check need a real PE)
	shipped := map[string]bool{}
	for _, n := range b.plugins() {
		shipped[n] = true
	}
	for n := range readList(plugins, pluginsList) {
		if !shipped[n] {
			os.Remove(filepath.Join(plugins, n))
		}
	}

	checks := map[string]string{
		filepath.Join(scripts, "cff4557b7d2ce426.dll"):      "stock-pulsar", // dropped: back to stock
		filepath.Join(scripts, "cff4557b7d2ce426.dll.orig"): "<missing>",
		filepath.Join(scripts, "aaaa.dll"):                  "MZnew-a", // still shipped: new code
		filepath.Join(scripts, "aaaa.dll.orig"):             "stock-a",
		filepath.Join(scripts, "bbbb.dll"):                  "<missing>", // added by the old build: gone
		filepath.Join(scripts, "unrelated.dll"):             "someone-else",
		filepath.Join(scripts, "23819c478e9d7e22.dll"):      "other-mod-patch", // not EchoCombat's: untouched
		filepath.Join(plugins, "OldThing.dll"):              "<missing>",
		filepath.Join(plugins, "OtherMod.dll"):              "other mod",
		filepath.Join(plugins, "VeilNet.dll"):               "new veilnet",
	}
	for p, want := range checks {
		if got := read(t, p); got != want {
			t.Errorf("%s = %q, want %q", p, got, want)
		}
	}
	if got := strings.TrimSpace(read(t, filepath.Join(scripts, createdList))); got != "" {
		t.Errorf("created list still names %q", got)
	}
}
