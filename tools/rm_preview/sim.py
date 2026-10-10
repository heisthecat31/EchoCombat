"""Simulate a particle effect with the game's own GPU shaders (run on the CPU by dxil.py).

What comes from the game, unchanged:
  - the effect file (effect_file.py): systems, emitters, param blobs, textures;
  - the per-effect Emit / Update / render-update shaders (77fc096173af254c);
  - the engine's reclaim shader (635f6220ae85fd46/e171e5d8145c9c6b);
  - how the CPU packs SPSystemDataPacked and SEmitterDataPacked, ported from
    echovr.exe (fcn.14059f6d0 and fcn.140538be0), including its truncating
    float -> half conversion.

What is estimated (marked ESTIMATE below): how many particles an emitter emits
per frame (the CPU code that sets it was not found; the emitter's rate fields
+0x2c/+0x30 are taken as particles per second), the emitter's initial velocity
direction, and the effect instance's transform (origin, no rotation, scale 1).

    sim = EffectSim(extract_root, effect_id)
    for _ in range(n): sim.step(1 / 90)
    sim.particles(system)   # live particles, raw 96-byte records
"""

from __future__ import annotations

import math
import os
import random
import struct

import numpy as np

import assets

import dxil
import effect_file as ef
import reflect
import textures

PSYS_STRIDE, EMITTER_STRIDE = 84, 92
EFFECT_DIR = "3ae7c41914252baa"
SHADER_CODE = "77fc096173af254c"
RECLAIM = ("635f6220ae85fd46", "e171e5d8145c9c6b")


def ehalf(f):
    """The engine's float -> half (fcn.14059f6d0): truncating, clamped to 65504, flush to zero."""
    u = struct.unpack("<I", struct.pack("<f", f))[0]
    a = u & 0x7FFFFFFF
    if a <= 0x37FFFFFF:
        return 0
    h = 0x7BFF if a > 0x477FFFFF else ((a * 8 + 0x40000000) >> 16) & 0xFFFF
    return h | ((u >> 16) & 0x8000)


def snorm16(x):
    return int(max(-1.0, min(1.0, x)) * 32767.0) & 0xFFFF


def u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def f32(b, o):
    return struct.unpack_from("<f", b, o)[0]


class Registry:
    """One bindless index space: every resource gets an id, valid in every table."""

    def __init__(self):
        self.table = {}
        self.ids = {}

    def add(self, name, obj):
        i = len(self.table) + 1
        self.table[i] = obj
        self.ids[name] = i
        return i


class System:
    def __init__(self, data: bytes, elem: ef.Struct, index: int):
        a = elem.at
        self.index = index
        self.graph = u32(data, a + 0x188)
        self.psize = u32(data, a + 0x18C)
        self.maxcount = u32(data, a + 0x198)
        self.life = (f32(data, a + 0x19C), f32(data, a + 0x1A0))
        self.maxtimestep = f32(data, a + 0x1A8)
        self.gforce = (f32(data, a + 0x1C0), struct.unpack_from("<H", data, a + 0x1C4)[0])
        arrs = {x.at - a: x for x in elem.arrays}
        blob = arrs.get(0x18)
        self.params = data[blob.data:blob.data + blob.size] if blob and blob.size else b""
        self.emitters = [data[e.at:e.at + e.size] for e in arrs[0x38].elems] if 0x38 in arrs else []
        self.billboards = [data[e.at:e.at + e.size] for e in arrs[0xA8].elems] if 0xA8 in arrs else []
        self.meshes = [data[e.at:e.at + e.size] for e in arrs[0xE0].elems] if 0xE0 in arrs else []
        self.ribbons = [data[e.at:e.at + e.size] for e in arrs[0x118].elems] if 0x118 in arrs else []
        self.emit_accum = [0.0] * len(self.emitters)
        self.burst_done = [False] * len(self.emitters)


