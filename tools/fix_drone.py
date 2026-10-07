"""Make the cut DRONE ordnance selectable and give it working data.

The drone is all there in the combat levels -- a magazine actor
(`10e40287a9bf5a13`), its `CR15NetAutoTargetCR` component, the pooled bullet
actor (`a8f84e7dd40b806e`) and its own script (`mp_combat_ordnance_drone`,
which reads all six `grenade_properties|drone|*` keys) -- but it was never put
in the gear registry, so nothing that resolves an ordnance by name knows it.
This adds the three data pieces it lacks:

1. `gear_table.ordnances` entry, appended so the shipped items keep their
   indices (the registry builds `gOrdnanceNameLookup`).
2. `damage_table.drone`, so its bullets have a per-location multiplier set.
3. A real `cooldown` (the cut data has 1 s; every shipped ordnance is 25-35).

    python tools/fix_drone.py --base <dir with 607d858c90268f9a/> --out <dir>

`--base` must hold the two `CJsonResourceWin10` blobs (mp_equipment and
mp_weapon_settings) that are live now, so other edits carry through.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from json_resource import build, minify, read

JSON_TYPE = "607d858c90268f9a"         # CSymbol64("CJsonResourceWin10")
EQUIPMENT = "f8d40525c88885d8"         # CSymbol64("mp_equipment")
WEAPON_SETTINGS = "11a8523ed4724ca7"   # CSymbol64("mp_weapon_settings")

DRONE_GEAR = {"name": "drone", "display_name": "DRONE"}
#: Same spread as the shipped bullet weapons: full body, light on barriers.
DRONE_DAMAGE = {"head": 1, "arm": 1, "leg": 1, "torso": 1, "ordnance": 1,
                "barrier": 1, "ssi": 1}
DRONE_COOLDOWN = 30


def load(base: str, name: str):
    path, body = read(open(os.path.join(base, JSON_TYPE, name), "rb").read())
    return path, json.loads(body.decode("utf-8"))


def save(out: str, name: str, path: str, obj) -> str:
    os.makedirs(os.path.join(out, JSON_TYPE), exist_ok=True)
    dest = os.path.join(out, JSON_TYPE, name)
    with open(dest, "wb") as f:
        f.write(build(path, minify(obj)))
    return dest


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--cooldown", type=float, default=DRONE_COOLDOWN)
    args = ap.parse_args(argv[1:])

    eq_path, equipment = load(args.base, EQUIPMENT)
    ws_path, settings = load(args.base, WEAPON_SETTINGS)

    ordnances = equipment["gear_table"]["ordnances"]
    if not any(o["name"] == "drone" for o in ordnances):
        ordnances.append(dict(DRONE_GEAR))
    settings["damage_table"].setdefault("drone", dict(DRONE_DAMAGE))
    drone = settings["grenade_properties"]["drone"]
    drone["cooldown"] = args.cooldown

    print(save(args.out, EQUIPMENT, eq_path, equipment))
    print(save(args.out, WEAPON_SETTINGS, ws_path, settings))
    print("ordnances:", [o["name"] for o in ordnances])
    print("drone:", json.dumps(drone))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
