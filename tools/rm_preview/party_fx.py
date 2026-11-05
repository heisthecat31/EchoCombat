"""Party gun confetti: our own pieces and our own burst.

The pieces: a 2x2 sheet per team (sheet()), four shapes, each in its own shade, so every piece of a
burst has its colour baked in (blue team: blue, purple, cyan, violet; orange team: orange, red,
gold, coral): a folded paper strip, a curled ribbon, a square flake, a thin streamer. Written as a
BC7 sRGB texture (streaming off, gear_icons / drone-model style).

The burst: a billboard effect container (the round-win confetti's, 1432f4f2b0f840df: one system,
one burst emitter, the game's compiled particle shaders for it) with every number ours:

  system  +198h max count, +19Ch / +1A0h life (s)
  emitter +3Ch / +40h burst count, +44h / +48h re-burst interval (s), +70h / +7Ch box corners (m),
          +98h / +9Ch cone angles (deg),
          +A0h / +A4h speed (m/s)
  params  (the system's parameter blob, found by offline probing with the game's shaders,
          tools/rm_preview/sim.py): +64h piece size (m, half), +6Ch / +78h / +84h colour r g b
          (halves: white, the sheet carries the colour), +2Ch brightness, +16h alpha, +56h drag,
          +92h..+A6h air (force field response), +5Eh / +8Eh fall (halves)
  textures root array [2]: the first (the piece sheet) -> the team's sheet

so a shot throws a dense, narrow stream of small pieces out along the effect's +Y that flutters
shoots out fast, brakes to a stop about 1.2 m out and fades (the reference GIFs,
docs/party_guns_ref/; a little longer than them).

    from party_fx import party_effect, sheet
"""

from __future__ import annotations

import math
import struct

import numpy as np

import effect_file as ef

CONTAINER = "1432f4f2b0f840df"               # pfx_test_jasonw_roomscale_confetti: the container
SOURCES = {"orange": CONTAINER, "blue": CONTAINER}
TEAMS = {
    "blue": [(0.10, 0.35, 1.00), (0.58, 0.28, 1.00), (0.15, 0.85, 1.00), (0.85, 0.40, 1.00)],
    "orange": [(1.00, 0.45, 0.06), (1.00, 0.12, 0.08), (1.00, 0.80, 0.15), (1.00, 0.35, 0.40)],
}
DEFAULTS = dict(count=264, life=(1.5, 2.5), burst=(204, 252), box=0.03, cone=(0.0, 9.0), speed=(0.4, 1.8),
                size=0.07, brightness=1.6, alpha=2.0, drag=0.3, air=1.0)
#: emitter +44h / +48h: the re-burst interval (s); the container's 16 re-burst the confetti for as
#: long as the effect lived, which looked like the gun firing by itself (tested 2026-11-05)
REBURST_S = 1000.0
P_ALPHA, P_SIZE, P_R, P_G, P_B, P_BRIGHT = 0x16, 0x64, 0x6C, 0x78, 0x84, 0x2C
#: probed 2026-11-05: +56h drag; +92h..+A6h (six, 1.875 in the container): how much the world's force
#: fields (the shader's forces / gforcegrid: the level's air) move a piece -- offline (no forces) they
#: change nothing, in game at full they made the room confetti drift anywhere, at 0 the pieces sat
#: still; +5Eh, +8Eh a fall along the effect's -Y, which on the gun is back towards the barrel
P_DRAG = 0x56
P_NOISE = (0x92, 0x96, 0x9A, 0x9E, 0xA2, 0xA6)
AIR_STOCK = 1.875
P_FALL = (0x5E, 0x8E)


def _half(b: bytearray, o: int, v: float):
    b[o:o + 2] = np.float16(v).tobytes()


def party_effect(data: bytes, sheet_id: int, **over) -> bytes:
    """The container with our burst and the team's piece sheet `sheet_id`."""
    o = dict(DEFAULTS)
    o.update({k: v for k, v in over.items() if v is not None})
    b = bytearray(data)
    tree = ef.parse(data)
    for sy in tree.arrays[0].elems:
        struct.pack_into("<I", b, sy.at + 0x198, int(o["count"]))
        struct.pack_into("<ff", b, sy.at + 0x19C, *o["life"])
        arrs = {x.at - sy.at: x for x in sy.arrays}
        p = arrs[0x18].data
        _half(b, p + P_SIZE, o["size"])
        for off in (P_R, P_G, P_B):
            _half(b, p + off, 1.0)
        _half(b, p + P_BRIGHT, o["brightness"])
        _half(b, p + P_ALPHA, o["alpha"])                # over 1: soft edges and blending read solid
        _half(b, p + P_DRAG, o["drag"])                  # out fast, stops ~1.2 m out (the GIF)
        for off in P_NOISE:                              # the level's air moves them a little (float)
            _half(b, p + off, AIR_STOCK * o["air"])
        for off in P_FALL:                               # no fall along the stream (back to the gun)
            _half(b, p + off, 0.0)
        for em in sy.arrays[1].elems:
            e = em.at
            struct.pack_into("<ff", b, e + 0x3C, *map(float, o["burst"]))
            struct.pack_into("<ff", b, e + 0x44, REBURST_S, REBURST_S)   # one burst per shot
            h = o["box"] / 2
            struct.pack_into("<fff", b, e + 0x70, -h, -h, -h)
            struct.pack_into("<fff", b, e + 0x7C, h, h, h)
            struct.pack_into("<ff", b, e + 0x98, *o["cone"])
            struct.pack_into("<ff", b, e + 0xA0, *o["speed"])
    tex = tree.arrays[2].elems[0].at                 # the first texture: the piece sheet
    struct.pack_into("<Q", b, tex, sheet_id)
    ef.parse(bytes(b))                               # still a valid effect file
    return bytes(b)


