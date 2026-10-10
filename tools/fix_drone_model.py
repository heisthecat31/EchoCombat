"""Give the DRONE its new look: the SAT MDL-6SP satellite ball with the sidearm on it.

The drone (actor DRONE_ACTOR) was drawn as a detonator puck with the sidearm on top: eight
model components, seven of them the detonator's parts, one the sidearm (GUN, model
82db842e37b356ea). newdronemodel.glb (repo root) is the new look, built in Blender from
two game meshes, each only moved:

* the satellite, game mesh SAT_SRC moved by SAT_OFFSET. It ships only as level scenery
  (CGInstancedModelResource, drawn by lightmapped instancing shaders), which a moving
  actor cannot draw, so this builds it as a model of its own, SAT_MODEL, the kind the
  drone's parts are (CGMeshListResource): the descriptor of DONOR (a one-mesh detonator
  part) with the satellite's LOD 0 vertex buffer, index buffer and bounds in it. Its
  vertex format is the donor's, byte for byte.
* the sidearm, moved by GUN_OFFSET: its model is kept as it is, at the drone's origin, and
  the satellite is moved by SAT_OFFSET - GUN_OFFSET instead, so the two sit as in the glb
  and the drone turns about the sidearm's origin. (An earlier version gave the sidearm a
  transform of its own instead; it was dropped while chasing a crash that turned out to be
  the collision, see MAIN.)

Materials: the satellite's own shader set reads lightmap inputs, so SAT_SHADERSET is a
copy of a plain prop shader set (SHADERSET_DONOR: albedo, normal and specular maps, on a
prop with the satellite's very vertex format) with its textures swapped for the
satellite's LOD 0 ones (TEXTURES, slot by slot), paired with that prop's material. (The
detonator body's shader set, tried first, is a composite one: it read the satellite's maps
as masks and tinted them in team colours.) The satellite's emissive map has no slot there.

Per level (CModelCRWin10, CTextureStreamingCRWin10):
* the actor's main model, MAIN, is left alone: it is never drawn, and it is the drone's
  collision;
* component SAT_COMP (the drawn copy of the grenade shell) shows SAT_MODEL;
* the other detonator parts show BLANK_MODEL (the satellite drawing one degenerate
  triangle), so the scripts that look them up still find them.

The bullets start at the drone's root (CR15NetAutoTargetCS fires from it), so
DroneFix.dll moves them to the gun's muzzle (MUZZLE, kept in step with dronefix.cpp).

    python tools/fix_drone_model.py --src <extract root> --out <stage>
"""

from __future__ import annotations

import argparse
import os
import struct
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import cr_table as ct
from le_symbol_names import symbol64

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
GUN = 0x72F91FFFA17C3C8C               # the sidearm's model component (model 82db842e37b356ea)
#: the actor's main model ("ncaModel", the same id on every actor): the grenade shell
#: 3ce2965d2a7b3975, flagged not drawn (model instance +0x18 bit 0x10 clear, as on 10 of the
#: level's 649 main models). Each model carries its own CPhysicsResource and this one's is
#: the drone's only collision: swapped out, the drone had no physics body, and grabbing it
#: crashed (echovr+0xd83dd7, null +0x8f8). Left as it is.
MAIN = 0x38EE951A26FB816A
#: the shell's drawn copy -> the satellite (its texture streaming record has the same id)
SAT_COMP = SAT_TEXSTREAM = 0x106C63A2927B7A4D
#: the detonator's other parts -> BLANK_MODEL: they still exist and draw nothing
STUBBED = (0xA977DD32B518F0DD, 0x45B09F0FA9F7FA33, 0x19B2A5AFE9C87B2C, 0x3944C0EAC6C7D2E5,
           0xC1FBD0BFDCFA0D08)

# --- the satellite model ------------------------------------------------------------
SAT_SRC = "33c6e9840092f5e3"
SAT_INSTANCED, SAT_GPU = "37102e4b27955a14", "e7a8ab5ceaef49cb"   # its instanced model + GPU
DONOR = "171942614d4df2b3"
MESHLIST, MESHLIST_GPU, SCENE, TEXSTREAM = ("4e426f88c1b5d7ac", "e642bfb1abcf76df",
                                             "a388ea69e5108f4c", "c2434c5a99e139ce")
