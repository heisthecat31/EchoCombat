"""POINT (the cut `point` tac mod) as a seventh tac mod: a stun field around the wall it places.

The game has only POINT's name and tuning (ability_properties.point: charge_required,
charge_up_time, radius, stun_duration); no script ever read them. POINT is built the
way UMBRAL VEIL is:

1. `point` is registered in gear_table.tacmods as POINT, and its recharge
   (required_charge, the key the engine reads) is set from charge_required.
2. Its script, `mp_combat_ability_point` (CSymbol64 94ba7ca39fc97e1a), is the barrier
   script with mark_param(POINT_RECORD): it places a barrier wall and bumps POINT's use
   counter, which VeilNet.dll (plugin/veilnet.cpp) sends to every machine as a "point
   token". It gets its `CScriptResourceWin10` entry and is attached to each player
   actor right after its barrier-script entry.
3. The controller's seventh branch (wraith -> smoke -> buff -> point, "equipped ==
   point") and the wall script's POINT mode come from fix_smoke.py --with-point: a wall
   that takes a point token hides, has no collision, waits charge_up_time, then shows
   the stun mine's burst, plays the stun field's sound and activates its stun
   explosion (veil_fx.point_block).
4. That explosion is the stun mine's own explosion component (`25905b54e61d3f10`,
   flags 0x890: stun), which this gives the barrier wall actor in every combat level's
   explosion table (4af215b19b297c34), with near / far radius = POINT's radius. The
   stun length comes from the activation (stun_duration).

    python tools/fix_point.py --base <stage> --src <extract root> --out <dir>
"""

from __future__ import annotations

import argparse
import os
import struct
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from fix_drone import EQUIPMENT, WEAPON_SETTINGS, load, save
from echocombat_config import section
from fix_smoke import BARRIER_SCRIPT, GLOBAL_LEVEL, PLAYER_ACTORS, SCRIPT_CR, SCRIPT_RESOURCE, SCRIPTS, u64
from veil_fx import POINT_MARKER, POINT_RECORD, STUN_EXPLOSION, mark_param

POINT_SCRIPT = 0x94BA7CA39FC97E1A      # CSymbol64("mp_combat_ability_point")
POINT = 0xE32DC7CAD6864AA4             # CSymbol64("point")
POINT_GEAR = {"name": "point", "display_name": "POINT"}

EXPLOSION_TYPE = "4af215b19b297c34"    # the explosion component tables, one per level
LEVELS = ["42670f2bed45703c", "43e2da7914642604", "43e2da7a0c623a19",
          "cb9977f7fc2b4526", "df5ca7b7dfa383d4"]
STUN_ACTOR = 0x7435764D2C648580
WALL_ACTOR = 0x3D8B8CA4D5292926        # the barrier wall (R15NetDynamicCover)
#: the wall's records carry ffff1f.. here (the grenades' ffff0f..), and +50h names a
#: companion component on the same actor: the wall's own (its bd1868f576836696 record)
WALL_MASK = bytes.fromhex("ffff1f0000000000")
WALL_LINK = bytes.fromhex("98527d4c8d8ed52f")
HDR, STRIDE = 0x38, 96


def add_wall_explosion(table: bytes, radius: float) -> tuple[bytes, bool]:
    """A copy of the stun mine's explosion record for the barrier wall (once)."""
    size, count = u64(table, 0x08), u64(table, 0x28)
    if size != count * STRIDE or u64(table, 0x30) != count or len(table) != HDR + size:
        raise ValueError("unexpected explosion table framing")
    recs = [table[HDR + i * STRIDE:HDR + (i + 1) * STRIDE] for i in range(count)]
    if any(u64(r, 8) == WALL_ACTOR for r in recs):
        return table, False
    stun = [r for r in recs if u64(r, 8) == STUN_ACTOR]
    if len(stun) != 1 or u64(stun[0], 0) != STUN_EXPLOSION:
        raise ValueError("no stun mine explosion record")
    new = bytearray(stun[0])
    struct.pack_into("<Q", new, 8, WALL_ACTOR)
    new[16:24] = WALL_MASK
    struct.pack_into("<ff", new, 32, radius, radius)                 # near / far radius
    new[80:88] = WALL_LINK
    head = bytearray(table[:HDR])
    struct.pack_into("<Q", head, 0x08, (count + 1) * STRIDE)
    struct.pack_into("<Q", head, 0x28, count + 1)
    struct.pack_into("<Q", head, 0x30, count + 1)
    return bytes(head) + b"".join(recs) + bytes(new), True


