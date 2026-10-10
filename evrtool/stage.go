package main

// What the tools share: reading a stage folder, the side package's symbols, and the
// drone's bullet tables (built for the stage by tools/fix_drone_bullet.py; `dronebullet`
// builds them from an install's stock files to check the stage against).

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

// stockReader reads <type>/<file> through the stock manifest.
func stockReader(dataDir string) (func(typ, file uint64) []byte, func()) {
	m, _ := stockManifest(dataDir)
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

// --- drone bullet effects (what tools/fix_drone_bullet.py stages) ---

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
// level into outDir, built from the install's stock tables.
func droneBulletStage(dataDir, outDir string) {
	read, done := stockReader(dataDir)
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
// then plays instead of the main package's (pack.go packs it there too).
const (
	sidePackage   = "2b47aab238f60515"
	soundBankType = 0x6d358eef7bb85a98
	veilBank      = 0x3f1464db1fe49b5
)