DONOR_AS_IS = ("230554bc3beca38c", "73d312a620da3824", "7b9a4c9fd03f37eb", "b7d338793fa37832")
SAT_MODEL = int(symbol64("echocombat_drone_satellite"), 16)
#: the satellite drawing one degenerate triangle (indices 0, 0, 0): a real mesh, nothing seen
BLANK_MODEL = int(symbol64("echocombat_drone_blank"), 16)
#: newdronemodel.glb's node translations (metres, game axes: the glTF's)
SAT_OFFSET = (0.049567967653274536, 0.007827199064195156, 0.0)
GUN_OFFSET = (-0.01412429939955473, 0.030333194881677628, -0.039136677980422974)
#: where the satellite goes: relative to the sidearm, as in the glb
SAT_MOVE = tuple(s - g for s, g in zip(SAT_OFFSET, GUN_OFFSET))
#: the sidearm's muzzle (bone EXP_C1_Muzzle1, bind pose); dronefix.cpp's MUZZLE
MUZZLE = (2.4e-05, 0.075634, 0.147283)
#: satellite instanced model: LOD 0's mesh record bounds (min, max, centre, radius), render
#: params (vertex count, index count), vertex buffer record, index buffer, GPU span
SAT_BOUNDS, SAT_VB, SAT_VB_SIZE = 0x3B4, 0x690, 0x150
SAT_NV, SAT_NI, SAT_STREAM0, SAT_IB, SAT_GPU_END = 1164, 4296, 23280, 0xDA40, 0xFBD0
POS_STRIDE = 28                        # stream 1: f32 x, y, z + packed normal / tangent
#: donor mesh list (count-prefixed tables, Win10): mesh bounds, render params counts,
#: vertex buffer record, index buffer record, GPU size
D_BOUNDS, D_RP_NV, D_RP_NI, D_VB, D_IB, D_GPU_SIZE = 0x40, 0xE8, 0xF0, 0x114, 0x270, 0x298
#: donor scene: (material, shader set) and the bounds
D_MATERIAL, D_SHADERSET = 0xE83EAD1D14EAB8BF, 0x99646226881A42E5
D_SCENE_BOUNDS = 0x278

# --- its material -------------------------------------------------------------------
SHADERSET_TYPES = ("4984e2bbb2ddb256", "43ddbd692282a6a7")   # shader set + its header
SHADERSET_DONOR = 0xC0FB34E681A628F1   # model 171b71164cac8315's (material MATERIAL)
MATERIAL = 0x2FDA868C4D7D598D
SAT_SHADERSET = int(symbol64("echocombat_drone_satellite_shaders"), 16)
#: donor texture -> satellite texture (its LOD 0 material e607a335364fa6d8's), by slot
TEXTURES = {
    0x917DB3CFEBE26296: 0xDB11311FE1C27E92,   # layer0 albedo (its basecolor map)
    0x917DB3CFEBEF6388: 0xDB11311FE1CF7F8C,   # layer0 normal
    0x917DB3CFEBF27E87: 0xDB11311FE1C27F90,   # layer0 specular
}


def q(b, o):
    return struct.unpack_from("<Q", b, o)[0]


def swap(data: bytes, old: int, new: int, count: int = 1) -> bytes:
    o, n = struct.pack("<Q", old), struct.pack("<Q", new)
    if data.count(o) != count:
        raise ValueError(f"expected {count} x {old:016x}, found {data.count(o)}")
    return data.replace(o, n)


def source_files() -> list:
    """(type, name) of every game file this reads besides the level tables."""
    return ([(t, DONOR) for t in DONOR_AS_IS + (MESHLIST, SCENE)]
            + [(t, SAT_SRC) for t in (SAT_INSTANCED, SAT_GPU, TEXSTREAM)]
            + [(t, f"{SHADERSET_DONOR:x}") for t in SHADERSET_TYPES])


def moved(bounds: tuple, by) -> tuple:
    """(min xyz, max xyz, centre xyz, radius) moved by `by`."""
    return (tuple(v + by[i % 3] for i, v in enumerate(bounds[:9])) + bounds[9:])


