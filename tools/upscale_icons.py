"""ICONS/<name>.png -> ICONS/hd/<gear name>.png: 1024x1024 with crisp edges.

Each icon is upscaled 4x (Lanczos), its alpha smoothed and re-cut into a hard
anti-aliased edge (so blur and wobble in the source go), and scaled to 1024x1024.
White on transparent, shapes and placement unchanged. The output is named after the
gear item gear_icons.py looks for (veil.png -> smoke.png, ...).

    python tools/upscale_icons.py                 # every PNG in ICONS/
    python tools/upscale_icons.py veil.png buff.png
"""

from __future__ import annotations

import os
import sys

import numpy as np
from PIL import Image, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "ICONS")
OUT = os.path.join(SRC, "hd")
#: file stem (lower case) -> the gear name gear_icons.py matches, when they differ
RENAME = {"veil": "smoke", "umbral veil": "smoke", "power boost": "buff"}


def sharpen(im: Image.Image, size: int = 1024) -> Image.Image:
    im = im.convert("RGBA")
    big = im.resize((im.width * 4, im.height * 4), Image.LANCZOS)
    a = np.asarray(big.split()[3].filter(ImageFilter.GaussianBlur(6.0))).astype(np.float32) / 255
    t = np.clip((a - 0.5) / 0.06 + 0.5, 0, 1)
    t = t * t * (3 - 2 * t)
    rgb = np.full(a.shape + (3,), 255, np.uint8)
    return Image.fromarray(np.dstack([rgb, (t * 255).astype(np.uint8)]), "RGBA").resize((size, size), Image.LANCZOS)


def main(argv) -> int:
    names = argv[1:] or sorted(f for f in os.listdir(SRC) if f.lower().endswith(".png"))
    os.makedirs(OUT, exist_ok=True)
    for f in names:
        stem = os.path.splitext(f)[0].lower()
        out = os.path.join(OUT, RENAME.get(stem, stem) + ".png")
        sharpen(Image.open(os.path.join(SRC, f))).save(out)
        print(f"{f} -> {os.path.relpath(out, ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
