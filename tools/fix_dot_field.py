"""Give the DOT FIELD a visible field: a red copy of the arc mine's arming bubble.

The DOT script (mp_combat_grenade_dot, 97d0806e6ea89130) was written for a field model
that was never built: model component FIELD (51b9f7653ecac7cb) on the DOT magazine. No
level has it, so the field showed only its faint particle haze.

1. The model. The arc mine's arming bubble is model component ARC_BUBBLE
   (f775b4bf32c0bf2f) on the arc magazine, model asset ARC_MODEL with scene set ARC_SCENE.
   This copies it onto the DOT as FIELD, in every level that has both magazines:
   * CModelCRWin10 (ea51a0d76eb90142): its element in each of the three parallel
     per-model arrays, and its bits in the three per-model bitsets (cr_table);
   * CTransformCRWin10 (92abd3e1432bf5e8): its transform, under the DOT's root (the same
     root component id, 1505268d1c65feab, as the arc's), scaled to the DOT's radius
     (grenade_properties.dot.radius; the bubble model is a unit sphere: the arc scales it
     to its own radius);
   * CTextureStreamingCRWin10 (96832b652460ecde): its texture streaming record;
   all pointing at RED_MODEL: a copy of ARC_MODEL (its eight files) whose two materials
   are red copies (RED_MATERIALS) of the arc bubble's (it shows them in their default
   colours, light blue: tested). The arc mine keeps its own model and materials.

2. When it shows (tested: the DOT's own "field on" scene set nodes only run on the server,
   so the client never showed it). On the client the DOT's event thread (ff4f9347: state
   changed / spawned / deposited) starts the field sound (f2a71917) when the field goes on,
   and runs 69412c20 (scene set 678a.. off) when it ends and when the DOT is grabbed; the
   sound was only stopped on deposit, so it carried on after the field and into the next
   pull. So:
   * the field sound continues to 9507dc91 (a scene set node fix_dot_script.py took out of
     the setup chain), now "ARC_SCENE on": the bubble shows with the field;
   * 69412c20 is now "ARC_SCENE off" and continues to 5fefe254, the sound's stop: the
     bubble and the sound end with the field (and on a grab).

Each table starts from the staged copy when another fix tool already wrote one (the
dampener edits the DOT's transforms; fix_dot_script.py the DOT script), and is a no-op
when already done.

    python tools/fix_dot_field.py --src <extract root> --out <stage>
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
from echocombat_config import section
from le_symbol_names import symbol64

MODEL_CR = "ea51a0d76eb90142"          # CSymbol64("CModelCRWin10")
TRANSFORM_CR = "92abd3e1432bf5e8"      # CSymbol64("CTransformCRWin10")
TEXSTREAM_CR = "96832b652460ecde"      # CSymbol64("CTextureStreamingCRWin10")
MODEL_ROOT, PLAIN_ROOT = 0x168, 0x38   # root struct sizes (cr_table)
SCRIPTS = "6eace9f64204fd0"
DOT_SCRIPT = "97d0806e6ea89130"
LEVELS = {
    "42670f2bed45703c": "mpl_combat_combustion",
    "43e2da7914642604": "mpl_combat_dyson",
    "43e2da7a0c623a19": "mpl_combat_gauss",
    "cb9977f7fc2b4526": "mpl_lobby_b_combat",
    "df5ca7b7dfa383d4": "mpl_combat_fission",
}
DOT_ACTOR = 0x0C00C9AC34BD2832
ARC_ACTOR = 0x0B53172E221366BD
ARC_BUBBLE = 0xF775B4BF32C0BF2F
FIELD = 0x51B9F7653ECAC7CB
ARC_SCENE = 0x0C8DD23BD40BA0C4

# --- the red bubble model ---------------------------------------------------------
ARC_MODEL = 0x07E824DAD4CD4EF3
MODEL_TYPES = ("230554bc3beca38c", "4e426f88c1b5d7ac", "73d312a620da3824", "7b9a4c9fd03f37eb",
               "a388ea69e5108f4c", "b7d338793fa37832", "c2434c5a99e139ce", "e642bfb1abcf76df")
MODEL_DEF = "a388ea69e5108f4c"         # the one that names the materials
MATERIAL = "e3e0266f1911dafa"
RED_MODEL = int(symbol64("fx_dot_field_bubble"), 16)
#: arc material -> (red copy, {value offset: rgba}); the arc's defaults are light blue,
#: (0.06, 0.48, 1, 1) at +1A8h and (0.61, 0.94, 1, 1) at +1B8h
RED_MATERIALS = {
    0x4A9B00B6EC40FBFA: (int(symbol64("mat_dot_field_bubble_a"), 16),
                         {0x1A8: (1.0, 0.06, 0.04, 1.0), 0x1B8: (1.0, 0.55, 0.50, 1.0)}),
    0x7AC7845083D5E9A6: (int(symbol64("mat_dot_field_bubble_b"), 16),
                         {0x1A8: (1.0, 0.06, 0.04, 1.0)}),
}
#: the bubble's transform: scale (x, y, z) at +3Ch (the record: quaternion +20h,
#: position +30h, scale +3Ch)
TRANSFORM_SCALE = 0x3C


def q(b, o):
    return struct.unpack_from("<Q", b, o)[0]


def asset_files() -> list:
    """(type, name) of every file the red bubble is copied from."""
    return [(t, f"{ARC_MODEL:x}") for t in MODEL_TYPES] + [(MATERIAL, f"{m:x}") for m in RED_MATERIALS]


def red_assets(read) -> list:
    """(type, name, data): the red model's files and its two red materials."""
    out = []
    for t in MODEL_TYPES:
        data = read(t, f"{ARC_MODEL:x}")
        if t == MODEL_DEF:
            for old, (new, _) in RED_MATERIALS.items():
                if struct.pack("<Q", old) not in data:
                    raise ValueError(f"the bubble model does not use material {old:x}")
                data = data.replace(struct.pack("<Q", old), struct.pack("<Q", new))
        out.append((t, f"{RED_MODEL:x}", data))
    for old, (new, colours) in RED_MATERIALS.items():
        data = bytearray(read(MATERIAL, f"{old:x}"))
        for off, rgba in colours.items():
            r, g, b, a = struct.unpack_from("<4f", data, off)
            if not (b == 1.0 and a == 1.0 and g > r):
                raise ValueError(f"material {old:x}: no light blue colour at +{off:#x}")
            struct.pack_into("<4f", data, off, *rgba)
        out.append((MATERIAL, f"{new:x}", bytes(data)))
    return out


