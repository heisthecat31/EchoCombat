"""Gear icons: a texture of our own, with a cell for every gear item.

Echo cuts its gear icons from two atlases: d8b84ca5707d3bd2 (1024x996, the HUD's gear
sheet) and 9ec57c5df16fef80 (1800x1800, the shared UI sheet the equipment station
uses). Both BC7 sRGB, one mip. A UI canvas (CUICanvasResourceWin10) is:

    header   +0x28 textured element count, +0x2c their vertex count (4 a quad),
             +0x78 element capacity, +0x80 element count,
             +0xc8 / +0xe8 / +0xf0 sprite table bytes (capacity * 24) / capacity / count
    elements from 0x1b0, 0xe0 bytes each: +0x00 name (CSymbol64), +0x60 index,
             +0x68 its parent's, +0x88 texture, +0x90 UV rect (u0 v0 u1 v1)
    sprites  right after the elements: 24-byte records (CSymbol64 name, UV rect), sorted
             by the name as a signed 64-bit number, one copy per element of the atlas a
             sprite is cut from

The UI shows an item's icon by showing the element named after it -- ABILITY_SMOKE,
GRENADE_DOT, WEAPON_RIFLE, ... (a stack of them at one place, one per item) -- with
that element's own UV. The cut items' elements were left holding their parent's icon,
the station has no GRENADE_DRONE at all, and several stock items share an icon
(translocator / detonator, the guns). The selection grid's empty next slot shows the
element LOCK.

The stock atlases are left alone. Instead, per atlas:

* a NEW texture twice as wide: the stock atlas's BC7 blocks on the left (copied, so
  every stock icon stays), a GRID x GRID table of cells on the right, one per ITEMS
  entry -- solid test colours for now (BC7 mode 6 blocks) until the real icons go in;
* every canvas element on the atlas moves to it (u halved, as are the atlas's sprites);
* every item's element, and its plain-name sprite (heal, assault, ...: what name-based
  screens such as the kill feed look up), points at the item's own cell; a missing
  GRENADE_DRONE element is cloned from GRENADE_DOT;
* LOCK points at an empty cell: nothing is drawn.

The texture is two assets: the 256-byte descriptor (cgtextureresourceWin10,
4a4c32c49300b8a0), cloned from the stock atlas's with the size fields changed and
streamingdisabled = 1, and the whole DDS as its GPU sidecar
(CGTextureResourceWin10GPU, beac1969cb7b8861), as lone_echo_blender's
le_lightmap_to_evr.py writes new textures.

    python tools/gear_icons.py --src <dir with the stock assets> --out <stage dir>
"""

from __future__ import annotations

import argparse
import importlib.util
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

#: every gear item: (element prefix, gear name, display name). Items in STOCK_ICON keep
#: their stock icon (each one distinct); the others get a cell of their own, with the
#: PNG from ICON_DIRS named after the gear or display name (blazar.png, dot.png, ...),
#: or a solid test colour (TEST_COLOURS) until one is made.
ITEMS = [
    ("ABILITY", "heal", "REPAIR MATRIX"), ("ABILITY", "sensor", "THREAT SCANNER"),
    ("ABILITY", "shield", "ENERGY BARRIER"), ("ABILITY", "wraith", "PHASE SHIFT"),
    ("ABILITY", "smoke", "UMBRAL VEIL"), ("ABILITY", "buff", "OVERCHARGE"), ("ABILITY", "point", "POINT"),
    ("GRENADE", "det", "DETONATOR"), ("GRENADE", "stun", "STUN FIELD"), ("GRENADE", "arc", "ARC MINE"),
    ("GRENADE", "burst", "INSTANT REPAIR"), ("GRENADE", "loc", "TRANSLOCATOR"), ("GRENADE", "dot", "DOT FIELD"),
    ("GRENADE", "drone", "DRONE"),
    ("WEAPON", "assault", "PULSAR"), ("WEAPON", "blaster", "NOVA"), ("WEAPON", "scout", "COMET"),
    ("WEAPON", "rocket", "METEOR"), ("WEAPON", "magnum", "PROTOSTAR"), ("WEAPON", "smg", "QUARK"),
    ("WEAPON", "chain", "BLAZAR"), ("WEAPON", "rifle", "STARBURST"),
]
STOCK_ICON = {"heal", "sensor", "shield", "wraith", "det", "stun", "arc", "burst",
              "assault", "blaster", "scout", "rocket"}
