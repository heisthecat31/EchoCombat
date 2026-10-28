"""OVERCHARGE's own hand effect: Repair Matrix's crosses as purple up arrows.

Repair Matrix's assets are never touched; this writes new ones beside them:

  * a new mesh, ARROW_MESH (CSymbol64 "fx_overcharge_arrow"): a bevelled up arrow the
    size of Repair Matrix's cross (c90ff12470c68d3b), in the cross's own vertex format
    and with the cross's vertex / index counts (the spare slots are degenerate), so the
    cross's mesh header is reused unchanged;
  * the beam copy fix_buff names (fx_power_boost_beam): its crosses are the arrow and
    its sparks' colour texture (3f39c6f7d0747367, the beam's only baked green) is a
    purple copy (by brightness); its strands stay white. The beam's green glow is the heal
    script's model / light colours, which fix_buff's script recolour handles;
  * the hand effect copy fix_buff already names (PARTICLES[hand] = fx_power_boost_hand),
    with its mesh reference pointed at the arrow and its colour made purple.

Where the colour lives (found by perturbing the effect's param blob and running the
effect's own shaders, sim.py): the particle colour is intensity (half at blob +0x12,
8.0) x rgb (three floats at blob +0x18 / +0x1C / +0x20, (0.01, 1.0, 0.04)). The cross
material's vertex shader then takes sat(colour)^2.2, so PURPLE is chosen to land on
purple after that clamp: 8 x (0.078, 0.021, 1.0) -> sat -> (0.62, 0.17, 1) -> ^2.2 ->
(0.35, 0.02, 1.0).

    python tools/rm_preview/buff_assets.py --src <extract root> --out <dir>
"""

from __future__ import annotations

import argparse
import os
import struct
import sys

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.dirname(_HERE))

import effect_file as ef          # noqa: E402
from le_symbol_names import symbol64  # noqa: E402

HAND = "be696d7d300cbaf7"
BEAM = "39424707bb2df316"
BEAM_COPY = "fa379871313745a5"            # CSymbol64("fx_power_boost_beam"), fix_buff.PARTICLES
SPARKS_TEX = "3f39c6f7d0747367"           # the beam sparks' green/olive colour texture (BC1, mips inline)
TEX, TEX_META = "beac1969cb7b8861", "4a4c32c49300b8a0"
#: the sparks texture's colours become purple by brightness: rgb' = SPARKS_PURPLE * luma(rgb) * SPARKS_GAIN
SPARKS_PURPLE = (0.55, 0.12, 1.0)
SPARKS_GAIN = 1.6
HAND_COPY = "fa3798713b334aac"            # CSymbol64("fx_power_boost_hand"), fix_buff.PARTICLES
CROSS_MESH = "c90ff12470c68d3b"
ARROW_MESH = symbol64("fx_overcharge_arrow")
EFFECT, COMPANION = "3ae7c41914252baa", "be45c22fa8c2d3f"
MESH_TYPES = ("37102e4b27955a14", "73d312a620da3824", "c2434c5a99e139ce", "e7a8ab5ceaef49cb")
MESH_DATA = "e7a8ab5ceaef49cb"
NV, NI = 248, 372                         # the cross's counts (header unchanged)
PURPLE = (0.078, 0.021, 1.0)
COLOUR_OFFS = (0x18, 0x1C, 0x20)

# arrow outline, counter-clockwise seen from +Z (metres; the cross spans +-0.039)
APEX, HEAD_W, HEAD_BASE, SHAFT_W, BOTTOM = 0.039, 0.037, 0.0, 0.0145, -0.039
HALF_T, BEVEL = 0.01219653, 0.004


def outline():
    return np.array([(0, APEX), (-HEAD_W, HEAD_BASE), (-SHAFT_W, HEAD_BASE), (-SHAFT_W, BOTTOM),
                     (SHAFT_W, BOTTOM), (SHAFT_W, HEAD_BASE), (HEAD_W, HEAD_BASE)], float)


CAP_TRIS = [(0, 1, 2), (0, 2, 5), (0, 5, 6), (2, 3, 4), (2, 4, 5)]


def inset(poly, d):
    """Offset a CCW polygon inward by d (mitred corners)."""
    n = len(poly)
    out = []
    for i in range(n):
        p0, p1, p2 = poly[i - 1], poly[i], poly[(i + 1) % n]
        e0, e1 = p1 - p0, p2 - p1
        n0 = np.array([-e0[1], e0[0]]) / np.linalg.norm(e0)
        n1 = np.array([-e1[1], e1[0]]) / np.linalg.norm(e1)
        # intersect the two offset lines p0 + n0 d + t e0 and p1 + n1 d + s e1
        a = np.array([e0, -e1]).T
        t = np.linalg.solve(a, (p1 + n1 * d) - (p0 + n0 * d))[0]
        out.append(p0 + n0 * d + t * e0)
    return np.array(out)


