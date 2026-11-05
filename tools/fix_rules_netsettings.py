"""Private Combat matches: a synced rules-settings actor in each Combat level.

Arena's private-match rules (the paged RULES screen) are a level actor,
mp_arena_rules_netsettings, whose R15NetUISettings component names a settings file
(sourcedb/rad15/json/r14/config/uisettings/arena_private_rules.json: pages of rows) that
the engine loads and keeps in sync between the server and the players. Only mpl_arena_a
has one. This gives a Combat level its own, mp_combat_rules_netsettings, naming
combat_custom_rules.json (config/combat_custom_rules.json, copied into each install's
uisettings folder by the deploy). Arena is not touched.

The actor, as Arena's (docs/combat_rules_screen.md), lives in six of the level's resources:

  CActorDataResource       (347869ce492dc7da)  the actor row (level_actor_table.py)
  CR15NetVarCR             (ac05e44816844a00)  a 32-byte component record
  CR15NetIdCR              (c29715d62e039402)  a 32-byte component record
  CR15NetUISettingsCR      (515bf2b6e2687c68)  a NEW resource for the level: Arena's,
                                               with the actor and file name swapped
  CComponentSpaceResource  (6901365c8bb8bf50)  the level's component systems: + the
                                               R15NetUISettings key
  CArchiveResource         (2a41cf1c1d9e5d32)  the level's resource list: + the new
                                               resource and its type

    python tools/fix_rules_netsettings.py --src <extract root> --out <stage dir> [--level <hash> ...]
"""

from __future__ import annotations

import argparse
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from le_symbol_names import symbol64  # noqa: E402
from level_actor_table import Actor, ActorTable, UNSET, signed  # noqa: E402

ACTORS = "347869ce492dc7da"
NETVAR = "ac05e44816844a00"
NETID = "c29715d62e039402"
NETUI = "515bf2b6e2687c68"
SPACE = "6901365c8bb8bf50"
ARCHIVE = "2a41cf1c1d9e5d32"
ARENA = "576ed3f8428ebc4b"                       # mpl_arena_a: the source of the copies
COMBAT_LEVELS = {"43e2da7914642604": "mpl_combat_dyson"}   # prototype: Dyson only

ARENA_ACTOR = 0xE3B8354D79B3D383                 # mp_arena_rules_netsettings
ACTOR_NAME = "mp_combat_rules_netsettings"
ARENA_FILE = b"arena_private_rules"
RULES_FILE = b"combat_custom_rules"              # same length: nothing in the resource moves
NETUI_KEY = 0x145DE6FF19A55DFB                   # R15NetUISettings in a component space
assert len(RULES_FILE) == len(ARENA_FILE)


def sym(name: str) -> int:
    return int(symbol64(name), 16)


def read(src: str, out: str, t: str, name: str) -> bytes:
    staged = os.path.join(out, t, name)
    return open(staged if os.path.exists(staged) else os.path.join(src, t, name), "rb").read()


def write(out: str, t: str, name: str, data: bytes):
    os.makedirs(os.path.join(out, t), exist_ok=True)
    open(os.path.join(out, t, name), "wb").write(data)


# --- base component tables: [descriptor][count x 32-byte SProperties] ------------------
def base_records(b: bytes):
    count = struct.unpack_from("<Q", b, 48)[0]
    if len(b) != 56 + 32 * count:
        raise ValueError("not a base component table")
    return [b[56 + 32 * k:88 + 32 * k] for k in range(count)]


def base_table(template: bytes, records) -> bytes:
    """Stock base tables hold capacity == count rows and nothing after them."""
    head = bytearray(template[:56])
    n = len(records)
    struct.pack_into("<Q", head, 8, 32 * n)          # size = 32 * capacity
    struct.pack_into("<Q", head, 40, n)              # capacity
    struct.pack_into("<Q", head, 48, n)              # count
    return bytes(head) + b"".join(records)


def add_base_record(b: bytes, arena: bytes, node: int) -> tuple:
    records = base_records(b)
    if any(struct.unpack_from("<Q", r, 8)[0] == node for r in records):
        return b, False
    src = [r for r in base_records(arena) if struct.unpack_from("<Q", r, 8)[0] == ARENA_ACTOR]
    if len(src) != 1:
        raise ValueError("Arena's record for its netsettings actor not found")
    rec = bytearray(src[0])
    struct.pack_into("<Q", rec, 8, node)
    return base_table(b, records + [bytes(rec)]), True


# --- the level's component space: level id, descriptor, sorted {key, level} -------------
def add_space_key(b: bytes, key: int) -> tuple:
    level = b[:8]
    n = struct.unpack_from("<Q", b, 8 + 48)[0]
    entries = [struct.unpack_from("<Q", b, 64 + 16 * k)[0] for k in range(n)]
    if len(b) != 64 + 16 * n or any(b[64 + 16 * k + 8:64 + 16 * k + 16] != level for k in range(n)):
        raise ValueError("unexpected component space layout")
    if key in entries:
        return b, False
    entries.append(key)
    entries.sort(key=signed)
    head = bytearray(b[:64])
    struct.pack_into("<Q", head, 8 + 8, 16 * (n + 1))
    struct.pack_into("<Q", head, 8 + 40, n + 1)
    struct.pack_into("<Q", head, 8 + 48, n + 1)
    return bytes(head) + b"".join(struct.pack("<Q", e) + level for e in entries), True


