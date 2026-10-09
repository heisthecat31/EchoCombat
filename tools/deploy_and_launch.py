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
     fix_buff.py                             POWER BOOST tac mod: Repair Matrix in purplish red
     fix_point.py                            POINT tac mod: a stun field where its wall lands
     gear_icons.py                           gear table / HUD icons for the new gear, from a texture of our own
     fix_loc_fx.py                           TRANSLOCATOR: stun field effect + sound on teleport
     fix_dot_trigger.py                      stacks onto the drone's script table
     fix_starburst_div.py                    STARBURST: no divide-by-zero log every frame
2. `evrtool repack` each install. QuickRepack always starts from the stock
   manifest (`manifests/<pkg>.bak`), so the stage must hold every patch you
   want live: anything left out goes back to stock.
3. `evrtool findlive` checks that the new scripts (DOT trigger, smoke) made it into each
   manifest, and its DLL is written to `bin/win10/scripts/`, which is where
   Echo actually loads script code from.
4. The DLLs (build_powerboost.bat, build_dronefix.bat, build_loader.bat, with
   MSVC; --no-build installs the committed out/ copies) go into each install:
   PowerBoost.dll, DroneFix.dll and VeilNet.dll in bin/win10/plugins/, the plugin loader as
   bin/win10/dbgcore.dll.
5. Launch the headless instances from the server install, then the VR client
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
    "4af215b19b297c34",                         # explosions: POINT's stun on the barrier wall (fix_point.py)
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
POINT_SOUND_BANK = "c823e2c9bc0168ad"           # the stun field's sounds, copied into the veil bank
WALL_SCRIPT = "ac4e9374a146d3a4"
#: (no longer used: the networked UMBRAL VEIL once read its params with this script's query)
QUERY_SCRIPT = "c3178dbdb1250dce"
HEAL_SCRIPT = "6a0f689e5b91c666"
BUFF_SCRIPT = "4b65d1b0088d2682"
POINT_SCRIPT = "94ba7ca39fc97e1a"
PARTICLE_TYPES = ("3ae7c41914252baa", "be45c22fa8c2d3f")   # particle effect + its companion asset
BUFF_PARTICLES = ("39424707bb2df316", "be696d7d300cbaf7",   # Repair Matrix's beam and hand effects
                  "de22b615c9c69cdd")                       # the stun field (fix_buff --fx-test)
