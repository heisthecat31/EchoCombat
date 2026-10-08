"""Pack the player zip: release/EchoCombat.zip.

Takes what a deploy stages and builds -- run deploy_and_launch.py (or its stage
step) first:

* build/stage/                    every patched package file  -> stage/
* out/PowerBoost.dll, out/DroneFix.dll                        -> bin/win10/plugins/
* out/dbgcore.dll, the plugin loader (plugin/loader.cpp)        -> bin/win10/dbgcore.dll
* evrtool, cross-built for Windows                            -> evrtool.exe
* release/install.bat, uninstall.bat, README.txt

install.bat runs `evrtool setup`: it merges the stage, writes the script DLLs
from the stage's script assets (there are no loose script DLLs in the zip), and
installs the plugins and the loader. The drone's bullet effects are left out of
the stage on purpose: setup patches them from the player's own install.

    python tools/make_release.py
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STAGE = os.path.join(ROOT, "build", "stage")
OUT = os.path.join(ROOT, "build", "release", "EchoCombat")
ZIP = os.path.join(ROOT, "release", "EchoCombat.zip")
#: Patched at install time (evrtool install), never shipped.
INSTALL_TIME = ("4fd65c8d2b63d470", "21a09c2016d8f3e6")


def main() -> int:
    if not os.path.isdir(STAGE):
        sys.exit("no build/stage: run deploy_and_launch.py --no-launch first")
    shutil.rmtree(OUT, ignore_errors=True)
    shutil.copytree(STAGE, os.path.join(OUT, "stage"),
                    ignore=lambda d, names: [n for n in names if d == STAGE and n in INSTALL_TIME])
    plugins = os.path.join(OUT, "bin", "win10", "plugins")
    os.makedirs(plugins)
    for dll in ("PowerBoost.dll", "DroneFix.dll"):
        src = os.path.join(ROOT, "out", dll)
        if not os.path.exists(src):
            sys.exit(f"out/{dll} not built")
        shutil.copy2(src, plugins)
    loader = os.path.join(ROOT, "out", "dbgcore.dll")
    if not os.path.exists(loader):
        sys.exit("out/dbgcore.dll (the plugin loader) missing")
    shutil.copy2(loader, os.path.join(OUT, "bin", "win10", "dbgcore.dll"))
    env = dict(os.environ, GOOS="windows", GOARCH="amd64")
    subprocess.run(["go", "build", "-trimpath", "-o", os.path.join(OUT, "evrtool.exe"), "."],
                   cwd=os.path.join(ROOT, "evrtool"), env=env, check=True)
    for f in ("install.bat", "uninstall.bat", "doctor.bat", "README.txt"):
        shutil.copy2(os.path.join(ROOT, "release", f), OUT)
    with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for path, _, files in os.walk(OUT):
            for f in sorted(files):
                full = os.path.join(path, f)
                z.write(full, os.path.relpath(full, os.path.dirname(OUT)))
    print(f"wrote {ZIP} ({os.path.getsize(ZIP) // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
