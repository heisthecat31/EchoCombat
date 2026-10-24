"""MEDIGUN: a gun that heals one teammate with Repair Matrix's beam (TF2's Medi Gun).

The data half; PowerBoost.dll (plugin/powerboost.cpp, "MEDIGUN") does the rest.

1. `medigun` is registered in gear_table.weapons as MEDIGUN, so the loadout terminal lists it.
   It has no gun actors of its own: PowerBoost.dll makes the gun enable manager
   (mpl_cbt_wpn_integrated_enable_manager2) read a MEDIGUN slot as "scout", so the player
   holds COMET's gun. With MEDIGUN equipped the plugin hides the gun hand's trigger from the
   game (COMET never charges or fires) and uses it for the beam instead.
2. Every player carries a third heal bubble, MEDI_BUBBLE (a copy of the stock Repair Matrix
   record, as fix_buff does for OVERCHARGE), and a copy of Repair Matrix's script that drives
   only that bubble (its handles retargeted), reads ability_properties.medigun, draws its
   effects from the gun's attach bone instead of the hand, and never activates the bubble
   itself: the plugin does (trigger held), sets its tuning, ends it on release, and narrows
   its targeting to one teammate in a cone (heal_radius = range + (angle + 500) / 100000,
   which PowerBoost tells apart from OVERCHARGE's range + angle / 100000).
3. Heal: Repair Matrix's rate (heal_amt / heal_duration) x heal_scale, for beam_seconds of
   holding at most; then the beam overheats for overheat_seconds. No self heal, no damage.

    python tools/fix_medigun.py --base <stage> --src <extract root> --out <dir>
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
from fix_smoke import PE, u64, SCRIPTS, SCRIPT_RESOURCE, SCRIPT_CR, GLOBAL_LEVEL, PLAYER_ACTORS
from le_symbol_names import symbol64
import cr_table as ct
import fix_buff

MEDIGUN = int(symbol64("medigun"), 16)
MEDIGUN_GEAR = {"name": "medigun", "display_name": "MEDIGUN"}
MEDI_SCRIPT = int(symbol64("mp_combat_ability_medigun"), 16)
MEDI_BUBBLE = int(symbol64("echocombat_medigun_bubble"), 16)
MEDI_PREFIX = int(symbol64("ability_properties|medigun|"), 16)
MEDI_UNIQUE = int(symbol64("ability_properties|medigun|unique_healing_only"), 16)
#: the bone Repair Matrix's effects hang from (its one bone constant), and the gun's attach bone
HAND_BONE = 0xCD009AA0BC77FD03          # EXP_R1_Hand1
#: the gun hand's attach bone on the player rig. EXP_R1_* is the left side there: with
#: EXP_R1_ToolAttach1 the beam left the left hand (tested 2026-10-19); right-handed players
#: hold the gun on EXP_L1_ToolAttach1.
GUN_BONE = 0x46FF0AC8FA842B21           # EXP_L1_ToolAttach1
#: the player model locator the beam and the hand effects spawn on: Repair Matrix's off hand.
#: MEDIGUN's spawn on the gun's attach bone instead, so the beam leaves the gun.
SPAWN_HAND = 0x64A149A1D3286EA4         # fx_spawn_hand
#: the beam's start sound (two PlaySound inputs): an id with no sound, so it starts silently
BEAM_START_SOUND = 0xBD027FF1EBD9CFA8   # evt_sfx_heal_beam_start
SILENT = int(symbol64("echocombat_medigun_silent"), 16)
#: Repair Matrix's loop sounds (Wwise event ids, imm32 in the PlaySound nodes): the bubble on
#: the user, on teammates, on enemies, and the beam's receive loop. MEDIGUN plays none of them
#: (their stops stay: stopping nothing is harmless).
LOOP_STARTS = (0xBBE4E309, 0x689F4621, 0xB408CCC9, 0x9FC3F082)   # loop_heal_bubble_teammate_start,
#                    loop_heal_bubble_enemy_start, loop_heal_beam_receive_start, loop_heal_bubble_player_start
SILENT_EVENT = 0x00000001        # no Wwise event has this id
#: heal script: R15NetHealBubbleActivate's execute_node -> "done" at once
ACTIVATE_NODE, ACTIVATE_OLD = fix_buff.ACTIVATE_NODE, fix_buff.ACTIVATE_OLD
#: the cone code PowerBoost reads from the radius fraction: angle + CONE_TAG
CONE_TAG = 500

CONFIG = section("ability_properties", "medigun")
#: every actor that carries Repair Matrix's script and bubble gets MEDIGUN's too: the two combat
#: player prefabs, and b113997837c29003 -- the copy other machines show a player as (without it a
#: MEDIGUN bubble activated on one machine has no bubble to activate on the server or the others)
MEDI_ACTORS = fix_buff.OC_ACTORS


def tuning(heal: dict, cfg: dict) -> dict:
    """ability_properties.medigun: the plugin's values, and the bubble keys from them."""
    rate = heal["heal_amt"] / heal["heal_duration"] * cfg.get("heal_scale", 0.85)
    seconds = cfg.get("beam_seconds", 40)
    length, angle = round(cfg.get("range", 20)), round(cfg.get("cone_angle", 20))
    if not (1 <= length <= 100 and 1 <= angle <= 90):
        raise ValueError(f"range {length} / cone_angle {angle} out of range")
    out = dict(cfg)
    out.update({
        "heal_per_second": round(rate, 4),
        "heal_amt": round(rate * seconds, 3), "heal_duration": seconds,
        "heal_radius": length + (angle + CONE_TAG) / 100000,
        "cap_healing": False, "max_healing": 0, "scale_healing": False, "min_heal_mult": 1,
        "time_to_max_heal": 0, "self_heal_mult": 0, "unique_healing_only": True,
    })
    return out