class EffectSim:
    def __init__(self, root: str, effect: str, shader_dir: str, seed=1):
        self.root, self.effect = root, effect
        self.data = open(assets.path(root, EFFECT_DIR, effect), "rb").read()
        self.tree = ef.parse(self.data)
        r = self.tree.arrays
        ids = lambda a: [struct.unpack_from("<Q", self.data, e.at)[0] for e in a.elems]
        self.graph_ids = [f"{x:016x}" for x in ids(r[1])]
        self.texture_ids = [f"{x:016x}" for x in ids(r[2])]
        self.mesh_ids = [f"{x:016x}" for x in ids(r[3])]
        self.systems = [System(self.data, e, i) for i, e in enumerate(r[0].elems)]
        self.rng = random.Random(seed)
        self.time = 0.0
        self.shader_dir = shader_dir
        self._load_shaders()
        self._alloc()

    # ------------------------------------------------------------ setup
    def _load_shaders(self):
        """Per graph: {'emit','update','render'} Shader objects (by their constant buffer's name)."""
        self.graphs = []
        for gid in self.graph_ids:
            kinds = {}
            for fn in sorted(os.listdir(self.shader_dir)):
                if fn.startswith(gid) and fn.endswith(".ll"):
                    text = open(os.path.join(self.shader_dir, fn), encoding="latin1").read()
                    lay = reflect.layouts(text)
                    sh = dxil.Shader(text, "k_" + fn[:-3])
                    sh.layout = lay
                    if "k_emit_constants_decl" in lay:
                        kinds["emit"] = sh
                    elif "k_update_constants_decl" in lay:
                        kinds["update"] = sh
                    else:
                        kinds["render"] = sh
                        kinds["render_kind"] = next(k for k in lay if k.endswith("update_constants_decl"))
            self.graphs.append(kinds)
        text = open(os.path.join(self.shader_dir, "global", RECLAIM[1] + "_00000.ll"), encoding="latin1").read()
        self.reclaim = dxil.Shader(text, "k_reclaim")
        self.reclaim.layout = reflect.layouts(text)

    def _alloc(self):
        n = len(self.systems)
        self.reg = Registry()
        params, poff = bytearray(), 0
        self.particles = dxil.RawBuf(size=sum(s.maxcount * s.psize for s in self.systems) + 16)
        bs_total = 0
        for s in self.systems:
            s.paramoffs = len(params)
            params += s.params + bytes((-len(s.params)) % 16)
            s.pbyteoffs = poff
            poff += s.maxcount * s.psize
            s.blockstatusoffs = bs_total
            bs_total += (s.maxcount + 63) // 64
        self.sysparams = dxil.RawBuf(bytes(params) + bytes(64))
        self.offsets = dxil.TypedBuf(n, 1)
        self.counts = dxil.TypedBuf(n, 1)
        self.blockstatus = dxil.TypedBuf(max(bs_total, 1), 2)
        self.psys = dxil.StructBuf(size=n * PSYS_STRIDE, stride=PSYS_STRIDE)
        self.emitters = dxil.StructBuf(size=EMITTER_STRIDE * 64, stride=EMITTER_STRIDE)
        self.events = dxil.StructBuf(size=28 * 4, stride=28)
        self.eventcounts = dxil.TypedBuf(n, 1)
        self.meshtris = dxil.StructBuf(size=20 * 4, stride=20)
        self.meshverts = dxil.StructBuf(size=28 * 4, stride=28)
        self.batchsys = dxil.TypedBuf(n, 1)
        self.curve = dxil.Tex2D(np.zeros((1, 32), np.float32))
        for t in self.texture_ids:
            w, h, fmt, _ = textures.raw(self.root, t)
            if w == 32 and fmt == 61:            # the baked curve texture: 32 x curves, R8
                self.curve = dxil.Tex2D(textures.load(self.root, t)[:, :, 0])
        self.sampler = dxil.Sampler(wrap=False)
        for name, obj in [("systems", self.psys), ("sysparams", self.sysparams), ("offsets", self.offsets),
                          ("counts", self.counts), ("emitters", self.emitters), ("events", self.events),
                          ("eventcounts", self.eventcounts), ("meshemittris", self.meshtris),
                          ("meshemitverts", self.meshverts), ("curve_tex", self.curve),
                          ("batchsysindices", self.batchsys), ("blockstatus", self.blockstatus),
                          ("particles", self.particles), ("forces", dxil.StructBuf(size=64, stride=16)),
                          ("gforceindices", dxil.TypedBuf(4, 1)), ("gforcegrid", dxil.TypedBuf(4, 1)),
                          ("lowresdepthmap", dxil.Tex2D(np.ones((4, 4), np.float32))),
                          ("lowrescolormap", dxil.Tex2D(np.zeros((4, 4, 4), np.float32)))]:
            self.reg.add(name, obj)

    # ------------------------------------------------------------ packing (ported from echovr.exe)
    def pack_psys(self, s: System, randseed: int):
        b = bytearray(PSYS_STRIDE)
        lo, hi = min(s.life), max(s.life)
        struct.pack_into("<IIIIIIIII", b, 0, 0, s.paramoffs, len(s.params), s.pbyteoffs, s.psize,
                         s.blockstatusoffs, 0xFFFFFFFF, s.maxcount, randseed)
        struct.pack_into("<HH", b, 36, ehalf(lo), ehalf(hi))
        struct.pack_into("<HH", b, 40, ehalf(s.gforce[0]), s.gforce[1])
        struct.pack_into("<II", b, 44, 0, 0)                       # no local forces
        struct.pack_into("<HH", b, 52, ehalf(1.0), ehalf(0.0))     # ESTIMATE: effect scale 1, no warmup
        struct.pack_into("<fff", b, 56, 0.0, 0.0, 0.0)             # ESTIMATE: effect at the origin
        struct.pack_into("<HHHH", b, 68, 0, 0, 0, 32767)           # identity rotation
        struct.pack_into("<HH", b, 76, ehalf(self.time % 60.0), ehalf(1.0))
        struct.pack_into("<f", b, 80, s.maxtimestep)
        return bytes(b)

    def pack_emitter(self, d: bytes, index: int, emitoffset: int, count: int, idoffs: int):
        b = bytearray(EMITTER_STRIDE)
        scale = 1.0
        p = [f32(d, 0x70 + 4 * i) * scale for i in range(3)]
        q = [f32(d, 0x7C + 4 * i) * scale for i in range(3)]
        inner = [min(a, c) for a, c in zip(p, q)]
        outer = [max(a, c) for a, c in zip(p, q)]
        struct.pack_into("<III", b, 0, emitoffset, count, idoffs)
        struct.pack_into("<HH", b, 12, index, struct.unpack_from("<H", d, 0x54)[0])
        struct.pack_into("<I", b, 16, 0xFFFFFFFF)
        struct.pack_into("<fff", b, 20, 0.0, 0.0, 0.0)
        struct.pack_into("<HHHH", b, 32, 0, 0, 0, 32767)
        struct.pack_into("<HHHH", b, 40, *(ehalf(x) for x in inner), u32(d, 0x20) & 0xFFFF)
        struct.pack_into("<HHHH", b, 48, *(ehalf(x) for x in outer), u32(d, 0x1C) & 0xFFFF)
        rad = math.pi / 180
        struct.pack_into("<HH", b, 56, ehalf(f32(d, 0x98) * rad), ehalf(f32(d, 0x9C) * rad))
        struct.pack_into("<HH", b, 60, ehalf(f32(d, 0xA0)), ehalf(f32(d, 0xA4)))
        struct.pack_into("<HH", b, 64, ehalf(f32(d, 0xA8)), ehalf(f32(d, 0xAC)))
        struct.pack_into("<HHHH", b, 68, ehalf(0.0), ehalf(1.0), ehalf(0.0), ehalf(f32(d, 0x88)))  # ESTIMATE dir +Y
        burstvar = min(int(abs(f32(d, 0x40) - f32(d, 0x3C))), 0xFFFF)
        struct.pack_into("<HHHH", b, 76, 0, 0, 0, burstvar)
        struct.pack_into("<II", b, 84, u32(d, 0x14), u32(d, 0x18))
        return bytes(b)

    # ------------------------------------------------------------ running shaders
    def _bind(self, sh, constants: dict, uavs: dict):
        for r in sh.tp.res:
            if r.cls == 0:
                sh.bind[r.name] = self.reg.table
            elif r.cls == 3:
                sh.bind[r.name] = self.sampler
        for name, obj in uavs.items():
            sh.bind[name] = obj
        for cb, vals in constants.items():
            sh.bind[cb] = dxil.CBuf(reflect.pack(sh.layout[cb], vals))
        # SGShaderInputs: every *_idx field points at our registry id
        sg = {}
        for fname, _, _ in sh.layout.get("SGShaderInputs", []):
            key = fname[2:] if fname.startswith("k_") else fname
            key = key[:-4] if key.endswith("_idx") else key
            if key in self.reg.ids:
                sg[fname] = self.reg.ids[key]
        sh.bind["SGShaderInputs"] = dxil.CBuf(reflect.pack(sh.layout["SGShaderInputs"], sg, 64))

    def step(self, dt: float):
        self.time += dt
        n = len(self.systems)
        self.psys.b[:] = b"".join(self.pack_psys(s, self.rng.getrandbits(32)) for s in self.systems)
        # 1. emit
        for s in self.systems:
            g = self.graphs[s.graph]
            rows, total = [], 0
            for i, d in enumerate(s.emitters):
                rate = self.rng.uniform(f32(d, 0x2C), f32(d, 0x30))          # ESTIMATE: particles / s
                s.emit_accum[i] += rate * dt
                cnt = int(s.emit_accum[i])
                s.emit_accum[i] -= cnt
                if not s.burst_done[i]:
                    cnt += int(self.rng.uniform(f32(d, 0x3C), f32(d, 0x40)))  # ESTIMATE: burst at start
                    s.burst_done[i] = True
                if cnt:
                    rows.append(self.pack_emitter(d, i, total, cnt, 0))
                    total += cnt
            if not total:
                continue
            self.emitters.b[:len(rows) * EMITTER_STRIDE] = b"".join(rows)
            sh = g["emit"]
            self._bind(sh, {"k_emit_constants_decl": dict(k_systemidx=s.index, k_deltatime=dt,
                                                         k_numemitters=len(rows), k_emitteroffs=0,
                                                         k_projectiona=1.0, k_projectionb=0.0)},
                       {"k_particles_decl": self.particles, "k_counts_decl": self.counts})
            sh.dispatch(((total + 63) // 64, 1, 1))
        # 2. update (one dispatch per system; group y picks the system through batchsysindices)
        for s in self.systems:
            sh = self.graphs[s.graph]["update"]
            self.batchsys.a[0][0] = s.index
            self._bind(sh, {"k_update_constants_decl": dict(k_deltatime=dt, k_batchoffset=0,
                                                           k_projectiona=1.0, k_projectionb=0.0,
                                                           k_disabledepthread=1)},
                       {"k_particles_decl": self.particles, "k_blockstatus_decl": self.blockstatus})
            sh.dispatch(((s.maxcount + 63) // 64, 1, 1))
        # 3. reclaim dead blocks (engine shader)
        sh = self.reclaim
        self._bind(sh, {}, {"offsets_decl": self.offsets, "counts_decl": self.counts})
        sh.bind["gBlockTable"] = self.reg.table
        sh.bind["SGShaderInputs"] = dxil.CBuf(reflect.pack(sh.layout["SGShaderInputs"],
                                                          dict(systems_idx=self.reg.ids["systems"],
                                                               blockstatus_idx=self.reg.ids["blockstatus"]), 16))
        sh.dispatch(((n + 63) // 64, 1, 1))

    # ------------------------------------------------------------ inspection
    def live(self, s: System):
        """[(slot, raw 96-byte record)] for the live ring range of system s."""
        head, count = self.offsets.a[s.index][0], self.counts.a[s.index][0]
        out = []
        for k in range(count):
            slot = (head + k) % s.maxcount
            o = s.pbyteoffs + slot * s.psize
            out.append((slot, bytes(self.particles.b[o:o + s.psize])))
        return out


# ------------------------------------------------------------ render-update passes
def _half(u):
    return float(np.frombuffer(struct.pack("<H", u & 0xFFFF), np.float16)[0])


def _snorm(u):
    v = u - 0x10000 if u & 0x8000 else u
    return max(-1.0, v / 32767.0)


def mesh_instances(sim: EffectSim, s: System, dt: float):
    """Run the graph's mesh-update shader for system s; returns a list of decoded SMeshParticlePacked."""
    g = sim.graphs[s.graph]
    sh = g["render"]
    out = dxil.StructBuf(size=60 * s.maxcount, stride=60)
    batch = dxil.StructBuf(struct.pack("<IIII", s.index, 0, 0, 0), stride=16)
    renderdata = dxil.RawBuf(bytes(64))
    for name, obj in [("renderdata", renderdata), ("mbatchconstants", batch)]:
        if name not in sim.reg.ids:
            sim.reg.add(name, obj)
        else:
            sim.reg.table[sim.reg.ids[name]] = obj
    sim._bind(sh, {g["render_kind"]: dict(k_deltatime=dt, k_batchoffset=0, k_numvalid=1)},
              {"k_output_decl": out})
    sh.dispatch(((s.maxcount + 63) // 64, 1, 1))
    res = []
    for i in range(sim.counts.a[s.index][0]):
        o = i * 60
        b = out.b
        pos = struct.unpack_from("<3f", b, o)
        h = struct.unpack_from("<20H", b, o + 12)
        res.append(dict(pos=pos, vel=[_half(x) for x in h[0:4]],
                        rot=[_snorm(x) for x in h[4:8]], prevrot=[_snorm(x) for x in h[8:12]],
                        scale_age=[_half(x) for x in h[12:16]], prevscale_inst=[_half(x) for x in h[16:20]],
                        color_alpha=[_half(x) for x in struct.unpack_from("<4H", b, o + 52)]))
    return res


# ------------------------------------------------------------ generic render-update (billboard / ribbon / mesh)
def _inv(a, b, dflt):
    d = a - b
    return 1.0 / d if abs(d) > 4.7683716e-07 else dflt


def pack_ribbon_record(d: bytes, inst=0, poffs=0, accum=0) -> bytes:
    """fcn.1405e79e0: a 0x78 ribbon renderer -> 0x3C GPU record."""
    f = lambda o: struct.unpack_from("<f", d, o)[0]
    b = bytearray(0x3C)
    struct.pack_into("<III", b, 0, inst, poffs, accum)
    struct.pack_into("<HHHH", b, 0xC, struct.unpack_from("<H", d, 0x18)[0], 0x3800, ehalf(f(0x1C)),
                     struct.unpack_from("<H", d, 0x28)[0])
    i1 = _inv(f(0x2C), f(0x30), 10000.0)
    i2 = _inv(f(0x38), f(0x3C), -10000.0)
    struct.pack_into("<ffff", b, 0x14, i1, -i1 * f(0x30), i2, -f(0x3C) * i2)
    struct.pack_into("<HH", b, 0x24, ehalf(f(0x40)), ehalf(f(0x34)))
    c0, c1 = math.cos(f(0x48) * 0.017453292), math.cos(f(0x44) * 0.017453292)
    ia = _inv(c1, c0, 10000.0)
    struct.pack_into("<HH", b, 0x28, ehalf(ia), ehalf(-c0 * ia))
    struct.pack_into("<HHHH", b, 0x2C, ehalf(f(0x68)), ehalf(f(0x6C)), ehalf(f(0x70)), ehalf(f(0x74)))
    k = f(0x60)
    struct.pack_into("<HHHH", b, 0x34, ehalf(k * f(0x50)), ehalf(k * f(0x54)), ehalf(k * f(0x58)), ehalf(f(0x5C)))
    return bytes(b)


def pack_billboard_record(d: bytes, inst=0, poffs=0) -> bytes:
    """fcn.1405e49e0 (the part read so far): a 0xF8 billboard renderer -> 0x6C GPU record."""
    f = lambda o: struct.unpack_from("<f", d, o)[0]
    i = lambda o: struct.unpack_from("<i", d, o)[0]
    u8 = lambda o: 0xFF if i(o) == -1 else i(o) & 0xFF
    b = bytearray(0x6C)
    struct.pack_into("<III", b, 0, inst, poffs, struct.unpack_from("<I", d, 0x2C)[0])
    b[0xC:0x10] = bytes((u8(0x28), u8(0x30), u8(0x60), u8(0x6C)))
    struct.pack_into("<HH", b, 0x10, ehalf(f(0x34)), ehalf(f(0x40)))
    i1 = _inv(f(0x38), f(0x3C), 10000.0)
    i2 = _inv(f(0x44), f(0x48), -10000.0)
    struct.pack_into("<ffff", b, 0x14, i1, -i1 * f(0x3C), i2, -i2 * f(0x48))
    struct.pack_into("<HH", b, 0x24, ehalf(f(0x4C)), ehalf(f(0x58)))
    c0, c1 = math.cos(f(0x54) * 0.017453292), math.cos(f(0x50) * 0.017453292)
    ia = _inv(c1, c0, 10000.0)
    struct.pack_into("<HH", b, 0x28, ehalf(ia), ehalf(-c0 * ia))
    struct.pack_into("<H", b, 0x2C, ehalf(f(0x78)))
    struct.pack_into("<HHHH", b, 0x30, ehalf(f(0x64)), ehalf(f(0x68)), ehalf(f(0x70)), ehalf(f(0x74)))
    k = f(0x90)
    struct.pack_into("<HHHH", b, 0x38, ehalf(k * f(0x80)), ehalf(k * f(0x84)), ehalf(k * f(0x88)), ehalf(f(0x8C)))
    struct.pack_into("<HHHH", b, 0x40, *(ehalf(f(0x94 + 4 * j)) for j in range(4)))
    k = f(0xB4)
    struct.pack_into("<HHHH", b, 0x48, ehalf(k * f(0xA4)), ehalf(k * f(0xA8)), ehalf(k * f(0xAC)), ehalf(f(0xB0)))
    return bytes(b)


KINDS = {  # render-update cbuffer -> (output stride, batch stride, batch table key, renderers attr, packer)
    "k_billboardupdate_constants_decl": (68, 16, "bbatchconstants", "billboards", pack_billboard_record),
    "k_ribbonupdate_constants_decl": (44, 20, "rbatchconstants", "ribbons", pack_ribbon_record),
    "k_meshupdate_constants_decl": (60, 16, "mbatchconstants", "meshes", None),
}


def render_shaders(sim_: EffectSim, s: System):
    """{cbuffer kind: Shader} for every render-update shader of s's graph."""
    gid = sim_.graph_ids[s.graph]
    out = {}
    for fn in sorted(os.listdir(sim_.shader_dir)):
        if fn.startswith(gid) and fn.endswith(".ll"):
            text = open(os.path.join(sim_.shader_dir, fn), encoding="latin1").read()
            lay = reflect.layouts(text)
            kind = next((k for k in lay if k in KINDS), None)
            if kind:
                sh = dxil.Shader(text, "k_" + fn[:-3])
                sh.layout = lay
                out[kind] = sh
    return out


def render_update(sim_: EffectSim, s: System, kind: str, renderer: int, dt: float, shaders=None):
    """Run one render-update pass; returns the raw output records of the live particles."""
    stride, bstride, bkey, attr, packer = KINDS[kind]
    sh = (shaders or render_shaders(sim_, s))[kind]
    items = getattr(s, attr)
    rec = packer(items[renderer]) if packer else bytes(16)
    renderdata = dxil.RawBuf(rec * 1 + bytes(64)) if packer is not pack_ribbon_record else \
        dxil.StructBuf(rec + bytes(64), stride=0x3C)
    if packer is pack_billboard_record:
        renderdata = dxil.StructBuf(rec + bytes(0x6C), stride=0x6C)
    batch = dxil.StructBuf(struct.pack("<IIIII", s.index, 0, renderer, 0, 0)[:bstride] + bytes(32), stride=bstride)
    for name, obj in (("renderdata", renderdata), (bkey, batch)):
        if name in sim_.reg.ids:
            sim_.reg.table[sim_.reg.ids[name]] = obj
        else:
            sim_.reg.add(name, obj)
    out = dxil.StructBuf(size=stride * (s.maxcount + 1), stride=stride)
    uavs = {"k_output_decl": out}
    for extra in ("k_indexcounts_decl", "k_indexbuffer_decl", "k_sortkeys_decl"):
        if any(r.name == extra for r in sh.tp.res):
            uavs[extra] = dxil.RawBuf(size=4 * 4 * (s.maxcount + 64))
    sim_._bind(sh, {kind: dict(k_deltatime=dt, k_batchoffset=0, k_numvalid=1)}, uavs)
    sh.dispatch(((s.maxcount + 63) // 64, 1, 1))
    n = sim_.counts.a[s.index][0]
    return [bytes(out.b[i * stride:(i + 1) * stride]) for i in range(n)], stride


def colour_of(kind: str, rec: bytes):
    """(r, g, b, a) halves of an output record."""
    off = {"k_billboardupdate_constants_decl": 20, "k_ribbonupdate_constants_decl": 16,
           "k_meshupdate_constants_decl": 52}[kind]
    return tuple(_half(x) for x in struct.unpack_from("<4H", rec, off))