TEST_COLOURS = {"smoke": (170, 60, 255, 255), "buff": (255, 150, 0, 255), "point": (255, 40, 120, 255)}
ALIASES = {"smoke": ("veil",)}         # other file names an item's icon may have
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ICON_DIRS = [os.path.join(ROOT_DIR, "ICONS", "hd"), os.path.join(ROOT_DIR, "ICONS")]
#: element clones for items a canvas has no element for: (new, copied from)
CLONES = [("GRENADE_DRONE", "GRENADE_DOT"), ("ABILITY_POINT", "ABILITY_SMOKE")]
#: an unused element of a canvas's own -- GRENADE_MINE, a cut item -- becomes the item's
#: instead of an added one wherever there is one: the equipment station only finds the
#: elements its index lists (INDEX_CANVAS), and that index lists GRENADE_MINE's place.
#: (new name, element to copy, spare element it replaces)
REUSE = [("ABILITY_POINT", "ABILITY_SMOKE", "GRENADE_MINE")]
#: The equipment station (canvas 72e4349798ae3ea1) holds 39 instances of the gear
#: canvases (36 grid slots of 1e5d2a97184cad81, the 3 big boxes of 6083f456d52ef5f1)
#: and, at its end, an index of every element in them: 24-byte records (key, slot,
#: element name), key = CSymbol64 of "<slot path>.<element name>" (the slot's symbol
#: continued with "." + the name), sorted by key as a signed number; the record count
#: is the dword at +1A0h. An element the index does not list is never shown there,
#: which is why POINT's slot and TAC-MOD box stayed empty. Its REUSE spares' records
#: are renamed to the new element.
INDEX_CANVAS, INDEX_COUNT = "72e4349798ae3ea1", 0x1A0
GRID = 5                                 # cells per row / column of the right half
EMPTY_CELL = GRID * GRID - 1             # never painted: fully transparent


def own_cells() -> dict:
    """gear name -> cell, for the items that get one."""
    return {name: k for k, (_, name, _) in enumerate(i for i in ITEMS if i[1] not in STOCK_ICON)}


def icon_png(name: str, display: str):
    for d in ICON_DIRS:
        for stem in (name, display, display.replace(" ", "_"), display.replace(" ", ""), *ALIASES.get(name, ())):
            for f in (os.listdir(d) if os.path.isdir(d) else []):
                if f.lower() == stem.lower() + ".png":
                    return os.path.join(d, f)
    return None


def cells_image(w: int, h: int):
    """The right half, (h, w, 4) RGBA: each item's PNG (or test colour) in its cell. Each
    cell's RGB is uniform (white under an icon, the colour under a test cell) so the
    BC7 blocks only have alpha to fit."""
    import numpy as np
    from PIL import Image
    img = np.zeros((h, w, 4), np.uint8)
    img[:, :, :3] = 255
    used = []
    for (kind, name, display) in ITEMS:
        cell = own_cells().get(name)
        if cell is None:
            continue
        cx, cy = cell % GRID, cell // GRID
        x0, x1 = round(cx * w / GRID), round((cx + 1) * w / GRID)
        y0, y1 = round(cy * h / GRID), round((cy + 1) * h / GRID)
        ix0, ix1 = round(x0 + (x1 - x0) * CELL_MARGIN), round(x1 - (x1 - x0) * CELL_MARGIN)
        iy0, iy1 = round(y0 + (y1 - y0) * CELL_MARGIN), round(y1 - (y1 - y0) * CELL_MARGIN)
        png = icon_png(name, display)
        if png:
            icon = Image.open(png).convert("RGBA")
            # cropped to a square round the artwork, as the stock sprites are cut, so it
            # fills its slot the way they do
            x0b, y0b, x1b, y1b = icon.getbbox() or (0, 0, icon.width, icon.height)
            half = max(x1b - x0b, y1b - y0b) * (0.5 + ICON_PAD)
            mx, my = (x0b + x1b) / 2, (y0b + y1b) / 2
            icon = icon.crop((round(mx - half), round(my - half), round(mx + half), round(my + half)))
            side = min(ix1 - ix0, iy1 - iy0)
            icon = icon.resize((side, side), Image.LANCZOS)
            a = np.asarray(icon)[:, :, 3]
            ox, oy = ix0 + (ix1 - ix0 - side) // 2, iy0 + (iy1 - iy0 - side) // 2
            img[oy:oy + side, ox:ox + side, 3] = a
            used.append(f"{name} <- {os.path.basename(png)}")
        else:
            r, g, b, a = TEST_COLOURS.get(name, (255, 255, 255, 255))
            img[y0:y1, x0:x1, :3] = (r, g, b)
            img[iy0:iy1, ix0:ix1, 3] = a
            used.append(f"{name} test colour")
    return img, used
