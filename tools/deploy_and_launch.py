"""Stage every DOT / drone / gun patch, repack both Echo installs, then launch a test session.

1. Stage into `build/stage` (wiped first), in an order where each step builds on
   the last:
     fix_dot.py --base <gun patch> --stage   gun patch tree + merged JSON (DOT preset)
   The extract-based tools read build/source: the gun patch's copy of each table
   they edit when it has one, otherwise the extract's.
     fix_drone.py                            drone registry / damage / cooldown, on that JSON
     fix_drone_script.py, fix_drone_bullet.py
     fix_dot_stick.py, fix_dot_constraints.py, fix_dot_dampener.py, fix_dot_script.py,
     fix_shared_frisbee.py
     fix_smoke.py (+ veil_fx.py)             UMBRAL VEIL tac mod: detonator smoke clouds, no wall
     veil_sound.py                           UMBRAL VEIL smoke sound (assets/umbral_veil.wav)
     fix_buff.py                             POWER BOOST tac mod: Repair Matrix in dark gold
     fix_dot_trigger.py                      stacks onto the drone's script table
2. `evrtool repack` each install. QuickRepack always starts from the stock
   manifest (`manifests/<pkg>.bak`), so the stage must hold every patch you
   want live: anything left out goes back to stock.
3. `evrtool findlive` checks that the new scripts (DOT trigger, smoke) made it into each
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
#: The install's second, small package. It may hold its own copy of a sound bank,
#: which the game then loads instead of the main package's.
SIDE_PACKAGE = "2b47aab238f60515"

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
DOT_SCRIPT = "97d0806e6ea89130"
SHARED_SCRIPT = "190ed14fe6c74dd3"
TACMOD_CONTROLLER = "4b65d1b009973281"
BARRIER_SCRIPT = "b87ba2039b049d5e"
SMOKE_SCRIPT = "94ba7ca09dcf7b0b"
STUN_SCRIPT = "190ed14ff6dc4ad8"
SOUND_BANK_TYPE, VEIL_BANK = "6d358eef7bb85a98", "3f1464db1fe49b5"
WALL_SCRIPT = "ac4e9374a146d3a4"
HEAL_SCRIPT = "6a0f689e5b91c666"
BUFF_SCRIPT = "4b65d1b0088d2682"
WRAITH_SCRIPT = "e1971566197d460"
POWERBOOST_DLL = os.path.join(ROOT, "out", "PowerBoost.dll")
GLOBAL_LEVEL = "3f9915d3001dc28e"
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
    wanted = [(t, lvl) for t in FIX_TYPES for lvl in LEVELS] + [(SCRIPTS_TYPE, DET_SCRIPT), (SCRIPTS_TYPE, DOT_SCRIPT),
                                                    (SCRIPTS_TYPE, SHARED_SCRIPT),
                                                    (SCRIPTS_TYPE, TACMOD_CONTROLLER),
                                                    (SCRIPTS_TYPE, BARRIER_SCRIPT),
                                                    (SCRIPTS_TYPE, STUN_SCRIPT),
                                                    (SOUND_BANK_TYPE, VEIL_BANK),
                                                    (SCRIPTS_TYPE, WALL_SCRIPT),
                                                    (SCRIPTS_TYPE, HEAL_SCRIPT),
                                                    (SCRIPTS_TYPE, WRAITH_SCRIPT),
                                                    ("d99f6bbd8009c92c", GLOBAL_LEVEL)]
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


def veil_mailbox(installs) -> str:
    """The spare bytes in echovr.exe both UMBRAL VEIL scripts share (veil_fx.mailbox_rva).
    The staged scripts are the same for both installs, so their exes must agree."""
    sys.path.insert(0, TOOLS)
    from veil_fx import mailbox_rva
    rvas = {install: mailbox_rva(open(os.path.join(install, EXE), "rb").read()) for install in installs}
    if len(set(rvas.values())) != 1:
        sys.exit(f"the installs' echovr.exe builds differ ({rvas}); drop --veil-anchor-sound")
    return hex(next(iter(rvas.values())))


def stage(gunpatch: str, extract: str, preset: str, drone: bool, damping: float, smoke: bool = True,
          veil: tuple = (), fx_preview: int = 0, veil_sound: bool = True, buff: bool = True):
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
    # UMBRAL VEIL (smoke tac mod): registered, own script, fifth controller branch.
    if smoke:
        tool("fix_smoke.py", "--base", STAGE, *src, *veil, *(("--with-buff",) if buff else ()))
        if buff:                              # POWER BOOST: Repair Matrix in dark gold, sixth tac mod
            tool("fix_buff.py", "--base", STAGE, *src)
        if veil_sound:                        # its smoke sound, in the unused 14 s sound slot
            tool("veil_sound.py", *src)
    tool("fix_dot_stick.py", *src)
    tool("fix_dot_constraints.py", *src)
    tool("fix_dot_dampener.py", *src, "--damping", str(damping))
    # fix_dot_frisbee.py is deliberately not run: with the frisbee component the
    # DOT glides on instead of slowing to a stop like the arc mine. Instead the
    # shared script skips enabling it for the DOT, as it already does for the arc.
    tool("fix_shared_frisbee.py", *src)
    tool("fix_dot_script.py", *src)
    tool("fix_dot_trigger.py", *src)          # after fix_drone_script: stacks on its table
    # Particle effect preview: each stun mine shows the next effect (for UMBRAL VEIL's smoke).
    if fx_preview:
        tool("fx_preview.py", *src, "--start", str(fx_preview))


def evrtool():
    src = os.path.join(EVRTOOL_DIR, "main.go")
    if not os.path.exists(EVRTOOL) or os.path.getmtime(src) > os.path.getmtime(EVRTOOL):
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
    for script in (DOT_TRIGGER_SCRIPT,) + tuple(s for s in (SMOKE_SCRIPT, BUFF_SCRIPT) if os.path.exists(
            os.path.join(STAGE, "991421b41de58370", s))):
        out = subprocess.run([evrtool(), "findlive", data, script], capture_output=True, text=True).stdout
        for t in ("6eace9f64204fd0", "991421b41de58370"):     # DLL + CScriptResource
            if f"{t}/{script}" not in out:
                sys.exit(f"script {script} ({t}) missing from {install}'s manifest after repack")
    print("   new scripts present: DOT trigger, smoke, buff")
    staged_bank = os.path.join(STAGE, SOUND_BANK_TYPE, VEIL_BANK)
    if os.path.exists(staged_bank):
        want = os.path.getsize(staged_bank)
        out = subprocess.run([evrtool(), "findlive", data, VEIL_BANK], capture_output=True, text=True).stdout
        sizes = [int(line.split()[1]) for line in out.splitlines() if SOUND_BANK_TYPE in line]
        if want not in sizes:
            sys.exit(f"sound bank {VEIL_BANK} in {install}'s manifest is {sizes}, not the patched {want} bytes")
        print(f"   UMBRAL VEIL sound bank present ({want} bytes)")
        # Read it back through the live manifest, as the game does: the size in
        # the manifest is not proof the package holds the patched bytes.
        check = os.path.join(ROOT, "build", "readback")
        shutil.rmtree(check, ignore_errors=True)
        os.makedirs(check)
        lst = os.path.join(check, "list.txt")
        open(lst, "w").write(f"{SOUND_BANK_TYPE}/{VEIL_BANK}\n")
        subprocess.run([evrtool(), "getlive", data, lst, check], capture_output=True, text=True)
        got_path = os.path.join(check, f"{int(SOUND_BANK_TYPE, 16):016x}", f"{int(VEIL_BANK, 16):016x}")
        got = open(got_path, "rb").read() if os.path.exists(got_path) else b""
        staged = open(staged_bank, "rb").read()
        stock = open(os.path.join(SOURCE, SOUND_BANK_TYPE, VEIL_BANK), "rb").read()
        if got == staged:
            print("   read back from the package: the patched bank")
        elif got[:len(stock)] == stock:
            print("   WARNING: the package returns the ORIGINAL bank under the new size: the repack "
                  "updated the size but not the data")
        else:
            print(f"   WARNING: the package returns {len(got)} bytes that match neither the patched "
                  f"nor the original bank")


def wwise_caches(install: str) -> list[str]:
    """Folders the game writes sound banks out to (`%s/_temp/wwise/`): under the
    install, and under any rad/echo folder in %LOCALAPPDATA% or %TEMP%."""
    roots = [install]
    for env in ("LOCALAPPDATA", "TEMP", "APPDATA"):
        base = os.environ.get(env)
        if base and os.path.isdir(base):
            roots += [os.path.join(base, d) for d in os.listdir(base)
                      if any(k in d.lower() for k in ("rad", "echo", "r14"))]
    found = []
    for root in roots:
        top = root.rstrip(os.sep).count(os.sep)
        for path, dirs, _ in os.walk(root):
            if path.count(os.sep) - top >= 6:
                dirs[:] = []
            if os.path.basename(path).lower() == "wwise" and \
                    os.path.basename(os.path.dirname(path)).lower() == "_temp":
                found.append(path)
                dirs[:] = []
    return found


def clear_wwise_cache(install: str):
    """A sound bank cached on disk from before the repack would be played instead
    of the patched one (UMBRAL VEIL's sound), so the cache is emptied; the game
    writes it again."""
    caches = wwise_caches(install)
    for cache in caches:
        shutil.rmtree(cache, ignore_errors=True)
        print(f"   cleared sound bank cache {cache}")
    if not caches:
        print("   no _temp/wwise sound bank cache found")


def evr(args: list, package: str = PACKAGE, **kw) -> subprocess.CompletedProcess:
    env = dict(os.environ, EVR_PKG=package)
    return subprocess.run([evrtool(), *args], env=env, capture_output=True, text=True, **kw)


def patch_side_package(install: str):
    """If the side package carries its own copy of UMBRAL VEIL's sound bank, the
    game plays that one (the original audio), so it gets the patched bank too."""
    data = os.path.join(install, DATA_DIR)
    staged_bank = os.path.join(STAGE, SOUND_BANK_TYPE, VEIL_BANK)
    if not (os.path.exists(staged_bank) and os.path.exists(os.path.join(data, "manifests", SIDE_PACKAGE))):
        return
    listing = evr(["list", data, SOUND_BANK_TYPE], SIDE_PACKAGE).stdout.split()
    print(f"   side package {SIDE_PACKAGE}: {len(listing)} sound bank(s)")
    found = evr(["findlive", data, VEIL_BANK], SIDE_PACKAGE).stdout
    if SOUND_BANK_TYPE not in found:
        print(f"   side package has no copy of the UMBRAL VEIL bank")
        return
    print(f"   side package HAS its own copy of the UMBRAL VEIL bank ({found.strip()}): patching it too")
    side = os.path.join(ROOT, "build", "stage_side")
    shutil.rmtree(side, ignore_errors=True)
    os.makedirs(os.path.join(side, SOUND_BANK_TYPE))
    shutil.copy2(staged_bank, os.path.join(side, SOUND_BANK_TYPE, VEIL_BANK))
    r = evr(["repack", data, side], SIDE_PACKAGE)
    print("   " + r.stdout.strip().replace("\n", "\n   "))
    if r.returncode:
        sys.exit(f"repack of {SIDE_PACKAGE} failed: {r.stderr}")
    check = os.path.join(ROOT, "build", "readback_side")
    shutil.rmtree(check, ignore_errors=True)
    os.makedirs(check)
    lst = os.path.join(check, "list.txt")
    open(lst, "w").write(f"{SOUND_BANK_TYPE}/{VEIL_BANK}\n")
    evr(["getlive", data, lst, check], SIDE_PACKAGE)
    got = os.path.join(check, f"{int(SOUND_BANK_TYPE, 16):016x}", f"{int(VEIL_BANK, 16):016x}")
    ok = os.path.exists(got) and open(got, "rb").read() == open(staged_bank, "rb").read()
    print("   side package read back: " + ("the patched bank" if ok else "NOT the patched bank"))


def install_powerboost(install: str):
    """POWER BOOST's damage reduction lives in PowerBoost.dll (build_powerboost.bat),
    loaded from bin/win10/plugins/ by every instance, the headless servers included."""
    folder = os.path.join(install, "bin", "win10", "plugins")
    if not os.path.exists(POWERBOOST_DLL):
        print(f"   warning: {POWERBOOST_DLL} not built (run build_powerboost.bat): POWER BOOST will not reduce damage")
        return
    os.makedirs(folder, exist_ok=True)
    shutil.copy2(POWERBOOST_DLL, os.path.join(folder, "PowerBoost.dll"))
    print(f"   wrote {os.path.join(folder, 'PowerBoost.dll')}")


def install_script_dlls(install: str):
    """Echo loads script code from bin/win10/scripts/<hash>.dll, not from the package,
    so every staged script (the new DOT trigger script, the sound-patched DOT script)
    is written there too. An original DLL is kept once as <hash>.dll.orig.
    The detonator's DLL on disk is checked against its packaged asset first, to be
    sure the two hold the same image."""
    folder = os.path.join(install, "bin", "win10", "scripts")
    os.makedirs(folder, exist_ok=True)
    det = open(os.path.join(SOURCE, SCRIPTS_TYPE, DET_SCRIPT), "rb").read()
    det_dll = os.path.join(folder, f"{DET_SCRIPT}.dll")
    if os.path.exists(det_dll) and open(det_dll, "rb").read() != det[det.find(b"MZ"):]:
        print(f"   warning: {det_dll} differs from the packaged detonator script")
    staged = set(os.listdir(os.path.join(STAGE, SCRIPTS_TYPE)))
    # A script patched by an earlier deploy but not this one goes back to stock.
    for orig in sorted(f for f in os.listdir(folder) if f.endswith(".dll.orig")):
        name = orig[:-len(".dll.orig")]
        if name not in staged:
            shutil.copy2(os.path.join(folder, orig), os.path.join(folder, f"{name}.dll"))
            print(f"   restored {name}.dll from its .orig")
    for name in sorted(staged):
        asset = open(os.path.join(STAGE, SCRIPTS_TYPE, name), "rb").read()
        dest = os.path.join(folder, f"{name}.dll")
        if os.path.exists(dest) and not os.path.exists(dest + ".orig") and name != DOT_TRIGGER_SCRIPT:
            shutil.copy2(dest, dest + ".orig")
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
    ap.add_argument("--dot-damping", type=float, default=25.0,
                    help="how fast a thrown DOT slows down (higher = stops sooner); 25 = arc mine")
    ap.add_argument("--no-smoke", action="store_true",
                    help="leave UMBRAL VEIL out (stock tac mod controller), e.g. to A/B a tac mod")
    ap.add_argument("--veil-count", default="7", help="UMBRAL VEIL smoke clouds per use")
    ap.add_argument("--veil-scale", default="6", help="UMBRAL VEIL cloud size (detonator's is about 2)")
    ap.add_argument("--veil-life", default="8", help="UMBRAL VEIL smoke lifetime, x the detonator's")
    ap.add_argument("--veil-spread", default="1.5", help="UMBRAL VEIL metres between clouds")
    ap.add_argument("--veil-emission", default="8", help="UMBRAL VEIL particles per cloud, x the detonator's")
    ap.add_argument("--veil-puff", default="2.5", help="UMBRAL VEIL size of each smoke puff")
    ap.add_argument("--veil-alpha", default="10", help="UMBRAL VEIL opacity multiplier")
    ap.add_argument("--veil-shade", default="0.9", help="UMBRAL VEIL colour multiplier (lower = darker)")
    ap.add_argument("--fx-preview", type=int, default=0, metavar="N",
                    help="stun mines show particle effects N, N+1, ... one per mine (see fx_preview.py --list)")
    ap.add_argument("--veil-anchor-sound", action="store_true",
                    help="EXPERIMENTAL, not working yet: UMBRAL VEIL's sound from an invisible smoke wall left "
                         "where it went off (walls run their start-up nodes when the pool is made, not when "
                         "placed, so the sound came ~20 s late, from the player). Default: on the player")
    ap.add_argument("--veil-stock-sound", action="store_true",
                    help="UMBRAL VEIL plays the slot's original audio (to tell a silent event from silent audio)")
    ap.add_argument("--no-buff", action="store_true", help="leave POWER BOOST out")
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
        stage(args.gunpatch, args.extract, args.preset, not args.no_drone, args.dot_damping,
              not args.no_smoke, ("--count", args.veil_count, "--scale", args.veil_scale,
                                  "--life", args.veil_life, "--spread", args.veil_spread,
                                  "--emission", args.veil_emission, "--particle-scale", args.veil_puff,
                                  "--alpha", args.veil_alpha, "--shade", args.veil_shade)
              + (() if not args.veil_anchor_sound else
                 ("--mailbox", veil_mailbox((args.server_install, args.client_install)))), args.fx_preview,
              not args.veil_stock_sound, not args.no_buff)
        for install in (args.server_install, args.client_install):
            repack(install)
            patch_side_package(install)
            install_script_dlls(install)
            clear_wwise_cache(install)
            if not args.no_buff:
                install_powerboost(install)

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
