"""Make the DOT field work, on top of whatever gear patch is in play.

## What the disassembly established

`mp_combat_grenade_dot` (`97d0806e6ea89130`) is a compiled DLL that queries
**exactly eight** balance keys, all of which the JSON already provides.  The
descriptors sit in `.rdata` as 16-byte `(file_symbol, key_symbol)` pairs against
`CSymbol64("mp_weapon_settings")`; every one resolves to a
`grenade_properties|dot|*` path.  So there is no missing-key fix on the data
side, and no hidden knob.

Comparing the symbol references of all six ordnance scripts shows the split of
responsibility:

* `delegate_OnTriggered` / `R15Trigger` / `R15SetTriggerHandNode` appear **only**
  in `burst` and `translocator` -- the two ordnances you hold and fire by hand.
  `arc`, `stun`, `dot` and `drone` have none of it.
* `dot` does have the grab and state machinery: `delegate_OnNetTouchGrab`,
  `delegate_OnNetTouchRelease`, `delegate_OnImpact`, `delegate_OnStateChanged`,
  `R15NetMagazineGetStateExpression` / `SetStateNode`, and the `Stable` /
  `Unstable` / `Exploding` / `Exploded` states.

That is not a broken script -- it is the normal shape.  Activation and cooldown
are **native**, in `CR15NetMagazinePouchCS`: it reads
`grenade_properties|%s|cooldown`, logs `Activating magazine %llx remotely from
user`, and drives `Setting magazine %llx to state %s`.  The script only reacts
to the state change.

## Why DOT misbehaves, and what fixes it

`activate_on_collision: true` and `use_remote_trigger: true` were both set.  The
script self-activates on the first impact, and a magazine held in the hand
collides immediately -- so it activates and sticks the instant it is grabbed,
and the remote-trigger path never gets a chance.  Clearing
`activate_on_collision` leaves remote activation (native, via the pouch) as the
only way in, which is the grab -> carry -> latch -> trigger flow.

`cooldown` was also absent, and it is the one key the pouch reads per ordnance,
so the pouch could never re-arm -- that is the "cannot be picked up again" half.

`damage_table.dot` was absent too, so `damage_per_tick` scaled by nothing.

Because the gear patch and this fix touch the same two resources, ALWAYS rebase
rather than overwrite: point `--base` at the patch tree and its changes carry
through untouched.

    python tools/fix_dot.py --base <patch_dir>                     # preview
    python tools/fix_dot.py --base <patch_dir> --deploy            # stage
    python tools/fix_dot.py --base <patch_dir> --preset impact --deploy

`--deploy` writes `<pcvr_input_folder>/<resource_type_hash>/<asset_hash>`, the
layout evrfiletools packages from, reading the path from its own
`Settings/config.json`.  `--stage <dir>` does the same into `<dir>` instead.  Every other type folder in the base tree is copied
verbatim.  Run evrfiletools afterwards; this only stages files.
"""

from __future__ import annotations

import json
import os
import shutil
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from json_resource import build, minify, read

ROOT = os.path.dirname(_HERE)

#: Pristine PC extract, used when no `--base` is given.
EXTRACT = r"H:\pcvr-extracted\607d858c90268f9a"

EQUIPMENT = "f8d40525c88885d8"        # CSymbol64("mp_equipment")
WEAPON_SETTINGS = "11a8523ed4724ca7"  # CSymbol64("mp_weapon_settings")

#: CSymbol64("CJsonResourceWin10") -- the type folder both resources live under.
JSON_RESOURCE_WIN10 = "607d858c90268f9a"

#: evrfiletools' own settings, which owns the staging paths.
TOOLS_CONFIG = ("C:/Oculus/Games/Software/Software/ready-at-dawn-echo-arena"
                "/bin/win10/Tools/Tools/Settings/config.json")

DISPLAY_NAMES = {"dot": "DOT FIELD", "drone": "DRONE"}

