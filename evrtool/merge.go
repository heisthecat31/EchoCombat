package main

// Merging into an install that other mods have already repacked.
//
// QuickRepack always starts from manifests/<pkg>.bak (the stock manifest) and
// deletes every delta package past the stock count, so a plain repack wipes
// whatever another mod put in <pkg>_3, <pkg>_4, ... Merging instead starts from
// the LIVE manifest: QuickRepack is handed it as its ".bak" for the one run, so
// it keeps the other mods' deltas, appends ours after them, and the real stock
// .bak is put back afterwards.
//
// Two files keep re-running idempotent:
//
//	manifests/<pkg>.echocombat       the manifest from before our first merge (the other mods)
//	manifests/<pkg>.echocombat.live  the manifest our last merge wrote
//
// While the live manifest is still the one we wrote, the next merge starts from
// .echocombat again and replaces our own deltas instead of stacking more. If
// anything repacked after us, the live manifest is taken as the new base.

import (
	"bytes"
	"encoding/binary"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"

	"github.com/EchoTools/cosmetic-editor/EvrFile/manifest"
)

func manifestPath(dataDir string) string { return filepath.Join(dataDir, "manifests", pkg) }

// recoverSwap puts the stock .bak back if a merge died while it was swapped out.
func recoverSwap(dataDir string) {
	if swapBack(dataDir) {
		fmt.Println("recovered the stock .bak from an interrupted merge")
	}
}

// swapBack moves the stock .bak back into place after QuickRepack has run on the base.
func swapBack(dataDir string) bool {
	mp := manifestPath(dataDir)
	if _, err := os.Stat(mp + ".bak.echocombat-tmp"); err == nil {
		os.Remove(mp + ".bak")
		if err := os.Rename(mp+".bak.echocombat-tmp", mp+".bak"); err != nil {
			die("restore stock .bak: %v", err)
		}
		return true
	}
	return false
}

// mergeBase is the manifest our files go on top of: the other mods' state.
func mergeBase(dataDir string) ([]byte, *manifest.Manifest) {
	recoverSwap(dataDir)
	mp := manifestPath(dataDir)
	live, err := os.ReadFile(mp)
	if err != nil {
		die("read manifest: %v", err)
	}
	base := live
	if ours, err := os.ReadFile(mp + ".echocombat.live"); err == nil && bytes.Equal(ours, live) {
		if prev, err := os.ReadFile(mp + ".echocombat"); err == nil {
			base = prev
		}
	}
	m, err := manifest.ReadFile(mp)
	if !bytes.Equal(base, live) {
		m, err = manifest.ReadFile(mp + ".echocombat")
	}
	if err != nil {
		die("read base manifest: %v", err)
	}
	return base, m
}

// merge repacks inputDir on top of the live install without dropping other mods.
func merge(dataDir string, files [][]manifest.ScannedFile) {
	mp := manifestPath(dataDir)
	base, bm := mergeBase(dataDir)
	if _, err := os.Stat(mp + ".bak"); err != nil {
		// Never repacked: live is stock, and QuickRepack makes the .bak itself.
		fmt.Println("install is unmodified: plain repack")
	} else {
		stock, err := manifest.ReadFile(mp + ".bak")
		if err != nil {
			die("read .bak: %v", err)
		}
		fmt.Printf("merging on top of %d existing delta package(s) (stock has %d packages, base %d)\n",
			bm.Header.PackageCount-stock.Header.PackageCount, stock.Header.PackageCount, bm.Header.PackageCount)
		if err := os.Rename(mp+".bak", mp+".bak.echocombat-tmp"); err != nil {
			die("move stock .bak aside: %v", err)
		}
		if err := os.WriteFile(mp+".bak", base, 0644); err != nil {
			recoverSwap(dataDir)
			die("write base: %v", err)
		}
	}
	m, err := manifest.ReadFile(mp)
	if err != nil {
		recoverSwap(dataDir)
		die("read manifest: %v", err)
	}
	rerr := manifest.QuickRepack(m, files, dataDir, pkg)
	swapBack(dataDir)
	if rerr != nil {
		die("repack: %v", rerr)
	}
	if err := os.WriteFile(mp+".echocombat", base, 0644); err != nil {
		die("write %s: %v", mp+".echocombat", err)
	}
	live, err := os.ReadFile(mp)
	if err != nil {
		die("read manifest: %v", err)
	}
	if err := os.WriteFile(mp+".echocombat.live", live, 0644); err != nil {
		die("write %s: %v", mp+".echocombat.live", err)
	}
	fmt.Println("merge OK")
}