def empty_effect(data: bytes) -> bytes:
    """A burst of no particles (the muzzle node's other trigger frames)."""
    b = bytearray(data)
    tree = ef.parse(data)
    for sy in tree.arrays[0].elems:
        struct.pack_into("<I", b, sy.at + 0x198, 1)
        for em in sy.arrays[1].elems:
            struct.pack_into("<ff", b, em.at + 0x3C, 0.0, 0.0)
    return bytes(b)


# --- the piece sheets ---------------------------------------------------------------------
N, CELL, SS = 256, 128, 4                        # sheet size, cell size, supersampling


def _band(n, path, width):
    """A smooth band along `path` (points in 0..1 cell units), as a 0..1 mask (n x n)."""
    from PIL import Image, ImageDraw
    m = Image.new("L", (n, n))
    d = ImageDraw.Draw(m)
    r = width * n / 2
    for x, y in path:                            # round stamps: no jagged joints
        d.ellipse((x * n - r, y * n - r, x * n + r, y * n + r), fill=255)
    return np.asarray(m, np.float32) / 255


def _shapes():
    from PIL import Image, ImageDraw
    n = CELL * SS
    yy, xx = np.mgrid[0:n, 0:n].astype(np.float32) / n - 0.5
    out = []
    m = Image.new("L", (n, n)); d = ImageDraw.Draw(m)            # folded paper strip
    d.polygon([(0.12 * n, 0.36 * n), (0.88 * n, 0.30 * n), (0.86 * n, 0.62 * n), (0.10 * n, 0.68 * n)], fill=255)
    out.append((np.asarray(m, np.float32) / 255, np.where(xx < 0.02 - 0.15 * yy, 1.0, 0.72)))
    t = np.linspace(0, 1, 400)                                    # curled ribbon
    path = list(zip(0.12 + 0.76 * t, 0.5 + 0.17 * np.sin(t * 2 * math.pi * 1.5)))
    out.append((_band(n, path, 0.14), 0.65 + 0.35 * np.cos((xx + 0.5) * 2 * math.pi * 1.5) ** 2))
    m = Image.new("L", (n, n)); d = ImageDraw.Draw(m)            # square flake
    c, r, a = 0.5 * n, 0.32 * n, math.radians(17)
    d.polygon([(c + r * math.cos(a + k * math.pi / 2), c + r * math.sin(a + k * math.pi / 2) * 0.82) for k in range(4)],
              fill=255)
    out.append((np.asarray(m, np.float32) / 255, np.clip(1.0 - 0.45 * (xx + yy + 0.5), 0.6, 1.0)))
    path = list(zip(0.08 + 0.84 * t, 0.5 + 0.27 * np.sin(t * 2 * math.pi) * (0.4 + 0.6 * t)))   # thin streamer
    out.append((_band(n, path, 0.08), 0.7 + 0.3 * np.abs(np.sin((xx + 0.5) * 2 * math.pi))))
    return out


def sheet(team: str) -> np.ndarray:
    """The team's piece sheet, RGBA uint8 (N, N, 4), sRGB colour."""
    from PIL import Image
    img = np.zeros((N, N, 4), np.float32)
    for k, ((mask, shade), rgb) in enumerate(zip(_shapes(), TEAMS[team])):
        rgba = np.zeros(mask.shape + (4,), np.float32)
        rgba[..., :3] = np.array(rgb, np.float32) * shade[..., None]
        rgba[..., 3] = mask
        cell = Image.fromarray((np.clip(rgba, 0, 1) * 255).astype(np.uint8), "RGBA").resize((CELL, CELL), Image.LANCZOS)
        cx, cy = (k % 2) * CELL, (k // 2) * CELL
        img[cy:cy + CELL, cx:cx + CELL] = np.asarray(cell, np.float32) / 255
    return (img * 255).astype(np.uint8)
