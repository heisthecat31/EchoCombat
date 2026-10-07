"""Gather the files needed to debug DOT activation, then commit and push them.

Copies them into `data/extract/`, keeping the extract's `<type>/<asset>` layout:

* level component tables for every combat level: magazine (`CR15NetMagazineCR`),
  script table (`CScriptCR`), magazine pouch (`CR15NetMagazinePouchCR`), plus the
  three DOT tables the fix scripts already touch
* the ordnance script DLLs (dot, det, shared magazine script, arc, stun, burst, loc)
* `echovr.exe`
* `le_symbol_names.py`, which `script_pe.py` needs
* the newest client logs
* `listing.txt`: every type folder in the extract and how many assets it holds

    python tools/collect_for_claude.py                 # collect, commit, push
    python tools/collect_for_claude.py --no-push       # collect and commit only
    python tools/collect_for_claude.py --dry-run       # just show what it would copy

Override paths with --extract, --game, --symbols or --log-dir if yours differ.
Missing files are reported and skipped, never fatal.
"""

from __future__ import annotations

import argparse
import glob
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "extract")

EXTRACT = r"H:\pcvr-extracted"
GAME = r"C:\Oculus\Games\Software\Software\ready-at-dawn-echo-arena"
SYMBOLS = os.path.join(os.path.dirname(ROOT), "lone_echo_blender", "scripts")

LEVELS = ["42670f2bed45703c", "43e2da7914642604", "43e2da7a0c623a19",
          "cb9977f7fc2b4526", "df5ca7b7dfa383d4"]

#: type folder -> name, for per-level component tables.
LEVEL_TABLES = {
    "5b723f040a3778ee": "CR15NetMagazineCRWin10",
    "d99f6bbd8009c92c": "CScriptCRWin10",
    "dde8fffc5b4d7ad4": "CR15RigidAttachConstraintCRWin10",
    "f2676c58c07bab0c": "CR15ParentedConstraintCRWin10",
    "2b292830e51c4fd2": "CR15DampenerCRWin10",
}
#: Type folders whose hash is only known by name; resolved with CSymbol64.
NAMED_TABLES = ["CR15NetMagazinePouchCRWin10", "CR15NetMagazineCSWin10"]

SCRIPTS_TYPE = "6eace9f64204fd0"
SCRIPTS = {
    "97d0806e6ea89130": "mp_combat_grenade_dot",
    "190ed14fe3da5ed1": "det",
    "190ed14fe6c74dd3": "shared magazine script",
    "97d0806e6ead8c27": "mp_combat_grenade_arc",
    "190ed14ff6dc4ad8": "mp_combat_grenade_stun",
    "cad33e1bc81ffbee": "mp_combat_grenade_burst",
    "9398a165c004a9c0": "mp_combat_grenade_translocator",
}
LOG_COUNT = 3


def find_extract_root(path: str) -> str:
    """Accept either the extract root or one of its type folders."""
    if os.path.isdir(os.path.join(path, SCRIPTS_TYPE)):
        return path
    parent = os.path.dirname(path.rstrip("\\/"))
    if os.path.isdir(os.path.join(parent, SCRIPTS_TYPE)):
        return parent
    return path


class Collector:
    def __init__(self, dry_run: bool):
        self.dry_run = dry_run
        self.copied, self.missing = [], []

    def copy(self, src: str, rel: str, label: str = ""):
        dst = os.path.join(OUT, rel)
        if not os.path.isfile(src):
            self.missing.append(f"{rel}  ({label or src})")
            return
        size = os.path.getsize(src)
        if size > 95 * 1024 * 1024:
            self.missing.append(f"{rel}  (too large for GitHub: {size >> 20} MB)")
            return
        if not self.dry_run:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
        self.copied.append(f"{rel}  {size:>10,}  {label}")


def symbol64_fn(symbols_dir: str):
    sys.path.insert(0, symbols_dir)
    try:
        from le_symbol_names import symbol64
        return symbol64
    except ImportError:
        return None


