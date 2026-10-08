"""Stage every DOT / drone / gun patch, repack both Echo installs, then launch a test session.

1. Stage into `build/stage` (wiped first), in an order where each step builds on
   the last:
     fix_dot.py --base <gun patch> --stage   gun patch tree + merged JSON (DOT preset)
   The extract-based tools read build/source: the gun patch's copy of each table
   they edit when it has one, otherwise the extract's.
     fix_drone.py                            drone registry / damage / cooldown, on that JSON
     fix_drone_script.py, fix_drone_bullet.py
     fix_dot_stick.py, fix_dot_constraints.py, fix_dot_dampener.py
     fix_dot_trigger.py                      stacks onto the drone's script table
2. `evrtool repack` each install. QuickRepack always starts from the stock
   manifest (`manifests/<pkg>.bak`), so the stage must hold every patch you
   want live: anything left out goes back to stock.
3. `evrtool findlive` checks that the new DOT trigger script made it into each
   manifest, and its DLL is written to `bin/win10/scripts/`, which is where
   Echo actually loads script code from.
4. Launch the headless instances from the server install, then the VR client
   from the other install.

    python tools/deploy_and_launch.py                                 # gun patch from GUNPATCH
    python tools/deploy_and_launch.py --gunpatch <dir> --no-launch    # patch only
    python tools/deploy_and_launch.py --launch-only                   # skip patching

Echo must not be running in either install while repacking; `--kill` closes it.
"""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, "tools")
STAGE = os.path.join(ROOT, "build", "stage")
EVRTOOL_DIR = os.path.join(ROOT, "evrtool")
EVRTOOL = os.path.join(EVRTOOL_DIR, "evrtool.exe")

EXTRACT = r"H:\pcvr-extracted"
GUNPATCH = r"J:\combatGunPatchFiles"
SERVER_INSTALL = r"H:\ready-at-dawn-echo-arena"
CLIENT_INSTALL = r"C:\Oculus\Games\Software\Software\ready-at-dawn-echo-arena"
DATA_DIR = os.path.join("_data", "5932408047", "rad15", "win10")
EXE = os.path.join("bin", "win10", "echovr.exe")
PACKAGE = "48037dc70b0ecab2"

#: Headless instances started from the server install. Edit to match how you
#: normally start them (region, ports, config path...).
HEADLESS_COUNT = 2
HEADLESS_ARGS = "-server -headless"
#: The VR client, started from the client install.
CLIENT_ARGS = ""

JSON_TYPE = "607d858c90268f9a"
DOT_TRIGGER_SCRIPT = "4e8af51fe7d6af8c"
#: Type folders the extract-based fix tools read and rewrite. Where the gun
#: patch carries its own copy of one of these tables, the tools start from that
#: copy instead of the pristine extract, so both sets of edits survive. Every fix
#: tool is a no-op on input it has already patched.
FIX_TYPES = [
    "5b723f040a3778ee", "dde8fffc5b4d7ad4", "f2676c58c07bab0c", "2b292830e51c4fd2",
    "92abd3e1432bf5e8", "d99f6bbd8009c92c", "4fd65c8d2b63d470", "21a09c2016d8f3e6",
]
LEVELS = ["42670f2bed45703c", "43e2da7914642604", "43e2da7a0c623a19",
          "cb9977f7fc2b4526", "df5ca7b7dfa383d4"]
SCRIPTS_TYPE = "6eace9f64204fd0"
DET_SCRIPT = "190ed14fe3da5ed1"
SOURCE = os.path.join(ROOT, "build", "source")


def run(cmd, **kw):
    print(">", " ".join(cmd))
    r = subprocess.run(cmd, **kw)
    if r.returncode:
        sys.exit(f"failed ({r.returncode}): {' '.join(cmd)}")


def tool(name, *args):
    run([sys.executable, os.path.join(TOOLS, name), *args])


def gunpatch_root(path: str) -> str:
    """The folder holding 607d858c90268f9a/, at `path` or one level down."""
    if os.path.isdir(os.path.join(path, JSON_TYPE)):
        return path
    subs = [os.path.join(path, d) for d in os.listdir(path)] if os.path.isdir(path) else []
    hits = [d for d in subs if os.path.isdir(os.path.join(d, JSON_TYPE))]
    if len(hits) == 1:
        return hits[0]
    sys.exit(f"{path} has no {JSON_TYPE}/ folder (extract the zip and point at the folder holding it)")


def overlay(base: str, extract: str):
    """build/source: the tables the fix tools read, gun patch copy first, else the extract."""
    from_patch = set()
    wanted = [(t, lvl) for t in FIX_TYPES for lvl in LEVELS] + [(SCRIPTS_TYPE, DET_SCRIPT)]
    for t, asset in wanted:
        src = os.path.join(base, t, asset)
        if os.path.exists(src):
            from_patch.add(t)
        else:
            src = os.path.join(extract, t, asset)
            if not os.path.exists(src):
                sys.exit(f"missing {t}/{asset} in both the gun patch and {extract}")
        os.makedirs(os.path.join(SOURCE, t), exist_ok=True)
        shutil.copy2(src, os.path.join(SOURCE, t, asset))
    if from_patch:
        print("starting from the gun patch's copy of:", ", ".join(sorted(from_patch)))


