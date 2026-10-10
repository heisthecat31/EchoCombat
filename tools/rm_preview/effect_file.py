"""Parse a particle effect asset (3ae7c41914252baa) into its nested arrays.

The file is a RAD serialized struct. Arrays sit inline as 0x38-byte headers:

    +00 u64 byte size of the data   +08 u64 0 (pointer, patched at load)
    +10 u32 0   +14 u32 1           +18 u64 0x20
    +20 u64 count                   +28 u64 count (capacity)   +30 u64 (not always 0)

and raw byte blobs as 0x20-byte headers (same first 0x18 bytes, +18 = 0).
The data is not addressed: after the root struct, each array field's data
follows in field order, and right after an array's data come the nested arrays
of its elements, element by element (depth first). Struct arrays are aligned to
8 when the element size is a multiple of 16, else to 4; blobs to 4. The root
struct is 0x1B8 bytes. With these rules the walk ends exactly at the end of the
file for all 81 effects in the game, so the schema follows from the headers.

    python tools/rm_preview/effect_file.py <effect asset> [--dump]
"""

from __future__ import annotations

import argparse
import struct
from dataclasses import dataclass, field

ROOT = 0x1B8


def q(b, o):
    return struct.unpack_from("<Q", b, o)[0]


def u(b, o):
    return struct.unpack_from("<I", b, o)[0]


@dataclass
class Arr:
    at: int            # header position in the file
    size: int
    count: int         # 0 for a blob
    blob: bool
    data: int = -1     # where its data was found
    elems: list = field(default_factory=list)   # list of Struct

    @property
    def esize(self):
        return self.size // self.count if self.count else self.size


@dataclass
class Struct:
    at: int
    size: int
    arrays: list = field(default_factory=list)  # Arr, in field order


def headers(b, start, size):
    """Array/blob headers inside b[start:start+size], in order."""
    out, o = [], start
    while o + 0x20 <= start + size:
        sz, p, z, one = q(b, o), q(b, o + 8), u(b, o + 0x10), u(b, o + 0x14)
        if p == 0 and z == 0 and one == 1 and sz < len(b):
            al = q(b, o + 0x18)
            if al == 0x20 and o + 0x38 <= start + size and q(b, o + 0x20) == q(b, o + 0x28) \
                    and (q(b, o + 0x20) == 0) == (sz == 0) \
                    and (sz == 0 or sz % q(b, o + 0x20) == 0):
                out.append(Arr(o, sz, q(b, o + 0x20), False))
                o += 0x38
                continue
            if al == 0 and sz > 0:
                out.append(Arr(o, sz, 0, True))
                o += 0x20
                continue
        o += 8
    return out


def align(x, a: Arr):
    n = 4 if a.blob or a.esize % 16 else 8
    return (x + n - 1) & ~(n - 1)


def walk(b, s: Struct, pos: int) -> int:
    """Place the data of s's arrays starting at pos; returns the end."""
    s.arrays = headers(b, s.at, s.size)
    for a in s.arrays:
        if a.size == 0:
            continue
        pos = a.data = align(pos, a)
        pos += a.size
        if a.blob:
            continue
        a.elems = [Struct(a.data + i * a.esize, a.esize) for i in range(a.count)]
        for e in a.elems:
            pos = walk(b, e, pos)
    return pos


def parse(b):
    s = Struct(0, ROOT)
    end = walk(b, s, ROOT)
    if end != len(b):
        raise ValueError(f"walk ended at {end:#x}, file is {len(b):#x}")
    return s


def dump(b, s: Struct, depth=0, name="root"):
    pad = "  " * depth
    fields = s.size - sum(0x20 if a.blob else 0x38 for a in s.arrays)
    print(f"{pad}{name} @{s.at:#06x} size {s.size:#x} ({len(s.arrays)} arrays, {fields:#x} bytes of fields)")
    for i, a in enumerate(s.arrays):
        kind = "blob" if a.blob else f"{a.count} x {a.esize:#x}"
        print(f"{pad}  [{i}] hdr@{a.at - s.at:#05x}  {kind}  data@{a.data:#06x}" if a.size else f"{pad}  [{i}] hdr@{a.at - s.at:#05x}  empty")
        if a.elems and depth < 3:
            dump(b, a.elems[0], depth + 2, f"elem[0] of [{i}]")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    a = ap.parse_args()
    data = open(a.path, "rb").read()
    root = parse(data)
    dump(data, root)
