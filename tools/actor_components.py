"""List every component record an actor has, across all component tables of a level.

Component tables (`C<Name>CRWin10` type folders) are per level: a 0x38-byte
header (record bytes at +0x08, record count at +0x28) then fixed-size records,
each bound to its actor by the node id at +0x08. This walks every type folder
in the extract, keeps the ones that parse that way, and reports, per actor:

* the records it owns, with the first 64 bytes of each
* every record anywhere (any actor) that mentions one of the `--find` hashes,
  e.g. the component names a script cannot find on the DOT

    python tools/actor_components.py --src <extract root> [--level <hash>]
                                     [--find 51b9f7653ecac7cb ...] [--out report.txt]
"""

from __future__ import annotations

import argparse
import os
import struct
import sys

ACTORS = {
    0x0C00C9AC34BD2832: "DOT",
    0x7435764D2C648580: "stun",
    0x0B53172E221366BD: "arc",
    0x0B53172E221671AA: "det",
    0x90EDEFF8B9B351BC: "burst",
    0x0C00C9AC34B52825: "loc",
    0x10E40287A9BF5A13: "drone",
}
DYSON = "43e2da7914642604"
HDR = 0x38


def records(blob: bytes):
    """Fixed-size records of a component table, or None if it does not parse as one."""
    if len(blob) < HDR:
        return None
    size, count = struct.unpack_from("<Q", blob, 0x08)[0], struct.unpack_from("<Q", blob, 0x28)[0]
    if not count or size % count or HDR + size > len(blob) or size // count < 16:
        return None
    stride = size // count
    return stride, [blob[HDR + i * stride:HDR + (i + 1) * stride] for i in range(count)]


def main(argv) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--src", required=True, help="extract root")
    ap.add_argument("--level", default=DYSON)
    ap.add_argument("--find", nargs="*", default=[], help="hashes to look for in any record")
    ap.add_argument("--out", help="also write the report here")
    args = ap.parse_args(argv[1:])

    finds = {int(h, 16): h for h in args.find}
    owned = {a: [] for a in ACTORS}
    mentions = []
    for t in sorted(os.listdir(args.src)):
        path = os.path.join(args.src, t, args.level)
        if not os.path.isfile(path):
            continue
        parsed = records(open(path, "rb").read())
        if not parsed:
            continue
        stride, recs = parsed
        for r in recs:
            actor = struct.unpack_from("<Q", r, 8)[0]
            if actor in owned:
                owned[actor].append((t, stride, r))
            for h, name in finds.items():
                if struct.pack("<Q", h) in r:
                    mentions.append((name, t, stride, ACTORS.get(actor, f"{actor:016x}"), r))

    lines = [f"level {args.level}"]
    for actor, name in ACTORS.items():
        lines.append(f"\n== {name} ({actor:016x}): {len(owned[actor])} records")
        for t, stride, r in owned[actor]:
            lines.append(f"  {t} stride {stride:4}  {r[:64].hex(' ', 8)}")
    for name, t, stride, actor, r in mentions:
        lines.append(f"\n-- {name} in {t} (stride {stride}) on {actor}: {r[:96].hex(' ', 8)}")
    text = "\n".join(lines) + "\n"
    print(text)
    if args.out:
        with open(args.out, "w", newline="\n") as fh:
            fh.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
