// evrtool: builds EchoCombat's content pack from the stage and an install's stock files, over
// the EvrFile library. The game's own files are only read: NvrContentOverlay serves the pack
// beside them while Echo runs.
//
//	evrtool pack    <dataDir> <stageDir> <outDir> [version]  the content pack (pack.go)
//	evrtool get     <dataDir> <listFile> <outDir>   dump <type>/<file> resources from the STOCK manifest
//	evrtool getlive <dataDir> <listFile> <outDir>   the same through the live manifest
//	evrtool list    <dataDir> <typeHex>             print every <type>/<file> of one type (stock manifest)
//	evrtool find    <dataDir> <fileHex>...          where a file symbol is stored (stock manifest; findlive: live)
//	evrtool dronebullet <dataDir> <outDir>          the drone's bullet tables built from stock (stage.go)
//	evrtool restore <dataDir>                       put the stock manifest back and delete delta packages (ALL mods)
//	evrtool clean   <gameDir>                       take out an install made the old way (clean.go)
//
// Set EVR_PKG=<package> to work on a package other than 48037dc70b0ecab2.
// "Stock" is manifests/<pkg>.bak when present (QuickRepack writes it before its first change),
// otherwise the live manifest, which is then still unmodified.
package main

import (
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"

	"github.com/EchoTools/cosmetic-editor/EvrFile/manifest"
)

// pkg is the package every command works on: the main one unless EVR_PKG names
// another (the install also has a small second package, 2b47aab238f60515).
var pkg = func() string {
	if p := os.Getenv("EVR_PKG"); p != "" {
		return p
	}
	return "48037dc70b0ecab2"
}()

func die(format string, args ...interface{}) {
	fmt.Fprintf(os.Stderr, format+"\n", args...)
	os.Exit(1)
}

func stockManifest(dataDir string) (*manifest.Manifest, string) {
	mp := filepath.Join(dataDir, "manifests", pkg)
	path := mp
	if _, err := os.Stat(mp + ".bak"); err == nil {
		path = mp + ".bak"
	}
	m, err := manifest.ReadFile(path)
	if err != nil {
		die("read manifest %s: %v", path, err)
	}
	return m, path
}

func parsePair(s string) ([2]int64, bool) {
	p := strings.Split(strings.TrimSpace(s), "/")
	if len(p) != 2 {
		return [2]int64{}, false
	}
	a, err1 := strconv.ParseUint(p[0], 16, 64)
	b, err2 := strconv.ParseUint(p[1], 16, 64)
	return [2]int64{int64(a), int64(b)}, err1 == nil && err2 == nil
}

func main() {
	if len(os.Args) < 3 {
		die("usage: evrtool pack|get|getlive|list|find|findlive|dronebullet|restore|clean <dir> ...")
	}
	mode, dataDir := os.Args[1], os.Args[2]
	switch mode {
	case "get", "getlive":
		// get: read files through the stock manifest; getlive: through the live
		// one, exactly as the game does after a repack
		if len(os.Args) < 5 {
			die("usage: evrtool get|getlive <dataDir> <listFile> <outDir>")
		}
		m, _ := stockManifest(dataDir)
		if mode == "getlive" {
			var err error
			if m, err = manifest.ReadFile(filepath.Join(dataDir, "manifests", pkg)); err != nil {
				die("read manifest: %v", err)
			}
		}
		pk, err := manifest.OpenPackage(m, filepath.Join(dataDir, "packages", pkg))
		if err != nil {
			die("open package: %v", err)
		}
		defer pk.Close()
		want := map[[2]int64]bool{}
		lst, err := os.ReadFile(os.Args[3])
		if err != nil {
			die("read list: %v", err)
		}
		for _, ln := range strings.Fields(string(lst)) {
			if k, ok := parsePair(ln); ok {
				want[k] = true
			}
		}
		got := 0
		for _, fc := range m.FrameContents {
			k := [2]int64{fc.TypeSymbol, fc.FileSymbol}
			if !want[k] {
				continue
			}
			fcc := fc
			data, err := pk.ReadContent(&fcc)
			if err != nil {
				fmt.Fprintf(os.Stderr, "read %016x/%016x: %v\n", uint64(k[0]), uint64(k[1]), err)
				continue
			}
			d := filepath.Join(os.Args[4], fmt.Sprintf("%016x", uint64(k[0])))
			os.MkdirAll(d, 0755)
			if err := os.WriteFile(filepath.Join(d, fmt.Sprintf("%016x", uint64(k[1]))), data, 0644); err != nil {
				die("write: %v", err)
			}
			got++
		}
		fmt.Println("got", got, "of", len(want))
	case "list":
		if len(os.Args) < 4 {
			die("usage: evrtool list <dataDir> <typeHex>")
		}
		m, _ := stockManifest(dataDir)
		t, err := strconv.ParseUint(os.Args[3], 16, 64)
		if err != nil {
			die("bad type: %v", err)
		}
		for _, fc := range m.FrameContents {
			if uint64(fc.TypeSymbol) == t {
				fmt.Printf("%016x/%016x\n", uint64(fc.TypeSymbol), uint64(fc.FileSymbol))
			}
		}
	case "pack":
		if len(os.Args) < 5 {
			die("usage: evrtool pack <dataDir> <stageDir> <outDir> [version]")
		}
		version := "dev"
		if len(os.Args) > 5 {
			version = os.Args[5]
		}
		pack(dataDir, os.Args[3], os.Args[4], version)
	case "dronebullet":
		if len(os.Args) < 4 {
			die("usage: evrtool dronebullet <dataDir> <outDir>")
		}
		droneBulletStage(dataDir, os.Args[3])
	case "find", "findlive":
		// find <dataDir> <hash>...: every type a file symbol is stored under (stock manifest)
		// findlive: the same against the live manifest, i.e. after a repack
		m, _ := stockManifest(dataDir)
		if mode == "findlive" {
			var err error
			if m, err = manifest.ReadFile(filepath.Join(dataDir, "manifests", pkg)); err != nil {
				die("read manifest: %v", err)
			}
		}
		want := map[uint64]bool{}
		for _, a := range os.Args[3:] {
			if v, err := strconv.ParseUint(a, 16, 64); err == nil {
				want[v] = true
			}
		}
		for _, fc := range m.FrameContents {
			if want[uint64(fc.FileSymbol)] {
				fmt.Println(fmt.Sprintf("%016x/%016x", uint64(fc.TypeSymbol), uint64(fc.FileSymbol)), fc.Size)
			}
		}
	case "restore":
		if !restorePackage(dataDir, pkg) {
			fmt.Println("no .bak manifest: the install was never repacked, nothing to restore")
		}
	case "clean":
		clean(dataDir)
	default:
		die("unknown mode %s", mode)
	}
}