def arrow_geometry():
    """(positions, normals, triangles) of a bevelled arrow, flat shaded, CCW = front."""
    O, I = outline(), inset(outline(), BEVEL)
    P, N, T = [], [], []

    def quad(a, b, c, d):        # a b c d counter-clockwise seen from outside
        n = np.cross(b - a, d - a)
        n /= np.linalg.norm(n)
        k = len(P)
        P.extend([a, b, c, d])
        N.extend([n] * 4)
        T.extend([(k, k + 1, k + 2), (k, k + 2, k + 3)])

    for z, flip in ((HALF_T, False), (-HALF_T, True)):
        k = len(P)
        for x, y in I:
            P.append(np.array([x, y, z]))
            N.append(np.array([0, 0, -1.0 if flip else 1.0]))
        for a, b, c in CAP_TRIS:
            T.append((k + a, k + c, k + b) if flip else (k + a, k + b, k + c))
    zi = HALF_T - BEVEL
    n = len(O)
    for i in range(n):
        j = (i + 1) % n
        o0, o1, i0, i1 = O[i], O[j], I[i], I[j]
        v = lambda p, z: np.array([p[0], p[1], z])
        quad(v(o0, zi), v(o1, zi), v(i1, HALF_T), v(i0, HALF_T))       # front chamfer
        quad(v(o0, -zi), v(o1, -zi), v(o1, zi), v(o0, zi))             # side wall
        quad(v(i0, -HALF_T), v(i1, -HALF_T), v(o1, -zi), v(o0, -zi))   # back chamfer
    return np.array(P), np.array(N), np.array(T)


def mesh_data(cross_data: bytes) -> bytes:
    """The arrow in the cross's buffer layout: stream 0 (20 B), stream 1 (28 B), u16 indices."""
    P, N, T = arrow_geometry()
    assert len(P) <= NV and len(T) * 3 <= NI, (len(P), len(T))
    # winding check: every triangle's geometric normal agrees with its vertex normal
    for t in T:
        g = np.cross(P[t[1]] - P[t[0]], P[t[2]] - P[t[0]])
        assert g @ N[t[0]] > 0, t
    s0, s1 = bytearray(), bytearray()
    span = 2 * max(APEX, HEAD_W) / (0.97726667 - 0.02273312)
    for k in range(NV):
        p, nrm = (P[k], N[k]) if k < len(P) else (P[0], N[0])
        u = 0.5 + p[0] / span
        v = 0.5 - p[1] / span
        s0 += bytes((255, 0, 0, 255)) + bytes((255, 255, 255, 255))   # colour1 (layer blend), colour0
        s0 += struct.pack("<ff", u, v) + struct.pack("<HH", int(u * 65535), int(v * 65535))
        tan = np.array([1.0, 0, 0]) if abs(nrm[0]) < 0.9 else np.array([0, 0, 1.0])
        tan = tan - nrm * (tan @ nrm)
        tan /= np.linalg.norm(tan)
        q = lambda x: int(round(max(-1, min(1, x)) * 32767))
        s1 += struct.pack("<fff", *p) + struct.pack("<4h", *(q(x) for x in nrm), 0)
        s1 += struct.pack("<4h", *(q(x) for x in tan), 32767)
    idx = [i for t in T for i in t] + [0] * (NI - 3 * len(T))
    out = bytes(s0) + bytes(s1) + struct.pack(f"<{NI}H", *idx)
    assert len(out) == len(cross_data), (len(out), len(cross_data))
    return out


def recolour(params: bytes, rgb=PURPLE) -> bytes:
    b = bytearray(params)
    for o, c in zip(COLOUR_OFFS, rgb):
        struct.pack_into("<f", b, o, c)
    return bytes(b)


def hand_copy(effect: bytes, rgb=PURPLE, arrow: bool = True) -> bytes:
    """The hand effect with its mesh pointed at the arrow (unless not `arrow`) and its colour rgb."""
    b = bytearray(effect)
    root = ef.parse(effect)
    mesh_arr = root.arrays[3]
    assert mesh_arr.count == 1 and struct.unpack_from("<Q", b, mesh_arr.data)[0] == int(CROSS_MESH, 16)
    if arrow:
        struct.pack_into("<Q", b, mesh_arr.data, int(ARROW_MESH, 16))
    sys0 = root.arrays[0].elems[0]
    blob = next(a for a in sys0.arrays if a.blob)
    b[blob.data:blob.data + blob.size] = recolour(effect[blob.data:blob.data + blob.size], rgb)
    return bytes(b)


def purple_matrix(purple=SPARKS_PURPLE, gain=SPARKS_GAIN):
    """rgb -> purple x brightness: a rank-1 linear map, so it commutes with BC1 interpolation."""
    return gain * np.outer(np.array(purple), np.array([0.299, 0.587, 0.114]))