CELL_MARGIN = 0.1                        # of a cell, left transparent around the icon
ICON_PAD = 0.03                          # of an icon's size, kept round its artwork

# descriptor fields (lone_echo_blender evr_texture_resource / le_lightmap_to_evr)
D_STREAMINGDISABLED, D_MAXW, D_MAXH, D_MAXMIPS = 0xC0, 0xC4, 0xC8, 0xCC
D_W, D_H, D_MIPS, D_RESMEM, D_PITCH = 0xE8, 0xEC, 0xF0, 0xF4, 0xF8
DDS_HEADER = 148                         # "DDS " + 124 + DX10 20
BC7 = (98, 99)

# canvas (see the top)
H_TEXTURED, H_VERTS, E_CAPACITY, ELEMENT_COUNT = 0x28, 0x2C, 0x78, 0x80
ELEMENTS, ELEMENT_SIZE = 0x1B0, 0xE0
E_NAME, E_INDEX, E_PARENT, E_TEX, E_UV = 0x00, 0x60, 0x68, 0x88, 0x90
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
    """The stock atlas on the left, our cells (cells_image) on the right.
    Returns (dds, w, h, mips, report)."""
    import numpy as np
    from PIL import Image
    import bc7
    if stock[:4] != b"DDS " or stock[84:88] != b"DX10":
        raise ValueError("stock atlas is not a DX10 DDS")
    h, w = struct.unpack_from("<II", stock, 12)
    mips = struct.unpack_from("<I", stock, 28)[0] or 1
    dxgi = struct.unpack_from("<I", stock, 128)[0]
    if dxgi not in BC7:
        raise ValueError(f"stock atlas is DXGI {dxgi}, not BC7")
    # mips whose left half is block-aligned (width a multiple of 4) copy exactly
    mips_new = min(mips, max(k for k in range(mips) if (w >> k) % 4 == 0) + 1)
    right, used = cells_image(w, h)
    nw = w * 2
    src = DDS_HEADER
    out = bytearray()
    for k in range(mips):
        mw, mh = mip_dims(w, h, k)
        bw, bh = blocks(mw, mh)
        level = stock[src:src + bw * bh * 16]
        src += bw * bh * 16
        if k >= mips_new:
            continue
        r = np.asarray(Image.fromarray(right).resize((mw, mh), Image.LANCZOS)) if k else right
        pad = np.zeros((bh * 4, bw * 4, 4), np.uint8)
        pad[:, :, :3] = 255
        pad[:mh, :mw] = r
        enc = bc7.encode(pad)
        for by in range(bh):
            out += level[by * bw * 16:(by + 1) * bw * 16]           # left: the stock row
            out += enc[by * bw * 16:(by + 1) * bw * 16]             # right: our row
    header = bytearray(stock[:DDS_HEADER])
    struct.pack_into("<I", header, 16, nw)                           # width
    struct.pack_into("<I", header, 28, mips_new)                     # mip count
    struct.pack_into("<I", header, 20, blocks(nw, h)[0] * blocks(nw, h)[1] * 16)   # top-level linear size
    return bytes(header) + bytes(out), nw, h, mips_new, used


