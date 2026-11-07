package main

// files.txt: the release's own list of what is in it (make_release.py writes it), one
// "<sha256>  <path>" line per file, paths relative to the bundle folder with "/".
//
// A zip extracted over an older one leaves the older one's files behind, and setup used to
// install whatever the folder held: on 2026-11-07 a 2.0.2 folder over a party-gun build put
// the party-gun Pulsar script back and crashed the game. So setup verifies every listed file,
// ignores the rest, and installs from a clean copy holding the listed files only.

import (
	"bufio"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

const fileList = "files.txt"

func fileSHA256(path string) (string, error) {
	f, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer f.Close()
	h := sha256.New()
	if _, err := io.Copy(h, f); err != nil {
		return "", err
	}
	return hex.EncodeToString(h.Sum(nil)), nil
}

// listed reads files.txt: path -> sha256. ok is false when the bundle has none (an older zip).
func (b bundle) listed() (map[string]string, bool) {
	f, err := os.Open(filepath.Join(b.dir, fileList))
	if err != nil {
		return nil, false
	}
	defer f.Close()
	m := map[string]string{}
	sc := bufio.NewScanner(f)
	for sc.Scan() {
		line := strings.TrimRight(sc.Text(), "\r")
		if line == "" {
			continue
		}
		sum, path, found := strings.Cut(line, "  ")
		if !found || len(sum) != 64 {
			die("%s: bad line %q (extract the whole zip again)", fileList, line)
		}
		m[path] = sum
	}
	if err := sc.Err(); err != nil {
		die("read %s: %v", fileList, err)
	}
	return m, true
}

// cleanCopy checks the bundle against files.txt and copies the files setup uses (stage/ and
// bin/) into a new temporary bundle, without anything else the folder holds. ok is false for a
// bundle without files.txt: then setup uses the folder as it is.
func (b bundle) cleanCopy() (bundle, bool) {
	want, ok := b.listed()
	if !ok {
		fmt.Println("no", fileList, "in this folder (an older zip): installing the folder as it is")
		return b, false
	}
	var missing, changed []string
	for path, sum := range want {
		got, err := fileSHA256(filepath.Join(b.dir, filepath.FromSlash(path)))
		switch {
		case err != nil:
			missing = append(missing, path)
		case got != sum:
			changed = append(changed, path)
		}
	}
	if len(missing)+len(changed) > 0 {
		sort.Strings(missing)
		sort.Strings(changed)
		die("this folder does not match the zip (nothing was changed):\n  missing: %s\n  changed: %s\n"+
			"Extract the whole zip again into a NEW, empty folder. If files disappear again, your "+
			"antivirus removed them: restore them from Windows Security > Protection history, or allow the folder.",
			strings.Join(missing, ", "), strings.Join(changed, ", "))
	}
	var extra []string
	for _, top := range []string{"stage", "bin"} {
		filepath.WalkDir(filepath.Join(b.dir, top), func(p string, d os.DirEntry, err error) error {
			if err != nil || d.IsDir() {
				return nil
			}
			rel, _ := filepath.Rel(b.dir, p)
			if _, ok := want[filepath.ToSlash(rel)]; !ok {
				extra = append(extra, filepath.ToSlash(rel))
			}
			return nil
		})
	}
	if len(extra) > 0 {
		sort.Strings(extra)
		fmt.Printf("ignoring %d file(s) in this folder that are not part of this release "+
			"(left over from an older zip extracted here):\n  %s\n", len(extra), strings.Join(extra, "\n  "))
	}
	tmp, err := os.MkdirTemp("", "echocombat-bundle")
	if err != nil {
		die("temp dir: %v", err)
	}
	for path := range want {
		if !strings.HasPrefix(path, "stage/") && !strings.HasPrefix(path, "bin/") {
			continue
		}
		dst := filepath.Join(tmp, filepath.FromSlash(path))
		if err := os.MkdirAll(filepath.Dir(dst), 0755); err != nil {
			die("create %s: %v", filepath.Dir(dst), err)
		}
		copyChecked(filepath.Join(b.dir, filepath.FromSlash(path)), dst)
	}
	fmt.Printf("checked %d file(s) against %s\n", len(want), fileList)
	return bundle{tmp}, true
}
