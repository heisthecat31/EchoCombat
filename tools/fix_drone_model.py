"""Give the DRONE its new look: the CubeSat from assets/drone/Drone4.glb.

The drone (actor DRONE_ACTOR) was drawn as a detonator puck with the sidearm on top: eight
model components, seven of them the detonator's parts, one the sidearm (GUN, model
82db842e37b356ea). The new look is the sidearm mounted on the CubeSat from Drone4.glb:

* the body (glb mesh "mesh_119.004", material CubeSat) -> BODY_MODEL, on SAT_COMP (the
  drawn copy of the grenade shell), moved by BODY_OFFSET to where the old look's
  satellite sat beside the sidearm, and drawn from both sides (the glb's material is
  double-sided);
* the sidearm, GUN, stays the game's own (its model at the drone's origin, where the
  drone turns and aims from), and the drone script's show / hide of it is mirrored onto
  SAT_COMP and PORT_COMP by DroneFix.dll (dronefix.cpp);
* the I/O port ("port.004", material IO_Port) -> PORT_MODEL, moved with the body: it fills
  the opening the body has in its +Z face.

The body is a model of the kind the drone's parts are (CGMeshListResource): DONOR's files (a
one-mesh detonator part) with the glb mesh in DONOR's vertex format (stream 0, 20 bytes:
two vertex colours, UV, a u16 UV; stream 1, 28 bytes: position, s16 normal, s16 tangent;
u16 indices), the glb node rotations applied, positions in game axes = the glTF's.
Tangents are computed from the UVs (the glb has none).

Materials: the game has no lit shader with an emissive map for a moving model (the
albedo + emissive shader sets all belong to level scenery, drawn with lightmaps), so each
mesh gets a copy of a plain prop shader set (SHADERSET_DONOR: albedo, normal and specular
maps, on a prop with this very vertex format) with its textures swapped for ones made from
the glb's (BC7, mips down to 4x4, streaming off, as gear_icons.py makes textures):

* albedo (sRGB): base colour, darkened where metallic; the emissive mask is drawn into it
  (white where the mask is), so it reads bright, though it does not light anything;
* normal: the glb's tangent-space map, green flipped (glTF is +Y, the game's -Y);
* specular (linear, the slot the satellite's BC7 map used): dielectric grey, the base
  colour where metallic; alpha 1.

Per level (CModelCRWin10, CTextureStreamingCRWin10):
* the actor's main model, MAIN, is left alone: it is never drawn, and it is the drone's
  collision;
* SAT_COMP shows BODY_MODEL, PORT_COMP (a detonator part, see there) PORT_MODEL; GUN keeps the sidearm;
* the other detonator parts show BLANK_MODEL (one degenerate triangle), so the scripts
  that look them up still find them.

The bullets start at the drone's root (CR15NetAutoTargetCS fires from it), so DroneFix.dll
moves them to MUZZLE, the sidearm's muzzle (kept in step with dronefix.cpp).

    python tools/fix_drone_model.py --src <extract root> --out <stage>
"""

from __future__ import annotations

import argparse
import io
import json
import math
import os
import struct
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import cr_table as ct
from le_symbol_names import symbol64

ROOT = os.path.dirname(_HERE)
GLB = os.path.join(ROOT, "assets", "drone", "Drone4.glb")
MODEL_CR = "ea51a0d76eb90142"          # CSymbol64("CModelCRWin10")
TEXSTREAM_CR = "96832b652460ecde"      # CSymbol64("CTextureStreamingCRWin10")
MODEL_ROOT, PLAIN_ROOT = 0x168, 0x38   # root struct sizes (cr_table)
LEVELS = {
    "42670f2bed45703c": "mpl_combat_combustion",
    "43e2da7914642604": "mpl_combat_dyson",
    "43e2da7a0c623a19": "mpl_combat_gauss",
    "cb9977f7fc2b4526": "mpl_lobby_b_combat",
    "df5ca7b7dfa383d4": "mpl_combat_fission",
}
DRONE_ACTOR = 0x10E40287A9BF5A13
GUN = 0x72F91FFFA17C3C8C               # the sidearm's model component (model 82db842e37b356ea), kept
#: the actor's main model ("ncaModel", the same id on every actor): the grenade shell
#: 3ce2965d2a7b3975, flagged not drawn (model instance +0x18 bit 0x10 clear, as on 10 of the
#: level's 649 main models). Each model carries its own CPhysicsResource and this one's is
#: the drone's only collision: swapped out, the drone had no physics body, and grabbing it
#: crashed (echovr+0xd83dd7, null +0x8f8). Left as it is.
MAIN = 0x38EE951A26FB816A
#: the shell's drawn copy -> the body (its texture streaming record has the same id)
SAT_COMP = SAT_TEXSTREAM = 0x106C63A2927B7A4D
#: a detonator part -> the port. The drone's script (the detonator's) shows this part once the
#: drone is deployed (0xA977DD32B518F0DD it shows only in the hand); DroneFix.dll makes it
#: follow the gun either way, as SAT_COMP.
PORT_COMP = 0x45B09F0FA9F7FA33
#: the detonator's other parts -> BLANK_MODEL: they still exist and draw nothing
STUBBED = (0xA977DD32B518F0DD, 0x19B2A5AFE9C87B2C, 0x3944C0EAC6C7D2E5, 0xC1FBD0BFDCFA0D08)