def cell_uv(cell: int, width_ratio: float = 0.5):
    """UV rect of a right-half cell (u 0.5..1 of the new texture), inside its margin."""
    cx, cy = cell % GRID, cell // GRID
    u0 = 0.5 + (cx + CELL_MARGIN) / GRID * width_ratio
    u1 = 0.5 + (cx + 1 - CELL_MARGIN) / GRID * width_ratio
    v0 = (cy + CELL_MARGIN) / GRID
    v1 = (cy + 1 - CELL_MARGIN) / GRID
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
    """(start, count): the sorted sprite records, right after the elements."""
    count = struct.unpack_from("<I", d, T_COUNT)[0]
    n = struct.unpack_from("<I", d, ELEMENT_COUNT)[0]
    start = ELEMENTS + n * ELEMENT_SIZE
    names = [struct.unpack_from("<q", d, start + k * RECORD)[0] for k in range(count)]
    if start + count * RECORD > len(d) or names != sorted(names) or 0 in names:
        raise ValueError(f"no sorted sprite table of {count} records after {n} elements")
    return start, count


def element(d, j: int, field: int, fmt: str = "<Q"):
    return struct.unpack_from(fmt, d, ELEMENTS + j * ELEMENT_SIZE + field)


def patch_canvas(d: bytes, atlas: int, new_tex: int) -> tuple:
    """The canvas's `atlas` elements on `new_tex`, every item on its own cell, LOCK
    blank. Returns (bytes, report)."""
    d = bytearray(d)
    report = []
    n = struct.unpack_from("<I", d, ELEMENT_COUNT)[0]
    texs = [element(d, j, E_TEX)[0] for j in range(n)]
    mine = texs.count(atlas)
    if not mine:
        return bytes(d), [f"no element uses {atlas:016x}; left as is"]
    others = {t for t in texs if t not in (atlas, 0) and texs.count(t) == mine}
    if others:
        raise ValueError(f"{', '.join(f'{t:016x}' for t in others)} has as many elements as the atlas: "
                         f"cannot tell their sprites apart")
    start, count = sprite_table(d)
    recs = [bytearray(d[start + k * RECORD:start + (k + 1) * RECORD]) for k in range(count)]
    copies = {}
    for r in recs:
        h = struct.unpack_from("<Q", r)[0]
        copies[h] = copies.get(h, 0) + 1
    atlas_sprites = {h for h, c in copies.items() if c == mine}       # one copy per atlas element
    for r in recs:                                                   # the atlas's sprites, halved
        if struct.unpack_from("<Q", r)[0] in atlas_sprites:
            f = struct.unpack_from("<4f", r, 8)
            struct.pack_into("<4f", r, 8, f[0] * 0.5, f[1], f[2] * 0.5, f[3])
    for j in range(n):                                               # the atlas's elements, moved
        if texs[j] == atlas:
            f = element(d, j, E_UV, "<4f")
            struct.pack_into("<Q4f", d, ELEMENTS + j * ELEMENT_SIZE + E_TEX, new_tex,
                             f[0] * 0.5, f[1], f[2] * 0.5, f[3])
    report.append(f"{mine} element(s) and {len(atlas_sprites)} sprite(s) moved to the new texture")

    names = {element(d, j, E_NAME)[0]: j for j in range(n)}
    for new_name, from_name, spare_name in REUSE:
        new, src_name, spare = symbol64(new_name), symbol64(from_name), symbol64(spare_name)
        if new in names or src_name not in names or spare not in names:
            continue
        j = names.pop(spare)
        at = ELEMENTS + j * ELEMENT_SIZE
        keep = d[at + E_INDEX:at + E_INDEX + 16]                      # its own index and parent
        src = ELEMENTS + names[src_name] * ELEMENT_SIZE
        d[at:at + ELEMENT_SIZE] = d[src:src + ELEMENT_SIZE]
        d[at + E_INDEX:at + E_INDEX + 16] = keep
        struct.pack_into("<Q", d, at + E_NAME, new)
        names[new] = j
        report.append(f"{new_name} replaces {spare_name} (e{j}, a copy of {from_name})")
    # items a canvas has no element for: a copy of a sibling (same place) becomes theirs
    for new_name, from_name in CLONES:
        new, src_name = symbol64(new_name), symbol64(from_name)
        if src_name not in names or new in names or texs[names[src_name]] != atlas:
            continue
        if n >= struct.unpack_from("<I", d, E_CAPACITY)[0]:
            raise ValueError("no room for another element")
        src = ELEMENTS + names[src_name] * ELEMENT_SIZE
        e = bytearray(d[src:src + ELEMENT_SIZE])
        idx, parent = struct.unpack_from("<qq", e, E_INDEX)
        struct.pack_into("<Q", e, E_NAME, new)
        struct.pack_into("<qq", e, E_INDEX, n, n + parent - idx)
        at = ELEMENTS + n * ELEMENT_SIZE                             # = the sprite table's start
        d[at:at] = e
        names[new] = n
        texs.append(atlas)
        n += 1
        mine += 1
        struct.pack_into("<I", d, ELEMENT_COUNT, n)
        struct.pack_into("<I", d, H_TEXTURED, struct.unpack_from("<I", d, H_TEXTURED)[0] + 1)
        struct.pack_into("<I", d, H_VERTS, struct.unpack_from("<I", d, H_VERTS)[0] + 4)
        start += ELEMENT_SIZE
        extra, seen = [], set()
        for r in recs:                                               # one more copy of each atlas sprite
            h = struct.unpack_from("<Q", r)[0]
            if h in atlas_sprites and h not in seen:
                seen.add(h)
                extra.append(bytearray(r))
        recs += extra
        report.append(f"{new_name} added (e{n - 1}, a copy of {from_name})")
    # items with a cell of their own: their element and their plain-name sprite on it
    pointed, added = [], []
    for kind, item, _ in ITEMS:
        cell = own_cells().get(item)
        if cell is None:
            continue
        uv = cell_uv(cell)
        j = names.get(symbol64(f"{kind}_{item.upper()}"))
        if j is not None and element(d, j, E_TEX)[0] == new_tex:
            struct.pack_into("<4f", d, ELEMENTS + j * ELEMENT_SIZE + E_UV, *uv)
            pointed.append(item)
        h = symbol64(item)
        mine_recs = [r for r in recs if struct.unpack_from("<Q", r)[0] == h]
        if mine_recs:
            for r in mine_recs:
                struct.pack_into("<4f", r, 8, *uv)
        else:
            recs += [bytearray(struct.pack("<Q4f", h, *uv)) for _ in range(mine)]
            added.append(item)
    report.append(f"on their own cells: {', '.join(pointed) or 'none'}")
    if added:
        report.append(f"sprites added: {', '.join(added)}")
    j = names.get(symbol64("LOCK"))
    if j is not None:                                                # the "next slot" padlock: blank
        struct.pack_into("<Q4f", d, ELEMENTS + j * ELEMENT_SIZE + E_TEX, new_tex, *cell_uv(EMPTY_CELL))
        report.append(f"LOCK (e{j}) blanked")
    recs.sort(key=lambda r: struct.unpack_from("<q", r)[0])
    d[start:start + count * RECORD] = b"".join(recs)
    cap = struct.unpack_from("<I", d, T_CAPACITY)[0]
    while cap < len(recs):
        cap *= 2
    struct.pack_into("<I", d, T_COUNT, len(recs))
    struct.pack_into("<I", d, T_CAPACITY, cap)
    struct.pack_into("<I", d, T_BYTES, cap * RECORD)
    report.append(f"sprites {count} -> {len(recs)}")
    return bytes(d), report