WRAITH_SCRIPT = "e1971566197d460"
LOC_SCRIPT = "9398a165c004a9c0"          # TRANSLOCATOR (fix_loc_fx.py: teleport effect + sound)
STARBURST_SCRIPT = "a9db89899292a98f"    # STARBURST gun (fix_starburst_div.py: divide-by-zero log)
GLOBAL_LEVEL = "3f9915d3001dc28e"
#: gear icons (gear_icons.py): the stock icon atlases (descriptor + DDS) -- the HUD's
#: gear sheet and the shared UI sheet the equipment station uses -- and their canvases
GEAR_ICON_ATLASES = ("d8b84ca5707d3bd2", "9ec57c5df16fef80")
GEAR_ICON_TEXTURE_TYPES = ("4a4c32c49300b8a0", "beac1969cb7b8861")
GEAR_ICON_CANVAS_TYPE = "59a9bd6e4525ecc4"
GEAR_ICON_CANVASES = ("1e5d2a97184cad81", "2262b1c4c25c734e", "6083f456d52ef5f1", "b138c20e60e662a1",
                      "13361c4773e07b3e", "2d06e14794a11e31", "8fcec01d07930956", "f4cc172339347e8b")
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
                                                    (SOUND_BANK_TYPE, POINT_SOUND_BANK),
                                                    (SCRIPTS_TYPE, WALL_SCRIPT),
                                                    (SCRIPTS_TYPE, QUERY_SCRIPT),
                                                    (SCRIPTS_TYPE, HEAL_SCRIPT),
                                                    (SCRIPTS_TYPE, WRAITH_SCRIPT),
                                                    (SCRIPTS_TYPE, LOC_SCRIPT),
                                                    (SCRIPTS_TYPE, STARBURST_SCRIPT),
                                                    ("d99f6bbd8009c92c", GLOBAL_LEVEL)] + [
        (t, fx) for t in PARTICLE_TYPES for fx in BUFF_PARTICLES] + [   # POWER BOOST's gold beam / hand
        (GEAR_ICON_CANVAS_TYPE, c) for c in GEAR_ICON_CANVASES] + [     # gear icons (gear_icons.py)
        (t, atlas) for t in GEAR_ICON_TEXTURE_TYPES for atlas in GEAR_ICON_ATLASES]
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
          veil: tuple = (), fx_preview: int = 0, veil_sound: bool = True, buff: bool = True,
          buff_dr: float = 0.09, buff_charge: float = 40, buff_fx_test: bool = False,
          buff_rez: bool = True, point: bool = True, point_sound_preview: bool = False,
          point_event: str = None):
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
        point = point and buff and "--mailbox" not in veil
        tool("fix_smoke.py", "--base", STAGE, *src, *veil, *(("--with-buff",) if buff else ()),
             *(("--with-point",) if point else ()),
             *(("--point-sound-preview",) if point and point_sound_preview else ()),
             *(("--point-event", point_event) if point and point_event else ()))
        if buff:                              # POWER BOOST: Repair Matrix in purplish red, sixth tac mod
            tool("fix_buff.py", "--base", STAGE, *src, "--dr", str(buff_dr), "--charge", str(buff_charge),
                 *(("--fx-test",) if buff_fx_test else ()), *(() if buff_rez else ("--no-rez",)))
        if point:                             # POINT: a stun field where its wall lands, seventh tac mod
            tool("fix_point.py", "--base", STAGE, *src)
        if veil_sound:                        # its smoke sound, in the unused 14 s sound slot
            tool("veil_sound.py", *src)
    # TRANSLOCATOR: the stun field's burst and a sound when the player teleports (its sound
    # event is added to the sound bank by veil_sound.py above).
    tool("fix_loc_fx.py", "--src", SOURCE, "--out", STAGE)
    # Gear icons: a texture of our own for the new gear (test colours for now), used by
    # the gear table / HUD canvases.
    tool("gear_icons.py", "--src", SOURCE, "--out", STAGE)
    tool("fix_dot_stick.py", *src)
    tool("fix_dot_constraints.py", *src)
    tool("fix_dot_dampener.py", *src, "--damping", str(damping))
    # fix_dot_frisbee.py is deliberately not run: with the frisbee component the
    # DOT glides on instead of slowing to a stop like the arc mine. Instead the
    # shared script skips enabling it for the DOT, as it already does for the arc.
    tool("fix_shared_frisbee.py", *src)
    tool("fix_dot_script.py", *src)
    tool("fix_dot_trigger.py", *src)          # after fix_drone_script: stacks on its table
    # STARBURST: its script's divide-by-zero log, written every frame while the gun is out.
    tool("fix_starburst_div.py", *src)
    # Particle effect preview: each stun mine shows the next effect (for UMBRAL VEIL's smoke).
    if fx_preview:
        tool("fx_preview.py", *src, "--start", str(fx_preview))


def evrtool():
    newest = max(os.path.getmtime(os.path.join(EVRTOOL_DIR, f))
                 for f in os.listdir(EVRTOOL_DIR) if f.endswith((".go", ".mod", ".sum")))
    if not os.path.exists(EVRTOOL) or newest > os.path.getmtime(EVRTOOL):
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
    for script in (DOT_TRIGGER_SCRIPT,) + tuple(s for s in (SMOKE_SCRIPT, BUFF_SCRIPT, POINT_SCRIPT) if os.path.exists(
            os.path.join(STAGE, "991421b41de58370", s))):
        out = subprocess.run([evrtool(), "findlive", data, script], capture_output=True, text=True).stdout
        for t in ("6eace9f64204fd0", "991421b41de58370"):     # DLL + CScriptResource
            if f"{t}/{script}" not in out:
                sys.exit(f"script {script} ({t}) missing from {install}'s manifest after repack")
    print("   new scripts present: DOT trigger, smoke, buff, point")
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