def satellite_assets(read) -> list:
    """(type, name, data): the satellite model's files, BLANK_MODEL's and the shader set."""
    inst, gpu = read(SAT_INSTANCED, SAT_SRC), bytearray(read(SAT_GPU, SAT_SRC)[:SAT_GPU_END])
    if struct.unpack_from("<4I", inst, 0x580) != (4, 0, SAT_NV, 0) or inst[SAT_VB:SAT_VB + 4] != b"\0\0\x08\x03":
        raise ValueError("the satellite's model is not the one this expects")
    for i in range(SAT_NV):                                  # positions, moved
        at = SAT_STREAM0 + POS_STRIDE * i
        struct.pack_into("<3f", gpu, at, *(v + d for v, d in zip(struct.unpack_from("<3f", gpu, at), SAT_MOVE)))
    bounds = moved(struct.unpack_from("<10f", inst, SAT_BOUNDS), SAT_MOVE)

    ml = bytearray(read(MESHLIST, DONOR))
    if struct.unpack_from("<I", ml, 0)[0] != 1 or ml[D_VB:D_VB + SAT_VB_SIZE][:4] != inst[SAT_VB:SAT_VB + 4]:
        raise ValueError("the donor mesh list is not the one this expects")
    struct.pack_into("<10f", ml, D_BOUNDS, *bounds)
    struct.pack_into("<I", ml, D_RP_NV, SAT_NV)
    struct.pack_into("<I", ml, D_RP_NI, SAT_NI)
    ml[D_VB:D_VB + SAT_VB_SIZE] = inst[SAT_VB:SAT_VB + SAT_VB_SIZE]
    struct.pack_into("<4I", ml, D_IB, SAT_IB, SAT_NI, 2, 0)
    struct.pack_into("<I", ml, D_GPU_SIZE, len(gpu))

    scene = bytearray(swap(swap(read(SCENE, DONOR), D_MATERIAL, MATERIAL, 2), D_SHADERSET, SAT_SHADERSET))
    struct.pack_into("<6f", scene, D_SCENE_BOUNDS, *bounds[:6])

    blank_ml, blank_gpu = bytearray(ml), bytearray(gpu)
    struct.pack_into("<I", blank_ml, D_RP_NI, 3)
    struct.pack_into("<4I", blank_ml, D_IB, SAT_IB, 3, 2, 0)
    struct.pack_into("<3H", blank_gpu, SAT_IB, 0, 0, 0)
    out = []
    for model, m, g in ((SAT_MODEL, ml, gpu), (BLANK_MODEL, blank_ml, blank_gpu)):
        name = f"{model:x}"
        out += [(MESHLIST, name, bytes(m)), (MESHLIST_GPU, name, bytes(g)), (SCENE, name, bytes(scene)),
                (TEXSTREAM, name, read(TEXSTREAM, SAT_SRC))]
        out += [(t, name, read(t, DONOR)) for t in DONOR_AS_IS]     # its CPhysicsResource: empty
    shaders = swap(read(SHADERSET_TYPES[0], f"{SHADERSET_DONOR:x}"), SHADERSET_DONOR, SAT_SHADERSET)
    for old, new in TEXTURES.items():
        shaders = swap(shaders, old, new)
    out += [(SHADERSET_TYPES[0], f"{SAT_SHADERSET:x}", shaders),
            (SHADERSET_TYPES[1], f"{SAT_SHADERSET:x}", read(SHADERSET_TYPES[1], f"{SHADERSET_DONOR:x}"))]
    return out


# --- the level tables -----------------------------------------------------------------
def model_table(blob: bytes) -> tuple[bytes, bool]:
    root = ct.parse(blob, MODEL_ROOT)
    recs, entries, insts = root.arrays[0], root.arrays[2], root.arrays[5]
    mine = {q(r.raw, 0): i for i, r in enumerate(recs.elems) if q(r.raw, 8) == DRONE_ACTOR}
    if set(mine) != {MAIN, GUN, SAT_COMP, *STUBBED}:
        raise ValueError(f"the drone's model components are not the eight expected: {sorted(map(hex, mine))}")
    if q(entries.elems[mine[SAT_COMP]].raw, 0) == SAT_MODEL:
        return blob, False
    for comp, model in [(SAT_COMP, SAT_MODEL)] + [(c, BLANK_MODEL) for c in STUBBED]:
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
        new = SAT_MODEL if comp == SAT_TEXSTREAM else BLANK_MODEL if comp in STUBBED else model
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

    for t, name, data in satellite_assets(read):
        write(t, name, data)
    for level, lname in LEVELS.items():
        done = []
        for t, fn in ((MODEL_CR, model_table), (TEXSTREAM_CR, texstream_table)):
            data, changed = fn(read(t, level))
            write(t, level, data)
            done.append("changed" if changed else "already done")
        print(f"{lname}: the drone is the satellite ({SAT_MODEL:x}) with the sidearm on it "
              "(model, texture streaming: " + ", ".join(done) + ")")
    print(f"muzzle (dronefix.cpp MUZZLE): {MUZZLE}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
