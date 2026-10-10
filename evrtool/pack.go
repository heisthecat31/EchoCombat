package main

// The content pack: EchoCombat's game data for NvrContentOverlay, the nEVR plugin that
// serves it in place of the stock files while Echo runs. Nothing in the install changes.
//
//	evrtool pack <dataDir> <stageDir> <outDir> [version]
//
// dataDir is an install's _data/5932408047/rad15/win10. Only its stock files are read: the
// stock manifest (manifests/<pkg>.bak when a repack left one, else the live one) and the
// stock packages. outDir is wiped and gets
//
//	manifests/<pkg>      the stock manifest with the stage packed on top
//	packages/<pkg>_<n>   the packages that adds (n from the stock package count on)
//	scripts/<hash>.dll   the script DLLs (Echo loads script code from bin/win10/scripts,
//	                     not from the package; the overlay hands the game these instead)
//	content.json         what the overlay checks before serving anything: each file's
//	                     sha256, and the sha256 of each stock manifest the pack was built from
//
// The side package (2b47aab238f60515) gets the UMBRAL VEIL sound bank too when it has its
// own copy, as `install` did. The netgun tables (CR15NetGunCRWin10) are left out: the
// launcher's community update serves the same tables through its required asset patch.

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"github.com/EchoTools/cosmetic-editor/EvrFile/manifest"
)

const (
	packID     = "echocombat"
	packName   = "EchoCombat"
	gameData   = "_data/5932408047/rad15/win10"
	netgunCR   = 0xdbaed509c67b8884 // CR15NetGunCRWin10: owned by the community update's asset patch
	scriptHead = 20                 // a script asset: 16-byte header, u32 DLL size, the DLL
)

type packManifest struct {
	Package       string   `json:"package"`
	StockSha256   string   `json:"stock_sha256"`
	StockPackages uint32   `json:"stock_packages"`
	File          string   `json:"file"`
	Packages      []string `json:"packages"`
}

type packContent struct {
	Format    int               `json:"format"`
	ID        string            `json:"id"`
	Name      string            `json:"name"`
	Version   string            `json:"version"`
	DataDir   string            `json:"data_dir"`
	Manifests []packManifest    `json:"manifests"`
	Scripts   []string          `json:"scripts"`
	Files     map[string]string `json:"files"`
}

func fileSha256(path string) string {
	f, err := os.Open(path)
	if err != nil {
		die("read %s: %v", path, err)
	}
	defer f.Close()
	h := sha256.New()
	if _, err := io.Copy(h, f); err != nil {
		die("read %s: %v", path, err)
	}
	return hex.EncodeToString(h.Sum(nil))
}

// stockFiles is the stock manifest of name in dataDir: its path and package count.
func stockFiles(dataDir, name string) (string, uint32) {
	path := filepath.Join(dataDir, "manifests", name)
	if _, err := os.Stat(path + ".bak"); err == nil {
		path += ".bak"
	}
	m, err := manifest.ReadFile(path)
	if err != nil {
		die("read %s: %v", path, err)
	}
	return path, m.Header.PackageCount
}

// workDir is a data folder QuickRepack can write into: a copy of the stock manifest and
// links to the stock packages, which it only reads (it writes from the stock count on).
func workDir(dataDir, work, name string) (string, uint32) {
	stock, count := stockFiles(dataDir, name)
	for _, d := range []string{"manifests", "packages"} {
		if err := os.MkdirAll(filepath.Join(work, d), 0755); err != nil {
			die("create %s: %v", work, err)
		}
	}
	data, err := os.ReadFile(stock)
	if err != nil {
		die("read %s: %v", stock, err)
	}
	if err := os.WriteFile(filepath.Join(work, "manifests", name), data, 0644); err != nil {
		die("write work manifest: %v", err)
	}
	for i := uint32(0); i < count; i++ {
		src := filepath.Join(dataDir, "packages", fmt.Sprintf("%s_%d", name, i))
		dst := filepath.Join(work, "packages", fmt.Sprintf("%s_%d", name, i))
		abs, _ := filepath.Abs(src)
		if os.Link(src, dst) != nil {
			if err := os.Symlink(abs, dst); err != nil {
				die("cannot link %s into %s (put the output on the game's drive, or allow symlinks): %v",
					src, work, err)
			}
		}
	}
	return stock, count
}

// packOne repacks files onto the stock manifest name and moves the result into outDir.
func packOne(dataDir, work, outDir, name string, files [][]manifest.ScannedFile) packManifest {
	stock, count := workDir(dataDir, filepath.Join(work, name), name)
	wd := filepath.Join(work, name)
	m, err := manifest.ReadFile(filepath.Join(wd, "manifests", name))
	if err != nil {
		die("read work manifest: %v", err)
	}
	if err := manifest.QuickRepack(m, files, wd, name); err != nil {
		die("repack %s: %v", name, err)
	}
	pm := packManifest{Package: name, StockSha256: fileSha256(stock), StockPackages: count,
		File: "manifests/" + name}
	if err := os.Rename(filepath.Join(wd, "manifests", name), filepath.Join(outDir, "manifests", name)); err != nil {
		die("move manifest: %v", err)
	}
	for i := count; ; i++ {
		base := fmt.Sprintf("%s_%d", name, i)
		src := filepath.Join(wd, "packages", base)
		if _, err := os.Stat(src); err != nil {
			break
		}
		if err := os.Rename(src, filepath.Join(outDir, "packages", base)); err != nil {
			die("move %s: %v", base, err)
		}
		pm.Packages = append(pm.Packages, "packages/"+base)
	}
	if len(pm.Packages) == 0 {
		die("repacking %s added no package", name)
	}
	return pm
}

