"""Gear icons for EchoCombat's new gear, from a texture of our own.

Echo's gear icons (gear table and HUD) are cut from one atlas texture,
d8b84ca5707d3bd2 (1024x996, BC7 sRGB, 4x4 cells). Four UI canvases show them;
each canvas element names its texture and a UV rectangle, and the canvas ends with
a sprite table -- 24-byte records (CSymbol64 name, u0, v0, u1, v1), sorted by the
name as a signed 64-bit number -- that the game looks an item's icon up in by name.
Its header keeps the table's capacity at +0xe8, its count at +0xf0 and capacity * 24
at +0xc8.

The stock atlases are left alone. Instead:

* per stock icon atlas (ATLASES), a NEW texture twice as wide:
  the left half is the stock atlas (its BC7 blocks copied as they are, every mip),
  the right half a 4x4 grid of cells for EchoCombat's own gear -- for now solid
  test colours (NEW_ICONS), painted as BC7 mode 6 blocks;
* in each canvas that shows it, every element that used the stock atlas uses the new
  texture instead, its UVs (and the stock sprites' table UVs) halved in u so they
  still land on the same icons, and a sprite record per new item is inserted (as many
  copies as the canvas keeps of a stock sprite) pointing at its cell.

The texture is two assets: the 256-byte descriptor (cgtextureresourceWin10,
4a4c32c49300b8a0), cloned from the stock atlas's with the size fields changed and
streamingdisabled = 1, and the whole DDS as its GPU sidecar
(CGTextureResourceWin10GPU, beac1969cb7b8861) -- as lone_echo_blender's
le_lightmap_to_evr.py writes new textures.

To replace the test colours with real art later, edit NEW_ICONS (or draw into the
right half of the DDS this writes).

    python tools/gear_icons.py --src <dir with the stock assets> --out <stage dir>
"""

from __future__ import annotations

import argparse
import os
import struct
import sys

TEXTURE_DESC = "4a4c32c49300b8a0"       # cgtextureresourceWin10
TEXTURE_GPU = "beac1969cb7b8861"        # CGTextureResourceWin10GPU: the DDS
CANVAS = "59a9bd6e4525ecc4"             # CUICanvasResourceWin10
#: stock icon atlas -> (our extended copy's name, the canvases that show it).
#: d8b84ca5707d3bd2 (1024x996) is the gear icon sheet the HUD canvases use;
#: 9ec57c5df16fef80 (1800x1800) is the shared UI sheet holding the same icons, which
#: the equipment station (13361c4773e07b3e) and its siblings use.
ATLASES = {
    0xD8B84CA5707D3BD2: ("echocombat_gear_icons",
                         ["1e5d2a97184cad81", "2262b1c4c25c734e", "6083f456d52ef5f1", "b138c20e60e662a1"]),
    0x9EC57C5DF16FEF80: ("echocombat_gear_icons_ui",
                         ["13361c4773e07b3e", "2d06e14794a11e31", "8fcec01d07930956", "f4cc172339347e8b"]),
}

#: our gear: (sprite name, cell 0..15 in the right half, RGBA test colour)
NEW_ICONS = [
    ("smoke", 0, (170, 60, 255, 255)),   # UMBRAL VEIL: violet
    ("buff", 1, (255, 150, 0, 255)),     # POWER BOOST: orange
    ("dot", 2, (0, 230, 90, 255)),       # DOT FIELD: green
    ("drone", 3, (0, 200, 255, 255)),    # DRONE: cyan
]
CELL_MARGIN = 0.1                        # of a cell, left transparent around the icon

# descriptor fields (lone_echo_blender evr_texture_resource / le_lightmap_to_evr)
D_STREAMINGDISABLED, D_MAXW, D_MAXH, D_MAXMIPS = 0xC0, 0xC4, 0xC8, 0xCC
D_W, D_H, D_MIPS, D_RESMEM, D_PITCH = 0xE8, 0xEC, 0xF0, 0xF4, 0xF8
DDS_HEADER = 148                         # "DDS " + 124 + DX10 20
BC7 = (98, 99)

# canvas: elements (0xe0 bytes each, the texture at +0 and its UV rect at +8) from 0x238,
# their count in the header's first array at +0x80
ELEMENTS, ELEMENT_SIZE, ELEMENT_COUNT = 0x238, 0xE0, 0x80
T_BYTES, T_CAPACITY, T_COUNT = 0xC8, 0xE8, 0xF0
RECORD = 24