# --- the models -----------------------------------------------------------------------
DONOR = "171942614d4df2b3"
MESHLIST, MESHLIST_GPU, SCENE, TEXSTREAM = ("4e426f88c1b5d7ac", "e642bfb1abcf76df",
                                             "a388ea69e5108f4c", "c2434c5a99e139ce")
DONOR_AS_IS = ("230554bc3beca38c", "73d312a620da3824", "7b9a4c9fd03f37eb", "b7d338793fa37832")
BODY_MODEL = int(symbol64("echocombat_drone_cubesat"), 16)
PORT_MODEL = int(symbol64("echocombat_drone_cubesat_port"), 16)
BLANK_MODEL = int(symbol64("echocombat_drone_blank"), 16)
#: glb mesh name -> (model, its name, texture size). The port fills the opening in the
#: body's +Z face (the body has a hole there for it), so both go in.
MESHES = {"mesh_119.004": (BODY_MODEL, "echocombat_drone_cubesat", 1024),
          "port.004": (PORT_MODEL, "echocombat_drone_cubesat_port", 512)}
#: where the body goes: where the satellite ball sat beside the sidearm in the look before
#: (newdronemodel.glb: the satellite moved by SAT_OFFSET, the sidearm by GUN_OFFSET; the
#: CubeSat is that satellite's size, with the same node rotation). The sidearm stays at the
#: drone's origin, so the body is moved by the difference.
SAT_OFFSET = (0.049567967653274536, 0.007827199064195156, 0.0)
GUN_OFFSET = (-0.01412429939955473, 0.030333194881677628, -0.039136677980422974)
BODY_OFFSET = tuple(s - g for s, g in zip(SAT_OFFSET, GUN_OFFSET))


def double_sided(m: dict) -> dict:
    """The mesh with every triangle drawn from both sides, as glTF's doubleSided material
    is (the game's prop shader culls back faces: faces wound inward vanished): each vertex
    again with its normal turned round, and each triangle again, reversed, on those."""
    n = len(m["positions"])
    idx = m["indices"]
    back = [i + n for t in range(0, len(idx), 3) for i in (idx[t], idx[t + 2], idx[t + 1])]
    return dict(m, positions=list(m["positions"]) * 2, uvs=list(m["uvs"]) * 2,
                normals=list(m["normals"]) + [tuple(-c for c in v) for v in m["normals"]],
                indices=list(idx) + back)
#: the sidearm's muzzle (its stock muzzle bone; metres, the drone's axes; dronefix.cpp's MUZZLE)
MUZZLE = (2.4e-05, 0.075634, 0.147283)
S0_STRIDE, S1_STRIDE = 20, 28
#: donor mesh list (count-prefixed tables, Win10): mesh bounds, render params counts,
#: vertex buffer record (+ stream 1's offset, the vertex count x3), index buffer record,
#: GPU size
D_BOUNDS, D_RP_NV, D_RP_NI, D_VB, D_IB, D_GPU_SIZE = 0x40, 0xE8, 0xF0, 0x114, 0x270, 0x298
VB_STREAM1, VB_COUNTS = 0x130, (0x13C, 0x140, 0x14C)
#: donor scene: (material, shader set) and the bounds
D_MATERIAL, D_SHADERSET = 0xE83EAD1D14EAB8BF, 0x99646226881A42E5
D_SCENE_BOUNDS = 0x278

