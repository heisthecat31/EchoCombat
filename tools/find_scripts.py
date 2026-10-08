"""Find the gameplay scripts that use given script node classes, and collect them.

Script DLLs keep the RTTI names of the node classes they compile in, e.g.
`.?AUR15NETPOOLEDACTORCUSTOMPARAMNODE@@`. This scans every StreamingScriptWin10
asset (6eace9f64204fd0) in the extract for those names, prints which script
uses which class, and copies the matches (plus their CScriptResourceWin10
entries) into data/extract/ so they can be committed and worked on.

Default search: the pooled-actor node classes. UMBRAL VEIL needs a script that
reads a pooled actor's custom params on every machine (the networked way to
tell a smoke wall from an energy barrier).

    python tools/find_scripts.py                        # pooled-actor classes, copy + commit + push
    python tools/find_scripts.py --no-push              # copy + commit only
    python tools/find_scripts.py --list-only            # just print
    python tools/find_scripts.py --no-commit            # copy only (collect_for_claude.bat runs it so)
    python tools/find_scripts.py --pattern QUERYEXPRESSION
    python tools/find_scripts.py --symbol LOCK          # scripts holding CSymbol64("LOCK") or "LOCK"
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXTRACT = r"H:\pcvr-extracted"
SCRIPTS = "6eace9f64204fd0"
SCRIPT_RESOURCE = "991421b41de58370"
OUT = os.path.join(ROOT, "data", "extract")
#: RTTI name fragments (upper case, as compiled)
DEFAULT = ["R15NETPOOLEDACTOR"]


def classes(blob: bytes, patterns) -> set[str]:
    found = set()
    for m in re.finditer(rb"\.\?A[UV]([A-Z0-9_]+)@@", blob):
        name = m.group(1).decode()
        if any(p in name for p in patterns):
            found.add(name)
    return found


def main(argv) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--extract", default=EXTRACT)
    ap.add_argument("--pattern", action="append", help="RTTI name fragment (repeatable)")
    ap.add_argument("--symbol", action="append",
                    help="a name the script uses: its CSymbol64 (or the string itself) (repeatable)")
    ap.add_argument("--list-only", action="store_true")
    ap.add_argument("--no-push", action="store_true")
    ap.add_argument("--no-commit", action="store_true", help="copy only (collect_for_claude.py commits)")
    args = ap.parse_args(argv[1:])
    patterns = [p.upper() for p in (args.pattern or ([] if args.symbol else DEFAULT))]
    symbols = {}
    if args.symbol:
        for d in (os.path.join(OUT, "tools"), os.path.join(os.path.dirname(ROOT), "lone_echo_blender", "scripts")):
            sys.path.insert(0, d)
        from le_symbol_names import symbol64
        for n in args.symbol:
            symbols[n] = (int(symbol64(n), 16).to_bytes(8, "little"), n.encode() + b"\0")

    folder = os.path.join(args.extract, SCRIPTS)
    if not os.path.isdir(folder):
        sys.exit(f"no {folder}: point --extract at the extract root")
    hits = {}
    names = sorted(os.listdir(folder))
    for name in names:
        blob = open(os.path.join(folder, name), "rb").read()
        found = classes(blob, patterns) if patterns else set()
        found |= {f"symbol {n}" for n, (h, txt) in symbols.items() if h in blob or txt in blob}
        if found:
            hits[name] = found
    what = ", ".join(patterns + [f"symbol {n}" for n in symbols])
    print(f"{len(hits)} of {len(names)} scripts use {what}:")
    for name, found in sorted(hits.items()):
        print(f"  {name}: {', '.join(sorted(found))}")
    if args.list_only or not hits:
        return 0

    copied = []
    for name in hits:
        for t in (SCRIPTS, SCRIPT_RESOURCE):
            src = os.path.join(args.extract, t, name)
            if os.path.exists(src):
                dst = os.path.join(OUT, t, name)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                if not (os.path.exists(dst) and os.path.samefile(src, dst)):
                    shutil.copy2(src, dst)
                copied.append(os.path.join("data", "extract", t, name))
    listing = os.path.join(OUT, "symbol_scripts.txt" if symbols and not args.pattern else "pooled_actor_scripts.txt")
    with open(listing, "w") as f:
        for name, found in sorted(hits.items()):
            f.write(f"{name}: {', '.join(sorted(found))}\n")
    copied.append(os.path.relpath(listing, ROOT))
    print(f"copied {len(copied)} file(s) into data/extract")

    if args.no_commit:
        return 0
    subprocess.run(["git", "add", *copied], cwd=ROOT, check=True)
    subprocess.run(["git", "commit", "-m", f"Scripts using {what} (find_scripts.py)"], cwd=ROOT)
    if not args.no_push:
        subprocess.run(["git", "push"], cwd=ROOT)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
