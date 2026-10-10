"""Render Repair Matrix's hand effect (be696d7d300cbaf7) offline, the way the engine does.

From the game, unchanged:
  - particle motion, life, size and colour: the effect's own Emit/Update/mesh-update
    shaders run by sim.py (colour comes out as the effect's HDR green);
  - the particle mesh (a 3D plus sign, c90ff12470c68d3b) via mesh.py;
  - every pixel's colour: the cross material's own pixel shader
    (4984e2bbb2ddb256/cbfa39eaf334b283, two rim-lighting layers) with the
    material's own parameters and texture (noise e2e43cf98919e317).

ESTIMATES (labelled on the image):
  - blending: additive, back faces culled, each cross depth-tested against itself;
  - the noise texture is sampled from a 256 px mip (the GPU picks a mip per pixel);
  - fog off; LODFADE 1; dead slots skipped instead of running the engine's visibility pass;
  - HDR -> display: Hable filmic tonemap, exposure 1 (the level sets the real one);
  - emit rate / emitter direction / effect transform, as in sim.py.

    python tools/rm_preview/render_hand.py --extract <extract root> --shaders <dir> --out <dir>
"""

from __future__ import annotations

import argparse
import math
import os
import struct

import numpy as np
from PIL import Image, ImageDraw

import assets
import dxil
import mesh
import reflect
import sim
import textures

MAT_SHADER = "cbfa39eaf334b283"
MATERIAL = ("e3e0266f1911dafa", "6d0fe1b95e82d618", 0x1A8, 0x53C)
NOISE = "e2e43cf98919e317"


def quat_rotate(q, v):
    x, y, z, w = q
    u = np.array([x, y, z])
    return v + 2.0 * np.cross(u, np.cross(u, v) + w * v)


def hable(x):
    A, B, C, D, E, F = 0.15, 0.50, 0.10, 0.20, 0.02, 0.30
    return ((x * (A * x + C * B) + D * E) / (x * (A * x + B) + D * F)) - E / F


def tonemap(hdr):
    w = 11.2
    return np.clip(hable(hdr) / hable(w), 0, 1) ** (1 / 2.2)


class Camera:
    def __init__(self, eye, target, fov_deg, w, h):
        self.eye = np.array(eye, float)
        f = np.array(target, float) - self.eye
        f /= np.linalg.norm(f)
        r = np.cross(f, [0, 1, 0])
        r /= np.linalg.norm(r)
        u = np.cross(r, f)
        self.f, self.r, self.u = f, r, u
        self.w, self.h = w, h
        self.k = (h / 2) / math.tan(math.radians(fov_deg) / 2)

    def project(self, p):
        d = p - self.eye
        z = d @ self.f
        return np.stack([self.w / 2 + (d @ self.r) / z * self.k, self.h / 2 - (d @ self.u) / z * self.k, z], -1)