# --- materials ------------------------------------------------------------------------
SHADERSET_TYPES = ("4984e2bbb2ddb256", "43ddbd692282a6a7")   # shader set + its header
SHADERSET_DONOR = 0xC0FB34E681A628F1   # model 171b71164cac8315's (material MATERIAL)
MATERIAL = 0x2FDA868C4D7D598D
#: the donor shader set's default textures, by slot
SLOTS = {"albedo": 0x917DB3CFEBE26296, "normal": 0x917DB3CFEBEF6388, "specular": 0x917DB3CFEBF27E87}
TEXTURE_DESC = "4a4c32c49300b8a0"       # cgtextureresourceWin10
TEXTURE_GPU = "beac1969cb7b8861"        # CGTextureResourceWin10GPU: the DDS
DESC_TEMPLATE = "d8b84ca5707d3bd2"      # a BC7 descriptor (the gear icon sheet's)
BC7_UNORM, BC7_SRGB = 98, 99
D_STREAMINGDISABLED, D_MAXW, D_MAXH, D_MAXMIPS = 0xC0, 0xC4, 0xC8, 0xCC
D_FORMAT, D_SRGB = 0xD8, 0xDC
D_W, D_H, D_MIPS, D_RESMEM, D_PITCH = 0xE8, 0xEC, 0xF0, 0xF4, 0xF8
DDS_HEADER = 148
#: texture streaming: the donor's texel density
TEXSTREAM_DENSITY = 0x3E161DD9
NORMAL_FLIP_GREEN = True
DIELECTRIC_SPEC = 0.25
METAL_DIFFUSE = 0.35                    # what is left of the base colour where metallic


def q(b, o):
    return struct.unpack_from("<Q", b, o)[0]


def swap(data: bytes, old: int, new: int, count: int = 1) -> bytes:
    o, n = struct.pack("<Q", old), struct.pack("<Q", new)
    if data.count(o) != count:
        raise ValueError(f"expected {count} x {old:016x}, found {data.count(o)}")
    return data.replace(o, n)


def source_files() -> list:
    """(type, name) of every game file this reads besides the level tables."""
    return ([(t, DONOR) for t in DONOR_AS_IS + (MESHLIST, SCENE, TEXSTREAM)]
            + [(t, f"{SHADERSET_DONOR:x}") for t in SHADERSET_TYPES]
            + [(TEXTURE_DESC, DESC_TEMPLATE)])


# --- the glb --------------------------------------------------------------------------
def read_glb(path: str) -> dict:
    """mesh name -> {positions, normals, uvs, indices, material}, node rotations applied."""
    b = open(path, "rb").read()
    if b[:4] != b"glTF":
        raise ValueError(f"{path} is not a glb")
    jlen = struct.unpack_from("<I", b, 12)[0]
    j = json.loads(b[20:20 + jlen])
    binary = b[20 + jlen + 8:]
    sizes = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}
    kinds = {5126: "f", 5123: "H", 5125: "I", 5121: "B"}

    def accessor(i):
        a = j["accessors"][i]
        bv = j["bufferViews"][a["bufferView"]]
        n, k = sizes[a["type"]], kinds[a["componentType"]]
        size = struct.calcsize("<" + k)
        stride = bv.get("byteStride", size * n)
        base = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
        return [struct.unpack_from(f"<{n}{k}", binary, base + stride * e) for e in range(a["count"])]

    def image(i):
        bv = j["bufferViews"][j["images"][i]["bufferView"]]
        o = bv.get("byteOffset", 0)
        return binary[o:o + bv["byteLength"]]

    out = {}
    for node in j["nodes"]:
        if "mesh" not in node:
            continue
        mesh = j["meshes"][node["mesh"]]
        if len(mesh["primitives"]) != 1:
            raise ValueError(f"glb mesh {mesh['name']} has {len(mesh['primitives'])} primitives")
        if any(k in node for k in ("translation", "scale", "matrix")):
            raise ValueError(f"glb node {node.get('name')}: only a rotation is handled")
        p = mesh["primitives"][0]
        rot = node.get("rotation", [0, 0, 0, 1])
        mat = j["materials"][p["material"]]

        def tex(ref):
            return image(j["textures"][ref["index"]]["source"]) if ref else None
        pbr = mat.get("pbrMetallicRoughness", {})
        out[mesh["name"]] = {
            "positions": [rotate(rot, v) for v in accessor(p["attributes"]["POSITION"])],
            "normals": [rotate(rot, v) for v in accessor(p["attributes"]["NORMAL"])],
            "uvs": accessor(p["attributes"]["TEXCOORD_0"]),
            "indices": [i[0] for i in accessor(p["indices"])],
            "albedo": tex(pbr.get("baseColorTexture")), "mr": tex(pbr.get("metallicRoughnessTexture")),
            "normal_map": tex(mat.get("normalTexture")), "emissive": tex(mat.get("emissiveTexture")),
            "metallic": pbr.get("metallicFactor", 1.0),
        }
    return out


