"""Give the DOT FIELD the frisbee (thrown-flight) component every other ordnance has.

The shared magazine script (190ed14fe6c74dd3, node e8657155) enables the
magazine's `CR15FrisbeeCR` component on every throw. The arc, detonator, stun
and burst magazines all carry one (component 81b1b8f03258c684, otherwise
empty); the DOT does not. That shows up on the server as

    ~ Scriptnode can't find actor/component ~  ... Target Component: 0x84C65832F0B8B181

and the DOT flies without the frisbee behaviour the other ordnance have. This
appends a copy of the stun's record with the DOT as its actor. Records bind to
their actor by nodeid (+0x08) and the table has no heap, so only the header
counts change.

    python tools/fix_dot_frisbee.py --src <extract root> --out <dir>
"""

from __future__ import annotations

import argparse
import os
import struct
import sys

FRISBEE_CR = "1875febbeab23f44"        # CSymbol64("CR15FrisbeeCRWin10")
LEVELS = {
    "42670f2bed45703c": "mpl_combat_combustion",
    "43e2da7914642604": "mpl_combat_dyson",
    "43e2da7a0c623a19": "mpl_combat_gauss",
    "cb9977f7fc2b4526": "mpl_lobby_b_combat",
    "df5ca7b7dfa383d4": "mpl_combat_fission",
}
DOT_ACTOR = 0x0C00C9AC34BD2832
STUN_ACTOR = 0x7435764D2C648580
HDR = 0x38


def u64(blob, offset):
    return struct.unpack_from("<Q", blob, offset)[0]


def add_dot(blob: bytes) -> bytes:
    size, count = u64(blob, 0x08), u64(blob, 0x28)
    if not count or size % count or len(blob) != HDR + size or u64(blob, 0x30) != count:
        raise ValueError("unexpected CR framing (or a trailing heap)")
    stride = size // count
    records = [blob[HDR + i * stride:HDR + (i + 1) * stride] for i in range(count)]
    if any(u64(r, 8) == DOT_ACTOR for r in records):
        return blob                                   # already has one
    donor = [r for r in records if u64(r, 8) == STUN_ACTOR]
    if len(donor) != 1:
        raise ValueError("stun frisbee record not found")
    rec = bytearray(donor[0])
    struct.pack_into("<Q", rec, 8, DOT_ACTOR)
    records.append(bytes(rec))
    head = bytearray(blob[:HDR])
    struct.pack_into("<Q", head, 0x08, len(records) * stride)
    struct.pack_into("<Q", head, 0x28, len(records))
    struct.pack_into("<Q", head, 0x30, len(records))
    return bytes(head) + b"".join(records)


def main(argv) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--src", required=True, help="extract root")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv[1:])
    os.makedirs(os.path.join(args.out, FRISBEE_CR), exist_ok=True)
    for level, name in LEVELS.items():
        blob = open(os.path.join(args.src, FRISBEE_CR, level), "rb").read()
        fixed = add_dot(blob)
        open(os.path.join(args.out, FRISBEE_CR, level), "wb").write(fixed)
        print(f"{name}: frisbee records {u64(blob, 0x28)} -> {u64(fixed, 0x28)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
