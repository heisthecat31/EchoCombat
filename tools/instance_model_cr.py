"""CInstanceModelCRWin10: read, append copies of rows, write (layout from EchoConstruct's
cr_shapes.gen.cpp). A 568-byte header of ten RadTable descriptors, their payloads in header order:

    0   lookup          24  Projection of the record's +0..24 (SLookup)
    56  bitwords         8  Bitmap, one bit per record; bit_count at header +112
    120 instancenames    8  Independent pool (asset symbols)
    176 instanceindices  2  Column: each record's u16 index into the pool
    232 modelassets      8  Projection of record +40 (transformname)
    288 instancecolors  16  Projection of +48
    344 instanceflags1   2  Projection of +64
    400 instanceflags2   2  Projection of +66
    456 instancescales   4  Projection of +68
    512 properties      72  Spine
"""

from __future__ import annotations

import struct

SLOTS = ((0, 24, 8), (56, 8, 8), (120, 8, 8), (176, 2, 2), (232, 8, 8), (288, 16, 4),
         (344, 2, 2), (400, 2, 2), (456, 4, 4), (512, 72, 8))
HEADER = 568
BITCOUNT = 112
PER_RECORD = (0, 3, 4, 5, 6, 7, 8, 9)    # slots with one row per record


def align_up(n, a):
    return n if a <= 1 else (n + a - 1) // a * a


class InstanceModels:
    def __init__(self, b: bytes):
        self.header = bytearray(b[:HEADER])
        self.slots = []
        cursor = HEADER
        for at, size, ealign in SLOTS:
            p, dsize, alloc, align, flags, grow, cap, count = struct.unpack_from("<QQQIIQQQ", b, at)
            assert p == 0 and alloc == 0 and (cap == 0 or dsize == cap * size), (at, dsize, cap)
            if count:
                start = align_up(cursor, max(align, ealign))
                assert not any(b[cursor:start])
            else:
                start = cursor
            self.slots.append([b[start + i * size:start + (i + 1) * size] for i in range(count)])
            cursor = start + count * size
        if cursor != len(b):
            raise ValueError(f"walk ends at {cursor:#x}, file is {len(b):#x}")
        self.nbits = struct.unpack_from("<Q", b, BITCOUNT)[0]

    @property
    def owners(self):
        return [struct.unpack_from("<Q", r, 8)[0] for r in self.slots[9]]

    def bit(self, i):
        return self.slots[1][i // 64] and (struct.unpack("<Q", self.slots[1][i // 64])[0] >> (i % 64)) & 1

    def copy_record(self, i: int, remap):
        """Append a copy of record i; remap(bytes) rewrites a row's nodeids."""
        n = len(self.slots[9])
        for s in PER_RECORD:
            row = self.slots[s][i]
            self.slots[s].append(remap(row) if s in (0, 9) else row)
        bit = self.bit(i)
        words = self.slots[1]
        while len(words) * 64 < n + 1:
            words.append(bytes(8))
        if bit:
            w = struct.unpack("<Q", words[n // 64])[0] | 1 << (n % 64)
            words[n // 64] = struct.pack("<Q", w)
        self.nbits = n + 1

    def write(self) -> bytes:
        out = bytearray(self.header)
        struct.pack_into("<Q", out, BITCOUNT, self.nbits)
        for (at, size, ealign), rows in zip(SLOTS, self.slots):
            p, dsize, alloc, align, flags, grow, cap, count = struct.unpack_from("<QQQIIQQQ", out, at)
            count = len(rows)
            cap = max(cap, count)
            struct.pack_into("<QQQIIQQQ", out, at, 0, cap * size, 0, align, flags, grow, cap, count)
        for (at, size, ealign), rows in zip(SLOTS, self.slots):
            align = struct.unpack_from("<I", out, at + 24)[0]
            if rows:
                out += bytes(align_up(len(out), max(align, ealign)) - len(out))
            out += b"".join(rows)
        return bytes(out)


if __name__ == "__main__":
    import sys
    b = open(sys.argv[1], "rb").read()
    m = InstanceModels(b)
    print(len(m.slots[9]), "records,", len(m.slots[2]), "assets", "round trip" if m.write() == b else "DIFFERS")
