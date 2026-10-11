"""Give the DRONE health, so it can be shot down.

Each combat level's CR15NetDamageableCRWin10 table (DAMAGEABLE_CR) has a record per
damageable actor: component id, actor id, then its settings; the float at HEALTH_OFFSET is
its health. Every ordnance's is 9999 (they never run out of it; the arc mine dies from its
own script on damage), the drone's too. This sets the drone's to
grenade_properties.drone.health (config/mp_weapon_settings.json).

    python tools/fix_drone_health.py --src <extract root> --out <stage>
"""

from __future__ import annotations

import argparse
import os
import struct
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import cr_table as ct                                         # noqa: E402
from echocombat_config import section                         # noqa: E402

DAMAGEABLE_CR = "bd1868f576836696"     # CSymbol64("CR15NetDamageableCRWin10")
LEVELS = {
    "42670f2bed45703c": "mpl_combat_combustion",
    "43e2da7914642604": "mpl_combat_dyson",
    "43e2da7a0c623a19": "mpl_combat_gauss",
    "cb9977f7fc2b4526": "mpl_lobby_b_combat",
    "df5ca7b7dfa383d4": "mpl_combat_fission",
}
DRONE_ACTOR = 0x10E40287A9BF5A13
ROOT = 0x38
HEALTH_OFFSET = 0x24
STOCK_HEALTH = 9999.0


def health() -> float:
    return float(section("grenade_properties", "drone").get("health", 60))


def patch(blob: bytes, hp: float) -> tuple[bytes, bool]:
    root = ct.parse(blob, ROOT)
    mine = [e for e in root.arrays[0].elems if struct.unpack_from("<Q", e.raw, 8)[0] == DRONE_ACTOR]
    if len(mine) != 1:
        raise ValueError(f"{len(mine)} damageable records for the drone, expected 1")
    old = struct.unpack_from("<f", mine[0].raw, HEALTH_OFFSET)[0]
    if old == hp:
        return blob, False
    if old != STOCK_HEALTH:
        raise ValueError(f"the drone's health is {old}, not the stock {STOCK_HEALTH}: unexpected table")
    struct.pack_into("<f", mine[0].raw, HEALTH_OFFSET, hp)
    return ct.build(root), True


def main(argv) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--src", required=True, help="extract root (or build/source)")
    ap.add_argument("--out", required=True, help="stage")
    args = ap.parse_args(argv[1:])
    hp = health()
    for level, name in LEVELS.items():
        staged = os.path.join(args.out, DAMAGEABLE_CR, level)
        src = staged if os.path.exists(staged) else os.path.join(args.src, DAMAGEABLE_CR, level)
        data, changed = patch(open(src, "rb").read(), hp)
        os.makedirs(os.path.dirname(staged), exist_ok=True)
        open(staged, "wb").write(data)
        print(f"{name}: the drone's health is {hp:g}" + ("" if changed else " (already)"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