#: The shipped spread is arc 25, burst 30, det/stun/loc 35.  DOT is persistent
#: area denial, so it sits with burst rather than the instant-effect ordnances.
DOT_COOLDOWN = 30

#: Flat multipliers: a damage-over-time field has no headshot, and line of sight
#: is already handled by `use_occlusion`.  `barrier` at 1 means the field chews
#: through an Energy Barrier at face value -- set it to 0 if barriers should stop
#: it outright.
#: the field's reach: 2.25 m as shipped, twice that now (wanted: a higher range)
DOT_RADIUS = 4.5
DOT_DAMAGE = {"head": 1, "arm": 1, "leg": 1, "torso": 1,
              "ordnance": 1, "barrier": 1, "ssi": 1}
DRONE_DAMAGE = {"head": 1.5, "arm": 1, "leg": 0.75, "torso": 1,
                "ordnance": 1, "barrier": 0.5, "ssi": 1}

#: Activation modes to try in game.  Only these three keys differ; the script
#: reads all of them, so each is a genuinely different code path.
PRESETS = {
    # Grab, carry, latch, then trigger.  Remote activation is native, in the
    # pouch, so the script not binding `delegate_OnTriggered` does not matter.
    "trigger": {"activate_on_collision": False, "use_remote_trigger": True,
                "stick_to_geo": True},
    # Same, but without the native geo weld.  `dot` has no transform-attach
    # nodes of its own (`TransformSetParentNode` and friends are absent from it
    # while present in other ordnance scripts), so the sticking is native and
    # gated on `stick_to_geo` ALONE -- clearing `activate_on_collision` does not
    # stop it.  It welds on spawn, which means it is no longer held, which is
    # why the trigger has nothing to fire.  This preset breaks that chain.
    "trigger-nostick": {"activate_on_collision": False,
                        "use_remote_trigger": True, "stick_to_geo": False},
    # Throw-and-forget: the field arms itself where it lands.  Use this if
    # `trigger` leaves it inert, which would mean remote activation is not
    # reaching the magazine.
    "impact": {"activate_on_collision": True, "use_remote_trigger": False,
               "stick_to_geo": True},
    # As `impact` but it does not weld to geometry -- useful to tell a sticking
    # problem apart from an activation problem.
    "impact-nostick": {"activate_on_collision": True,
                       "use_remote_trigger": False, "stick_to_geo": False},
    # Exactly as shipped.  Reproduces the bug; keep it to A/B against.
    "stock": {"activate_on_collision": True, "use_remote_trigger": True,
              "stick_to_geo": True},
}
DEFAULT_PRESET = "trigger"


def pcvr_input_folder(config_path: str = TOOLS_CONFIG) -> str:
    """The `input-pcvr` staging folder, per evrfiletools' config."""
    with open(config_path, "r", encoding="utf-8") as fh:
        folder = json.load(fh).get("pcvr_input_folder")
    if not folder:
        raise RuntimeError(f"no pcvr_input_folder in {config_path}")
    return folder


def load(base_dir: str, name: str):
    path, body = read(open(os.path.join(base_dir, name), "rb").read())
    return path, json.loads(body.decode("utf-8"))


def register(gear: dict, name: str) -> bool:
    """Append `name` to gear_table.ordnances if it is not already there."""
    ordnances = gear["gear_table"]["ordnances"]
    if any(o["name"] == name for o in ordnances):
        return False
    ordnances.append({"name": name, "display_name": DISPLAY_NAMES[name]})
    return True


def _arg(argv: list[str], flag: str, default=None):
    if flag not in argv:
        return default
    i = argv.index(flag)
    if i + 1 >= len(argv):
        raise SystemExit(f"{flag} needs a value")
    return argv[i + 1]