// withoutNetgun drops the netgun tables from the scanned stage.
func withoutNetgun(files [][]manifest.ScannedFile) [][]manifest.ScannedFile {
	out := make([][]manifest.ScannedFile, len(files))
	for i, g := range files {
		for _, f := range g {
			if uint64(f.TypeSymbol) != netgunCR {
				out[i] = append(out[i], f)
			}
		}
	}
	return out
}

// packScripts writes the DLL of every staged script asset to outDir/scripts.
func packScripts(stageDir, outDir string) []string {
	entries, err := os.ReadDir(filepath.Join(stageDir, scriptsType))
	if err != nil {
		die("read staged scripts: %v", err)
	}
	if err := os.MkdirAll(filepath.Join(outDir, "scripts"), 0755); err != nil {
		die("create scripts: %v", err)
	}
	var out []string
	for _, e := range entries {
		var sym uint64
		if _, err := fmt.Sscanf(e.Name(), "%x", &sym); err != nil || e.IsDir() || strings.HasPrefix(e.Name(), ".") {
			fmt.Println("skipping", e.Name(), "(not a script symbol)")
			continue
		}
		asset, err := os.ReadFile(filepath.Join(stageDir, scriptsType, e.Name()))
		if err != nil {
			die("read script %s: %v", e.Name(), err)
		}
		if len(asset) < scriptHead || string(asset[scriptHead:scriptHead+2]) != "MZ" {
			die("staged script %s holds no PE image", e.Name())
		}
		size := int(uint32(asset[16]) | uint32(asset[17])<<8 | uint32(asset[18])<<16 | uint32(asset[19])<<24)
		if scriptHead+size > len(asset) {
			die("staged script %s: its DLL runs past the asset", e.Name())
		}
		name := fmt.Sprintf("%016x.dll", sym)
		if err := os.WriteFile(filepath.Join(outDir, "scripts", name), asset[scriptHead:scriptHead+size], 0644); err != nil {
			die("write script %s: %v", name, err)
		}
		out = append(out, "scripts/"+name)
	}
	sort.Strings(out)
	return out
}

// sideHasVeilBank: whether the stock side package carries its own UMBRAL VEIL bank.
func sideHasVeilBank(dataDir string) bool {
	path := filepath.Join(dataDir, "manifests", sidePackage)
	if _, err := os.Stat(path); err != nil {
		return false
	}
	stock, _ := stockFiles(dataDir, sidePackage)
	m, err := manifest.ReadFile(stock)
	if err != nil {
		die("read %s: %v", stock, err)
	}
	for _, fc := range m.FrameContents {
		if uint64(fc.TypeSymbol) == soundBankType && uint64(fc.FileSymbol) == veilBank {
			return true
		}
	}
	return false
}

func pack(dataDir, stageDir, outDir, version string) {
	if _, err := os.Stat(filepath.Join(stageDir, scriptsType)); err != nil {
		die("%s is no stage (no %s/): run deploy_and_launch.py --stage-only first", stageDir, scriptsType)
	}
	if err := os.RemoveAll(outDir); err != nil {
		die("clear %s: %v", outDir, err)
	}
	for _, d := range []string{"manifests", "packages"} {
		if err := os.MkdirAll(filepath.Join(outDir, d), 0755); err != nil {
			die("create %s: %v", outDir, err)
		}
	}
	work := filepath.Join(outDir, ".work")
	defer os.RemoveAll(work)

	content := packContent{Format: 1, ID: packID, Name: packName, Version: version, DataDir: gameData}
	content.Manifests = append(content.Manifests, packOne(dataDir, work, outDir, pkg, withoutNetgun(scan(stageDir))))

	bank := filepath.Join(stageDir, fmt.Sprintf("%x", uint64(soundBankType)), fmt.Sprintf("%x", uint64(veilBank)))
	if _, err := os.Stat(bank); err == nil && sideHasVeilBank(dataDir) {
		fmt.Println("side package", sidePackage, "has its own UMBRAL VEIL sound bank: packing it there too")
		side := filepath.Join(work, "side-stage", fmt.Sprintf("%x", uint64(soundBankType)))
		if err := os.MkdirAll(side, 0755); err != nil {
			die("create %s: %v", side, err)
		}
		data, err := os.ReadFile(bank)
		if err != nil {
			die("read bank: %v", err)
		}
		if err := os.WriteFile(filepath.Join(side, fmt.Sprintf("%x", uint64(veilBank))), data, 0644); err != nil {
			die("write bank: %v", err)
		}
		content.Manifests = append(content.Manifests,
			packOne(dataDir, work, outDir, sidePackage, scan(filepath.Dir(side))))
	}

	content.Scripts = packScripts(stageDir, outDir)
	os.RemoveAll(work)

	content.Files = map[string]string{}
	err := filepath.WalkDir(outDir, func(path string, d os.DirEntry, err error) error {
		if err != nil || d.IsDir() {
			return err
		}
		rel, _ := filepath.Rel(outDir, path)
		rel = filepath.ToSlash(rel)
		if rel != "content.json" {
			content.Files[rel] = fileSha256(path)
		}
		return nil
	})
	if err != nil {
		die("list %s: %v", outDir, err)
	}
	data, err := json.MarshalIndent(content, "", "  ")
	if err != nil {
		die("content.json: %v", err)
	}
	if err := os.WriteFile(filepath.Join(outDir, "content.json"), append(data, '\n'), 0644); err != nil {
		die("write content.json: %v", err)
	}
	fmt.Printf("packed %s %s into %s: %d files (%s)\n", packName, version, outDir, len(content.Files),
		strings.Join(func() []string {
			var s []string
			for _, m := range content.Manifests {
				s = append(s, fmt.Sprintf("%s + %d package(s)", m.Package, len(m.Packages)))
			}
			return s
		}(), ", "))
}