# --- the component tables ----------------------------------------------------------
def swap_ids(raw: bytearray, at=(), actor_at=(), model_at=()):
    for o in at:
        if q(raw, o) != ARC_BUBBLE:
            raise ValueError(f"expected the arc bubble id at +{o:#x}")
        struct.pack_into("<Q", raw, o, FIELD)
    for o in actor_at:
        if q(raw, o) != ARC_ACTOR:
            raise ValueError(f"expected the arc actor at +{o:#x}")
        struct.pack_into("<Q", raw, o, DOT_ACTOR)
    for o in model_at:
        if q(raw, o) != ARC_MODEL:
            raise ValueError(f"expected the arc bubble model at +{o:#x}")
        struct.pack_into("<Q", raw, o, RED_MODEL)


def model_table(blob: bytes) -> tuple[bytes, bool]:
    root = ct.parse(blob, MODEL_ROOT)
    recs, entries, insts = root.arrays[0], root.arrays[2], root.arrays[5]
    bitsets = (root.arrays[1], root.arrays[3], root.arrays[4])
    key = lambda e: (q(e.raw, 0), q(e.raw, 8))
    if any(key(e) == (FIELD, DOT_ACTOR) for e in recs.elems):
        return blob, False
    hits = [i for i, e in enumerate(recs.elems) if key(e) == (ARC_BUBBLE, ARC_ACTOR)]
    if len(hits) != 1:
        raise ValueError(f"{len(hits)} arc bubble model records")
    i, n = hits[0], recs.count
    if not (len(entries.elems) == len(insts.elems) == n):
        raise ValueError("per-model arrays are not parallel")
    rec, entry, inst = ct.copy(recs.elems[i]), ct.copy(entries.elems[i]), ct.copy(insts.elems[i])
    swap_ids(rec.raw, at=(0,), actor_at=(8,))
    swap_ids(entry.raw, at=(0x10,), model_at=(0,))
    swap_ids(inst.raw, at=(0, 0x30), actor_at=(8,), model_at=(0x20,))
    for a, e in ((0, rec), (2, entry), (5, inst)):
        ct.add_element(root, a, e)
    for bits in bitsets:                       # model n gets model i's bit in each bitset
        idx = root.arrays.index(bits)
        while len(bits.elems) * 64 <= n:
            ct.add_element(root, idx, ct.Node(bytearray(8)))
        on = q(bits.elems[i // 64].raw, 0) >> (i % 64) & 1
        w = bits.elems[n // 64].raw
        struct.pack_into("<Q", w, 0, q(w, 0) & ~(1 << (n % 64)) | on << (n % 64))
    return ct.build(root), True


def plain_table(blob: bytes, actor_offsets=(8,), model_at=(), scale=None) -> tuple[bytes, bool]:
    """One-array tables: a copy of the arc bubble's record for the DOT."""
    root = ct.parse(blob, PLAIN_ROOT)
    recs = root.arrays[0]
    if any((q(e.raw, 0), q(e.raw, 8)) == (FIELD, DOT_ACTOR) for e in recs.elems):
        return blob, False
    hits = [e for e in recs.elems if (q(e.raw, 0), q(e.raw, 8)) == (ARC_BUBBLE, ARC_ACTOR)]
    if len(hits) != 1:
        raise ValueError(f"{len(hits)} arc bubble records")
    new = ct.copy(hits[0])
    swap_ids(new.raw, at=(0,), actor_at=[o for o in actor_offsets if q(new.raw, o) == ARC_ACTOR],
             model_at=model_at)
    if scale is not None:
        if struct.unpack_from("<3f", new.raw, TRANSFORM_SCALE) != (1.0, 1.0, 1.0):
            raise ValueError("the bubble's transform has no unit scale where expected")
        struct.pack_into("<3f", new.raw, TRANSFORM_SCALE, scale, scale, scale)
    ct.add_element(root, 0, new)
    return ct.build(root), True


# --- the DOT script: show / hide on the client ------------------------------------
SET_LOAD, SET_FLAG = 0x4B, 0x8C        # in an EnableModelSceneSet execute_node: movdqa xmm0,
                                       # [rip+x] (component, scene set); mov byte [rsp+54h], on
SHOW_NODE = 0xCFE0                     # execute_node_9507dc91 -> ARC_SCENE on
HIDE_NODE = 0xDA00                     # execute_node_69412c20 -> ARC_SCENE off
#: next_node: (site, original instruction, replacement)
LINKS = [
    (0x12B4F, bytes.fromhex("48b81719a7f201000000"), b"\x48\xb8" + struct.pack("<Q", 0x9507DC91)),  # sound -> show
    (0x11E33, bytes.fromhex("b8c59e08cd"), None),                                                 # show: end
    (0x11B72, bytes.fromhex("48b8202c416901000000"), b"\x48\xb8" + struct.pack("<Q", 0x5FEFE254)),  # hide -> sound stop
]
NEXT_DEFAULT_END = 0x12CDD             # next_node: or rax, -1; ret


def dot_script(pe_bytes: bytes) -> tuple[bytes, bool]:
    from fix_smoke import PE, rel32
    pe = PE(pe_bytes)
    site, old, _ = LINKS[0]
    if pe.read(site, len(old)) != old:
        if pe.read(site, 10) == LINKS[0][2]:
            return pe_bytes, False
        raise ValueError("unexpected DOT next_node: wrong DOT script build")
    _, _, vs, va, rs, _ = pe.section(b".rdata")
    rdata = pe.read(va, min(vs, rs))
    const = rdata.find(struct.pack("<QQ", FIELD, 0x678A17B53BD64695))   # the hide node's own constant
    if const < 0:
        raise ValueError("no (FIELD, 678a..) constant")
    # a 16-byte aligned (FIELD, ARC_SCENE) constant: the existing one turned into it is
    # shared by three 678a.. nodes (e94b7b9c, 9507dc91, 69412c20), all of which become the
    # bubble's own
    if (va + const) % 16:
        raise ValueError("unaligned scene set constant")
    pe.write(va + const + 8, struct.pack("<Q", ARC_SCENE))
    for node, on in ((SHOW_NODE, 1), (HIDE_NODE, 0)):
        ins = pe.read(node + SET_LOAD, 8)
        if ins[:4] != bytes.fromhex("660f6f05") or pe.read(node + SET_FLAG, 5) != bytes.fromhex("c644245400"):
            raise ValueError(f"unexpected scene set node at {node:#x}")
        if node + SET_LOAD + 8 + struct.unpack_from("<i", ins, 4)[0] != va + const:
            raise ValueError(f"scene set node at {node:#x} does not load the 678a.. constant")
        pe.write(node + SET_FLAG + 4, bytes([on]))
    for site, old, new in LINKS:
        if pe.read(site, len(old)) != old:
            raise ValueError(f"unexpected next_node at {site:#x}")
        pe.write(site, new if new is not None else b"\xe9" + rel32(site + 5, NEXT_DEFAULT_END))
    return bytes(pe.d), True


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

    radius = float(section("grenade_properties", "dot")["radius"])
    for t, name, data in red_assets(read):
        write(t, name, data)
    for level, lname in LEVELS.items():
        done = []
        for t, fn in ((MODEL_CR, model_table),
                      (TRANSFORM_CR, lambda b: plain_table(b, (8, 0x58), scale=radius)),
                      (TEXSTREAM_CR, lambda b: plain_table(b, model_at=(0x20,)))):
            data, changed = fn(read(t, level))
            write(t, level, data)
            done.append("added" if changed else "already there")
        print(f"{lname}: the red bubble ({RED_MODEL:x}) on the DOT as {FIELD:x}, radius {radius} "
              "(model, transform, texture streaming: " + ", ".join(done) + ")")
    script = read(SCRIPTS, DOT_SCRIPT)
    mz = script.find(b"MZ")
    patched, changed = dot_script(script[mz:])
    write(SCRIPTS, DOT_SCRIPT, script[:mz] + patched)
    print(f"{SCRIPTS}/{DOT_SCRIPT}: " + ("the bubble shows with the field sound; it and the sound end with "
                                        "the field" if changed else "already patched"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