def main(argv: list[str]) -> int:
    do_drone = "--drone" in argv
    stage_dir = _arg(argv, "--stage")
    do_deploy = "--deploy" in argv or stage_dir is not None
    base_tree = _arg(argv, "--base")
    preset = _arg(argv, "--preset", DEFAULT_PRESET)
    if preset not in PRESETS:
        raise SystemExit(f"unknown preset {preset!r}; "
                         f"choose from {', '.join(PRESETS)}")
    json_base = (os.path.join(base_tree, JSON_RESOURCE_WIN10)
                 if base_tree else EXTRACT)

    eq_path, gear = load(json_base, EQUIPMENT)
    ws_path, settings = load(json_base, WEAPON_SETTINGS)
    print(f"base:   {json_base}")
    print("        ordnances registered: "
          + ", ".join(o["name"] for o in gear["gear_table"]["ordnances"]))
    print(f"preset: {preset}")

    changes = []
    if register(gear, "dot"):
        changes.append("gear_table.ordnances += dot (DOT FIELD)")
    dot = settings["grenade_properties"]["dot"]
    if "cooldown" not in dot:
        dot["cooldown"] = DOT_COOLDOWN
        changes.append(f"grenade_properties.dot.cooldown = {DOT_COOLDOWN}")
    for key, want in PRESETS[preset].items():
        if dot.get(key) != want:
            dot[key] = want
            changes.append(f"grenade_properties.dot.{key} = "
                           f"{str(want).lower()}")
    if dot.get("radius") != DOT_RADIUS:
        dot["radius"] = DOT_RADIUS
        changes.append(f"grenade_properties.dot.radius = {DOT_RADIUS}")
    if "dot" not in settings["damage_table"]:
        settings["damage_table"]["dot"] = dict(DOT_DAMAGE)
        changes.append("damage_table.dot added")

    if do_drone:
        if register(gear, "drone"):
            changes.append("gear_table.ordnances += drone (DRONE)")
        if "drone" not in settings["damage_table"]:
            settings["damage_table"]["drone"] = dict(DRONE_DAMAGE)
            changes.append("damage_table.drone added")

    out = os.path.join(ROOT, "data", "patched")
    os.makedirs(out, exist_ok=True)
    for fname, obj in [("mp_equipment.json", gear),
                       ("mp_weapon_settings.json", settings)]:
        with open(os.path.join(out, fname), "w", encoding="utf-8",
                  newline="\n") as fh:
            json.dump(obj, fh, indent=1)
            fh.write("\n")

    print()
    for c in changes:
        print("  +", c)
    if not changes:
        print("  (already in this state)")
    print(f"\ndot -> {json.dumps(dot)}")
    print(f"{len(changes)} change(s) -> {out}")

    if do_deploy:
        root = stage_dir or pcvr_input_folder()
        staging = os.path.join(root, JSON_RESOURCE_WIN10)
        os.makedirs(staging, exist_ok=True)
        print(f"\nstaging into {root}")
        for name, path, obj in [(EQUIPMENT, eq_path, gear),
                                (WEAPON_SETTINGS, ws_path, settings)]:
            open(os.path.join(staging, name), "wb").write(
                build(path, minify(obj)))
            src = os.path.basename(path.replace(chr(92), "/"))
            print(f"  {JSON_RESOURCE_WIN10}/{name}  <- {src} (merged)")
        if base_tree:
            for type_dir in sorted(os.listdir(base_tree)):
                if type_dir == JSON_RESOURCE_WIN10:
                    continue
                src_dir = os.path.join(base_tree, type_dir)
                if not os.path.isdir(src_dir):
                    continue
                dst_dir = os.path.join(root, type_dir)
                os.makedirs(dst_dir, exist_ok=True)
                for asset in sorted(os.listdir(src_dir)):
                    shutil.copy2(os.path.join(src_dir, asset),
                                 os.path.join(dst_dir, asset))
                    print(f"  {type_dir}/{asset}  <- verbatim")
        print("\nnow run evrfiletools to build the package and manifest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