def medigun_script(heal_pe: bytes) -> bytes:
    """Repair Matrix's script for the MEDIGUN bubble: its tuning lookups, its bubble, the
    gun's bone, none of its loop sounds, and a bubble activate node that never activates anything."""
    out = bytes(heal_pe)
    # the bone: a node input's default and its two setters
    for old, new, n in ((fix_buff.HEAL_PREFIX, MEDI_PREFIX, 1), (fix_buff.HEAL_UNIQUE, MEDI_UNIQUE, 1),
                        (HAND_BONE, GUN_BONE, 3), (SPAWN_HAND, GUN_BONE, 9), (BEAM_START_SOUND, SILENT, 2)):
        o = struct.pack("<Q", old)
        if out.count(o) != n:
            raise ValueError(f"heal script: expected {n} of {old:#x}, found {out.count(o)}")
        out = out.replace(o, struct.pack("<Q", new))
    old, new = struct.pack("<Q", fix_buff.HEAL_BUBBLE), struct.pack("<Q", MEDI_BUBBLE)
    if out.count(old) != fix_buff.HEAL_BUBBLE_REFS:
        raise ValueError(f"heal script has {out.count(old)} heal bubble ids, not {fix_buff.HEAL_BUBBLE_REFS}")
    out = out.replace(old, new)
    for event in LOOP_STARTS:
        imm = bytes.fromhex("c745ef") + struct.pack("<I", event)          # mov dword [rbp-11h], event
        if out.count(imm) != 1:
            raise ValueError(f"heal script: expected one PlaySound of {event:#x}, found {out.count(imm)}")
        out = out.replace(imm, bytes.fromhex("c745ef") + struct.pack("<I", SILENT_EVENT))
    pe = PE(out)
    if pe.read(ACTIVATE_NODE, len(ACTIVATE_OLD)) != ACTIVATE_OLD:
        raise ValueError("unexpected heal script build (bubble activate node)")
    pe.write(ACTIVATE_NODE, bytes.fromhex("31c0 c3"))
    return bytes(pe.d)


def add_bubbles(blob: bytes) -> tuple[bytes, int]:
    """Each combat player's stock bubble record copied as MEDI_BUBBLE (global level)."""
    root = ct.parse(blob, 0x38)
    recs = root.arrays[0].elems
    have = {u64(e.raw, 8) for e in recs if u64(e.raw, 0) == MEDI_BUBBLE}
    added = 0
    for e in list(recs):
        actor = u64(e.raw, 8)
        if u64(e.raw, 0) == fix_buff.HEAL_BUBBLE and actor in MEDI_ACTORS and actor not in have:
            new = ct.copy(e)
            struct.pack_into("<Q", new.raw, 0, MEDI_BUBBLE)
            ct.add_element(root, 0, new)
            added += 1
    return (ct.build(root) if added else blob), added


