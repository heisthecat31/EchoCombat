"""Draws the gear icons that have no art yet, in the style of the others (flat white,
thick strokes with cut ends, bracket arcs and a centre dot), into ICONS/hd/:

* smoke.png  UMBRAL VEIL: a dot behind three drifting smoke bands, inside open brackets
* buff.png   POWER BOOST: a double chevron rising out of a dot, inside open brackets
* point.png  POINT: a marker pin (a broken ring that narrows to a point) over a dot

Drawn at 4096 px and scaled to 1024 with Lanczos, so the edges come out anti-aliased.

    python tools/make_icons.py
"""

from __future__ import annotations

import math
import os

from PIL import Image, ImageChops, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "ICONS", "hd")
S = 4096                                   # drawing size
W = int(S * 0.075)                         # stroke width (the others use about this)
WHITE = (255, 255, 255, 255)


def canvas():
    im = Image.new("RGBA", (S, S), (255, 255, 255, 0))
    return im, ImageDraw.Draw(im)


def arc(d, cx, cy, r, a0, a1, w=W, steps=64):
    """A thick arc from a0 to a1 degrees (0 = right, counter-clockwise, y up) with flat
    (radial) ends, as a polygon."""
    pts_out, pts_in = [], []
    for k in range(steps + 1):
        a = math.radians(a0 + (a1 - a0) * k / steps)
        pts_out.append((cx + (r + w / 2) * math.cos(a), cy - (r + w / 2) * math.sin(a)))
        pts_in.append((cx + (r - w / 2) * math.cos(a), cy - (r - w / 2) * math.sin(a)))
    d.polygon(pts_out + pts_in[::-1], fill=WHITE)


def dot(d, cx, cy, r):
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=WHITE)


def brackets(d, r=S * 0.36, span=50):
    """The pair of open arcs most of the set is framed by: ( and )."""
    c = S / 2
    arc(d, c, c, r, 180 - span, 180 + span)
    arc(d, c, c, r, -span, span)


def band(d, y, x0, x1, w=W, wave=S * 0.012, steps=80, fill=WHITE):
    """A thick, gently waving horizontal band with flat ends."""
    top, bot = [], []
    for k in range(steps + 1):
        x = x0 + (x1 - x0) * k / steps
        off = wave * math.sin(2 * math.pi * (k / steps) * 1.5)
        top.append((x, y + off - w / 2))
        bot.append((x, y + off + w / 2))
    d.polygon(top + bot[::-1], fill=fill)


def chevron(d, cx, tip_y, half, depth, w=W):
    """An upward chevron: tip at (cx, tip_y), arms reaching `half` out and `depth` down,
    cut square at the arm ends."""
    t = w / math.cos(math.atan2(depth, half))     # vertical thickness of an arm
    d.polygon([(cx, tip_y), (cx + half, tip_y + depth), (cx + half, tip_y + depth + t),
               (cx, tip_y + t), (cx - half, tip_y + depth + t), (cx - half, tip_y + depth)], fill=WHITE)


SMOKE_BANDS = ((-0.05, -0.21, 0.13), (0.08, -0.13, 0.21), (0.21, -0.19, 0.07))  # (y, x0, x1) / S from the centre


def smoke():
    im, d = canvas()
    c = S / 2
    dot(d, c, c - S * 0.15, S * 0.075)                             # the one the veil hides
    gaps = Image.new("L", (S, S), 255)                              # a clear gap round each band
    g = ImageDraw.Draw(gaps)
    for y, x0, x1 in SMOKE_BANDS:
        band(g, c + S * y, c + S * x0 - W * 0.6, c + S * x1 + W * 0.6, w=W * 2.2, fill=0)
    im.putalpha(ImageChops.multiply(im.split()[3], gaps))
    d = ImageDraw.Draw(im)
    brackets(d)                                                     # after the gaps: left whole
    for y, x0, x1 in SMOKE_BANDS:
        band(d, c + S * y, c + S * x0, c + S * x1)
    return im


def buff():
    im, d = canvas()
    c = S / 2
    brackets(d)
    dot(d, c, c + S * 0.17, S * 0.07)
    chevron(d, c, c - S * 0.27, S * 0.17, S * 0.15)
    chevron(d, c, c - S * 0.09, S * 0.17, S * 0.15)
    return im


def pin_shape(cx, cy, r, tip):
    """A filled pin: the circle (cx, cy, r) and the tangent triangle down to (cx, tip)."""
    m = Image.new("L", (S, S), 0)
    g = ImageDraw.Draw(m)
    g.ellipse((cx - r, cy - r, cx + r, cy + r), fill=255)
    a = math.acos(r / (tip - cy))                                   # tangent points at 270 -+ a
    pts = [(cx + r * math.cos(t), cy - r * math.sin(t)) for t in (1.5 * math.pi - a, 1.5 * math.pi + a)]
    g.polygon([pts[0], (cx, tip), pts[1], (cx, cy)], fill=255)
    return m


def point():
    """A pin outline, open at the top, with a dot inside and a tick either side."""
    im, d = canvas()
    c = S / 2
    cy, r = c - S * 0.10, S * 0.22         # the ring
    tip = c + S * 0.36
    k = (tip - cy) / r                     # keep the outline's width even down to the tip
    outer = pin_shape(c, cy, r + W / 2, cy + (r + W / 2) * k)
    inner = pin_shape(c, cy, r - W / 2, cy + (r - W / 2) * k)
    ring = ImageChops.subtract(outer, inner)
    g = ImageDraw.Draw(ring)
    gap = math.radians(10)                                          # the style gap at the top
    g.polygon([(c, cy), (c + 2 * S * math.cos(math.pi / 2 - gap), cy - 2 * S * math.sin(math.pi / 2 - gap)),
               (c + 2 * S * math.cos(math.pi / 2 + gap), cy - 2 * S * math.sin(math.pi / 2 + gap))], fill=0)
    im.putalpha(ring)
    d = ImageDraw.Draw(im)
    dot(d, c, cy, S * 0.075)
    for side in (-1, 1):                                            # a tick out from each side
        x0 = c + side * (r + W * 1.2)
        x1 = c + side * (r + W * 1.2 + S * 0.08)
        d.rectangle((min(x0, x1), cy - W / 2, max(x0, x1), cy + W / 2), fill=WHITE)
    return im


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    for name, draw in (("smoke", smoke), ("buff", buff), ("point", point)):
        im = draw().resize((1024, 1024), Image.LANCZOS)
        im.save(os.path.join(OUT, f"{name}.png"))
        print("wrote", os.path.join(OUT, f"{name}.png"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
