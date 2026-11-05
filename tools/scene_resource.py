"""A level's CGSceneResourceWin10: section walk (port of EchoConstruct's scene_resource.cpp).

Tables are {u32 count, count x row}; a "tailed" table has one more u32 after its rows. The node
graph (SNodeGraph, +2008 in memory) is decoded; every other section is carried as bytes.

    python tools/scene_resource.py <extract>/<scene type>/<level>
"""

from __future__ import annotations

import struct
import sys
from dataclasses import dataclass, field


class Reader:
    def __init__(self, b: bytes, at: int = 0):
        self.b, self.at = b, at

    def u32(self) -> int:
        v = struct.unpack_from("<I", self.b, self.at)[0]
        self.at += 4
        return v

    def skip(self, n: int):
        if self.at + n > len(self.b):
            raise ValueError(f"runs past EOF at {self.at:#x}")
        self.at += n

    def table(self, stride: int) -> list:
        n = self.u32()
        rows = [self.b[self.at + i * stride:self.at + (i + 1) * stride] for i in range(n)]
        self.skip(n * stride)
        return rows

    def skip_table(self, stride: int):
        self.skip(self.u32() * stride)


def skip_irradiance(r: Reader):
    for s in (120, 8, 8, 8, 8):
        r.skip_table(s)
    for _ in range(4):
        r.skip_table(1)
    r.skip(8)


def skip_shape_lists(r: Reader):
    fixed = (12, 32, 16, 40)
    for shape in range(6):
        for _ in range(2):
            r.skip_table(16)
            r.skip(4)
        n = r.u32()
        if shape < 4:
            r.skip(n * fixed[shape])
            continue
        for _ in range(n):
            if shape == 4:
                r.skip(4); r.skip_table(4); r.skip_table(12); r.skip(4); r.skip_table(12); r.skip_table(12)
            else:
                r.skip_table(16); r.skip(24); r.skip_table(12)


def skip_sound_volumes(r: Reader):
    for _ in range(r.u32()):
        r.skip(16); r.skip_table(8); r.skip(8)
        for _ in range(r.u32()):
            r.skip(8); r.skip_table(4)
        r.skip_table(8)
        for _ in range(r.u32()):
            r.skip_table(16); r.skip(24); r.skip_table(12)
        r.skip_table(16)


def skip_portal_groups(r: Reader):
    for _ in range(r.u32()):
        r.skip_table(8)


# the node graph's tables, in stream order: (name, stride, tailed)
GRAPH = (("vertices", 16, False), ("edges", 8, False), ("edges_by_target", 8, False),
         ("edge_index_a", 8, True), ("edge_index_b", 8, True), ("vertex_of_node", 4, False),
         ("free_list", 8, False), ("graph_words", None, False), ("table_u32_a", 4, False),
         ("slot_by_name", 16, True), ("table_u32_b", 4, False), ("names", 8, False))


@dataclass
class Scene:
    before: bytes                        # every section before the node graph
    graph: dict = field(default_factory=dict)   # name -> [rows] (+ name + "_tail")
    after: bytes = b""

    @classmethod
    def read(cls, b: bytes) -> "Scene":
        r = Reader(b)
        for stride in (360, 296, 120, 12, 4):
            r.skip_table(stride)
        skip_irradiance(r)
        r.skip_table(168)
        r.skip(8)
        r.skip_table(56)                 # transforms_816
        r.skip_table(1)                  # block_872
        skip_shape_lists(r)
        s = cls(b[:r.at])
        for name, stride, tailed in GRAPH:
            if stride is None:
                s.graph[name] = b[r.at:r.at + 16]
                r.skip(16)
                continue
            s.graph[name] = r.table(stride)
            if tailed:
                s.graph[name + "_tail"] = r.u32()
        start = r.at
        skip_sound_volumes(r)
        r.skip_table(128)
        skip_portal_groups(r)
        r.skip_table(8); r.skip_table(24); r.skip(8); r.skip(24)
        r.skip_table(16); r.skip_table(16); r.u32(); r.skip_table(48); r.skip_table(16); r.u32()
        r.skip_table(112); r.skip_table(32); r.skip_table(32)
        for _ in range(3):
            r.skip_table(8)
        if r.at != len(b):
            raise ValueError(f"walk ends at {r.at:#x}, file is {len(b):#x}")
        s.after = b[start:]
        return s

    def write(self) -> bytes:
        out = bytearray(self.before)
        for name, stride, tailed in GRAPH:
            if stride is None:
                out += self.graph[name]
                continue
            rows = self.graph[name]
            out += struct.pack("<I", len(rows)) + b"".join(rows)
            if tailed:
                out += struct.pack("<I", self.graph[name + "_tail"])
        return bytes(out + self.after)


if __name__ == "__main__":
    for p in sys.argv[1:]:
        b = open(p, "rb").read()
        s = Scene.read(b)
        print(p, "round trip" if s.write() == b else "DIFFERS",
              {k: (len(v) if isinstance(v, list) else v) for k, v in s.graph.items() if k != "graph_words"})
