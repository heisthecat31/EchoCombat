"""Stop the DOT FIELD welding to the first thing it touches and yanking to 0,0,0.

`CR15NetMagazineCR` record +0x18 bit 0x10 makes `CR15NetMagazineCS` register a
native stick-on-contact listener that welds the magazine through its
`CR15RigidAttachConstraint`. The DOT magazine `0c00c9ac34bd2832` is the only
ordnance with the bit set (and the only one with a rigid-attach component), and
its attach record is left unconfigured (+0x18 = 0, +0x20 = 0; the working wall
shield `3d8b8ca4d5292926` has 0x10 / 1). So the field welds to the hand on grab,
and once released the weld pulls it toward world 0,0,0 -- the -156 m/s velocity
in the client log -- snagging on geometry on the way.

Clearing the bit leaves the DOT handled like every other ordnance: the DOT
script's own impact activation (`activate_on_collision`) and its
R15EnableDampenerNode freeze the field where it lands. The rigid-attach record
is left as shipped (inert without the bit). Its sibling, the parented
constraint, pulls toward 0,0,0 the same way and is switched off by
`fix_dot_dampener.py`; this fix alone, with that constraint on, still left the
field "latching to a wall" in game.

    python tools/fix_dot_stick.py --src <extract root> --out <dir>
"""

from __future__ import annotations

import argparse
import os
import struct
import sys

MAGAZINE_CR = "5b723f040a3778ee"   # CSymbol64("CR15NetMagazineCRWin10")
LEVELS = {
    "42670f2bed45703c": "mpl_combat_combustion",
    "43e2da7914642604": "mpl_combat_dyson",
    "43e2da7a0c623a19": "mpl_combat_gauss",
    "cb9977f7fc2b4526": "mpl_lobby_b_combat",
    "df5ca7b7dfa383d4": "mpl_combat_fission",
}
DOT_ACTOR = 0x0C00C9AC34BD2832
STICK_BIT = 0x10
HDR = 0x38
STRIDE = 40


def patch(blob: bytes) -> bytes:
    size, count = struct.unpack_from("<Q", blob, 0x08)[0], struct.unpack_from("<Q", blob, 0x28)[0]
    if size != count * STRIDE or len(blob) != HDR + size:
        raise ValueError("unexpected CR15NetMagazineCR framing")
    out = bytearray(blob)
    hits = 0
    for i in range(count):
        rec = HDR + i * STRIDE
        if struct.unpack_from("<Q", out, rec + 8)[0] == DOT_ACTOR:
            flags = struct.unpack_from("<I", out, rec + 0x18)[0]
            struct.pack_into("<I", out, rec + 0x18, flags & ~STICK_BIT)
            hits += 1
    if hits != 1:
        raise ValueError(f"expected one DOT magazine record, found {hits}")
    return bytes(out)


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--src", required=True, help="extract root holding 5b723f040a3778ee/")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv[1:])
    os.makedirs(os.path.join(args.out, MAGAZINE_CR), exist_ok=True)
    for level, name in LEVELS.items():
        blob = open(os.path.join(args.src, MAGAZINE_CR, level), "rb").read()
        open(os.path.join(args.out, MAGAZINE_CR, level), "wb").write(patch(blob))
        print(f"{name}: DOT stick-on-contact bit cleared")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