#: (build script, the DLL it writes to out/, where it goes under bin/win10)
DLLS = [("build_powerboost.bat", "PowerBoost.dll", os.path.join("plugins", "PowerBoost.dll")),
        ("build_dronefix.bat", "DroneFix.dll", os.path.join("plugins", "DroneFix.dll")),
        ("build_veilnet.bat", "VeilNet.dll", os.path.join("plugins", "VeilNet.dll")),
        ("build_combatbots.bat", "CombatBots.dll", os.path.join("plugins", "CombatBots.dll")),
        ("build_loader.bat", "dbgcore.dll", "dbgcore.dll")]


def build_dlls():
    """Build the plugins and the plugin loader with MSVC (the build_*.bat scripts).
    A DLL that fails to build falls back to the committed copy in out/."""
    print("\n== building DLLs")
    for bat, dll, _ in DLLS:
        r = subprocess.run(["cmd", "/c", os.path.join(ROOT, bat)], cwd=ROOT, capture_output=True, text=True)
        out = (r.stdout + r.stderr).strip()
        if r.returncode:
            print(f"   {bat} FAILED ({r.returncode}); using the committed out/{dll}\n      "
                  + out.replace("\n", "\n      "))
        else:
            print(f"   built out/{dll}")
        if not os.path.exists(os.path.join(ROOT, "out", dll)):
            sys.exit(f"out/{dll} missing and could not be built")


def is_plugin_loader(data: bytes) -> bool:
    return b"plugins\0" in data and b"LoadLibrary" in data


