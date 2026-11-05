"""Copy an actor subtree inside a stock level: new actors + their component rows.

For each copy of the subtree rooted at actor index `root`:
  * the actor table gets one new actor per source actor, appended at the end (after the scene
    block, so no scene-graph node: the level's 744 static-geometry actors live the same way), its
    parent = the copy of its source's parent, or the source's own parent for the subtree root;
  * every component table of the level gets a copy of each row the source actors OWN (row +8),
    with every 8-byte word naming a source actor rewritten to that actor's copy (owner, script
    actordata, ButtonInteract's press part, ...); words naming actors outside the subtree are kept;
  * world positions move by `offset`: the actor table transform, CTransformCR init_position and
    the CR15ButtonInteractCR pose at +0x80.

Component rows hold actorid / numpooled = 0xffff (unset) in every stock button row, so no indices
need fixing. The scene graph (CGSceneResource) is not touched.
"""

from __future__ import annotations

import os
import struct

from cr_rows import spans
from instance_model_cr import InstanceModels
from level_actor_table import Actor, ActorTable

ACTORS = "347869ce492dc7da"
SCENE = "a388ea69e5108f4c"
INSTANCE_MODEL = "2464c4ed290f3268"
TYPE_NAMES = {          # the types a stock button subtree uses (others are walked as flat tables)
    "142026f469321d54": "COcclusionCullCR",
    "22f9fcb2d5e52e3c": "CBoundingSphereCR",
    "2464c4ed290f3268": "CInstanceModelCR",
    "7f49abae39aaf2aa": "CComponentLODCR",
    "8b91efd51747c21e": "CR15UILayoutCR",
    "92abd3e1432bf5e8": "CTransformCR",
    "ca5a03d5a497238c": "CFrustumCullCR",
    "d99f6bbd8009c92c": "CScriptCR",
    "e9b24ea816dece48": "CR15ButtonInteractCR",
    "4127ff2ffe6be26a": "CTextureOverrideCR",
    "822fd4ccb42e8a3c": "CCanvasUICR",
}
POSITIONS = {           # type -> row offsets of a world Vec3 that moves with the copy
    "CTransformCR": (0x30,),
    "CR15ButtonInteractCR": (0x80,),
}


def remap_words(data: bytes, mapping: dict) -> bytes:
    out = bytearray(data)
    for at in range(0, len(out) - 7, 8):
        w = struct.unpack_from("<Q", out, at)[0]
        if w in mapping:
            struct.pack_into("<Q", out, at, mapping[w])
    return bytes(out)


class Place:
    """Where a copy (or a moved original) goes: p -> pivot + scale * (p - pivot) + offset."""

    def __init__(self, pivot=(0.0, 0.0, 0.0), offset=(0.0, 0.0, 0.0), scale=1.0):
        self.pivot, self.offset, self.scale = pivot, offset, scale

    def point(self, p):
        return tuple(c + self.scale * (v - c) + d for v, c, d in zip(p, self.pivot, self.offset))


def shift(row: bytes, offsets, place: "Place", scales=()) -> bytes:
    out = bytearray(row)
    for at in offsets:
        struct.pack_into("<3f", out, at, *place.point(struct.unpack_from("<3f", out, at)))
    for at in scales:
        struct.pack_into("<3f", out, at, *(v * place.scale for v in struct.unpack_from("<3f", out, at)))
    return bytes(out)


SCALES = {"CTransformCR": (0x3C,)}     # init_scale


def place_actor(transform: bytes, place: "Place") -> bytes:
    return shift(transform, (16,), place, (28,))


def subtree(table: ActorTable, root: int) -> list:
    out, todo = [], [root]
    while todo:
        i = todo.pop(0)
        out.append(i)
        todo += [j for j, a in enumerate(table.actors) if a.parent == i and j != i]
    return out


