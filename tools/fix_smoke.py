"""UMBRAL VEIL (the cut `smoke` tac mod), stage 1: register it and prove the plumbing.

No script among the 567 reads any `ability_properties|smoke|*` key and no smoke
wall actor exists, so the tac mod has to be built. How tac mods work (from the
player's scripts in the global level, 3f9915d3001dc28e):

* every player actor runs all four tac mod scripts (barrier b87ba2039b049d5e,
  sensor 0e1975416e8dcf7a, heal 6a0f689e5b91c666, wraith 0e1971566197d460) plus
  a controller, 4b65d1b009973281
* the controller has one EXTERNALFUNCTION node per tac mod, calling that
  script's enable function (3efff939e87f2683) with a flag param
  (43e1ed75065c0148) = "equipped tac mod == <name>"; for the barrier that is
  node 5e2732a4, flag expression_5e2732a4_params_0_flagvalue, "== shield"
* `Activate` (37ee801e3ffe9063, exported by each tac mod script) is called by
  the engine; the enabled script acts on it. The barrier script then creates
  the pooled wall actor 3d8b8ca4d5292926.

Stage 1 answers the open question cheaply: does the engine's ability system
(charge, input, Activate) handle a fifth tac mod name? It

* registers `smoke` in gear_table.tacmods as UMBRAL VEIL (its tuning,
  required_charge 37 etc., is already in ability_properties.smoke), and
* patches the barrier's flag expression in the controller to
  "== shield or == smoke", so equipping UMBRAL VEIL enables the barrier script.

Expected in game: UMBRAL VEIL can be equipped, charges, and on use spawns an
Energy Barrier. Then stage 2 gives it its own script and smoke wall actor.

The flag expression's leading string-copy loop only fills an unused stack
buffer, so the new compare goes there. Low 32 bits of the ability symbols are
unique among all seven names (heal 32761fbc, sensor 1430080c, shield 13260b1a,
wraith 1b2a1316, smoke d4804fb5, buff 386618b6, point d6864aa4).

    python tools/fix_smoke.py --base <dir with 607d858c90268f9a/> --src <extract root> --out <dir>
"""

from __future__ import annotations

import argparse
import os
import struct
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from fix_drone import EQUIPMENT, load, save
from fix_dot_trigger import rva_to_raw

SCRIPTS = "6eace9f64204fd0"            # CSymbol64("StreamingScriptWin10")
CONTROLLER = "4b65d1b009973281"
SMOKE_GEAR = {"name": "smoke", "display_name": "UMBRAL VEIL"}

SHIELD = 0x41D2D43513260B1A            # CSymbol64("shield")
SMOKE = 0xE32DC7C9D4804FB5             # CSymbol64("smoke")
FLAG_EXPR_RVA = 0x20CA4                # expression_5e2732a4_params_0_flagvalue + 4
FLAG_EXPR_OLD = bytes.fromhex(
    "33d24c8d0d5c6900008bc290460fb604084584c0740affc248ffc083fa3f72ec8bc2c6440410"
    "00488b01488b486848b81a0b261335d4d241483981f00000000f94c04883c458c3")
FLAG_EXPR_NEW = (bytes.fromhex("488b01 488b4868 8b81f0000000")          # eax = equipped ability
                 + b"\x3d" + struct.pack("<I", SHIELD & 0xFFFFFFFF)   # cmp eax, shield
                 + bytes.fromhex("7405")                              # je -> sete (ZF=1)
                 + b"\x3d" + struct.pack("<I", SMOKE & 0xFFFFFFFF)    # cmp eax, smoke
                 + bytes.fromhex("0f94c0 4883c458 c3"))               # sete al; add rsp,58; ret
FLAG_EXPR_NEW += b"\xcc" * (len(FLAG_EXPR_OLD) - len(FLAG_EXPR_NEW))


def patch_controller(asset: bytes) -> bytes:
    mz = asset.find(b"MZ")
    at = mz + rva_to_raw(asset[mz:], FLAG_EXPR_RVA)
    n = len(FLAG_EXPR_OLD)
    if asset[at:at + n] == FLAG_EXPR_NEW:
        return asset
    if asset[at:at + n] != FLAG_EXPR_OLD:
        raise ValueError("unexpected bytes in the barrier flag expression: wrong controller build")
    return asset[:at] + FLAG_EXPR_NEW + asset[at + n:]


def main(argv) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", required=True, help="dir holding the live 607d858c90268f9a/ JSON")
    ap.add_argument("--src", required=True, help="extract root (for the controller script)")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv[1:])

    eq_path, equipment = load(args.base, EQUIPMENT)
    tacmods = equipment["gear_table"]["tacmods"]
    if not any(t["name"] == "smoke" for t in tacmods):
        tacmods.append(dict(SMOKE_GEAR))
    print(save(args.out, EQUIPMENT, eq_path, equipment))
    print("tacmods:", [t["name"] for t in tacmods])

    asset = open(os.path.join(args.src, SCRIPTS, CONTROLLER), "rb").read()
    os.makedirs(os.path.join(args.out, SCRIPTS), exist_ok=True)
    open(os.path.join(args.out, SCRIPTS, CONTROLLER), "wb").write(patch_controller(asset))
    print(f"{SCRIPTS}/{CONTROLLER}: barrier enabled for shield or smoke (stage 1 test)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