// unmerge takes our files back out and leaves the other mods in place.
func unmerge(dataDir string) {
	recoverSwap(dataDir)
	mp := manifestPath(dataDir)
	live, err := os.ReadFile(mp)
	if err != nil {
		die("read manifest: %v", err)
	}
	ours, err1 := os.ReadFile(mp + ".echocombat.live")
	prev, err2 := os.ReadFile(mp + ".echocombat")
	if err1 != nil || err2 != nil {
		fmt.Println("no EchoCombat merge recorded for", pkg)
		return
	}
	if !bytes.Equal(ours, live) {
		die("something repacked %s after EchoCombat; unmerging now would drop its changes. "+
			"Reinstall that mod after a full restore instead.", pkg)
	}
	m, err := manifest.ReadFile(mp + ".echocombat")
	if err != nil {
		die("read %s: %v", mp+".echocombat", err)
	}
	if err := os.WriteFile(mp, prev, 0644); err != nil {
		die("write manifest: %v", err)
	}
	removeDeltas(dataDir, m.Header.PackageCount)
	os.Remove(mp + ".echocombat")
	os.Remove(mp + ".echocombat.live")
	fmt.Println("EchoCombat removed from", pkg)
}

func removeDeltas(dataDir string, from uint32) {
	for i := from; ; i++ {
		p := filepath.Join(dataDir, "packages", fmt.Sprintf("%s_%d", pkg, i))
		if _, err := os.Stat(p); err != nil {
			break
		}
		if err := os.Remove(p); err != nil {
			die("remove %s: %v", p, err)
		}
		fmt.Println("removed", p)
	}
}

// baseReader reads <type>/<file> through the merge base manifest.
func baseReader(dataDir string) (func(typ, file uint64) []byte, func()) {
	_, m := mergeBase(dataDir)
	pk, err := manifest.OpenPackage(m, filepath.Join(dataDir, "packages", pkg))
	if err != nil {
		die("open package: %v", err)
	}
	read := func(typ, file uint64) []byte {
		for _, fc := range m.FrameContents {
			if uint64(fc.TypeSymbol) == typ && uint64(fc.FileSymbol) == file {
				fcc := fc
				data, err := pk.ReadContent(&fcc)
				if err != nil {
					die("read %016x/%016x: %v", typ, file, err)
				}
				return data
			}
		}
		die("%016x/%016x not in the install", typ, file)
		return nil
	}
	return read, func() { pk.Close() }
}

// --- drone bullet effects (tools/fix_drone_bullet.py, applied on the player's install) ---

const (
	bulletCR    = 0x4fd65c8d2b63d470 // CR15NetBulletCRWin10
	particleCR  = 0x21a09c2016d8f3e6 // CParticleEffectCRWin10
	donorBullet = 0x12001003B8E9A2A6
	droneBullet = 0xA8F84E7DD40B806E
	crHdr       = 0x38
)

var combatLevels = []uint64{0x42670f2bed45703c, 0x43e2da7914642604, 0x43e2da7a0c623a19,
	0xcb9977f7fc2b4526, 0xdf5ca7b7dfa383d4}

func u64(b []byte, o int) uint64 { return binary.LittleEndian.Uint64(b[o:]) }

func splitCR(blob []byte) [][]byte {
	size, count := u64(blob, 0x08), u64(blob, 0x28)
	if count == 0 || size%count != 0 || uint64(len(blob)) != crHdr+size || u64(blob, 0x30) != count {
		die("unexpected CR framing (or a trailing heap)")
	}
	stride := size / count
	recs := make([][]byte, count)
	for i := range recs {
		recs[i] = append([]byte(nil), blob[crHdr+uint64(i)*stride:crHdr+uint64(i+1)*stride]...)
	}
	return recs
}