def attach_script(blob: bytes) -> tuple[bytes, int]:
    """A MEDIGUN-script entry after each combat player's heal-script entry."""
    stride, hdr = 720, 0x38
    count = u64(blob, 0x28)
    if u64(blob, 0x08) != count * stride or u64(blob, 0x30) != count:
        raise ValueError("unexpected CScriptCR framing")
    entries = [blob[hdr + stride * i:hdr + stride * (i + 1)] for i in range(count)]
    pool = blob[hdr + stride * count:]
    out, added = [], 0
    for e in entries:
        out.append(e)
        if u64(e, 8) in MEDI_ACTORS and u64(e, 32) == fix_buff.HEAL_SCRIPT:
            if any(u64(x, 8) == u64(e, 8) and u64(x, 32) == MEDI_SCRIPT for x in entries):
                continue
            new = bytearray(e)
            struct.pack_into("<Q", new, 0, MEDI_SCRIPT)
            struct.pack_into("<Q", new, 32, MEDI_SCRIPT)
            out.append(bytes(new))
            added += 1
    head = bytearray(blob[:hdr])
    struct.pack_into("<Q", head, 0x08, len(out) * stride)
    struct.pack_into("<Q", head, 0x28, len(out))
    struct.pack_into("<Q", head, 0x30, len(out))
    return bytes(head) + b"".join(out) + pool, added


def staged_or_src(out: str, src: str, t: str, asset: str) -> tuple[str, bytes]:
    staged = os.path.join(out, t, asset)
    path = staged if os.path.exists(staged) else os.path.join(src, t, asset)
    os.makedirs(os.path.join(out, t), exist_ok=True)
    return staged, open(path, "rb").read()


def main(argv) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", required=True, help="dir holding the live 607d858c90268f9a/ JSON")
    ap.add_argument("--src", required=True, help="extract root")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv[1:])

    eq_path, equipment = load(args.base, EQUIPMENT)
    weapons = equipment["gear_table"]["weapons"]
    if not any(w["name"] == "medigun" for w in weapons):
        weapons.append(dict(MEDIGUN_GEAR))
    print(save(args.out, EQUIPMENT, eq_path, equipment))
    print("weapons:", [w["name"] for w in weapons])

    ws_path, settings = load(args.base, WEAPON_SETTINGS)
    t = tuning(settings["ability_properties"]["heal"], CONFIG)
    settings["ability_properties"]["medigun"] = t
    print(save(args.out, WEAPON_SETTINGS, ws_path, settings))
    print(f"medigun: {t['heal_per_second']} hp/s for {t['heal_duration']} s, then {t.get('overheat_seconds', 3)} s "
          f"overheat; one teammate in {t.get('cone_angle', 20)} deg out to {t.get('range', 20)} m "
          f"(bubble radius {t['heal_radius']})")

    heal = open(os.path.join(args.src, SCRIPTS, f"{fix_buff.HEAL_SCRIPT:x}"), "rb").read()
    mz = heal.find(b"MZ")
    os.makedirs(os.path.join(args.out, SCRIPTS), exist_ok=True)
    open(os.path.join(args.out, SCRIPTS, f"{MEDI_SCRIPT:x}"), "wb").write(heal[:mz] + medigun_script(heal[mz:]))
    os.makedirs(os.path.join(args.out, SCRIPT_RESOURCE), exist_ok=True)
    open(os.path.join(args.out, SCRIPT_RESOURCE, f"{MEDI_SCRIPT:x}"), "wb").write(bytes(4))
    print(f"{SCRIPTS}/{MEDI_SCRIPT:x}: mp_combat_ability_medigun (bubble {MEDI_BUBBLE:x})")

    staged, blob = staged_or_src(args.out, args.src, SCRIPT_CR, GLOBAL_LEVEL)
    fixed, added = attach_script(blob)
    open(staged, "wb").write(fixed)
    print(f"global level: MEDIGUN script attached to {added} player actor(s)")
    staged, blob = staged_or_src(args.out, args.src, fix_buff.BUBBLE_CR, GLOBAL_LEVEL)
    fixed, added = add_bubbles(blob)
    open(staged, "wb").write(fixed)
    print(f"global level: MEDIGUN heal bubble on {added} player actor(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
