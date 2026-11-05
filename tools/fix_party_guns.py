"""CONFETTI GUN, BUBBLE GUN, MONEY GUN: party guns on the Pulsar (Collin Harris' end-of-round FX idea).

The data half; PowerBoost.dll ("PARTY GUNS") does the rest.

1. `confetti_gun`, `bubble_gun`, `money_gun` go into gear_table.weapons (before MEDIGUN, which
   VeilNet trims as the list's last entry), so the loadout terminal lists them. Like MEDIGUN they
   have no gun actors of their own: PowerBoost makes the gun enable manager read them as
   "assault", so the player holds the Pulsar.
2. The shot: PowerBoost swaps the Pulsar's muzzle flash for the party effect. For now that is the
   game's own round-win confetti (pfx_test_jasonw_roomscale_confetti, orange, and _blue; Collin's
   confetti texture), which only the Combat levels list. Every level with a loadout terminal gets
   those resources in its archive (CArchiveResource), copied from Dyson's.

    python tools/fix_party_guns.py --base <stage> --src <extract root> --out <dir>
"""

from __future__ import annotations

import argparse
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from fix_drone import EQUIPMENT, load, save  # noqa: E402
from fix_rules_netsettings import ARCHIVE, read, read_archive, write, write_archive  # noqa: E402

#: UNFINISHED (user, 2026-11-05): the party guns stay out of gear_table.weapons, so no loadout
#: terminal lists them and nothing hands them out. The rest (PowerBoost hooks, the Pulsar script
#: caves, the confetti) stays built and is inert without them. True: back on the terminals.
PARTY_GUNS_SHOWN = False
PARTY_GEAR = [{"name": "confetti_gun", "display_name": "CONFETTI GUN"},
              {"name": "bubble_gun", "display_name": "BUBBLE GUN"},
              {"name": "money_gun", "display_name": "MONEY GUN"}]
#: the level whose archive lists the confetti, and what it lists for it
SOURCE_LEVEL = "43e2da7914642604"            # mpl_combat_dyson
CONFETTI = {0x1432F4F2B0F840DF,              # pfx_test_jasonw_roomscale_confetti (orange)
            0x7676880776A1F757,              # pfx_test_jasonw_roomscale_confetti_blue
            0xC296F756A92F4CCC,              # fx_test_collin_weapon_custom_textures_confetti_2x2_clr
            0xB3C7D865E9B726DF,              # ..._roomscale_confetti_radpfx__generated_curve_texture
            0x20E84447E2AB0B65}              # ..._roomscale_confetti_blue_radpfx__generated_curve_texture
#: every level with a loadout terminal: the Combat lobby and the four maps
LEVELS = ("cb9977f7fc2b4526", "43e2da7914642604", "42670f2bed45703c", "df5ca7b7dfa383d4", "43e2da7a0c623a19")


def add_confetti(src: str, out: str) -> list:
    dyson = read_archive(read(src, out, ARCHIVE, SOURCE_LEVEL))
    wanted = [p for p in dyson[0] if p[1] in CONFETTI]
    if len(wanted) != len(CONFETTI):
        raise SystemExit(f"Dyson's archive lists {len(wanted)} of the {len(CONFETTI)} confetti resources")
    done = []
    for level in LEVELS:
        b = read(src, out, ARCHIVE, level)
        pairs, types, tail = read_archive(b)
        if write_archive(pairs, types, tail) != b:
            raise SystemExit(f"{level}: the archive does not round-trip: not editing it")
        add = [p for p in wanted if p not in pairs]
        if not add:
            done.append(f"{level}: has them")
            continue
        for t in {p[0] for p in add} - {t[0] for t in types}:
            types += [x for x in dyson[1] if x[0] == t]
        order = {t[0]: k for k, t in enumerate(types)}
        pairs += add
        pairs.sort(key=lambda p: order[p[0]])
        write(out, ARCHIVE, level, write_archive(pairs, types, tail))
        done.append(f"{level}: +{len(add)}")
    return done


def main(argv) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", required=True, help="dir holding the live 607d858c90268f9a/ JSON")
    ap.add_argument("--src", required=True, help="extract root")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv[1:])

    eq_path, equipment = load(args.base, EQUIPMENT)
    weapons = equipment["gear_table"]["weapons"]
    names = [w["name"] for w in weapons]
    at = names.index("medigun") if "medigun" in names else len(weapons)
    for g in reversed(PARTY_GEAR):
        if PARTY_GUNS_SHOWN and g["name"] not in names:
            weapons.insert(at, dict(g))
        if not PARTY_GUNS_SHOWN and g["name"] in names:
            weapons.pop(names.index(g["name"]))
            names = [w["name"] for w in weapons]
    if not PARTY_GUNS_SHOWN:
        print("party guns: UNFINISHED, hidden (fix_party_guns.PARTY_GUNS_SHOWN)")
    print(save(args.out, EQUIPMENT, eq_path, equipment))
    print("weapons:", [w["name"] for w in weapons])
    print("confetti in the level archives:", "; ".join(add_confetti(args.src, args.out)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