def append_flat(type_name: str, b: bytes, copies) -> bytes:
    """copies: [(mapping, Place)]. Rows owned by a mapping key are appended once per copy."""
    s = spans(type_name, b)
    head = bytearray(b[:s.rows_at])
    rows = [b[r0:r1] for r0, r1 in s.rows]
    nested = [b[n0:n1] for n0, n1 in s.nested]
    pos = POSITIONS.get(type_name, ())
    for mapping, d in copies:
        for k, owner in enumerate(s.owners):
            if owner in mapping:
                rows.append(shift(remap_words(rows[k], mapping), pos, d, SCALES.get(type_name, ())))
                nested.append(remap_words(nested[k], mapping))
    n = len(rows)
    size, cap = struct.unpack_from("<Q", head, 8)[0], struct.unpack_from("<Q", head, 40)[0]
    if n > cap:
        struct.pack_into("<Q", head, 8, n * s.stride)
        struct.pack_into("<Q", head, 40, n)
    struct.pack_into("<Q", head, 48, n)
    out = bytes(head) + b"".join(rows) + b"".join(nested)
    again = spans(type_name, out)                 # a nested table's padding must not have moved
    assert len(again.owners) == n
    for k in range(len(s.owners), n):
        assert again.nested[k][1] - again.nested[k][0] == len(nested[k]), type_name
    return out


def copy_subtree(files: dict, root: int, copies) -> dict:
    """files: {type hash: bytes} for one level (the actor table included). copies: [(new nodeids
    in subtree order, Place)]. Returns the changed files."""
    table = ActorTable.read(files[ACTORS])
    src = subtree(table, root)
    plans = []
    for nodeids, d in copies:
        assert len(nodeids) == len(src)
        taken = {a.nodeid for a in table.actors}
        assert not taken & set(nodeids), "nodeid clash"
        mapping = {table.actors[i].nodeid: n for i, n in zip(src, nodeids)}
        index = {}
        for i, n in zip(src, nodeids):
            a = table.actors[i]
            parent = index.get(a.parent, a.parent)
            index[i] = len(table.actors)
            table.actors.append(Actor(n, a.name, a.prefabid, place_actor(a.transform, d), a.numpooled,
                                      parent, list(a.bits)))
        plans.append((mapping, d))
    out = {ACTORS: table.write()}
    owners = set().union(*(m.keys() for m, _ in plans))
    for t, b in files.items():
        if t in (ACTORS, SCENE):
            continue
        if t == INSTANCE_MODEL:
            m = InstanceModels(b)
            own = m.owners
            hit = False
            for mapping, d in plans:
                for k, o in enumerate(own):
                    if o in mapping:
                        m.copy_record(k, lambda row, mp=mapping: remap_words(row, mp))
                        hit = True
            if hit:
                out[t] = m.write()
            continue
        name = TYPE_NAMES.get(t)
        if name is None:
            if any(struct.pack("<Q", o) in b for o in owners):
                try:
                    s = spans("?", b)
                except (ValueError, AssertionError, struct.error):
                    raise SystemExit(f"type {t} names a source actor and is not a flat table")
                if not owners & set(s.owners):
                    continue
                name = "?"
            else:
                continue
        s = spans(name, b)
        if owners & set(s.owners):
            out[t] = append_flat(name, b, plans)
    return out


def level_files(src: str, out: str, level: str) -> dict:
    files = {}
    for t in os.listdir(src):
        p = os.path.join(src, t, level)
        if len(t) == 16 and os.path.isfile(p):
            staged = os.path.join(out, t, level)
            files[t] = open(staged if os.path.exists(staged) else p, "rb").read()
    return files


def move_subtree(files: dict, root: int, place: "Place") -> dict:
    """Moves / scales the subtree at `root` in place: its actors and the rows they own."""
    table = ActorTable.read(files[ACTORS])
    src = subtree(table, root)
    for i in src:
        table.actors[i].transform = place_actor(table.actors[i].transform, place)
    owners = {table.actors[i].nodeid for i in src}
    out = {ACTORS: table.write()}
    for t, name in TYPE_NAMES.items():
        if t not in files or (name not in POSITIONS and name not in SCALES):
            continue
        b = bytearray(files[t])
        s = spans(name, bytes(b))
        hit = False
        for k, o in enumerate(s.owners):
            if o in owners:
                r0, r1 = s.rows[k]
                b[r0:r1] = shift(bytes(b[r0:r1]), POSITIONS.get(name, ()), place, SCALES.get(name, ()))
                hit = True
        if hit:
            out[t] = bytes(b)
    return out