func joinCR(blob []byte, recs [][]byte) []byte {
	head := append([]byte(nil), blob[:crHdr]...)
	size := 0
	for _, r := range recs {
		size += len(r)
	}
	binary.LittleEndian.PutUint64(head[0x08:], uint64(size))
	binary.LittleEndian.PutUint64(head[0x28:], uint64(len(recs)))
	binary.LittleEndian.PutUint64(head[0x30:], uint64(len(recs)))
	return bytes.Join(append([][]byte{head}, recs...), nil)
}

func patchDroneBullet(bullets, particles []byte) ([]byte, []byte) {
	brecs := splitCR(bullets)
	var donor, drone []byte
	for _, r := range brecs {
		switch u64(r, 8) {
		case donorBullet:
			donor = r
		case droneBullet:
			drone = r
		}
	}
	if donor == nil || drone == nil {
		die("drone or donor bullet record not found")
	}
	wanted := map[uint64]bool{}
	for _, o := range []int{0x58, 0x60} {
		if v := u64(donor, o); v != ^uint64(0) {
			wanted[v] = true
		}
	}
	precs := splitCR(particles)
	has := false
	for _, r := range precs {
		if u64(r, 8) == droneBullet {
			has = true
		}
	}
	if !has {
		var copies [][]byte
		for _, r := range precs {
			if u64(r, 8) == donorBullet && wanted[u64(r, 0)] {
				c := append([]byte(nil), r...)
				binary.LittleEndian.PutUint64(c[8:], droneBullet)
				copies = append(copies, c)
			}
		}
		if len(copies) != len(wanted) {
			die("donor particle components not found")
		}
		precs = append(precs, copies...)
	}
	copy(drone[0x58:0x68], donor[0x58:0x68])
	return joinCR(bullets, brecs), joinCR(particles, precs)
}

// droneBulletStage writes the patched bullet + particle tables of every combat
// level into outDir, read from the player's own install.
func droneBulletStage(dataDir, outDir string) {
	read, done := baseReader(dataDir)
	defer done()
	for _, lvl := range combatLevels {
		nb, np := patchDroneBullet(read(bulletCR, lvl), read(particleCR, lvl))
		for t, data := range map[uint64][]byte{bulletCR: nb, particleCR: np} {
			d := filepath.Join(outDir, fmt.Sprintf("%x", t))
			os.MkdirAll(d, 0755)
			if err := os.WriteFile(filepath.Join(d, fmt.Sprintf("%x", lvl)), data, 0644); err != nil {
				die("write: %v", err)
			}
		}
	}
	fmt.Println("drone bullet effects staged for", len(combatLevels), "levels")
}

// wwiseCaches clears the caches under the install (dataDir is
// <install>/_data/5932408047/rad15/win10) and under any rad / echo folder in
// %LOCALAPPDATA%, %TEMP% or %APPDATA%.
func wwiseCaches(dataDir string) {
	roots := []string{filepath.Join(dataDir, "..", "..", "..", "..")}
	for _, env := range []string{"LOCALAPPDATA", "TEMP", "APPDATA"} {
		base := os.Getenv(env)
		entries, _ := os.ReadDir(base)
		for _, e := range entries {
			n := strings.ToLower(e.Name())
			if e.IsDir() && (strings.Contains(n, "rad") || strings.Contains(n, "echo") || strings.Contains(n, "r14")) {
				roots = append(roots, filepath.Join(base, e.Name()))
			}
		}
	}
	clearWwiseCache(roots...)
}

