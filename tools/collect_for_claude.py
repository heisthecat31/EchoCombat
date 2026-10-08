"""Gather the files needed to debug DOT activation, then commit and push them.

Copies them into `data/extract/`, keeping the extract's `<type>/<asset>` layout:

* level component tables for every combat level: magazine (`CR15NetMagazineCR`),
  script table (`CScriptCR`), trigger (`CR15TriggerCR`), explosion
  (`CR15NetExplosionCR`), plus the three DOT tables the fix scripts already touch
* the magazine pouch table (`CR15NetMagazinePouchCR`), whole folder
* the ordnance script DLLs (dot, det, shared magazine script, arc, stun, burst, loc)
  and their `CScriptResourceWin10` entries
* every other script that mentions one of the external functions the DOT script
  calls for its remote trigger, or that reads trigger input or the pouch's
  last-thrown magazine; all matches are listed in `search.txt`
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
import struct
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
    "39284e7992befc92": "CR15TriggerCRWin10",
    "4af215b19b297c34": "CR15NetExplosionCRWin10",
    "1875febbeab23f44": "CR15FrisbeeCRWin10",
    "4e7c2e6a7ebd80e": "CSoundCRWin10",
    "ea51a0d76eb90142": "CModelCRWin10",
    "21a09c2016d8f3e6": "CParticleEffectCRWin10",
    # UMBRAL VEIL stage 3: the barrier wall actor's collision, cover, health, pool
    "f6bab7207d923478": "CPhysicsCRWin10",
    "71131e0e3b8aa17c": "CR15NetPhysicsCRWin10",
    "42d101b2307bbc16": "CR15NetDynamicCoverCRWin10",
    "bd1868f576836696": "CR15NetDamageableCRWin10",
    "c28a49e8e5639d32": "CR15NetPooledActorCRWin10",
}
#: type folder -> name, copied whole (not stored per level).
WHOLE_FOLDERS = {
    "2d90ee7bd8175ec2": "CR15NetMagazinePouchCRWin10",
}
#: Actors whose every table entry is collected (barrier wall, to clone as the smoke wall).
ACTOR_SCAN = [0x3D8B8CA4D5292926]

#: Level loaded before every map; holds the player actor.
GLOBAL_LEVEL = "3f9915d3001dc28e"
#: Tac mod scripts: barrier, sensor, wraith, heal, and the trigger/charge script they call.
TACMOD_SCRIPTS = ["b87ba2039b049d5e", "0e1975416e8dcf7a", "0e1971566197d460",
                  "6a0f689e5b91c666", "4b65d1b009973281"]

#: Component names the DOT's scripts look for but cannot find on it (server log).
COMPONENT_FINDS = ["51b9f7653ecac7cb", "84c65832f0b8b181"]

#: External functions the DOT script calls when use_remote_trigger is on.  None
#: of the scripts collected so far defines them; any script that mentions one is
#: copied in.
SEARCH = {
    0xA150B1C25E86AC18: "DOT ext fn (grab, takes the hand)",
    0x048BCC7D19348703: "DOT ext fn (grab)",
    0x048BCC7D19398C03: "DOT ext fn (deposited / exploded)",
    0x4CC1130866B48FC1: "DOT ext fn (release)",
    0xDD8165E98A3BD99E: "DOT ext fn param name",
    # Whatever sends the detonator its remote trigger.  Matched as text: the
    # scripts embed their debug info, so node type names show up verbatim.
    b"R15MAGAZINEPOUCHLASTCREATED": "uses the pouch's last-thrown magazine",
    b"R15TRIGGEREXPRESSION": "reads trigger input",
    b"delegate_ontriggered": "handles OnTriggered",
    # Tac mods: every script that reads a smoke (the next item), heal, buff or
    # point tuning key. Scripts read balance values by CSymbol64 of the full path.
    0xE0A5D4E07E125408: "smoke key duration",
    0xEB6A5949EBBF26CD: "smoke key required_charge",
    0xCF782A65BD268122: "smoke key opacity_max",
    0xCF782A65BD268934: "smoke key opacity_min",
    0x7D5019A0B00ED2E0: "smoke key enable_voxel_wall",
    0xBA97872710CBF6ED: "smoke key enable_voxel_wall_particles",
    0xD5F2D1275FE11807: "smoke key enable_thin_cube_walls",
    0xA237E866446C4227: "smoke key voxel_wall_particle_delay_time",
    0xC718F5C7B6F5E7EC: "smoke key voxel_wall_particle_play_speed",
    0x65D21C5794D7C5C9: "smoke key voxel_wall_particle_scale",
    0x942C4299FE1C5714: "smoke key voxel_wall_particle_scale_per_effect",
    0xCCF1F958DA26026B: "smoke key enable_debug_voxels",
    0x16AA5ECD68827C78: "smoke key voxel_wall_extra_start_dist_z",
    0x494744EEE7CD09B5: "smoke key voxel_wall_velocity",
    0x3CCEE454E59755D0: "smoke key voxel_wall_accel",
    0x48AF46257140459E: "smoke key voxel_wall_grid_size_x",
    0x48AF46257140459F: "smoke key voxel_wall_grid_size_y",
    0x48AF46257140459C: "smoke key voxel_wall_grid_size_z",
    0xB8CE4EC92B987478: "smoke key voxel_wall_cell_size_x",
    0xB8CE4EC92B987479: "smoke key voxel_wall_cell_size_y",
    0xB8CE4EC92B98747A: "smoke key voxel_wall_cell_size_z",
    0x562823130AF1A1C2: "smoke key voxel_wall_radius_max",
    0xB5E61C4B2FB31C7F: "smoke key voxel_wall_intro_fade_time",
    0xD2D522BAC5CFCCD2: "smoke key voxel_wall_intro_fade_dist_start",
    0x4F0176CD1E7B6AA5: "smoke key enable_drone_mode",
    0x59C5806668F45B87: "smoke key enable_drone_hand_follow",
    0xE3BBD89198448F88: "smoke key drone_suction_dist",
    0x612D0F9E9B5926A4: "smoke key suction_palm_x_offset",
    0x632D0F9E9B5926A4: "smoke key suction_palm_z_offset",
    0xAEBDF6CB3AFAB3A8: "smoke key accel_amount",
    0x6B5BDAF38DC11280: "smoke key follow_left_hand",
    0x60C8493DC433CB7D: "smoke key do_electrocuter_mode",
    0x127B685EDAAC6259: "heal key required_charge",
    0xDD8CD57B551E67B5: "heal key primeable",
    0x73FEC7CB04EC185F: "heal key cancellable",
    0x58180B6FA3A5209C: "heal key cancel_buffer",
    0xFF018C3FC0E229AE: "heal key activate_while_stunned",
    0xD3CF9A4313DDFCFD: "heal key unique_healing_only",
    0x504604720DB4493E: "heal key heal_amt",
    0x5467C631C5C04CF6: "heal key heal_duration",
    0x129F9D08D35E8A47: "heal key heal_radius",
    0x5B7E4C829753DCD1: "heal key cap_healing",
    0xD18485051396EC5F: "heal key max_healing",
    0x0EC007F1EB9C6E21: "heal key scale_healing",
    0x7EE3249A18B5C786: "heal key min_heal_mult",
    0xD27E8CFDAFCFB5C2: "heal key time_to_max_heal",
    0x2F7DF6C982C7E34C: "heal key self_heal_mult",
    0x66F2F92DE13128AF: "heal key disable_weapons",
    0xAC2EF020F6009E18: "heal key can_interrupt",
    0xB63A88F5022867BA: "heal key raycast_head_to_head",
    0xB63A88F5082262A7: "heal key raycast_head_to_body",
    0x6275F7F360D5455C: "heal key raycast_body_to_head",
    0x6275F7F36ADF4041: "heal key raycast_body_to_body",
    0x556516F2FADF93ED: "buff key required_charge",
    0xF7D711639F2E4460: "buff key dr",
    0x22421E89E4B1D0F6: "buff key dr_duration",
    0x69A8F7F8890378B3: "buff key conn_time",
    0x586F9F6B841B5549: "buff key activate_on_release",
    0x9BF7A1A11645258D: "buff key heal_amt_on_success",
    0xA3F28203500CBB18: "buff key len",
    0xC49A0319C287C40D: "buff key init_angle",
    0x640AB2E8AF4F059F: "buff key conn_angle",
    0x9E47EDB455E35404: "buff key do_rez_buff",
    0xFDD646C844D70277: "point key radius",
    0x9D10FF0A22272176: "point key charge_required",
    0xCD3C2BE1F5B2600B: "point key charge_up_time",
    0x608FA57E4B219FE2: "point key stun_duration",
}

SCRIPTS_TYPE = "6eace9f64204fd0"         # StreamingScriptWin10: the compiled DLL
SCRIPT_RESOURCE_TYPE = "991421b41de58370"  # CScriptResourceWin10: what the level loads first
SCRIPTS = {
    "97d0806e6ea89130": "mp_combat_grenade_dot",
    "190ed14fe3da5ed1": "det",
    "190ed14fe6c74dd3": "shared magazine script",
    "97d0806e6ead8c27": "mp_combat_grenade_arc",
    "190ed14ff6dc4ad8": "mp_combat_grenade_stun",
    "cad33e1bc81ffbee": "mp_combat_grenade_burst",
    "9398a165c004a9c0": "mp_combat_grenade_translocator",
    "3a678375df604b4f": "script on the only R15Trigger actor (26b939fcac9fbff8)",
    "b87ba2039b049d5e": "mp_combat_ability_barrier",
    "e1975416e8dcf7a": "mp_combat_ability_sensor",     # extract names drop leading zeros
    "e1971566197d460": "mp_combat_ability_wraith",
    "6a0f689e5b91c666": "heal tac mod (reads ability_properties|heal|*)",
    "ac4e9374a146d3a4": "barrier wall actor script (R15NetDynamicCover)",
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


def search_scripts(folder: str) -> list[tuple[str, list]]:
    """Every script asset in `folder` holding one of the SEARCH hashes or strings."""
    needles = {k: k if isinstance(k, bytes) else struct.pack("<Q", k) for k in SEARCH}
    found = []
    for asset in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        blob = open(os.path.join(folder, asset), "rb").read()
        hits = [h for h, n in needles.items() if n in blob]
        if hits:
            found.append((asset, hits))
    return found


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
    # Merge whatever was pushed meanwhile, so the push is a fast-forward.
    r = git("pull", "--no-rebase", "--no-edit", "origin", branch)
    if r.returncode:
        print(r.stdout + r.stderr)
        print("pull failed; resolve it, then run `git push` yourself")
        return 1
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

    for type_hash, name in LEVEL_TABLES.items():
        for level in LEVELS:
            c.copy(os.path.join(extract, type_hash, level), f"{type_hash}/{level}", name)
    c.copy(os.path.join(extract, "d99f6bbd8009c92c", GLOBAL_LEVEL),
           f"d99f6bbd8009c92c/{GLOBAL_LEVEL}", "CScriptCRWin10 (global level)")
    for type_hash, name in WHOLE_FOLDERS.items():
        folder = os.path.join(extract, type_hash)
        assets = sorted(os.listdir(folder)) if os.path.isdir(folder) else []
        if not assets:
            c.missing.append(f"{type_hash}/*  ({name})")
        for asset in assets:
            c.copy(os.path.join(folder, asset), f"{type_hash}/{asset}", name)

    for asset, name in SCRIPTS.items():
        c.copy(os.path.join(extract, SCRIPTS_TYPE, asset), f"{SCRIPTS_TYPE}/{asset}", name)
        c.copy(os.path.join(extract, SCRIPT_RESOURCE_TYPE, asset),
               f"{SCRIPT_RESOURCE_TYPE}/{asset}", name + " (CScriptResource)")

    # Every component the DOT and the other ordnance own, across all tables, and
    # where the components the DOT scripts cannot find live on other actors.
    if not args.dry_run:
        os.makedirs(OUT, exist_ok=True)
        inv = os.path.join(ROOT, "tools", "actor_components.py")
        subprocess.run([sys.executable, inv, "--src", extract, "--out", os.path.join(OUT, "components.txt"),
                        "--find", *COMPONENT_FINDS, "--scripts", *TACMOD_SCRIPTS],
                       stdout=subprocess.DEVNULL)
        c.copied.append("components.txt  (component inventory per ordnance actor)")
        # The player, and so the tac mod scripts, live in the global level.
        subprocess.run([sys.executable, inv, "--src", extract, "--level", GLOBAL_LEVEL,
                        "--out", os.path.join(OUT, "components_global.txt"),
                        "--scripts", *TACMOD_SCRIPTS], stdout=subprocess.DEVNULL)
        c.copied.append("components_global.txt  (actors running tac mod scripts, global level)")

    # Every per-level table that mentions one of the ACTOR_SCAN actors, so an
    # actor can be cloned completely (UMBRAL VEIL's smoke wall from the barrier wall).
    scan = []
    needles = [struct.pack("<Q", a) for a in ACTOR_SCAN]
    for t in sorted(os.listdir(extract)) if os.path.isdir(extract) else []:
        if t == SCRIPTS_TYPE:
            continue
        for level in LEVELS:
            path = os.path.join(extract, t, level)
            if os.path.isfile(path) and os.path.getsize(path) < 8 * 1024 * 1024:
                blob = open(path, "rb").read()
                if any(n in blob for n in needles):
                    scan.append(f"{t}/{level}")
                    c.copy(path, f"{t}/{level}", "mentions a scanned actor")
    if not args.dry_run:
        os.makedirs(OUT, exist_ok=True)
        with open(os.path.join(OUT, "actor_scan.txt"), "w", newline="\n") as fh:
            fh.write("\n".join(scan) + "\n")
    c.copied.append(f"actor_scan.txt  ({len(scan)} tables mention the scanned actors)")

    found = search_scripts(os.path.join(extract, SCRIPTS_TYPE))
    report = [f"{asset}  {', '.join(sorted(set(SEARCH[h] for h in hits)))}" for asset, hits in found]
    for asset, _ in found:
        if asset not in SCRIPTS:
            c.copy(os.path.join(extract, SCRIPTS_TYPE, asset), f"{SCRIPTS_TYPE}/{asset}", "matches search")
    if not args.dry_run:
        os.makedirs(OUT, exist_ok=True)
        with open(os.path.join(OUT, "search.txt"), "w", newline="\n") as fh:
            fh.write("\n".join(report or ["no script mentions any searched hash"]) + "\n")
    c.copied.append(f"search.txt  ({len(found)} script(s) matched)")

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
