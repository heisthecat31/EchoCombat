"""A level's actor table (CActorDataResourceWin10, type 347869ce492dc7da): read, edit, write.

Layout (from EchoConstruct's src/codecs/level_tables.cpp, checked here by a byte-exact
round trip of every stock level): a 784-byte header holding 13 RadTable descriptors

    0  headers       {nodeid, actor index}  16/8   the key array: one per actor (plus
                                                   aliases), sorted as SIGNED int64
    1  prefabgroups  {prefabid, CTable<u16>} 64/8  derived: the inverted index of prefabids,
                                                   each followed (after the group array) by
                                                   its u16 actor indices
    2  nodeids       8      3 names  8      4 prefabids 8
    5  transforms    48/4   quat, pos, scale, 2 pad words
    6  numpooled     u16    7 parents u16
    8..12            five bitfields, ceil(actors / 64) words each; their bit counts sit
                     in the header at 520, 584, 648, 712, 776

then each table's rows in that order, each aligned to max(desc.alignment, its element
alignment) unless empty. A descriptor's size is element size * capacity.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

HEADER = 784
DESC_AT = (0, 64, 128, 184, 240, 296, 352, 408, 464, 528, 592, 656, 720)
BITCOUNT_AT = (520, 584, 648, 712, 776)
SHAPES = ((16, 8), (64, 8), (8, 8), (8, 8), (8, 8), (48, 4), (2, 2), (2, 2),
          (8, 8), (8, 8), (8, 8), (8, 8), (8, 8))
UNSET = 0xFFFFFFFFFFFFFFFF


def signed(v: int) -> int:
    return v - (1 << 64) if v >> 63 else v


@dataclass
class Desc:
    size: int
    alignment: int
    flags: int
    grow: int
    capacity: int
    count: int

    @classmethod
    def read(cls, b: bytes, at: int) -> "Desc":
        p, size, alloc, align, flags, grow, cap, count = struct.unpack_from("<QQQIIQQQ", b, at)
        if p or alloc or flags != 1 or cap < count:
            raise ValueError(f"no table descriptor at {at:#x}")
        return cls(size, align, flags, grow, cap, count)

    def pack(self) -> bytes:
        return struct.pack("<QQQIIQQQ", 0, self.size, 0, self.alignment, self.flags, self.grow,
                           self.capacity, self.count)

    def payload_align(self, elem_align: int) -> int:
        return 1 if self.count == 0 else max(self.alignment, elem_align)


def align_up(n: int, a: int) -> int:
    return n if a <= 1 else (n + a - 1) // a * a


@dataclass
class Actor:
    nodeid: int
    name: int
    prefabid: int
    transform: bytes          # 48 bytes
    numpooled: int
    parent: int
    bits: list = field(default_factory=lambda: [False] * 5)


@dataclass
class ActorTable:
    header: bytearray                     # the original header (descriptors rewritten on write)
    descs: list                           # the 13 descriptors (capacities, alignment, grow kept)
    group_template: Desc                  # the inline descriptor shape of a prefab group
    actors: list                          # [Actor]
    aliases: list                         # [(alias nodeid, target nodeid)]

    @classmethod
    def read(cls, b: bytes) -> "ActorTable":
        if len(b) < HEADER:
            raise ValueError("shorter than the actor table header")
        descs = [Desc.read(b, at) for at in DESC_AT]
        for i, d in enumerate(descs):
            if d.capacity and d.size != d.capacity * SHAPES[i][0]:
                raise ValueError(f"descriptor {i}: stride {d.size // d.capacity}")
        n = descs[2].count
        cursor, at = HEADER, [0] * 13
        groups = []                                       # (inner desc, index payload)
        for i, d in enumerate(descs):
            size, align = SHAPES[i]
            start = align_up(cursor, d.payload_align(align))
            if any(b[cursor:start]):
                raise ValueError(f"slot {i}: non-zero padding")
            at[i], cursor = start, start + d.count * size
            if i == 1:
                for g in range(d.count):
                    inner = Desc.read(b, at[1] + g * 64 + 8)
                    s = align_up(cursor, inner.payload_align(2))
                    groups.append((inner, s))
                    cursor = s + inner.count * 2
        if cursor != len(b):
            raise ValueError(f"walk ends at {cursor:#x}, file is {len(b):#x}")
        actors = []
        for i in range(n):
            bits = [bool(struct.unpack_from("<Q", b, at[8 + k] + (i // 64) * 8)[0] >> (i % 64) & 1)
                    for k in range(5)]
            actors.append(Actor(struct.unpack_from("<Q", b, at[2] + i * 8)[0],
                                struct.unpack_from("<Q", b, at[3] + i * 8)[0],
                                struct.unpack_from("<Q", b, at[4] + i * 8)[0],
                                bytes(b[at[5] + i * 48:at[5] + i * 48 + 48]),
                                struct.unpack_from("<H", b, at[6] + i * 2)[0],
                                struct.unpack_from("<H", b, at[7] + i * 2)[0], bits))
        by_index = [a.nodeid for a in actors]
        aliases = []
        for k in range(descs[0].count):
            node, index = struct.unpack_from("<QQ", b, at[0] + k * 16)
            if by_index[index] != node:
                aliases.append((node, by_index[index]))
        template = groups[0][0] if groups else Desc(0, 0, 1, 0, 0, 0)
        return cls(bytearray(b[:HEADER]), descs, template, actors, aliases)

    def write(self) -> bytes:
        n = len(self.actors)
        groups = {}
        for i, a in enumerate(self.actors):
            if a.prefabid != UNSET:
                groups.setdefault(a.prefabid, []).append(i)
        groups = sorted(groups.items(), key=lambda kv: signed(kv[0]))
        index = {a.nodeid: i for i, a in enumerate(self.actors)}
        keys = [(a.nodeid, i) for i, a in enumerate(self.actors)]
        keys += [(alias, index[target]) for alias, target in self.aliases]
        keys.sort(key=lambda kv: signed(kv[0]))
        words = (n + 63) // 64
        counts = [len(keys), len(groups), n, n, n, n, n, n] + [words] * 5
        rows = [b"".join(struct.pack("<QQ", k, i) for k, i in keys), None,
                b"".join(struct.pack("<Q", a.nodeid) for a in self.actors),
                b"".join(struct.pack("<Q", a.name) for a in self.actors),
                b"".join(struct.pack("<Q", a.prefabid) for a in self.actors),
                b"".join(a.transform for a in self.actors),
                b"".join(struct.pack("<H", a.numpooled) for a in self.actors),
                b"".join(struct.pack("<H", a.parent) for a in self.actors)]
        for k in range(5):
            w = [0] * words
            for i, a in enumerate(self.actors):
                if a.bits[k]:
                    w[i // 64] |= 1 << (i % 64)
            rows.append(b"".join(struct.pack("<Q", x) for x in w))
        header = bytearray(self.header)
        for i, d in enumerate(self.descs):
            d.count = counts[i]
            if d.capacity < d.count:
                d.capacity = d.count
            d.size = d.capacity * SHAPES[i][0]
            header[DESC_AT[i]:DESC_AT[i] + 56] = d.pack()
        for k in range(5):
            struct.pack_into("<Q", header, BITCOUNT_AT[k], n)
        out = bytearray(header)

        def put(payload: bytes, align: int):
            out.extend(bytes(align_up(len(out), align) - len(out)))
            out.extend(payload)

        for i, d in enumerate(self.descs):
            if i != 1:
                put(rows[i], d.payload_align(SHAPES[i][1]))
                continue
            t = self.group_template
            inner = []
            recs = b""
            for prefab, members in groups:
                cap = len(members)
                desc = Desc(cap * 2, t.alignment, t.flags, t.grow, cap, cap)
                inner.append((desc, members))
                recs += struct.pack("<Q", prefab) + desc.pack()
            put(recs, d.payload_align(SHAPES[1][1]))
            for desc, members in inner:
                put(b"".join(struct.pack("<H", m) for m in members), desc.payload_align(2))
        return bytes(out)


if __name__ == "__main__":
    import os
    import sys
    root = sys.argv[1] if len(sys.argv) > 1 else r"H:\pcvr-extracted\347869ce492dc7da"
    ok = bad = 0
    for f in sorted(os.listdir(root)):
        b = open(os.path.join(root, f), "rb").read()
        try:
            t = ActorTable.read(b)
            same = t.write() == b
        except ValueError as e:
            print(f, "read failed:", e)
            bad += 1
            continue
        ok += same
        bad += not same
        if not same:
            print(f, "round trip differs")
    print(f"{ok} byte-exact, {bad} not")