def symbol64_from(seed: int, text: str) -> int:
    """CSymbol64 of (the text `seed` hashes) + `text`: the hash carried on from `seed`."""
    from le_symbol_names import SEEDS
    r = seed
    for byte in text.encode():
        if 0x41 <= byte <= 0x5A:
            byte += 0x20
        r = ((r << 8) & 0xFFFFFFFFFFFFFFFF) ^ SEEDS[(r >> 56) & 0xFF] ^ byte
    return r


def patch_index(d: bytes) -> tuple:
    """The station's element index (see INDEX_CANVAS): each REUSE spare's records
    renamed to the element that took its place. Returns (bytes, report)."""
    d = bytearray(d)
    count = struct.unpack_from("<I", d, INDEX_COUNT)[0]
    start = len(d) - count * RECORD
    recs = [list(struct.unpack_from("<qQQ", d, start + k * RECORD)) for k in range(count)]
    if start <= ELEMENTS or [r[0] for r in recs] != sorted(r[0] for r in recs) \
            or any(symbol64_from(b, ".ABILITY_HEAL") != a & 0xFFFFFFFFFFFFFFFF
                   for a, b, c in recs if c == symbol64("ABILITY_HEAL")):
        raise ValueError(f"no element index of {count} records at the end of the station canvas")
    report = []
    for new_name, _, spare_name in REUSE:
        new, spare = symbol64(new_name), symbol64(spare_name)
        if any(c == new for _, _, c in recs):
            continue
        k = 0
        for r in recs:
            if r[2] == spare:
                key = symbol64_from(r[1], "." + new_name)
                r[0], r[2] = key - (1 << 64) if key >> 63 else key, new
                k += 1
        report.append(f"{spare_name} -> {new_name} in {k} slot(s)")
    recs.sort(key=lambda r: r[0])
    d[start:] = b"".join(struct.pack("<qQQ", *r) for r in recs)
    return bytes(d), report or ["already renamed"]