def install_dlls(install: str):
    """PowerBoost.dll, DroneFix.dll and VeilNet.dll into bin/win10/plugins/, and the plugin loader as
    bin/win10/dbgcore.dll (echovr.exe loads it at startup; it loads plugins/). A
    dbgcore.dll from another mod is moved into plugins/ so it still loads; an older
    plugin loader is replaced (kept as dbgcore.dll.bak) so nothing loads twice."""
    bin_dir = os.path.join(install, "bin", "win10")
    plugins = os.path.join(bin_dir, "plugins")
    os.makedirs(plugins, exist_ok=True)
    for _, dll, dest in DLLS:
        src = open(os.path.join(ROOT, "out", dll), "rb").read()
        dst = os.path.join(bin_dir, dest)
        if dll == "dbgcore.dll" and os.path.exists(dst):
            old = open(dst, "rb").read()
            if old != src:
                if is_plugin_loader(old):
                    shutil.copy2(dst, dst + ".bak")
                    print(f"   replacing an older plugin loader (kept as {dst}.bak)")
                else:
                    moved = os.path.join(plugins, "dbgcore.dll")
                    if os.path.exists(moved) and open(moved, "rb").read() != old:
                        moved = os.path.join(plugins, "dbgcore_previous.dll")
                    shutil.copy2(dst, moved)
                    print(f"   moved the existing dbgcore.dll to {moved} so the loader still loads it")
        open(dst, "wb").write(src)
        if open(dst, "rb").read() != src:
            sys.exit(f"{dst} did not keep what was written (antivirus? Echo running?)")
        print(f"   wrote {dst}")
    # CombatBots' per-map war room orbs and routes (tools/record_nav.py)
    nav_dir = os.path.join(ROOT, "data", "nav")
    for name in sorted(os.listdir(nav_dir)) if os.path.isdir(nav_dir) else []:
        if name.endswith(".json"):
            dst = os.path.join(plugins, f"CombatBots_{name}")
            shutil.copy2(os.path.join(nav_dir, name), dst)
            print(f"   wrote {dst}")


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
    # UMBRAL VEIL's particle load is clouds x emission x life (7 x 8 x 8 cost ~45 fps);
    # fewer, bigger, more opaque puffs keep the cover at about 1/7 of the particles.
    ap.add_argument("--veil-count", default="4", help="UMBRAL VEIL smoke clouds per use")
    ap.add_argument("--veil-scale", default="6", help="UMBRAL VEIL cloud size (detonator's is about 2)")
    ap.add_argument("--veil-life", default="5", help="UMBRAL VEIL smoke lifetime, x the detonator's")
    ap.add_argument("--veil-spread", default="1.5", help="UMBRAL VEIL metres between clouds")
    ap.add_argument("--veil-emission", default="4", help="UMBRAL VEIL particles per cloud, x the detonator's")
    ap.add_argument("--veil-puff", default="3.5", help="UMBRAL VEIL size of each smoke puff")
    ap.add_argument("--veil-alpha", default="35", help="UMBRAL VEIL opacity multiplier")
    ap.add_argument("--veil-shade", default="0.6", help="UMBRAL VEIL colour multiplier (lower = darker)")
    ap.add_argument("--fx-preview", type=int, default=0, metavar="N",
                    help="stun mines show particle effects N, N+1, ... one per mine (see fx_preview.py --list)")
    ap.add_argument("--veil-anchor-sound", action="store_true",
                    help="EXPERIMENTAL, not working yet: UMBRAL VEIL's sound from an invisible smoke wall left "
                         "where it went off (walls run their start-up nodes when the pool is made, not when "
                         "placed, so the sound came ~20 s late, from the player). Default: on the player")
    ap.add_argument("--veil-stock-sound", action="store_true",
                    help="UMBRAL VEIL plays the slot's original audio (to tell a silent event from silent audio)")
    ap.add_argument("--no-buff", action="store_true", help="leave POWER BOOST out (and POINT, whose branch follows it)")
    ap.add_argument("--no-point", action="store_true", help="leave POINT out")
    ap.add_argument("--point-event", help="POINT plays this sound event instead (a number), e.g. the translocator's 2819690668 to test POINT's sound path")
    ap.add_argument("--point-sound-preview", action="store_true",
                    help="each POINT use plays the next sound: 1st the stun field's (a check), then the arc mine's 9, to pick POINT's")
    ap.add_argument("--buff-dr", type=float, default=0.09,
                    help="POWER BOOST damage reduction (0.09 = 9%% less damage taken)")
    ap.add_argument("--buff-charge", type=float, default=40, help="POWER BOOST recharge time in seconds")
    ap.add_argument("--no-buff-rez", action="store_true",
                    help="POWER BOOST without cheat death for linked teammates")
    ap.add_argument("--buff-fx-test", action="store_true",
                    help="test: POWER BOOST's beam shows the stun field effect instead (is the beam copy used?)")
    ap.add_argument("--no-drone", action="store_true", help="leave the drone fixes out")
    ap.add_argument("--no-build", action="store_true",
                    help="do not build the DLLs with MSVC; install the committed ones in out/")
    ap.add_argument("--headless", type=int, default=HEADLESS_COUNT)
    ap.add_argument("--headless-args", default=HEADLESS_ARGS)
    ap.add_argument("--bots", type=int, metavar="N",
                    help="EchoRelay game servers: add N AI bots (any team, up to 16) to each session once it's "
                         "in game (adds -noovr -bots N to their command line)")
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
        if not args.no_build:
            build_dlls()
        stage(args.gunpatch, args.extract, args.preset, not args.no_drone, args.dot_damping,
              not args.no_smoke, ("--count", args.veil_count, "--scale", args.veil_scale,
                                  "--life", args.veil_life, "--spread", args.veil_spread,
                                  "--emission", args.veil_emission, "--particle-scale", args.veil_puff,
                                  "--alpha", args.veil_alpha, "--shade", args.veil_shade)
              + (() if not args.veil_anchor_sound else
                 ("--mailbox", veil_mailbox((args.server_install, args.client_install)))), args.fx_preview,
              not args.veil_stock_sound, not args.no_buff, args.buff_dr, args.buff_charge, args.buff_fx_test,
              not args.no_buff_rez, not args.no_point, args.point_sound_preview, args.point_event)
        for install in (args.server_install, args.client_install):
            repack(install)
            patch_side_package(install)
            install_script_dlls(install)
            clear_wwise_cache(install)
            install_dlls(install)

    if args.no_launch:
        return 0
    print()
    headless_args = args.headless_args
    if args.bots:
        headless_args += ("" if "-noovr" in headless_args.split() else " -noovr") + f" -bots {args.bots}"
    for i in range(args.headless):
        # each server its own session API port (they all default to 6719, so only the
        # first got one): CombatBots.dll reads the bots' world from it
        extra = "" if "-httpport" in headless_args else f" -httpport {6730 + i}"
        launch(args.server_install, headless_args + extra, f"headless {i + 1}")
        time.sleep(5)
    time.sleep(5)
    launch(args.client_install, args.client_args, "VR client")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
