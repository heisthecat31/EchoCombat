// evrtool: the package operations the ArenaColours app needs, over the EvrFile library.
//
//	evrtool get     <dataDir> <listFile> <outDir>   dump <type>/<file> resources from the STOCK manifest
//	evrtool list    <dataDir> <typeHex>             print every <type>/<file> of one type (stock manifest)
//	evrtool repack  <dataDir> <inputDir>            QuickRepack: stock + inputDir -> one delta package
//	evrtool merge   <dataDir> <inputDir>            like repack, but keeps other mods' delta packages (merge.go)
//	evrtool unmerge <dataDir>                       take a merge back out, leaving the other mods
//	evrtool install <dataDir> <stageDir>            player install: drone bullet tables + merge, side package too
//	evrtool setup   <gameDir> <bundleDir>           install.bat: install + script DLLs, plugins, plugin loader (files.go)
//	evrtool remove  <gameDir> <bundleDir>           uninstall.bat: unmerge, scripts back, plugins out
//	evrtool doctor  <gameDir> [bundleDir]           doctor.bat: why Echo will not start on this PC (doctor.go)
//	evrtool getlive <dataDir> <listFile> <outDir>   read files back through the live manifest
//	evrtool restore <dataDir>                       put the stock manifest back and delete delta packages (ALL mods)
//	evrtool cmp     <dataDir> <oldDir>              diff the install against an old manifest + delta copy
//	evrtool find    <dataDir> <fileHex>...          where a file symbol is stored (stock manifest; findlive: live)
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
		die("usage: evrtool get|list|repack|merge|unmerge|install|restore|cmp <dataDir> ...")
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
	case "repack":
		if len(os.Args) < 4 {
			die("usage: evrtool repack <dataDir> <inputDir>")
		}
		files := scan(os.Args[3])
		m, err := manifest.ReadFile(filepath.Join(dataDir, "manifests", pkg))
		if err != nil {
			die("read manifest: %v", err)
		}
		if err := manifest.QuickRepack(m, files, dataDir, pkg); err != nil {
			die("repack: %v", err)
		}
		fmt.Println("repack OK")
	case "merge":
		if len(os.Args) < 4 {
			die("usage: evrtool merge <dataDir> <inputDir>")
		}
		merge(dataDir, scan(os.Args[3]))
	case "unmerge":
		unmerge(dataDir)
	case "dronebullet":
		if len(os.Args) < 4 {
			die("usage: evrtool dronebullet <dataDir> <outDir>")
		}
		droneBulletStage(dataDir, os.Args[3])
	case "doctor":
		// doctor <gameDir> [bundleDir]: why Echo will not start on this PC
		b := ""
		if len(os.Args) > 3 {
			b = os.Args[3]
		}
		doctor(dataDir, b)
	case "setup", "remove":
		// setup <gameDir> <bundleDir>: the whole player install (install.bat)
		if len(os.Args) < 4 {
			die("usage: evrtool setup|remove <gameDir> <bundleDir>")
		}
		if mode == "setup" {
			setup(dataDir, os.Args[3])
		} else {
			remove(dataDir, os.Args[3])
		}
	case "install":
		if len(os.Args) < 4 {
			die("usage: evrtool install <dataDir> <stageDir>")
		}
		install(dataDir, os.Args[3])
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
		mp := filepath.Join(dataDir, "manifests", pkg)
		orig, err := manifest.ReadFile(mp + ".bak")
		if err != nil {
			fmt.Println("no .bak manifest: the install was never repacked, nothing to restore")
			return
		}
		data, err := os.ReadFile(mp + ".bak")
		if err != nil {
			die("read .bak: %v", err)
		}
		if err := os.WriteFile(mp, data, 0644); err != nil {
			die("write manifest: %v", err)
		}
		os.Remove(mp + ".echocombat")
		os.Remove(mp + ".echocombat.live")
		for i := orig.Header.PackageCount; ; i++ {
			p := filepath.Join(dataDir, "packages", fmt.Sprintf("%s_%d", pkg, i))
			if _, err := os.Stat(p); err != nil {
				break
			}
			if err := os.Remove(p); err != nil {
				die("remove %s: %v", p, err)
			}
			fmt.Println("removed", p)
		}
		fmt.Println("restored stock manifest")
	case "cmp":
		if len(os.Args) < 4 {
			die("usage: evrtool cmp <dataDir> <oldDir>")
		}
		cmpOldNew(dataDir, os.Args[3])
	default:
		die("unknown mode %s", mode)
	}
}
