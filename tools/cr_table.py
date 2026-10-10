"""Read / rewrite a level's component table (`<CR type>/<level>` in the extract).

A table is a RAD serialized struct, the same layout as a particle effect
(rm_preview/effect_file.py): arrays sit inline in their struct as 0x38-byte headers

    +00 u64 byte size   +08 u64 0 (pointer)   +10 u32 0  +14 u32 1
    +18 u64 alignment (0 or 0x20)   +20 u64 count   +28 u64 capacity   +30 u64

and the data is not addressed: after the root struct, each array's elements follow in
field order, each element's own arrays right after the array's data (depth first).
Most tables (CTransformCR, CTextureStreamingCR, CR15NetExplosionCR, ...) are a root of
one array of fixed records; CModelCR's root has six arrays, three of them parallel
per-model arrays whose elements carry arrays of their own.

`parse` / `build` round-trip byte for byte (checked on load); `add_element` appends a
copy of an element (with its nested data) to one of the root's arrays.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field


def q(b, o):
    return struct.unpack_from("<Q", b, o)[0]


def u(b, o):
    return struct.unpack_from("<I", b, o)[0]


@dataclass
class Arr:
    at: int              # header offset, relative to its struct
    count: int
    esize: int
    elems: list = field(default_factory=list)   # Node per element


@dataclass
class Node:
    raw: bytearray       # the struct's own bytes (headers included)
    arrays: list = field(default_factory=list)


def is_header(b, o, end):
    if o + 0x30 > end:
        return False
    sz, p, z, one, al, c, cap = q(b, o), q(b, o + 8), u(b, o + 0x10), u(b, o + 0x14), q(b, o + 0x18), \
        q(b, o + 0x20), q(b, o + 0x28)
    return p == 0 and z == 0 and one == 1 and al in (0, 0x20) and c == cap and sz < len(b) \
        and (c == 0) == (sz == 0) and (c == 0 or sz % c == 0)


def headers(b, start, size):
    out, o = [], start
    while o + 0x30 <= start + size:
        if is_header(b, o, start + size):
            c = q(b, o + 0x20)
            out.append(Arr(o - start, c, q(b, o) // c if c else 0))
            o += 0x30
        else:
            o += 8
    return out


def align(x, esize):
    n = 8 if esize % 16 == 0 else 4
    return (x + n - 1) & ~(n - 1)


def parse(b: bytes, root_size: int) -> Node:
    def walk(at, size, pos):
        node = Node(bytearray(b[at:at + size]))
        node.arrays = headers(b, at, size)
        for a in node.arrays:
            if not a.count:
                continue
            pos = align(pos, a.esize)
            first = pos
            pos += a.count * a.esize
            for i in range(a.count):
                e, pos = walk(first + i * a.esize, a.esize, pos)
                a.elems.append(e)
        return node, pos

    root, end = walk(0, root_size, root_size)
    if end != len(b):
        raise ValueError(f"table walk ended at {end:#x}, file is {len(b):#x}")
    out = build(root)
    if out != b:
        raise ValueError("table does not round-trip")
    return root


def build(root: Node) -> bytes:
    out = bytearray()

    def emit(node: Node):
        # node.raw is already in `out`; place its arrays' data, then each element's
        for a in node.arrays:
            if not a.count:
                continue
            while len(out) != align(len(out), a.esize):
                out.append(0)
            for e in a.elems:
                out.extend(e.raw)
            for e in a.elems:
                emit(e)

    out.extend(root.raw)
    emit(root)
    return bytes(out)


def set_count(node: Node, a: Arr):
    n = len(a.elems)
    a.count = n
    struct.pack_into("<Q", node.raw, a.at, n * a.esize)
    struct.pack_into("<QQ", node.raw, a.at + 0x20, n, n)


def add_element(root: Node, index: int, elem: Node):
    """Append `elem` to the root's array `index` (its count and size fixed up)."""
    a = root.arrays[index]
    if a.esize and len(elem.raw) != a.esize:
        raise ValueError("element size mismatch")
    a.elems.append(elem)
    set_count(root, a)


def copy(node: Node) -> Node:
    return Node(bytearray(node.raw), [Arr(a.at, a.count, a.esize, [copy(e) for e in a.elems]) for a in node.arrays])