class CrossShader:
    def __init__(self, extract, shader_dir):
        text = open(os.path.join(shader_dir, MAT_SHADER + "_08359.ll"), encoding="latin1").read()
        self.ps = dxil.Shader(text, "k_cross_ps")
        lay = reflect.layouts(text)
        t, a, off, size = MATERIAL
        mp = open(assets.path(extract, t, a), "rb").read()[off:off + size]
        noise = textures.load(extract, NOISE)
        step = max(1, noise.shape[0] // 256)
        noise = noise[::step, ::step]
        table = {1: dxil.Tex2D(noise), 2: dxil.Tex2D(np.zeros((1, 64, 4), np.float32))}
        sg = {"layer1_rimlighting_map_idx": 1, "layer1_rimlighting_map2_idx": 1,
              "layer2_rimlighting_map_idx": 1, "k_fog_ramp_idx": 2}
        for r in self.ps.tp.res:
            if r.cls == 0:
                self.ps.bind[r.name] = table
            elif r.cls == 3:
                self.ps.bind[r.name] = dxil.Sampler(wrap=True)
        self.ps.bind["matparamcb_decl"] = dxil.CBuf(mp)
        self.ps.bind["SGShaderInputs"] = dxil.CBuf(reflect.pack(lay["SGShaderInputs"], sg, 128))
        self.lay = lay
        self.time = 0.0

    def frame(self, cam: Camera, time: float):
        pf = bytearray(4096)
        struct.pack_into("<f", pf, 4, time)               # perframe row0.y: time (texture scroll)
        struct.pack_into("<4f", pf, 11 * 16, 0, 0, 0, 0)  # fog colour, intensity 0 -> fog off
        struct.pack_into("<4f", pf, 12 * 16, 0, 1, 0, 1)
        self.ps.bind["perframecb_decl"] = dxil.CBuf(bytes(pf))
        pv = bytearray(2048)
        struct.pack_into("<3f", pv, 0, *cam.eye)
        struct.pack_into("<3f", pv, 16, *cam.eye)
        self.ps.bind["perviewcb_decl"] = dxil.CBuf(bytes(pv))

    def shade(self, wpos, color, uv, normal, blend=(1.0, 0.0, 0.0)):
        inp = {}
        for i in range(3):
            inp[(1, 0, i)] = float(wpos[i])
            inp[(5, 0, i)] = float(normal[i])
        for i in range(4):
            inp[(2, 0, i)] = float(color[i])
        for i in range(3):
            inp[(3, 0, i)] = float(blend[i])
        inp[(4, 0, 0)], inp[(4, 0, 1)] = float(uv[0]), float(uv[1])
        inp[(9, 0, 0)] = 0
        inp[(10, 0, 0)] = 0
        inp[(11, 0, 0)] = 1.0
        out = self.ps.run_vertex(inp)
        return [out.get((0, 0, c), 0.0) for c in range(4)]


def render(sim_: sim.EffectSim, cam: Camera, shader: CrossShader, geo, dt):
    attrs, idx = geo
    P, N, UV = attrs["position0"], attrs["normal0"][:, :3], attrs["texcoord0"]
    C0, C1 = attrs["color0"], attrs["color1"]
    s = sim_.systems[0]
    hdr = np.zeros((cam.h, cam.w, 3), np.float32)
    shader.frame(cam, sim_.time)
    for inst in sim.mesh_instances(sim_, s, dt):
        if inst["scale_age"][3] <= 0.0:   # dead slot (the mesh-update shader writes a default record);
            continue                      # the engine's visibility pass culls these
        q = [x for x in inst["rot"]]
        q = np.array(q) / (np.linalg.norm(q) or 1)
        sc = np.array(inst["scale_age"][:3])
        W = np.array([quat_rotate(q, p * sc) for p in P]) + np.array(inst["pos"])
        Nw = np.array([quat_rotate(q, n) for n in N])
        scr = cam.project(W)
        zbuf = np.full((cam.h, cam.w), np.inf)
        frag = {}
        for t in idx:
            a, b, c = scr[t]
            if min(a[2], b[2], c[2]) <= 0.01:
                continue
            area = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
            if area >= 0:            # back face (screen y points down)
                continue
            x0, x1 = int(max(0, min(a[0], b[0], c[0]))), int(min(cam.w - 1, max(a[0], b[0], c[0])))
            y0, y1 = int(max(0, min(a[1], b[1], c[1]))), int(min(cam.h - 1, max(a[1], b[1], c[1])))
            for y in range(y0, y1 + 1):
                for x in range(x0, x1 + 1):
                    px, py = x + 0.5, y + 0.5
                    w0 = ((b[0] - px) * (c[1] - py) - (b[1] - py) * (c[0] - px)) / area
                    w1 = ((c[0] - px) * (a[1] - py) - (c[1] - py) * (a[0] - px)) / area
                    w2 = 1 - w0 - w1
                    if w0 < 0 or w1 < 0 or w2 < 0:
                        continue
                    # perspective-correct weights
                    iz = np.array([w0 / a[2], w1 / b[2], w2 / c[2]])
                    z = 1 / iz.sum()
                    if z >= zbuf[y, x]:
                        continue
                    zbuf[y, x] = z
                    frag[(y, x)] = (iz * z, t)
        ic = np.array(inst["color_alpha"])
        for (y, x), (bw, t) in frag.items():
            wp = bw @ W[t]
            nn = bw @ Nw[t]
            uv = bw @ UV[t]
            vc0, vc1 = bw @ C0[t], bw @ C1[t]
            # the material's vertex shader (dynvtxcolorset 0): COLOR = sat(vtx)^2.2 * sat(inst)^2.2,
            # alpha = |inst a| * vtx a (a negative particle alpha would pass the HDR colour through)
            if ic[3] < 0:
                rgb = ic[:3]
            else:
                rgb = np.clip(ic[:3], 0, 1) ** 2.2
            col = list(np.clip(vc0[:3], 0, 1) ** 2.2 * rgb) + [abs(ic[3]) * vc0[3]]
            r, g, b_, a_ = shader.shade(wp, col, uv, nn, vc1[:3])
            hdr[y, x] += np.array([r, g, b_]) * max(a_, 0.0)
    return hdr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--extract", required=True)
    ap.add_argument("--shaders", required=True, help="dir with the graph .ll files (+ global/)")
    ap.add_argument("--matshaders", required=True, help="dir with cbfa39eaf334b283_*.ll")
    ap.add_argument("--out", required=True)
    ap.add_argument("--frames", type=int, default=6)
    ap.add_argument("--size", default="480x360")
    ap.add_argument("--effect", default="be696d7d300cbaf7")
    ap.add_argument("--label", default="Repair Matrix hand effect")
    ap.add_argument("--prefix", default="hand")
    a = ap.parse_args()
    w, h = map(int, a.size.split("x"))
    os.makedirs(a.out, exist_ok=True)
    s = sim.EffectSim(a.extract, a.effect, a.shaders)
    geo = mesh.load(a.extract, s.mesh_ids[0])
    shader = CrossShader(a.extract, a.matshaders)
    cam = Camera((0.0, 0.05, 0.75), (0, 0, 0), 50, w, h)
    dt = 1 / 90
    for _ in range(60):
        s.step(dt)
    for k in range(a.frames):
        for _ in range(9):
            s.step(dt)
        hdr = render(s, cam, shader, geo, dt)
        img = (tonemap(hdr) * 255).astype(np.uint8)
        im = Image.fromarray(img)
        d = ImageDraw.Draw(im)
        d.text((6, 4), f"{a.label}  t={s.time:.2f}s  (game shaders; blend/tonemap estimated)", fill=(200, 200, 200))
        im.save(os.path.join(a.out, f"{a.prefix}_{k:02d}.png"))
        np.save(os.path.join(a.out, f"{a.prefix}_{k:02d}_hdr.npy"), hdr)
        print("frame", k, "max hdr", float(hdr.max()), "lit px", int((hdr.sum(-1) > 0).sum()))


if __name__ == "__main__":
    main()
