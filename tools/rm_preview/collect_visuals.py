"""Collect everything Repair Matrix draws, for the offline preview (and POWER BOOST's look).

Starting from the visuals the heal script (mp_combat_ability_heal, 6a0f689e5b91c666)
creates -- its particle effects, models, material and light names -- this copies every
asset they lead to: an ID that names an asset in some type folder of the extract is
copied (data/extract/<type>/<asset>) and its own contents searched for more IDs, a few
levels deep. An ID that names no asset (a component's name: the bubble models, the
material they colour) is looked up in the global level's and the combat levels'
component tables instead: each table record that holds it is kept (the table is
copied) and that record's IDs are followed too.

visuals.txt lists what was found: every ID, where it was found, and what it is.

    python tools/collect_visuals.py --extract <extract root> [--out data/extract]
"""

from __future__ import annotations

import argparse
import os
import shutil
import struct
import sys

#: what the heal script names (see fix_buff.PREVIEW_GROUPS)
SEEDS = {
    0x39424707BB2DF316: "beam particle effect",
    0xBE696D7D300CBAF7: "hand particle effect",
    0x127705D644E32E78: "model (bubble/beam) A",
    0x9425FFC9D7797400: "model (bubble/beam) B",
    0xEAD4957B7D7E8A18: "light on model A",
    0xEFDB3FB0BF8B5356: "light on model B",
    0x09F1312F49418925: "model the material colours go on",
    0xCAE7EDFDAF2DCB52: "material property 1",
    0x1F7C1E4524CB3344: "material property 2",
    0xD2C1F7DAE5A4C87F: "material colour node: actor / material",
    0x64A149A1D3286EA4: "beam effect: attach component",
    0xB1FDA2A83F3DEBD1: "beam effect: attachment",
    0xDC009AA0B878FD03: "hand effect: attachment",
    0x2E84793FDA0CD43B: "transform scaled to 1",
}
GLOBAL_LEVEL = "3f9915d3001dc28e"
LEVELS = ["42670f2bed45703c", "43e2da7914642604", "43e2da7a0c623a19", "cb9977f7fc2b4526", "df5ca7b7dfa383d4"]
DEPTH = 4
MAX_FILE = 48 << 20           # skip anything bigger (a whole level's geometry, say)
MAX_TOTAL = 400 << 20
HDR = 0x38


def ids_in(blob: bytes) -> set:
    """Every 8-byte value at a 4-byte step that could be an asset ID."""
    out = set()
    for o in range(0, len(blob) - 7, 4):
        v = struct.unpack_from("<Q", blob, o)[0]
        b = blob[o:o + 8]
        if b.count(0) <= 1 and len(set(b)) >= 5:
            out.add(v)
    return out


def table_records(blob: bytes):
    if len(blob) < HDR:
        return None
    size, count = struct.unpack_from("<Q", blob, 0x08)[0], struct.unpack_from("<Q", blob, 0x28)[0]
    if not count or size % count or HDR + size > len(blob) or size // count < 16:
        return None
    stride = size // count
    return stride, [blob[HDR + i * stride:HDR + (i + 1) * stride] for i in range(count)]


def main(argv) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--extract", required=True, help="extract root (folder holding the type hash folders)")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                                  "data", "extract"))
    args = ap.parse_args(argv[1:])

    types = [t for t in sorted(os.listdir(args.extract)) if os.path.isdir(os.path.join(args.extract, t))]
    index = {}                                        # asset id -> [(type, file name)]
    for t in types:
        for f in os.listdir(os.path.join(args.extract, t)):
            try:
                index.setdefault(int(f, 16), []).append((t, f))
            except ValueError:
                pass
    print(f"indexed {len(index)} asset ids in {len(types)} type folders")

    # Seeds that name no asset are components: one pass over the global and combat
    # levels' component tables finds the records holding them (and copies those tables).
    comp_seeds = {h for h in SEEDS if h not in index}
    in_records = {}                                    # seed -> [(type, level, record)]
    for t in types:
        for level in [GLOBAL_LEVEL] + LEVELS:
            p = os.path.join(args.extract, t, level)
            if not os.path.isfile(p) or os.path.getsize(p) > MAX_FILE:
                continue
            blob = open(p, "rb").read()
            recs = table_records(blob)
            if not recs:
                continue
            stride = recs[0]
            for h in comp_seeds:
                needle, at = struct.pack("<Q", h), blob.find(struct.pack("<Q", h), HDR)
                while at >= 0:
                    k = (at - HDR) // stride
                    if k < len(recs[1]):
                        in_records.setdefault(h, []).append((t, level, recs[1][k]))
                    at = blob.find(needle, at + 1)
    print(f"component records found for {len(in_records)} of {len(comp_seeds)} component seeds", flush=True)

    lines, total = [], 0
    seen = set()
    queue = [(h, 0, name) for h, name in SEEDS.items()]
    copied_tables = set()
    while queue:
        h, depth, why = queue.pop(0)
        if h in seen or depth > DEPTH:
            continue
        seen.add(h)
        nxt = set()
        if h in index:
            for t, f in index[h]:
                p = os.path.join(args.extract, t, f)
                size = os.path.getsize(p)
                if size > MAX_FILE or total + size > MAX_TOTAL:
                    lines.append(f"{'  ' * depth}{h:016x}  {t}/{f}  {size} bytes  NOT COPIED (too big)  <- {why}")
                    continue
                dest = os.path.join(args.out, t, f)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                shutil.copy2(p, dest)
                total += size
                lines.append(f"{'  ' * depth}{h:016x}  {t}/{f}  {size} bytes  <- {why}")
                if size < 4 << 20:
                    nxt |= ids_in(open(p, "rb").read())
        else:
            hits = []
            for t, level, r in in_records.get(h, [])[:64]:
                hits.append((t, level))
                nxt |= ids_in(r)
                if (t, level) not in copied_tables:
                    copied_tables.add((t, level))
                    dest = os.path.join(args.out, t, level)
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    shutil.copy2(os.path.join(args.extract, t, level), dest)
            if hits:
                lines.append(f"{'  ' * depth}{h:016x}  component record in "
                             + ", ".join(sorted({f'{t}/{lv}' for t, lv in hits})) + f"  <- {why}")
            elif depth == 0:
                lines.append(f"{h:016x}  not found  <- {why}")
        for v in nxt:
            if v not in seen and v in index:
                queue.append((v, depth + 1, f"{h:016x}"))
    out = os.path.join(args.out, "visuals.txt")
    with open(out, "w", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"{out}: {len(lines)} entries, {total >> 20} MB of assets, {len(copied_tables)} component tables")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