def recolour_bc1(dds: bytes, m=None) -> bytes:
    """Apply a colour matrix to every BC1 block's two endpoints (all mips). The 2-colour /
    3-colour mode of a block depends on c0 > c1, so the order is kept by swapping the
    endpoints and remapping the indices when the new colours compare the other way."""
    m = purple_matrix() if m is None else m
    out = bytearray(dds)
    for o in range(148, len(out), 8):
        c0, c1, idx = struct.unpack_from("<HHI", out, o)
        def dec(c):
            return np.array([(c >> 11) * 255 / 31, ((c >> 5) & 63) * 255 / 63, (c & 31) * 255 / 31])
        def enc(v):
            v = np.clip(v, 0, 255)
            return (int(round(v[0] * 31 / 255)) << 11) | (int(round(v[1] * 63 / 255)) << 5) | int(round(v[2] * 31 / 255))
        n0, n1 = enc(m @ dec(c0)), enc(m @ dec(c1))
        if (c0 > c1) != (n0 > n1) or (c0 > c1 and n0 == n1):
            if c0 > c1:            # 4-colour block: swap endpoints, indices 0<->1, 2<->3
                n0, n1 = n1, n0
                idx = sum(((((idx >> (2 * i)) & 3) ^ 1) << (2 * i)) for i in range(16))
            else:                  # 3-colour block: swap endpoints, indices 0<->1 (2 stays, 3 stays)
                n0, n1 = n1, n0
                idx = sum((({0: 1, 1: 0}.get((idx >> (2 * i)) & 3, (idx >> (2 * i)) & 3)) << (2 * i)) for i in range(16))
            if c0 > c1 and n0 == n1:
                n0 = min(n0 + 1, 0xFFFF)
        struct.pack_into("<HHI", out, o, n0, n1, idx)
    return bytes(out)


def beam_copy(effect: bytes, colour=None, sparks=None, arrow: bool = True) -> bytes:
    """The beam with its crosses as arrows (unless not `arrow`), its sparks texture the copy
    `sparks` (default the purple one) and its colour `colour` (default BEAM_PURPLE); the white
    strands stay."""
    colour = BEAM_PURPLE if colour is None else colour
    sparks = SPARKS_COPY if sparks is None else sparks
    b = bytearray(effect)
    root = ef.parse(effect)
    mesh_arr, tex_arr = root.arrays[3], root.arrays[2]
    assert struct.unpack_from("<Q", b, mesh_arr.data)[0] == int(CROSS_MESH, 16)
    if arrow:
        struct.pack_into("<Q", b, mesh_arr.data, int(ARROW_MESH, 16))
    for e in tex_arr.elems:
        if struct.unpack_from("<Q", b, e.at)[0] == int(SPARKS_TEX, 16):
            struct.pack_into("<Q", b, e.at, int(sparks, 16))
            break
    else:
        raise ValueError("sparks texture not referenced")
    # Its green (tested in game: the beam stays green without this): each ribbon / flash
    # system's param blob has two float colours, (.01, 1, .04) at +80h (laid out like the
    # hand's particle colour, +18h there) and a pale green at +08h. Both become
    # min + (max - min) * BEAM_PURPLE, and nothing else is touched. Tested: +60h / +70h
    # look green as floats but start with half floats (3be8, 3266: shape / noise
    # values); recolouring them, or every green-looking triple (fix_buff.gold_particles),
    # gave stray zigzag strands that outlived the bubble.
    span = lambda c: [min(c) + (max(c) - min(c)) * k for k in colour]
    for s in root.arrays[0].elems:
        blob = s.arrays[0]
        if not blob.blob or blob.size != 0xA8:
            continue
        for off in (0x08, 0x80):
            c = struct.unpack_from("<3f", b, blob.data + off)
            c = [0.0 if abs(v) < 1e-6 else v for v in c]        # the 0s are stored as denormals
            if c[1] > 0.05 and c[1] >= 1.2 * max(c[0], c[2]) and min(c) >= 0:
                struct.pack_into("<3f", b, blob.data + off, *span(c))
    return bytes(b)


#: the beam's purple: (0.01, 1, 0.04) -> (0.36, 0.03, 1.0), the glow colour fix_buff.GOLD
BEAM_PURPLE = (0.35, 0.02, 1.00)


SPARKS_COPY = symbol64("fx_overcharge_sparks_tex")


def write(src: str, out: str) -> list:
    done = []

    def put(folder, name, data):
        os.makedirs(os.path.join(out, folder), exist_ok=True)
        open(os.path.join(out, folder, name), "wb").write(data)
        done.append(f"{folder}/{name}")

    for t in MESH_TYPES:
        data = open(os.path.join(src, t, CROSS_MESH), "rb").read()
        put(t, ARROW_MESH, mesh_data(data) if t == MESH_DATA else data)
    put(EFFECT, HAND_COPY, hand_copy(open(os.path.join(src, EFFECT, HAND), "rb").read()))
    put(COMPANION, HAND_COPY, open(os.path.join(src, COMPANION, HAND), "rb").read())
    put(EFFECT, BEAM_COPY, beam_copy(open(os.path.join(src, EFFECT, BEAM), "rb").read()))
    put(COMPANION, BEAM_COPY, open(os.path.join(src, COMPANION, BEAM), "rb").read())
    put(TEX, SPARKS_COPY, recolour_bc1(open(os.path.join(src, TEX, SPARKS_TEX), "rb").read()))
    put(TEX_META, SPARKS_COPY, open(os.path.join(src, TEX_META, SPARKS_TEX), "rb").read())
    return done


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    for f in write(a.src, a.out):
        print(f)