// clearWwiseCache empties _temp/wwise folders, so a sound bank cached from before
// the repack is not played instead of the patched one.
func clearWwiseCache(roots ...string) {
	for _, root := range roots {
		top := strings.Count(filepath.Clean(root), string(os.PathSeparator))
		filepath.Walk(root, func(p string, info os.FileInfo, err error) error {
			if err != nil || !info.IsDir() {
				return nil
			}
			if strings.Count(p, string(os.PathSeparator))-top >= 6 {
				return filepath.SkipDir
			}
			if strings.EqualFold(info.Name(), "wwise") && strings.EqualFold(filepath.Base(filepath.Dir(p)), "_temp") {
				os.RemoveAll(p)
				fmt.Println("cleared sound bank cache", p)
				return filepath.SkipDir
			}
			return nil
		})
	}
}

// scan reads <type>/<file> (or <frame>/<type>/<file>) under dir. The library's
// ScanFiles silently drops every symbol above 0x7fffffffffffffff (half of them:
// level tables, scripts, the recoloured effects), so the hex names are parsed
// as uint64 and stored two's-complement, as the manifest holds them.
func scan(dir string) [][]manifest.ScannedFile {
	var files [][]manifest.ScannedFile
	n := 0
	err := filepath.WalkDir(dir, func(path string, d os.DirEntry, err error) error {
		if err != nil || d.IsDir() {
			return err
		}
		rel, _ := filepath.Rel(dir, path)
		parts := strings.Split(filepath.ToSlash(rel), "/")
		chunk := 0
		if len(parts) == 3 {
			c, err := strconv.Atoi(parts[0])
			if err != nil {
				return nil
			}
			chunk, parts = c, parts[1:]
		}
		if len(parts) != 2 {
			return nil
		}
		t, err1 := strconv.ParseUint(parts[0], 16, 64)
		f, err2 := strconv.ParseUint(parts[1], 16, 64)
		if err1 != nil || err2 != nil {
			fmt.Println("skipping", rel, "(not <type>/<file> hex symbols)")
			return nil
		}
		info, err := d.Info()
		if err != nil {
			return err
		}
		for chunk >= len(files) {
			files = append(files, nil)
		}
		files[chunk] = append(files[chunk], manifest.ScannedFile{
			TypeSymbol: int64(t), FileSymbol: int64(f), Path: path, Size: uint32(info.Size())})
		n++
		return nil
	})
	if err != nil {
		die("scan %s: %v", dir, err)
	}
	fmt.Println("staged files", n)
	return files
}

// sidePackage may carry its own copy of UMBRAL VEIL's sound bank, which the game
// then plays instead of the main package's.
const (
	sidePackage   = "2b47aab238f60515"
	soundBankType = 0x6d358eef7bb85a98
	veilBank      = 0x3f1464db1fe49b5
)

// install is what the player's install.bat runs: stage the drone bullet tables
// from their own install, merge the stage into the main package, and give the
// side package the patched sound bank if it has its own copy.
func install(dataDir, stageDir string) {
	droneBulletStage(dataDir, stageDir)
	merge(dataDir, scan(stageDir))
	defer wwiseCaches(dataDir)

	bank := filepath.Join(stageDir, fmt.Sprintf("%x", uint64(soundBankType)), fmt.Sprintf("%x", uint64(veilBank)))
	if _, err := os.Stat(bank); err != nil {
		return
	}
	mainPkg := pkg
	defer func() { pkg = mainPkg }()
	pkg = sidePackage
	if _, err := os.Stat(manifestPath(dataDir)); err != nil {
		return
	}
	_, m := mergeBase(dataDir)
	for _, fc := range m.FrameContents {
		if uint64(fc.TypeSymbol) == soundBankType && uint64(fc.FileSymbol) == veilBank {
			fmt.Println("side package", sidePackage, "has its own UMBRAL VEIL sound bank: patching it too")
			side, err := os.MkdirTemp("", "echocombat-side")
			if err != nil {
				die("temp dir: %v", err)
			}
			defer os.RemoveAll(side)
			d := filepath.Join(side, fmt.Sprintf("%x", uint64(soundBankType)))
			os.MkdirAll(d, 0755)
			data, err := os.ReadFile(bank)
			if err != nil {
				die("read bank: %v", err)
			}
			os.WriteFile(filepath.Join(d, fmt.Sprintf("%x", uint64(veilBank))), data, 0644)
			merge(dataDir, scan(side))
			return
		}
	}
}