def rotate(qt, v):
    """v rotated by the unit quaternion qt (x, y, z, w)."""
    x, y, z, w = qt
    tx, ty, tz = 2 * (y * v[2] - z * v[1]), 2 * (z * v[0] - x * v[2]), 2 * (x * v[1] - y * v[0])
    return (v[0] + w * tx + y * tz - z * ty, v[1] + w * ty + z * tx - x * tz, v[2] + w * tz + x * ty - y * tx)


def tangents(pos, nrm, uvs, idx):
    """Per-vertex (tangent xyz, handedness) from the UVs, orthogonal to the normal."""
    n = len(pos)
    tan, bit = [[0.0] * 3 for _ in range(n)], [[0.0] * 3 for _ in range(n)]
    for t in range(0, len(idx), 3):
        a, b, c = idx[t:t + 3]
        e1 = [pos[b][k] - pos[a][k] for k in range(3)]
        e2 = [pos[c][k] - pos[a][k] for k in range(3)]
        du1, dv1 = uvs[b][0] - uvs[a][0], uvs[b][1] - uvs[a][1]
        du2, dv2 = uvs[c][0] - uvs[a][0], uvs[c][1] - uvs[a][1]
        det = du1 * dv2 - du2 * dv1
        if abs(det) < 1e-12:
            continue
        r = 1.0 / det
        sd = [(e1[k] * dv2 - e2[k] * dv1) * r for k in range(3)]
        td = [(e2[k] * du1 - e1[k] * du2) * r for k in range(3)]
        for v in (a, b, c):
            for k in range(3):
                tan[v][k] += sd[k]
                bit[v][k] += td[k]
    out = []
    for v in range(n):
        nn, t = nrm[v], tan[v]
        d = sum(nn[k] * t[k] for k in range(3))
        t = [t[k] - nn[k] * d for k in range(3)]
        ln = math.sqrt(sum(c * c for c in t))
        if ln < 1e-9:                                        # no UV direction: any perpendicular
            t = [0.0, -nn[2], nn[1]] if abs(nn[0]) < 0.9 else [-nn[2], 0.0, nn[0]]
            ln = math.sqrt(sum(c * c for c in t)) or 1.0
        t = [c / ln for c in t]
        cr = (nn[1] * t[2] - nn[2] * t[1], nn[2] * t[0] - nn[0] * t[2], nn[0] * t[1] - nn[1] * t[0])
        out.append((t, -1.0 if sum(cr[k] * bit[v][k] for k in range(3)) < 0 else 1.0))
    return out


def snorm16(f: float) -> int:
    return max(-32767, min(32767, int(round(f * 32767))))


def unit(v):
    ln = math.sqrt(sum(c * c for c in v)) or 1.0
    return [c / ln for c in v]


