"""Audit Echo Combat's equipment registry against its balance tuning.

Echo Combat gear lives in two JSON resources that have to agree:

* `mp_equipment.json` -> `gear_table.{weapons,ordnances,tacmods}` is the
  REGISTRY.  `CR15NetProfileSymbolLookup::InitializeForEquipment` walks it to
  build `gWeaponNameLookup` / `gOrdnanceNameLookup` / `gTacModNameLookup`.
  An item that is not in this table has no symbol, so the engine answers
  `CR15NetProfileSymbolLookup doesn't recognize '%s'` and the magazine pouch
  falls back to `INVALID ORDNANCE TYPE`.

* `mp_weapon_settings.json` -> `weapon_properties` / `grenade_properties` /
  `ability_properties` is the TUNING, and `damage_table` is the per-hit-location
  multiplier set used for damage and kill attribution.

An item with tuning but no registry entry is cut/unfinished content: it can
still be spawned, but nothing that resolves it by name works.  That is the
state `dot` and `drone` are in.

    python tools/audit_gear.py [extract_dir]
"""

from __future__ import annotations

import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from json_resource import read

DEFAULT_EXTRACT = r"H:\pcvr-extracted\607d858c90268f9a"

EQUIPMENT = "f8d40525c88885d8"        # CSymbol64("mp_equipment")
WEAPON_SETTINGS = "11a8523ed4724ca7"  # CSymbol64("mp_weapon_settings")

#: gear_table section  ->  the tuning section that should back it.
SECTIONS = [
    ("weapons", "weapon_properties"),
    ("ordnances", "grenade_properties"),
    ("tacmods", "ability_properties"),
]

#: Sub-damage entries that are damage sources, not selectable gear.  They
#: belong in a weapon's `aliases` list, never in `gear_table` as their own item.
AOE_SUFFIXES = ("_aoe", "_cone")


def load(extract_dir: str, name: str):
    blob = open(os.path.join(extract_dir, name), "rb").read()
    _path, body = read(blob)
    return json.loads(body.decode("utf-8"))


def main(argv: list[str]) -> int:
    extract = argv[1] if len(argv) > 1 else DEFAULT_EXTRACT
    gear = load(extract, EQUIPMENT)["gear_table"]
    settings = load(extract, WEAPON_SETTINGS)
    damage = settings["damage_table"]

    problems = 0
    for section, tuning_key in SECTIONS:
        registered = [i["name"] for i in gear[section]]
        aliased = {a for i in gear[section] for a in i.get("aliases", [])}
        tuned = list(settings[tuning_key])
        selectable = [t for t in tuned if not t.endswith(AOE_SUFFIXES)]
        sub = [t for t in tuned if t.endswith(AOE_SUFFIXES)]

        print(f"== {section}")
        print(f"   registered in gear_table : {len(registered):2d}  "
              f"{', '.join(registered)}")
        print(f"   tuned in {tuning_key:<19}: {len(selectable):2d}  "
              f"{', '.join(selectable)}")
        if sub:
            print(f"   sub-damage entries        : {len(sub):2d}  "
                  f"{', '.join(sub)}")

        unregistered = [t for t in selectable if t not in registered]
        if unregistered:
            problems += len(unregistered)
            print(f"   !! TUNED BUT NOT REGISTERED -> not in the name lookup:")
            for item in unregistered:
                bits = []
                if item not in damage and _deals_damage(settings[tuning_key][item]):
                    bits.append("no damage_table entry")
                if tuning_key == "grenade_properties" and \
                        "cooldown" not in settings[tuning_key][item]:
                    bits.append("no cooldown (grenade_properties|%s|cooldown)")
                note = f"   [{'; '.join(bits)}]" if bits else ""
                print(f"        - {item}{note}")

        orphan_alias = [a for a in aliased if a not in tuned and a not in damage]
        if orphan_alias:
            print(f"   ?  aliases with no tuning or damage entry: "
                  f"{', '.join(sorted(orphan_alias))}")
        print()

    print(f"{problems} item(s) have tuning data but no registry entry.")
    return 1 if problems else 0


def _deals_damage(props: dict) -> bool:
    return any(k in props for k in
               ("damage_per_tick", "bullet_damage", "projectile_damage",
                "explosion_damage", "volume_damage", "projectile_damage_max"))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
