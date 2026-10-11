"""Pack the release: release/EchoCombat-<version>.zip, which the Echo VR launcher installs.

Takes what a deploy stages and builds -- run deploy_and_launch.py first (or
`deploy_and_launch.py --stage-only` for the stage, and the build_*.bat
scripts with MSVC for the plugins):

* build/stage + a stock install    -> content/echocombat/ (`evrtool pack`: the manifests,
                                      the packages they add, the script DLLs, content.json)
* out/DroneFix.dll, PowerBoost.dll, VeilNet.dll -> plugins/ (CombatBots.dll stays out: work
                                      in progress)
* PowerBoost.ini (config/mp_weapon_settings.json) -> plugins/
* release/README.txt, config/mp_weapon_settings.json (what this release was built with)

The launcher installs the zip from its Mods page: plugins/ into bin/win10/plugins/, content/
into bin/win10/content/, and lists them in nEVR's config.yaml (NvrContentOverlay early, with
the pack active). Nothing in the game's own files changes. Game servers take the same two
folders (README.txt). release/echocombat.mods.json is the zip's catalog entry for the
launcher (sha256 and size filled in); the zip goes where its "url" says: packs/ on the
mirror, or files/ in a dev folder (--url-base files/, see README.md: Publishing).

    python tools/make_release.py [--install <Echo VR install>] [--version 1.0.0] [--url-base files/]

The install only has to be stock (or repacked by an old install.bat: its .bak manifests
are stock): every live install has the same stock files, so the pack fits them all.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STAGE = os.path.join(ROOT, "build", "stage")
OUT = os.path.join(ROOT, "build", "release", "EchoCombat")
DATA_DIR = os.path.join("_data", "5932408047", "rad15", "win10")
PLUGINS = ("DroneFix.dll", "PowerBoost.dll", "VeilNet.dll")
PACK_ID = "echocombat"


def version_from_header() -> str:
    """ECHOCOMBAT_VERSION_* in plugin/nevr_plugin.h: the plugins report it to nEVR."""
    parts = {}
    for line in open(os.path.join(ROOT, "plugin", "nevr_plugin.h"), encoding="utf-8"):
        bits = line.split()
        if len(bits) == 3 and bits[0] == "#define" and bits[1].startswith("ECHOCOMBAT_VERSION_"):
            parts[bits[1].rsplit("_", 1)[1]] = bits[2]
    return f"{parts['MAJOR']}.{parts['MINOR']}.{parts['PATCH']}"


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from echocombat_config import local, powerboost_ini

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--install", default=local()["client_install"],
                    help="an Echo VR install to read the stock files from (default: local.json client_install)")
    ap.add_argument("--version", default=version_from_header())
    ap.add_argument("--url-base", default="packs/",
                    help="where the zip goes, relative to the catalogue: packs/ on the mirror (default), "
                         "files/ in a launcher dev folder")
    args = ap.parse_args()
    if not os.path.isdir(STAGE):
        sys.exit("no build/stage: run deploy_and_launch.py --stage-only first")
    if not args.install or not os.path.isdir(os.path.join(args.install, DATA_DIR)):
        sys.exit(f"no Echo VR install with {DATA_DIR} at {args.install!r}: pass --install")
    for dll in PLUGINS:
        if not os.path.exists(os.path.join(ROOT, "out", dll)):
            sys.exit(f"out/{dll} not built (build_*.bat)")

    shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(OUT)
    evrtool = os.path.join(ROOT, "build", "evrtool.exe" if os.name == "nt" else "evrtool")
    subprocess.run(["go", "build", "-trimpath", "-o", evrtool, "."], cwd=os.path.join(ROOT, "evrtool"), check=True)
    subprocess.run([evrtool, "pack", os.path.join(args.install, DATA_DIR), STAGE,
                    os.path.join(OUT, "content", PACK_ID), args.version], check=True)

    plugins = os.path.join(OUT, "plugins")
    os.makedirs(plugins)
    for dll in PLUGINS:
        shutil.copy2(os.path.join(ROOT, "out", dll), plugins)
    with open(os.path.join(plugins, "PowerBoost.ini"), "w", encoding="ascii", newline="\r\n") as fh:
        fh.write(powerboost_ini())
    shutil.copy2(os.path.join(ROOT, "release", "README.txt"), OUT)
    shutil.copy2(os.path.join(ROOT, "config", "mp_weapon_settings.json"), OUT)

    name = f"EchoCombat-{args.version}.zip"
    zip_path = os.path.join(ROOT, "release", name)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for path, dirs, files in os.walk(OUT):
            dirs.sort()
            for f in sorted(files):
                full = os.path.join(path, f)
                z.write(full, os.path.relpath(full, OUT).replace(os.sep, "/"))

    entry = {
        "id": PACK_ID,
        "name": "EchoCombat",
        "summary": "New and fixed Echo Combat gear: DOT FIELD, DRONE, UMBRAL VEIL, OVERCHARGE, NEUTRON, "
                   "TRANSLOCATOR. Servers need it too.",
        "author": "heisthecat31",
        "version": args.version,
        "pack": {
            "url": f"{args.url_base.rstrip('/')}/{name}",
            "sha256": sha256(zip_path),
            "size": os.path.getsize(zip_path),
            "content": PACK_ID,
            "plugins": list(PLUGINS),
        },
        "capabilities": ["alters-gameplay", "network", "hooks-engine"],
    }
    with open(os.path.join(ROOT, "release", "echocombat.mods.json"), "w", encoding="utf-8") as fh:
        json.dump(entry, fh, indent=2)
        fh.write("\n")
    print(f"wrote {zip_path} ({os.path.getsize(zip_path) // 1024} KB) and release/echocombat.mods.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
