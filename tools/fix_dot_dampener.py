"""Stop the DOT FIELD freezing, snapping to the world origin and dragging its owner.

The DOT magazine actor `0c00c9ac34bd2832` carries level component data the
balance JSON cannot reach (which is why the activate_on_collision /
use_remote_trigger edits did nothing):

* `CR15DampenerCR`: enabled from spawn (+0x18 = 1) with damping 10000. The body
  cannot move, so it will not follow the hand. The fix starts it OFF, but that
  alone is not enough: the shared magazine script (190ed14fe6c74dd3, node
  09563fe2) enables the dampener as soon as a magazine is Unstable and not held,
  i.e. on every throw. That is how the arc slows to a stop (damping 25). With
  10000 the DOT stopped dead where it was let go, so the damping is lowered
  too: `--damping`, default 25, the arc's in-flight value (higher = stops sooner).
* `CR15ParentedConstraintCR`: no longer edited here -- `fix_dot_constraints.py`
  removes the DOT's record outright, together with its rigid attach.

* `CTransformCR`: every DOT node carries a stray local translation of
  (-3.01, 0, 1.99) at +0x30 -- the prefab was saved off-origin. Every other
  ordnance's nodes (the translocator's, whose tree has the same shape) are at 0.
  Children inherit it, so body, model and grab point end up metres apart and the
  field jumps toward the origin when grabbed. Zeroed (w stays 1).

Records bind to their actor by nodeid (+0x08) and none of these tables has a heap.

    python tools/fix_dot_dampener.py --src <extract root> --out <dir>
"""

from __future__ import annotations

import argparse
import os
import struct
import sys

DAMPENER_CR = "2b292830e51c4fd2"   # CSymbol64("CR15DampenerCRWin10")
TRANSFORM_CR = "92abd3e1432bf5e8"  # CSymbol64("CTransformCRWin10")
LEVELS = {
    "42670f2bed45703c": "mpl_combat_combustion",
    "43e2da7914642604": "mpl_combat_dyson",
    "43e2da7a0c623a19": "mpl_combat_gauss",
    "cb9977f7fc2b4526": "mpl_lobby_b_combat",
    "df5ca7b7dfa383d4": "mpl_combat_fission",
}
DOT_ACTOR = 0x0C00C9AC34BD2832
HDR = 0x38


def edit(blob: bytes, fn, expect_one=True) -> bytes:
    size, count = struct.unpack_from("<Q", blob, 0x08)[0], struct.unpack_from("<Q", blob, 0x28)[0]
    stride = size // count
    out = bytearray(blob)
    hits = 0
    for i in range(count):
        rec = HDR + i * stride
        if struct.unpack_from("<Q", out, rec + 8)[0] == DOT_ACTOR:
            fn(out, rec)
            hits += 1
    if hits == 0 or (expect_one and hits != 1):
        raise ValueError(f"unexpected DOT record count {hits}")
    return bytes(out)


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--damping", type=float, default=25.0)
    args = ap.parse_args(argv[1:])

    def dampener(out, rec):
        struct.pack_into("<I", out, rec + 0x18, 0)                    # off at spawn
        struct.pack_into("<2f", out, rec + 0x20, args.damping, args.damping)

    def transform(out, rec):
        struct.pack_into("<3f", out, rec + 0x30, 0.0, 0.0, 0.0)       # local translation

    for t, fn, one in ((DAMPENER_CR, dampener, True), (TRANSFORM_CR, transform, False)):
        os.makedirs(os.path.join(args.out, t), exist_ok=True)
        for level, name in LEVELS.items():
            blob = open(os.path.join(args.src, t, level), "rb").read()
            open(os.path.join(args.out, t, level), "wb").write(edit(blob, fn, one))
    print("DOT damper: off at spawn, damping %g; "
          "node translations zeroed (5 levels)" % args.damping)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