def symbol64(name: str) -> int:
    from le_symbol_names import symbol64 as s
    return int(s(name), 16)




# --- texture --------------------------------------------------------------------------
def bc7_solid(r: int, g: int, b: int, a: int) -> bytes:
    """A BC7 mode 6 block of one colour (both endpoints the colour, every index 0;
    the shared p-bit makes each channel even)."""
    v = 1 << 6                                             # mode 6
    pos = 7
    for c in (r, r, g, g, b, b, a, a):                     # R0 R1 G0 G1 B0 B1 A0 A1, 7 bits each
        v |= (c >> 1) << pos
        pos += 7
    return v.to_bytes(16, "little")                        # p-bits 0, indices 0


def mip_dims(w: int, h: int, k: int):
    return max(1, w >> k), max(1, h >> k)


def blocks(w: int, h: int):
    return (w + 3) // 4, (h + 3) // 4


def build_dds(stock: bytes):
    """The stock atlas on the left, NEW_ICONS' cells on the right. Returns (dds, w, h, mips)."""
    if stock[:4] != b"DDS " or stock[84:88] != b"DX10":
        raise ValueError("stock atlas is not a DX10 DDS")
    h, w = struct.unpack_from("<II", stock, 12)
    mips = struct.unpack_from("<I", stock, 28)[0] or 1
    dxgi = struct.unpack_from("<I", stock, 128)[0]
    if dxgi not in BC7:
        raise ValueError(f"stock atlas is DXGI {dxgi}, not BC7")
    # mips whose left half is block-aligned (width a multiple of 4) copy exactly
    mips_new = min(mips, max(k for k in range(mips) if (w >> k) % 4 == 0) + 1)
    nw = w * 2
    src = DDS_HEADER
    out = bytearray()
    colour = {cell: bc7_solid(*rgba) for _, cell, rgba in NEW_ICONS}
    clear = bc7_solid(0, 0, 0, 0)
    for k in range(mips):
        mw, mh = mip_dims(w, h, k)
        bw, bh = blocks(mw, mh)
        level = stock[src:src + bw * bh * 16]
        src += bw * bh * 16
        if k >= mips_new:
            continue
        nmw, _ = mip_dims(nw, h, k)
        nbw, _ = blocks(nmw, mh)
        for by in range(bh):
            out += level[by * bw * 16:(by + 1) * bw * 16]           # left: the stock row
            for bx in range(bw, nbw):                                # right: our cells
                u = ((bx - bw) * 4 + 2) / (nmw - mw)                 # 0..1 across the right half
                v = (by * 4 + 2) / mh
                cx, cy = min(int(u * 4), 3), min(int(v * 4), 3)
                fu, fv = u * 4 - cx, v * 4 - cy
                inside = CELL_MARGIN <= fu <= 1 - CELL_MARGIN and CELL_MARGIN <= fv <= 1 - CELL_MARGIN
                out += colour.get(cy * 4 + cx, clear) if inside else clear
    header = bytearray(stock[:DDS_HEADER])
    struct.pack_into("<I", header, 16, nw)                           # width
    struct.pack_into("<I", header, 28, mips_new)                     # mip count
    struct.pack_into("<I", header, 20, blocks(nw, h)[0] * blocks(nw, h)[1] * 16)   # top-level linear size
    return bytes(header) + bytes(out), nw, h, mips_new


def cell_uv(cell: int, width_ratio: float = 0.5):
    """UV rect of a right-half cell (u 0.5..1 of the new texture), inside its margin."""
    cx, cy = cell % 4, cell // 4
    u0 = 0.5 + (cx + CELL_MARGIN) / 4 * width_ratio
    u1 = 0.5 + (cx + 1 - CELL_MARGIN) / 4 * width_ratio
    v0 = (cy + CELL_MARGIN) / 4
    v1 = (cy + 1 - CELL_MARGIN) / 4
    return u0, v0, u1, v1


def descriptor(stock_desc: bytes, dds: bytes, w: int, h: int, mips: int) -> bytes:
    if len(stock_desc) < 256:
        raise ValueError("stock texture descriptor shorter than 256 bytes")
    d = bytearray(stock_desc[:256])
    for off, val in ((D_STREAMINGDISABLED, 1), (D_MAXW, w), (D_MAXH, h), (D_MAXMIPS, mips),
                     (D_W, w), (D_H, h), (D_MIPS, mips), (D_RESMEM, len(dds)),
                     (D_PITCH, len(dds) - DDS_HEADER)):
        struct.pack_into("<I", d, off, val)
    return bytes(d)