def stage(gunpatch: str, extract: str, preset: str, drone: bool, damping: float):
    base = gunpatch_root(gunpatch)
    for d in (STAGE, SOURCE):
        if os.path.isdir(d):
            shutil.rmtree(d)
        os.makedirs(d)
    overlay(base, extract)
    tool("fix_dot.py", "--base", base, "--preset", preset, "--stage", STAGE)
    src = ["--src", SOURCE, "--out", STAGE]
    if drone:
        tool("fix_drone.py", "--base", STAGE, "--out", STAGE)
        tool("fix_drone_script.py", *src)
        tool("fix_drone_bullet.py", *src)
    tool("fix_dot_stick.py", *src)
    tool("fix_dot_constraints.py", *src)
    tool("fix_dot_dampener.py", *src, "--damping", str(damping))
    tool("fix_dot_trigger.py", *src)          # after fix_drone_script: stacks on its table


def evrtool():
    if not os.path.exists(EVRTOOL):
        print("building evrtool.exe")
        run(["go", "build", "-o", EVRTOOL, "."], cwd=EVRTOOL_DIR)
    return EVRTOOL


def echo_running() -> bool:
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq echovr.exe"],
                         capture_output=True, text=True).stdout
    return "echovr.exe" in out.lower()


def repack(install: str):
    data = os.path.join(install, DATA_DIR)
    if not os.path.exists(os.path.join(data, "manifests", PACKAGE)):
        sys.exit(f"no manifest under {data}")
    print(f"\n== repacking {install}")
    run([evrtool(), "repack", data, STAGE])
    out = subprocess.run([evrtool(), "findlive", data, DOT_TRIGGER_SCRIPT],
                         capture_output=True, text=True).stdout
    for t in ("6eace9f64204fd0", "991421b41de58370"):     # DLL + CScriptResource
        if f"{t}/{DOT_TRIGGER_SCRIPT}" not in out:
            sys.exit(f"DOT trigger script ({t}) missing from {install}'s manifest after repack")
    print("   DOT trigger script present:", out.strip())


def install_script_dll(install: str):
    """Echo loads script code from bin/win10/scripts/<hash>.dll, not from the package:
    put the DOT trigger script's PE there. The detonator's DLL on disk is checked
    against its packaged asset first, to be sure the two hold the same image."""
    folder = os.path.join(install, "bin", "win10", "scripts")
    os.makedirs(folder, exist_ok=True)
    det = open(os.path.join(SOURCE, SCRIPTS_TYPE, DET_SCRIPT), "rb").read()
    det_dll = os.path.join(folder, f"{DET_SCRIPT}.dll")
    if os.path.exists(det_dll) and open(det_dll, "rb").read() != det[det.find(b"MZ"):]:
        print(f"   warning: {det_dll} differs from the packaged detonator script")
    asset = open(os.path.join(STAGE, SCRIPTS_TYPE, DOT_TRIGGER_SCRIPT), "rb").read()
    dest = os.path.join(folder, f"{DOT_TRIGGER_SCRIPT}.dll")
    open(dest, "wb").write(asset[asset.find(b"MZ"):])
    print(f"   wrote {dest}")


def launch(install: str, args: str, label: str):
    exe = os.path.join(install, EXE)
    print(f"launching {label}: {exe} {args}")
    subprocess.Popen([exe, *shlex.split(args, posix=False)], cwd=os.path.dirname(exe),
                     creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))


def main(argv) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--gunpatch", default=GUNPATCH, help="extracted combat gun patch folder")
    ap.add_argument("--extract", default=EXTRACT)
    ap.add_argument("--server-install", default=SERVER_INSTALL)
    ap.add_argument("--client-install", default=CLIENT_INSTALL)
    # stick_to_geo stops the field on its first contact after release, which is
    # the thrower's own hand, so the trigger preset leaves it off.
    ap.add_argument("--preset", default="trigger-nostick", help="fix_dot.py activation preset")
    ap.add_argument("--dot-damping", type=float, default=3.0,
                    help="how fast a thrown DOT slows down (higher = stops sooner; the arc uses 25)")
    ap.add_argument("--no-drone", action="store_true", help="leave the drone fixes out")
    ap.add_argument("--headless", type=int, default=HEADLESS_COUNT)
    ap.add_argument("--headless-args", default=HEADLESS_ARGS)
    ap.add_argument("--client-args", default=CLIENT_ARGS)
    ap.add_argument("--kill", action="store_true", help="close running echovr.exe first")
    ap.add_argument("--no-launch", action="store_true")
    ap.add_argument("--launch-only", action="store_true")
    args = ap.parse_args(argv[1:])

    if not args.launch_only:
        if echo_running():
            if not args.kill:
                sys.exit("echovr.exe is running; close it or pass --kill")
            subprocess.run(["taskkill", "/IM", "echovr.exe", "/F"])
            time.sleep(3)
        stage(args.gunpatch, args.extract, args.preset, not args.no_drone, args.dot_damping)
        for install in (args.server_install, args.client_install):
            repack(install)
            install_script_dll(install)

    if args.no_launch:
        return 0
    print()
    for i in range(args.headless):
        launch(args.server_install, args.headless_args, f"headless {i + 1}")
        time.sleep(5)
    time.sleep(5)
    launch(args.client_install, args.client_args, "VR client")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