def encode_mesh(m: dict):
    """(gpu bytes, vertex count, index count, bounds (min, max, centre, radius))."""
    pos, uvs, idx = m["positions"], m["uvs"], m["indices"]
    nrm = [unit(v) for v in m["normals"]]
    if len(pos) > 65535:
        raise ValueError(f"{len(pos)} vertices: more than u16 indices reach")
    tans = tangents(pos, nrm, uvs, idx)
    s0, s1 = bytearray(), bytearray()
    for v in range(len(pos)):
        u, w = uvs[v]
        s0 += b"\xff\xff\xff\xff\xff\xff\xff\xff" + struct.pack(
            "<2f2H", u, w, int(min(1, max(0, u)) * 65535), int(min(1, max(0, w)) * 65535))
        t, hand = tans[v]
        s1 += struct.pack("<3f4h4h", *pos[v], *(snorm16(c) for c in nrm[v]), 0,
                          *(snorm16(c) for c in t), -32767 if hand < 0 else 32767)
    ib = struct.pack(f"<{len(idx)}H", *idx)
    lo = [min(p[k] for p in pos) for k in range(3)]
    hi = [max(p[k] for p in pos) for k in range(3)]
    centre = [(lo[k] + hi[k]) / 2 for k in range(3)]
    radius = max(math.dist(p, centre) for p in pos)
    return bytes(s0 + s1 + ib), len(pos), len(idx), (*lo, *hi, *centre, radius)


# --- textures -------------------------------------------------------------------------
def load_rgba(png: bytes, size: int):
    import numpy as np
    from PIL import Image
    return np.asarray(Image.open(io.BytesIO(png)).convert("RGBA").resize((size, size), Image.LANCZOS)).astype(np.float32) / 255


def texture_images(m: dict, size: int) -> dict:
    """slot -> (h, w, 4) uint8 image, sRGB or not (see the top)."""
    import numpy as np
    base = load_rgba(m["albedo"], size)
    mr = load_rgba(m["mr"], size) if m["mr"] else None
    metal = (mr[..., 2] * m["metallic"]) if mr is not None else np.zeros(base.shape[:2], np.float32)
    emis = load_rgba(m["emissive"], size)[..., :3] if m["emissive"] else 0
    diffuse = base[..., :3] * (1 - (1 - METAL_DIFFUSE) * metal[..., None])
    diffuse = np.maximum(diffuse, emis)
    albedo = np.dstack([diffuse, np.ones(base.shape[:2], np.float32)])
    spec = DIELECTRIC_SPEC + (base[..., :3] - DIELECTRIC_SPEC) * metal[..., None]
    spec = np.dstack([spec, np.ones(base.shape[:2], np.float32)])
    nm = load_rgba(m["normal_map"], size)
    if NORMAL_FLIP_GREEN:
        nm[..., 1] = 1 - nm[..., 1]
    nm[..., 3] = 1
    to8 = lambda a: (np.clip(a, 0, 1) * 255 + 0.5).astype(np.uint8)
    return {"albedo": (to8(albedo), True), "normal": (to8(nm), False), "specular": (to8(spec), False)}