# --- canvases -------------------------------------------------------------------------
def sprite_table(d: bytes):
    """(start, count): the sorted sprite records, `count` from the header."""
    count = struct.unpack_from("<I", d, T_COUNT)[0]
    n = struct.unpack_from("<I", d, ELEMENT_COUNT)[0]
    lo = ELEMENTS + 8                                                # past the header, at least
    for start in range(lo, len(d) - count * RECORD + 1, 8):
        prev = None
        ok = True
        for i in range(count):
            o = start + i * RECORD
            h = struct.unpack_from("<q", d, o)[0]
            f = struct.unpack_from("<4f", d, o + 8)
            if not all(-0.01 <= x <= 1.01 for x in f) or h == 0 or (prev is not None and h < prev):
                ok = False
                break
            prev = h
        if ok:
            return start, count
    raise ValueError(f"no sorted sprite table of {count} records found ({n} elements)")


def element_textures(d: bytes) -> list:
    n = struct.unpack_from("<I", d, ELEMENT_COUNT)[0]
    return [struct.unpack_from("<Q", d, ELEMENTS + k * ELEMENT_SIZE)[0] for k in range(n)]


def patch_canvas(d: bytes, atlas: int, new_tex: int) -> tuple:
    """The canvas's elements on `atlas` moved to `new_tex`, with NEW_ICONS added.
    Returns (bytes, report).

    The sprite table keeps one copy of each sprite per element of the atlas it is cut
    from, so a sprite whose copy count is the number of `atlas` elements belongs to
    `atlas` (when no other texture has as many elements)."""
    d = bytearray(d)
    report = []
    texs = element_textures(d)
    mine = texs.count(atlas)
    if not mine:
        return bytes(d), [f"no element uses {atlas:016x}; left as is"]
    others = {t for t in texs if t not in (atlas, 0) and texs.count(t) == mine}
    if others:
        raise ValueError(f"{', '.join(f'{t:016x}' for t in others)} has as many elements as the atlas: "
                         f"cannot tell their sprites apart")
    for k, t in enumerate(texs):
        if t == atlas:
            o = ELEMENTS + k * ELEMENT_SIZE
            f = struct.unpack_from("<4f", d, o + 8)
            struct.pack_into("<Q4f", d, o, new_tex, f[0] * 0.5, f[1], f[2] * 0.5, f[3])
    report.append(f"{mine} element(s) moved to the new texture")
    start, count = sprite_table(d)
    names = [struct.unpack_from("<Q", d, start + k * RECORD)[0] for k in range(count)]
    copies = {h: names.count(h) for h in set(names)}
    halved = 0
    for k, h in enumerate(names):
        if copies[h] == mine:
            o = start + k * RECORD + 8
            f = struct.unpack_from("<4f", d, o)
            struct.pack_into("<4f", d, o, f[0] * 0.5, f[1], f[2] * 0.5, f[3])
            halved += 1
    report.append(f"{halved // mine} of its sprites rescaled")
    recs = [bytes(d[start + k * RECORD:start + (k + 1) * RECORD]) for k in range(count)]
    added = []
    for name, cell, _ in NEW_ICONS:
        h = symbol64(name)
        if h in copies:
            report.append(f"'{name}' already has a sprite here; left as is")
            continue
        recs += [struct.pack("<Q4f", h, *cell_uv(cell))] * mine
        added.append(name)
    recs.sort(key=lambda r: struct.unpack_from("<q", r)[0])
    d[start:start + count * RECORD] = b"".join(recs)
    report += point_duplicates(d, new_tex, recs)
    cap = struct.unpack_from("<I", d, T_CAPACITY)[0]
    while cap < len(recs):
        cap *= 2
    struct.pack_into("<I", d, T_COUNT, len(recs))
    struct.pack_into("<I", d, T_CAPACITY, cap)
    struct.pack_into("<I", d, T_BYTES, cap * RECORD)
    report.append(f"added {', '.join(added) or 'nothing'} ({mine} record(s) each); sprites {count} -> {len(recs)}")
    return bytes(d), report