def attach_point_script(blob: bytes):
    """Add a point-script entry after each player actor's barrier-script entry."""
    stride, hdr = 720, 0x38
    count = u64(blob, 0x28)
    if u64(blob, 0x08) != count * stride or u64(blob, 0x30) != count:
        raise ValueError("unexpected CScriptCR framing")
    entries = [blob[hdr + stride * i:hdr + stride * (i + 1)] for i in range(count)]
    pool = blob[hdr + stride * count:]
    out, added = [], 0
    for e in entries:
        out.append(e)
        if u64(e, 8) in PLAYER_ACTORS and u64(e, 32) == BARRIER_SCRIPT:
            if any(u64(x, 8) == u64(e, 8) and u64(x, 32) == POINT_SCRIPT for x in entries):
                continue                              # already attached
            new = bytearray(e)
            struct.pack_into("<Q", new, 0, POINT_SCRIPT)
            struct.pack_into("<Q", new, 32, POINT_SCRIPT)
            out.append(bytes(new))
            added += 1
    head = bytearray(blob[:hdr])
    struct.pack_into("<Q", head, 0x08, len(out) * stride)
    struct.pack_into("<Q", head, 0x28, len(out))
    struct.pack_into("<Q", head, 0x30, len(out))
    return bytes(head) + b"".join(out) + pool, added


def main(argv) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", required=True, help="dir holding the live 607d858c90268f9a/ JSON")
    ap.add_argument("--src", required=True, help="extract root")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv[1:])

    eq_path, equipment = load(args.base, EQUIPMENT)
    tacmods = equipment["gear_table"]["tacmods"]
    if not any(t["name"] == "point" for t in tacmods):
        tacmods.append(dict(POINT_GEAR))
    print(save(args.out, EQUIPMENT, eq_path, equipment))
    print("tacmods:", [t["name"] for t in tacmods])

    ws_path, settings = load(args.base, WEAPON_SETTINGS)
    tuning = settings["ability_properties"]["point"]
    cfg = section("ability_properties", "point")                 # config/mp_weapon_settings.json
    tuning.update({k: cfg[k] for k in ("radius", "charge_required", "charge_up_time", "stun_duration") if k in cfg})
    tuning["required_charge"] = tuning["charge_required"]
    print(save(args.out, WEAPON_SETTINGS, ws_path, settings))

    barrier = open(os.path.join(args.src, SCRIPTS, f"{BARRIER_SCRIPT:x}"), "rb").read()
    mz = barrier.find(b"MZ")
    os.makedirs(os.path.join(args.out, SCRIPTS), exist_ok=True)
    open(os.path.join(args.out, SCRIPTS, f"{POINT_SCRIPT:x}"), "wb").write(
        barrier[:mz] + mark_param(barrier[mz:], POINT_MARKER, POINT_RECORD))
    os.makedirs(os.path.join(args.out, SCRIPT_RESOURCE), exist_ok=True)
    open(os.path.join(args.out, SCRIPT_RESOURCE, f"{POINT_SCRIPT:x}"), "wb").write(bytes(4))
    print(f"{SCRIPTS}/{POINT_SCRIPT:x}: mp_combat_ability_point: a barrier wall that goes off as a "
          f"{tuning['radius']} m stun field after {tuning['charge_up_time']} s, stunning for "
          f"{tuning['stun_duration']} s; {tuning['required_charge']} charge (needs VeilNet.dll)")

    os.makedirs(os.path.join(args.out, SCRIPT_CR), exist_ok=True)
    staged = os.path.join(args.out, SCRIPT_CR, GLOBAL_LEVEL)
    src = staged if os.path.exists(staged) else os.path.join(args.src, SCRIPT_CR, GLOBAL_LEVEL)
    fixed, added = attach_point_script(open(src, "rb").read())
    open(staged, "wb").write(fixed)
    print(f"global level: point script attached to {added} player actor(s)")

    os.makedirs(os.path.join(args.out, EXPLOSION_TYPE), exist_ok=True)
    for level in LEVELS:
        staged = os.path.join(args.out, EXPLOSION_TYPE, level)
        src = staged if os.path.exists(staged) else os.path.join(args.src, EXPLOSION_TYPE, level)
        fixed, added = add_wall_explosion(open(src, "rb").read(), tuning["radius"])
        open(staged, "wb").write(fixed)
        print(f"{EXPLOSION_TYPE}/{level}: barrier wall " + ("gains the stun explosion" if added else "already has it"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