def newest_logs(game: str, log_dir: str | None) -> list[str]:
    dirs = [log_dir] if log_dir else [
        os.path.join(game, "_local", "r14logs"),
        os.path.join(game, "bin", "win10", "_local", "r14logs"),
        os.path.join(game, "_local"),
    ]
    logs = []
    for d in dirs:
        if d and os.path.isdir(d):
            logs += glob.glob(os.path.join(d, "*.log")) + glob.glob(os.path.join(d, "*.txt"))
    return sorted(set(logs), key=os.path.getmtime, reverse=True)[:LOG_COUNT]


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", ROOT, *args], capture_output=True, text=True)


def commit_and_push(push: bool) -> int:
    git("add", "-f", "data/extract")
    if not git("diff", "--cached", "--quiet").returncode:
        print("nothing new to commit")
    else:
        msg = "Add game files for DOT activation debugging"
        r = git("commit", "-m", msg)
        print(r.stdout or r.stderr)
        if r.returncode:
            return r.returncode
    if not push:
        return 0
    branch = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    for delay in (0, 2, 4, 8, 16):
        time.sleep(delay)
        r = git("push", "-u", "origin", branch)
        if not r.returncode:
            print(f"pushed to {branch}")
            return 0
        print(r.stderr.strip())
    print("push failed -- run `git push` yourself once the network is back")
    return 1


def main(argv) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--extract", default=EXTRACT, help="extract root (folder holding the type hash folders)")
    ap.add_argument("--game", default=GAME, help="ready-at-dawn-echo-arena install folder")
    ap.add_argument("--symbols", default=SYMBOLS, help="folder holding le_symbol_names.py")
    ap.add_argument("--log-dir", help="folder holding the client logs, if not the default")
    ap.add_argument("--no-push", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv[1:])

    extract = find_extract_root(args.extract)
    c = Collector(args.dry_run)
    symbol64 = symbol64_fn(args.symbols)

    tables = dict(LEVEL_TABLES)
    for name in NAMED_TABLES:
        if symbol64:
            tables[f"{symbol64(name) & (2**64 - 1):016x}".lstrip("0") or "0"] = name
        else:
            c.missing.append(f"{name}  (le_symbol_names.py not found, can't hash the folder name)")
    for type_hash, name in tables.items():
        folder = os.path.join(extract, type_hash)
        if not os.path.isdir(folder):          # folder names may or may not keep leading zeros
            folder = os.path.join(extract, type_hash.zfill(16))
        for level in LEVELS:
            c.copy(os.path.join(folder, level), f"{type_hash}/{level}", name)

    for asset, name in SCRIPTS.items():
        c.copy(os.path.join(extract, SCRIPTS_TYPE, asset), f"{SCRIPTS_TYPE}/{asset}", name)

    c.copy(os.path.join(args.game, "bin", "win10", "echovr.exe"), "bin/echovr.exe", "game executable")
    c.copy(os.path.join(args.symbols, "le_symbol_names.py"), "tools/le_symbol_names.py", "CSymbol64")
    for log in newest_logs(args.game, args.log_dir):
        c.copy(log, f"logs/{os.path.basename(log)}", "client log")

    if os.path.isdir(extract):
        lines = [f"{d}  {len(os.listdir(os.path.join(extract, d)))}"
                 for d in sorted(os.listdir(extract)) if os.path.isdir(os.path.join(extract, d))]
        if not args.dry_run:
            os.makedirs(OUT, exist_ok=True)
            with open(os.path.join(OUT, "listing.txt"), "w", newline="\n") as fh:
                fh.write("\n".join(lines) + "\n")
        c.copied.append(f"listing.txt  ({len(lines)} type folders)")
    else:
        c.missing.append(f"extract root {extract}")

    print(f"extract: {extract}\n\ncopied ({len(c.copied)}):")
    for line in c.copied:
        print("  " + line)
    if c.missing:
        print(f"\nmissing ({len(c.missing)}):")
        for line in c.missing:
            print("  " + line)
    if args.dry_run:
        return 0
    print()
    return commit_and_push(not args.no_push)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
