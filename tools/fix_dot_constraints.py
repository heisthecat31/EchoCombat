"""Remove the DOT FIELD's two leftover constraints so it handles like the translocator.

The DOT magazine `0c00c9ac34bd2832` is the only ordnance carrying a
`CR15RigidAttachConstraintCR` and a `CR15ParentedConstraintCR` -- copied from
the wall shield (`R15NetDynamicCover`, actor `3d8b8ca4d5292926`), whose
stick-to-wall code the magazine reuses: echovr.exe's own message for the DOT path
reads "No R15RigidAttachConstraint found on R15NetMagazine!
(CR15NetDynamicCoverCS::PhysicsImpactCB)".

The DOT's rigid-attach record was never configured (+0x18 / +0x20 are 0 where the
shield has 0x10 / 1), and `R15SocketPlug` -- the pouch socket every ordnance
plugs into -- uses a rigid attach whenever the item has one ("Could not find
R15RigidAttachConstraint component on %s required by R15SocketPlug"). Ordnance
without one (all the working ones) never get welded. With one, the DOT gets
welded and yanked: in game it latched on the first grab and floated on the next,
with a fixed -156 velocity in the client log, unchanged by the stick bit
(`fix_dot_stick.py`) or switching the parented constraint off at spawn.

Both DOT records are dropped; the shield's records are untouched, so neither
table empties. Records bind to their actor by nodeid (+0x08) and neither table
has a heap, so only the header counts change.

    python tools/fix_dot_constraints.py --src <extract root> --out <dir>
"""

from __future__ import annotations

import argparse
import os
import struct
import sys

TABLES = {
    "dde8fffc5b4d7ad4": "CR15RigidAttachConstraintCRWin10",
    "f2676c58c07bab0c": "CR15ParentedConstraintCRWin10",
}
LEVELS = {
    "42670f2bed45703c": "mpl_combat_combustion",
    "43e2da7914642604": "mpl_combat_dyson",
    "43e2da7a0c623a19": "mpl_combat_gauss",
    "cb9977f7fc2b4526": "mpl_lobby_b_combat",
    "df5ca7b7dfa383d4": "mpl_combat_fission",
}
DOT_ACTOR = 0x0C00C9AC34BD2832
HDR = 0x38


def u64(blob, offset):
    return struct.unpack_from("<Q", blob, offset)[0]


def drop_dot(blob: bytes) -> bytes:
    size, count = u64(blob, 0x08), u64(blob, 0x28)
    if not count or size % count or len(blob) != HDR + size or u64(blob, 0x30) != count:
        raise ValueError("unexpected CR framing (or a trailing heap)")
    stride = size // count
    records = [blob[HDR + i * stride:HDR + (i + 1) * stride] for i in range(count)]
    kept = [r for r in records if u64(r, 8) != DOT_ACTOR]
    if len(kept) == count:
        return blob                                   # already removed
    if len(kept) != count - 1 or not kept:
        raise ValueError("expected exactly one DOT record and at least one other")
    head = bytearray(blob[:HDR])
    struct.pack_into("<Q", head, 0x08, len(kept) * stride)
    struct.pack_into("<Q", head, 0x28, len(kept))
    struct.pack_into("<Q", head, 0x30, len(kept))
    return bytes(head) + b"".join(kept)


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--src", required=True, help="extract root")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv[1:])
    for t, tname in TABLES.items():
        os.makedirs(os.path.join(args.out, t), exist_ok=True)
        for level, name in LEVELS.items():
            blob = open(os.path.join(args.src, t, level), "rb").read()
            fixed = drop_dot(blob)
            open(os.path.join(args.out, t, level), "wb").write(fixed)
            print(f"{name} {tname}: {u64(blob, 0x28)} -> {u64(fixed, 0x28)} records")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