def build_dds(img, srgb: bool):
    """A BC7 DDS with mips down to 4x4. Returns (dds, w, h, mips)."""
    import numpy as np
    from PIL import Image
    import bc7
    h, w = img.shape[:2]
    out, levels, cur = bytearray(), 0, img
    while True:
        out += bc7.encode(np.ascontiguousarray(cur))
        levels += 1
        ch, cw = cur.shape[:2]
        if ch <= 4 or cw <= 4:
            break
        cur = np.asarray(Image.fromarray(cur).resize((cw // 2, ch // 2), Image.LANCZOS))
    hdr = bytearray(DDS_HEADER)
    hdr[0:4] = b"DDS "
    struct.pack_into("<7I", hdr, 4, 124, 0x1 | 0x2 | 0x4 | 0x1000 | 0x20000 | 0x80000, h, w,
                     (w // 4) * (h // 4) * 16, 0, levels)
    struct.pack_into("<2I4s", hdr, 76, 32, 0x4, b"DX10")
    struct.pack_into("<I", hdr, 108, 0x1000 | 0x400000 | 0x8)
    struct.pack_into("<5I", hdr, 128, BC7_SRGB if srgb else BC7_UNORM, 3, 0, 1, 0)
    return bytes(hdr) + bytes(out), w, h, levels


def descriptor(template: bytes, dds: bytes, w: int, h: int, mips: int, srgb: bool) -> bytes:
    d = bytearray(template[:256])
    for off, val in ((D_STREAMINGDISABLED, 1), (D_MAXW, w), (D_MAXH, h), (D_MAXMIPS, mips),
                     (D_FORMAT, BC7_SRGB if srgb else BC7_UNORM), (D_SRGB, 1 if srgb else 0),
                     (D_W, w), (D_H, h), (D_MIPS, mips), (D_RESMEM, len(dds)),
                     (D_PITCH, len(dds) - DDS_HEADER)):
        struct.pack_into("<I", d, off, val)
    return bytes(d)


def texstream_record(textures: list) -> bytes:
    """The model's CGTextureStreamingResourceWin10: its textures, one density entry each."""
    n = len(textures)
    out = struct.pack("<qI", -1, n) + b"".join(struct.pack("<Q", t) for t in textures)
    out += struct.pack("<III", 0, n, 0)
    out += b"".join(struct.pack("<II", TEXSTREAM_DENSITY, (i + 1) % n) for i in range(n))
    return out + struct.pack("<I", 0)


# --- assembling a model ---------------------------------------------------------------
def model_assets(read, model: int, name: str, gpu: bytes, nv: int, ni: int, bounds, textures: dict,
                 own_material: bool = True) -> list:
    """The model's files. own_material False (the blank): the donor's own material and shader
    set, kept: the drone's script sets two of its properties (0xFD0268DFE1C80980,
    0x8B6F20C39D3F428B: the detonator parts' light) on every part each time, and on our
    material, which has neither, each drone in the match logged "Unable to find property"
    for each blank part -- 114 lines in one frame at a time."""
    ml = bytearray(read(MESHLIST, DONOR))
    if struct.unpack_from("<I", ml, 0)[0] != 1 or ml[D_VB:D_VB + 4] != b"\0\0\x08\x03":
        raise ValueError("the donor mesh list is not the one this expects")
    struct.pack_into("<10f", ml, D_BOUNDS, *bounds)
    struct.pack_into("<I", ml, D_RP_NV, nv)
    struct.pack_into("<I", ml, D_RP_NI, ni)
    struct.pack_into("<I", ml, D_VB + VB_STREAM1, nv * S0_STRIDE)
    for o in VB_COUNTS:
        struct.pack_into("<I", ml, D_VB + o, nv)
    struct.pack_into("<4I", ml, D_IB, nv * (S0_STRIDE + S1_STRIDE), ni, 2, 0)
    struct.pack_into("<I", ml, D_GPU_SIZE, len(gpu))

    fn = f"{model:x}"
    if not own_material:
        scene = bytearray(read(SCENE, DONOR))
        struct.pack_into("<6f", scene, D_SCENE_BOUNDS, *bounds[:6])
        return ([(MESHLIST, fn, bytes(ml)), (MESHLIST_GPU, fn, gpu), (SCENE, fn, bytes(scene)),
                 (TEXSTREAM, fn, read(TEXSTREAM, DONOR))]
                + [(t, fn, read(t, DONOR)) for t in DONOR_AS_IS])
    shaderset = int(symbol64(name + "_shaders"), 16)
    scene = bytearray(swap(swap(read(SCENE, DONOR), D_MATERIAL, MATERIAL, 2), D_SHADERSET, shaderset))
    struct.pack_into("<6f", scene, D_SCENE_BOUNDS, *bounds[:6])
    shaders = swap(read(SHADERSET_TYPES[0], f"{SHADERSET_DONOR:x}"), SHADERSET_DONOR, shaderset)
    for slot, tex in textures.items():
        shaders = swap(shaders, SLOTS[slot], tex)

    out = [(MESHLIST, fn, bytes(ml)), (MESHLIST_GPU, fn, gpu), (SCENE, fn, bytes(scene)),
           (TEXSTREAM, fn, texstream_record(list(textures.values())))]
    out += [(t, fn, read(t, DONOR)) for t in DONOR_AS_IS]          # its CPhysicsResource: empty
    out += [(SHADERSET_TYPES[0], f"{shaderset:x}", shaders),
            (SHADERSET_TYPES[1], f"{shaderset:x}", read(SHADERSET_TYPES[1], f"{SHADERSET_DONOR:x}"))]
    return out


def drone_assets(read) -> list:
    """(type, name, data): the body's files, BLANK_MODEL's, their textures."""
    meshes = read_glb(GLB)
    if not set(MESHES) <= set(meshes):
        raise ValueError(f"{GLB}: meshes {sorted(meshes)}, expected {sorted(MESHES)} among them")
    template = read(TEXTURE_DESC, DESC_TEMPLATE)
    out = []
    for mesh_name, (model, name, size) in MESHES.items():
        m = dict(meshes[mesh_name])
        if model in (BODY_MODEL, PORT_MODEL):                # beside the sidearm, as the satellite was
            m["positions"] = [tuple(p[k] + BODY_OFFSET[k] for k in range(3)) for p in m["positions"]]
            print(f"body moved by ({BODY_OFFSET[0]:.4f}, {BODY_OFFSET[1]:.4f}, {BODY_OFFSET[2]:.4f})")
        if m.get("double_sided", True):
            m = double_sided(m)
        gpu, nv, ni, bounds = encode_mesh(m)
        textures = {}
        for slot, (img, srgb) in texture_images(m, size).items():
            tex = int(symbol64(f"{name}_{slot}"), 16)
            dds, w, h, mips = build_dds(img, srgb)
            out += [(TEXTURE_GPU, f"{tex:x}", dds), (TEXTURE_DESC, f"{tex:x}", descriptor(template, dds, w, h, mips, srgb))]
            textures[slot] = tex
        out += model_assets(read, model, name, gpu, nv, ni, bounds, textures)
        print(f"{name} ({model:x}): {nv} vertices, {ni // 3} triangles, {size}x{size} textures")
        if model == BODY_MODEL:                              # the blank: the body, one degenerate triangle
            blank_gpu = gpu[:nv * (S0_STRIDE + S1_STRIDE)] + b"\0" * 6
            out += [a for a in model_assets(read, BLANK_MODEL, "echocombat_drone_blank", blank_gpu, nv, 3,
                                            bounds, textures, own_material=False)]
    return out


# --- the level tables -----------------------------------------------------------------
#: drone component -> the model it shows
SHOWS = {SAT_COMP: BODY_MODEL, PORT_COMP: PORT_MODEL, **{c: BLANK_MODEL for c in STUBBED}}


def model_table(blob: bytes) -> tuple[bytes, bool]:
    root = ct.parse(blob, MODEL_ROOT)
    recs, entries, insts = root.arrays[0], root.arrays[2], root.arrays[5]
    mine = {q(r.raw, 0): i for i, r in enumerate(recs.elems) if q(r.raw, 8) == DRONE_ACTOR}
    if set(mine) != {MAIN, GUN, *SHOWS}:
        raise ValueError(f"the drone's model components are not the eight expected: {sorted(map(hex, mine))}")
    if all(q(entries.elems[mine[c]].raw, 0) == m for c, m in SHOWS.items()):
        return blob, False
    for comp, model in SHOWS.items():
        i = mine[comp]
        struct.pack_into("<Q", entries.elems[i].raw, 0, model)
        struct.pack_into("<Q", insts.elems[i].raw, 0x20, model)
    return ct.build(root), True


def texstream_table(blob: bytes) -> tuple[bytes, bool]:
    root = ct.parse(blob, PLAIN_ROOT)
    changed = False
    for e in root.arrays[0].elems:
        if q(e.raw, 8) != DRONE_ACTOR:
            continue
        comp, model = q(e.raw, 0), q(e.raw, 0x20)
        new = SHOWS.get(comp, model)
        if new != model:
            struct.pack_into("<Q", e.raw, 0x20, new)
            changed = True
    return (ct.build(root) if changed else blob), changed


def main(argv) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--src", required=True, help="extract root (or build/source)")
    ap.add_argument("--out", required=True, help="stage: tables already there are built on")
    args = ap.parse_args(argv[1:])

    def read(t, name):
        staged = os.path.join(args.out, t, name)
        return open(staged if os.path.exists(staged) else os.path.join(args.src, t, name), "rb").read()

    def write(t, name, data):
        os.makedirs(os.path.join(args.out, t), exist_ok=True)
        open(os.path.join(args.out, t, name), "wb").write(data)

    for t, name, data in drone_assets(read):
        write(t, name, data)
    for level, lname in LEVELS.items():
        done = []
        for t, fn in ((MODEL_CR, model_table), (TEXSTREAM_CR, texstream_table)):
            data, changed = fn(read(t, level))
            write(t, level, data)
            done.append("changed" if changed else "already done")
        print(f"{lname}: the drone is the sidearm on the CubeSat ({BODY_MODEL:x}, port {PORT_MODEL:x}) "
              "(model, texture streaming: " + ", ".join(done) + ")")
    print(f"muzzle (dronefix.cpp MUZZLE): {MUZZLE}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