# --- the level's archive: {u32 0, u32 n} n x {type, name}, u32 types, types x {type, tag, flag} --
def read_archive(b: bytes):
    zero, n = struct.unpack_from("<II", b, 0)
    pairs = [struct.unpack_from("<QQ", b, 8 + 16 * k) for k in range(n)]
    at = 8 + 16 * n
    t = struct.unpack_from("<I", b, at)[0]
    types = [struct.unpack_from("<QII", b, at + 4 + 16 * k) for k in range(t)]
    tail = b[at + 4 + 16 * t:]
    if zero or len(tail) > 8:
        raise ValueError("unexpected archive layout")
    return pairs, types, tail


def write_archive(pairs, types, tail) -> bytes:
    out = struct.pack("<II", 0, len(pairs)) + b"".join(struct.pack("<QQ", *p) for p in pairs)
    out += struct.pack("<I", len(types)) + b"".join(struct.pack("<QII", *t) for t in types)
    return out + tail


def add_archive_entry(b: bytes, arena: bytes, rtype: int, name: int) -> tuple:
    pairs, types, tail = read_archive(b)
    if write_archive(pairs, types, tail) != b:
        raise ValueError("the archive does not round-trip: not editing it")
    if (rtype, name) in pairs:
        return b, False
    if not any(t[0] == rtype for t in types):
        src = [t for t in read_archive(arena)[1] if t[0] == rtype]
        if len(src) != 1:
            raise ValueError(f"Arena's archive has no type record for {rtype:016x}")
        types.append(src[0])
        types.sort(key=lambda t: signed(t[0]))
    order = {t[0]: k for k, t in enumerate(types)}
    pairs.append((rtype, name))
    pairs.sort(key=lambda p: order[p[0]])                 # grouped by type, in the types' order
    return write_archive(pairs, types, tail), True


# --- the R15NetUISettings resource: Arena's, re-aimed ------------------------------------
def netui_resource(arena: bytes, node: int) -> bytes:
    old, new = struct.pack("<Q", ARENA_ACTOR), struct.pack("<Q", node)
    if arena.count(old) != 3 or arena.count(ARENA_FILE + b"\x00") != 2:
        raise ValueError("unexpected Arena R15NetUISettings resource")
    return arena.replace(old, new).replace(ARENA_FILE + b"\x00", RULES_FILE + b"\x00")


def patch_level(src: str, out: str, level: str) -> list:
    node = sym(ACTOR_NAME)
    lvl = int(level, 16)
    done = []
    # 1. the actor
    table = ActorTable.read(read(src, out, ACTORS, level))
    if not any(a.nodeid == node for a in table.actors):
        arena = ActorTable.read(read(src, out, ACTORS, ARENA))
        a = next(x for x in arena.actors if x.nodeid == ARENA_ACTOR)
        table.actors.append(Actor(node, node, UNSET, a.transform, a.numpooled, a.parent, list(a.bits)))
        write(out, ACTORS, level, table.write())
        done.append(f"actor {ACTOR_NAME} (#{len(table.actors) - 1})")
    # 2. its NetVar and NetId records
    for t, label in ((NETVAR, "NetVar"), (NETID, "NetId")):
        data, added = add_base_record(read(src, out, t, level), read(src, out, t, ARENA), node)
        if added:
            write(out, t, level, data)
            done.append(label)
    # 3. its R15NetUISettings resource
    write(out, NETUI, level, netui_resource(read(src, out, NETUI, ARENA), node))
    done.append(f"R15NetUISettings -> {RULES_FILE.decode()}")
    # 4. the component system
    data, added = add_space_key(read(src, out, SPACE, level), NETUI_KEY)
    if added:
        write(out, SPACE, level, data)
        done.append("component space")
    # 5. the archive
    data, added = add_archive_entry(read(src, out, ARCHIVE, level), read(src, out, ARCHIVE, ARENA),
                                    int(NETUI, 16), lvl)
    if added:
        write(out, ARCHIVE, level, data)
        done.append("archive")
    return done


def main(argv) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", required=True, help="extract root (<type>/<asset>)")
    ap.add_argument("--out", required=True, help="stage directory")
    ap.add_argument("--level", action="append", help="level hash (default: the Combat levels)")
    args = ap.parse_args(argv)
    for level in args.level or COMBAT_LEVELS:
        try:
            done = patch_level(args.src, args.out, level)
        except (ValueError, StopIteration, FileNotFoundError) as e:
            sys.exit(f"{COMBAT_LEVELS.get(level, level)}: {e}")
        print(f"{COMBAT_LEVELS.get(level, level)}: rules settings actor: {', '.join(done) or 'already there'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
