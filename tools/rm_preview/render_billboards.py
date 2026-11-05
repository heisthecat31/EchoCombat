"""Render a billboard particle effect offline: the game's own shaders move the particles (sim.py), this
draws them.

From the game: every particle's position (+00, 3 floats), colour (+20, 4 halves: rgb x intensity, a)
and size (+28, 2 halves, metres) out of the effect's billboard render-update shader, and the
effect's first texture (a 2x2 atlas for confetti).
ESTIMATED (not read from the engine yet): the material (texture rgb x colour, alpha = texture alpha x
colour alpha, blended back to front over a dark background), which atlas cell a particle shows (by
its index), no billboard rotation, the camera and the effect transform (sim.py: origin, scale 1).

    python tools/rm_preview/render_billboards.py --extract H:/pcvr-extracted --shaders <dir> \\
        --effect 1432f4f2b0f840df --out <dir> [--frames 6] [--every 0.5] [--eye 0,1.5,-25] [--target 0,0,0]
"""

from __future__ import annotations

import argparse
import math
import os
import struct

import numpy as np
from PIL import Image, ImageDraw

import sim
import textures
from render_hand import Camera

KIND = "k_billboardupdate_constants_decl"


def halves(rec: bytes, off: int, n: int):
    return [float(np.frombuffer(rec[off + 2 * k:off + 2 * k + 2], np.float16)[0]) for k in range(n)]


def particles(s: sim.EffectSim, dt: float, shaders):
    """(position, colour rgba, size xy, index) of every live billboard particle, all systems."""
    out = []
    for sy in s.systems:
        if not sy.billboards:
            continue
        sh = shaders.setdefault(sy.index, sim.render_shaders(s, sy))
        if KIND not in sh:
            continue
        for r in range(len(sy.billboards)):
            recs, _ = sim.render_update(s, sy, KIND, r, dt, sh)
            for i, rec in enumerate(recs):
                p = np.array(struct.unpack_from("<3f", rec, 0))
                out.append((p, halves(rec, 20, 4), halves(rec, 28, 2), i, s.texture_ids))
    return out


def render(parts, cam: Camera, atlas: np.ndarray, cells=2, bg=(0.06, 0.06, 0.07)):
    img = np.empty((cam.h, cam.w, 3), np.float32)
    img[:] = bg
    th, tw = atlas.shape[0] // cells, atlas.shape[1] // cells
    order = sorted(parts, key=lambda t: -float((t[0] - cam.eye) @ cam.f))
    for p, col, size, idx, _ in order:
        x, y, z = cam.project(p)
        if z <= 0.05:
            continue
        hw, hh = abs(size[0]) * cam.k / z / 2, abs(size[1]) * cam.k / z / 2
        x0, x1, y0, y1 = int(x - hw), int(x + hw) + 1, int(y - hh), int(y + hh) + 1
        if x1 <= 0 or y1 <= 0 or x0 >= cam.w or y0 >= cam.h or hw < 0.3:
            continue
        cx, cy = (idx % cells) * tw, ((idx // cells) % cells) * th
        xs = np.clip(((np.arange(max(x0, 0), min(x1, cam.w)) - (x - hw)) / (2 * hw) * tw).astype(int), 0, tw - 1)
        ys = np.clip(((np.arange(max(y0, 0), min(y1, cam.h)) - (y - hh)) / (2 * hh) * th).astype(int), 0, th - 1)
        tex = atlas[cy + ys[:, None], cx + xs[None, :]]
        a = np.clip(tex[..., 3] * col[3], 0, 1)[..., None]
        c = tex[..., :3] * np.array(col[:3], np.float32)
        dst = img[max(y0, 0):min(y1, cam.h), max(x0, 0):min(x1, cam.w)]
        dst[:] = dst * (1 - a) + c * a
    return img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--extract", required=True)
    ap.add_argument("--shaders", required=True)
    ap.add_argument("--effect", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--frames", type=int, default=6)
    ap.add_argument("--every", type=float, default=0.5, help="seconds between frames")
    ap.add_argument("--fps", type=float, default=30)
    ap.add_argument("--size", default="640x480")
    ap.add_argument("--eye", default="0,1.5,-25")
    ap.add_argument("--target", default="0,0,0")
    ap.add_argument("--fov", type=float, default=60)
    ap.add_argument("--label", default="")
    a = ap.parse_args()
    w, h = map(int, a.size.split("x"))
    os.makedirs(a.out, exist_ok=True)
    s = sim.EffectSim(a.extract, a.effect, a.shaders)
    atlas = textures.load(a.extract, s.texture_ids[0])
    cam = Camera(tuple(map(float, a.eye.split(","))), tuple(map(float, a.target.split(","))), a.fov, w, h)
    dt, shaders, sheet = 1 / a.fps, {}, []
    for k in range(a.frames):
        for _ in range(max(1, round(a.every * a.fps))):
            s.step(dt)
        parts = particles(s, dt, shaders)
        img = render(parts, cam, atlas)
        im = Image.fromarray((np.clip(img, 0, 1) ** (1 / 2.2) * 255).astype(np.uint8))
        ImageDraw.Draw(im).text((6, 4), f"{a.label or a.effect}  t={s.time:.2f}s  {len(parts)} particles "
                                         f"(game shaders; material/blend estimated)", fill=(200, 200, 200))
        im.save(os.path.join(a.out, f"{a.effect}_{k:02d}.png"))
        sheet.append(im)
        print("frame", k, f"t={s.time:.2f}", len(parts), "particles")
    cols = min(3, len(sheet))
    rows = (len(sheet) + cols - 1) // cols
    big = Image.new("RGB", (w * cols, h * rows))
    for k, im in enumerate(sheet):
        big.paste(im, ((k % cols) * w, (k // cols) * h))
    big.save(os.path.join(a.out, f"{a.effect}_sheet.png"))


if __name__ == "__main__":
    main()