def read(src: str, t: str, asset: str, fallback: str = "") -> bytes:
    for p in (os.path.join(src, t, asset), os.path.join(fallback, t, asset) if fallback else "",
              os.path.join(fallback, asset) if fallback else ""):
        if p and os.path.exists(p):
            return open(p, "rb").read()
    raise FileNotFoundError(f"{t}/{asset} not found in {src}" + (f" or {fallback}" if fallback else ""))


def need_modules():
    """numpy and Pillow (the icon PNGs and the BC7 encoder): installed with pip if missing."""
    import importlib
    import subprocess
    missing = [pip for mod, pip in (("numpy", "numpy"), ("PIL", "pillow"))
               if importlib.util.find_spec(mod) is None]
    if missing:
        print(f"gear icons: installing {', '.join(missing)} (python -m pip install --user ...)")
        subprocess.run([sys.executable, "-m", "pip", "install", "--user", *missing], check=True)
        importlib.invalidate_caches()


def main(argv) -> int:
    need_modules()
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
        dds, w, h, mips, used = build_dds(stock_dds)
        new_tex = symbol64(tex_name)
        name = f"{new_tex:016x}"
        for t, blob in ((TEXTURE_GPU, dds), (TEXTURE_DESC, descriptor(stock_desc, dds, w, h, mips))):
            os.makedirs(os.path.join(args.out, t), exist_ok=True)
            open(os.path.join(args.out, t, name), "wb").write(blob)
        print(f"gear icons: {a} -> texture {name} ({tex_name}) {w}x{h}, {len(dds) >> 10} KB; "
              f"cells: {'; '.join(used)}")
        for c in canvases:
            d = read(args.src, CANVAS, c, os.path.join(fb, "canvases"))
            out, report = patch_canvas(d, atlas, new_tex)
            os.makedirs(os.path.join(args.out, CANVAS), exist_ok=True)
            open(os.path.join(args.out, CANVAS, c), "wb").write(out)
            print(f"   canvas {c}: " + "; ".join(report))
    d = read(args.src, CANVAS, INDEX_CANVAS, os.path.join(fb, "canvases"))
    out, report = patch_index(d)
    open(os.path.join(args.out, CANVAS, INDEX_CANVAS), "wb").write(out)
    print(f"gear icons: station index {INDEX_CANVAS}: " + "; ".join(report))
    return 0


if __name__ == "__main__":
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                    "data", "extract", "tools"))
    sys.exit(main(sys.argv))
