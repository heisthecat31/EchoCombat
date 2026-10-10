"""Decode a small engine mesh (37102e4b27955a14 header + e7a8ab5ceaef49cb data), e.g. a particle mesh.

Header: CGVertexBufferData at +0x480 (36 x 8-byte CGVertexFormat elements, see
lone_echo_blender/le_mesh/vertex_format.py), then vertex count at +0x5BC,
stream sizes / offsets (+0x5B0 stream 0 bytes, +0x5D0 end of stream 1) and the
index count at +0x5D4. The data asset holds stream 0, stream 1, then u16 indices.
Verified on the Repair Matrix hand mesh: 248 x (20 + 28) bytes + 372 x 2 = 12648.
"""

from __future__ import annotations

import os
import struct

import numpy as np

import assets

HDR, DATA = "37102e4b27955a14", "e7a8ab5ceaef49cb"
TYPES = {0: ("B", 1, 1), 1: ("B", 1, 255.0), 2: ("H", 2, 1), 3: ("H", 2, 65535.0), 4: ("h", 2, 1),
         5: ("h", 2, 32767.0), 6: ("e", 2, 1), 8: ("f", 4, 1)}
USAGE = {0: "position", 1: "color", 2: "normal", 3: "tangent", 4: "texcoord"}


def load(root: str, mid: str):
    h = open(assets.path(root, HDR, mid), "rb").read()
    d = open(assets.path(root, DATA, mid), "rb").read()
    els = []
    for i in range(36):
        u, off, ty, cnt, slot, size, stream, inst = h[0x480 + 8 * i:0x488 + 8 * i]
        if u == 12 or u == 11:
            continue
        els.append((u, off, ty, cnt, slot, size, stream))
    nv = struct.unpack_from("<I", h, 0x5BC)[0]
    s0 = struct.unpack_from("<I", h, 0x5B0)[0]
    s1_end, ni = struct.unpack_from("<II", h, 0x5D0)
    strides = {}
    for u, off, ty, cnt, slot, size, stream in els:
        strides[stream] = max(strides.get(stream, 0), off + size)
    base = {0: 0, 1: s0}
    attrs = {}
    for u, off, ty, cnt, slot, size, stream in els:
        name = f"{USAGE.get(u, u)}{slot}"
        if name in attrs:
            continue
        fmt, w, norm = TYPES[ty]
        a = np.empty((nv, cnt), np.float32)
        for v in range(nv):
            o = base[stream] + v * strides[stream] + off
            a[v] = np.array(struct.unpack_from("<" + fmt * cnt, d, o), np.float32) / norm
        attrs[name] = a
    idx = np.frombuffer(d, np.uint16, ni, s1_end).astype(np.int32).reshape(-1, 3)
    return attrs, idx