#: The UI shows an item's icon by showing one element of a stack (elements at the same
#: rect, one per item type), each with its own fixed UV -- not by sprite name. The cut
#: items' elements are there, holding their parent's icon: in a stack, the second
#: element on `parent`'s sprite is the `item`'s. (The translocator's element holds the
#: detonator's icon in the stock game the same way.)
DUPLICATE_OF = [("buff", "heal"), ("smoke", "shield"), ("dot", "stun")]
E_RECT = 0x6C


def point_duplicates(d: bytearray, new_tex: int, recs: list) -> list:
    """Points each cut item's element (see DUPLICATE_OF) at the item's cell."""
    sprite = {struct.unpack_from("<Q", r)[0]: struct.unpack_from("<4f", r, 8) for r in recs}
    cells = {name: cell for name, cell, _ in NEW_ICONS}
    stacks = {}
    for k, t in enumerate(element_textures(d)):
        if t == new_tex:
            o = ELEMENTS + k * ELEMENT_SIZE
            stacks.setdefault(bytes(d[o + E_RECT:o + E_RECT + 16]), []).append(k)
    done = []
    for rect, ks in stacks.items():
        if len(ks) < 2:
            continue
        for item, parent in DUPLICATE_OF:
            uv = sprite.get(symbol64(parent))
            if uv is None or item not in cells:
                continue
            same = [k for k in ks if all(abs(a - b) < 1e-4 for a, b in
                                        zip(struct.unpack_from("<4f", d, ELEMENTS + k * ELEMENT_SIZE + 8), uv))]
            if len(same) >= 2:
                k = same[-1]
                struct.pack_into("<4f", d, ELEMENTS + k * ELEMENT_SIZE + 8, *cell_uv(cells[item]))
                done.append(f"e{k} {item}")
    return [f"cut items' elements -> our cells: {', '.join(done)}" if done else "no cut-item elements found"]


def read(src: str, t: str, asset: str, fallback: str = "") -> bytes:
    for p in (os.path.join(src, t, asset), os.path.join(fallback, t, asset) if fallback else "",
              os.path.join(fallback, asset) if fallback else ""):
        if p and os.path.exists(p):
            return open(p, "rb").read()
    raise FileNotFoundError(f"{t}/{asset} not found in {src}" + (f" or {fallback}" if fallback else ""))


def main(argv) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", required=True, help="where the stock assets are (<type>/<asset>)")
    ap.add_argument("--out", required=True, help="stage directory")
    ap.add_argument("--fallback", default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                                       "data", "extract", "weapon_icons"),
                    help="collected copies (find_weapon_icons.py) used when --src lacks them")
    args = ap.parse_args(argv[1:])
    fb = args.fallback
    for atlas, (tex_name, canvases) in ATLASES.items():
        a = f"{atlas:016x}"
        try:
            stock_dds = read(args.src, TEXTURE_GPU, a)
        except FileNotFoundError:                        # the .dds find_weapon_icons.py collected
            stock_dds = read(fb, "", f"{a}.dds")
        if not stock_dds.startswith(b"DDS "):
            raise SystemExit(f"the GPU sidecar of {a} is not a DDS")
        stock_desc = read(args.src, TEXTURE_DESC, a)
        dds, w, h, mips = build_dds(stock_dds)
        new_tex = symbol64(tex_name)
        name = f"{new_tex:016x}"
        for t, blob in ((TEXTURE_GPU, dds), (TEXTURE_DESC, descriptor(stock_desc, dds, w, h, mips))):
            os.makedirs(os.path.join(args.out, t), exist_ok=True)
            open(os.path.join(args.out, t, name), "wb").write(blob)
        print(f"gear icons: {a} -> texture {name} ({tex_name}) {w}x{h}, {len(dds) >> 10} KB; "
              f"cells: " + ", ".join(f"{n} #{c}" for n, c, _ in NEW_ICONS))
        for c in canvases:
            d = read(args.src, CANVAS, c, os.path.join(fb, "canvases"))
            out, report = patch_canvas(d, atlas, new_tex)
            os.makedirs(os.path.join(args.out, CANVAS), exist_ok=True)
            open(os.path.join(args.out, CANVAS, c), "wb").write(out)
            print(f"   canvas {c}: " + "; ".join(report))
    return 0


if __name__ == "__main__":
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                    "data", "extract", "tools"))
    sys.exit(main(sys.argv))
