"""POWER BOOST (the cut `buff` tac mod) as a sixth tac mod: Repair Matrix in purplish red.

The engine has no buff / damage-reduction system a script can drive, but it
has Repair Matrix's: the heal bubble component every player carries
(CR15NetHealBubbleCR), run from `mp_combat_ability_heal` (6a0f689e5b91c666)
through the R15NetHealBubble* nodes. POWER BOOST is that tac mod, same
behaviour and tuning, recoloured from green to purplish red (the code still says gold):

1. `buff` is registered in gear_table.tacmods as POWER BOOST.
2. Its script, `mp_combat_ability_buff` (CSymbol64 4b65d1b0088d2682), is a
   copy of the heal script whose three colour node classes recolour on the
   way in: a new `.gold` section holds a stub per class, run from each
   class's Execute entry (`mov [rsp+8], rbx` -> jmp stub; the stub recolours
   the node's colour fields when green is the strongest channel, so the
   reds stay red, then does that instruction and jumps back):
     * SETMATERIALPROPERTYCOLORNODE (val_x..z, node+44h) and
       SETMODELLIGHTCOLORNODE (color_x..z, node+20h): rgb = max(rgb) * GOLD
     * SETFULLSCREENTINTNODE (tint r..b, node+08h): rgb = min + (max-min) * TINT
       (keeps the tint as light as the green one was)
   The particle effects have their green baked in; the buff script spawns
   recoloured copies (gold_particles).
3. The script gets its `CScriptResourceWin10` entry and is attached to each
   player actor right after its heal-script entry.
4. The controller's sixth branch (wraith -> smoke -> buff, "equipped == buff")
   comes from fix_smoke.py --with-buff.
5. The buff (phase 1 of the config's design): using POWER BOOST heals yourself
   with a "marker" amount, 1,000,000 + dr_permille * 1000 + dr_duration s, read
   from ability_properties.buff at deploy, through a R15NetDamageableHeal node
   transplanted from the wraith script and run just before the
   R15NetHealBubbleActivate node (which still runs, so the ability ends and
   recharges as before; the heal runs on a snapshot of the node's context, see
   marker_stub). PowerBoost.dll (plugin/powerboost.cpp) catches the marker
   on your client, forwards it to the server as a negative DamageDealt (which the
   server turns back into a heal), and the server's copy reduces your damage taken
   by dr for dr_duration.
6. The link (phase 2): the buff script's bubble reads ability_properties.buff
   (its "ability_properties|heal|" lookups are re-pointed), and link_tuning()
   fills in the bubble keys from len / init_angle / heal_amt_on_success /
   dr_duration / conn_time. PowerBoost.dll narrows the bubble's radius check to
   the init_angle cone of the owner's aim and gives each linked teammate the dr
   buff; the bubble's tethers are the (recoloured) link.
7. The revive (do_rez_buff) is cheat death: a linked teammate survives the first hit
   that would kill them at 1 health, with a short grace after it, once per buff. The
   marker carries it (REZ_FLAG); PowerBoost.dll does the rest on the server.

    python tools/fix_buff.py --base <stage> --src <extract root> --out <dir>
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
from fix_smoke import PE, rel32, u64, SCRIPTS, SCRIPT_RESOURCE, SCRIPT_CR, GLOBAL_LEVEL, PLAYER_ACTORS
from veil_fx import SELF, add_section, transplant

HEAL_SCRIPT = 0x6A0F689E5B91C666
BUFF_SCRIPT = 0x4B65D1B0088D2682       # CSymbol64("mp_combat_ability_buff")
BUFF = 0xC8C33E48386618B6              # CSymbol64("buff")
BUFF_GEAR = {"name": "buff", "display_name": "POWER BOOST"}

#: Purplish red (it was dark gold; the names stayed). Material / light colours become
#: max(rgb) * GOLD; the fullscreen tint becomes min + (max - min) * TINT.
GOLD = (0.80, 0.06, 0.55)
TINT = (1.00, 0.30, 0.75)

#: Repair Matrix's particle effects have their green baked in; the buff script spawns
#: recoloured copies of them instead (Repair Matrix keeps the originals).
#: original -> copy: the beam (one per bubble slot) and the healer's hand effect.
PARTICLES = {0x39424707BB2DF316: 0xFA379871313745A5,    # -> CSymbol64("fx_power_boost_beam")
             0xBE696D7D300CBAF7: 0xFA3798713B334AAC}    # -> CSymbol64("fx_power_boost_hand")
BEAM = 0x39424707BB2DF316
#: --fx-test: the stun mine's field effect, put in the beam copy's place
FX_TEST_EFFECT = 0xDE22B615C9C69CDD
#: each effect is two assets: the effect itself (recoloured) and a companion (copied)
PARTICLE_TYPE, PARTICLE_COMPANION = "3ae7c41914252baa", "be45c22fa8c2d3f"
#: the effects' colour: rgb = min + (max - min) * FX_GOLD (keeps their white cores white).
#: Red and blue are kept close, so it stays purplish red whether the effect's 8-bit
#: colours are stored RGB or BGR.
FX_GOLD = (1.00, 0.075, 0.69)

ENTRY = bytes.fromhex("48895c2408")   # mov [rsp+8], rbx: first instruction of each Execute
#: (Execute rva in the heal script, colour field offset in the node, mode)
CLASSES = [
    (0x4990, 0x44, "max"),             # SETMATERIALPROPERTYCOLORNODE::Execute: val_x..z
    (0x5A50, 0x20, "max"),             # SETMODELLIGHTCOLORNODE::Execute: color_x..z
    (0x50E0, 0x08, "span"),            # SETFULLSCREENTINTNODE::Execute: tintr..b
]
GOLD_SECTION = b".gold\0\0\0"

# --- the buff itself (phase 1: on use, buff yourself) ---------------------------
#: The wraith script (mp_combat_ability_wraith) is the one script with a
#: R15NetDamageableHeal node; it is transplanted into the buff script.
WRAITH_SCRIPT = "e1971566197d460"
HEAL_NODE = {
    "ctor": (0x5240, 51, "37739209daec313fdfb447322c9bb1ad393c8b8dd29b75efd3876ca5da56b1cc", []),
    "exec": (0x5280, 166, "ae03fcc1cceaafa693bd29c42825efa7d3a6c1edc61e3248f79fa56edc704274",
             [0x1e, 0x36, 0x47, 0x4d, 0x5e, 0x64, 0x75, 0x7b, 0x8c, 0xa2]),
    "bind": (0x5170, 194, "0460d9e9d721fe6b1d09629eb89ce02abba86870e63dee4ee69233776142e731",
             [0x22, 0x29, 0x30, 0x37, 0x4e, 0x55, 0x5c, 0x73, 0x7a, 0x81, 0x98, 0x9f, 0xa6]),
}
#: heal script: setup_bindings' call to R15NETHEALBUBBLESETHEALDURATIONNODE::Bind (rdi = binding table)
HEAL_BIND_CALL, HEAL_BIND_TARGET = 0x7905, 0x1900
#: heal script: the R15NetHealBubbleActivate node (execute_node_fb9e3f50), run on use
ACTIVATE_NODE = 0xAC00
ACTIVATE_OLD = bytes.fromhex("4053 4883ec40")
MARKER_BASE = 1_000_000
#: added to the marker when the buff carries cheat death (ability_properties.buff.do_rez_buff)
REZ_FLAG = 2_000_000

# --- phase 2: the link (the heal bubble's targeting, reshaped into a cone) -------
#: The heal script reads its bubble tuning as "ability_properties|heal|" + key; the
#: buff script's copy reads "ability_properties|buff|" + key instead.
HEAL_PREFIX = 0x71EEF7EEEA7CFD64          # CSymbol64("ability_properties|heal|")
BUFF_PREFIX = 0x71EEF7E4FA7BF764          # CSymbol64("ability_properties|buff|")
HEAL_UNIQUE = 0xD3CF9A4313DDFCFD          # CSymbol64("ability_properties|heal|unique_healing_only")
BUFF_UNIQUE = 0x8870DFA9A8731203          # CSymbol64("ability_properties|buff|unique_healing_only")


def link_tuning(t: dict) -> dict:
    """The bubble keys POWER BOOST's bubble reads, from the config's own buff values.

    heal_radius carries the cone to PowerBoost.dll: len (whole metres) +
    init_angle / 100000, e.g. 12 m at 37 deg = 12.00037. A bubble whose radius has
    such a fraction is POWER BOOST's: the plugin only links targets inside that cone
    of the owner's aim, and gives each linked teammate the dr buff. (Repair Matrix's
    radius, a whole 8, is left alone.) The bubble heals each linked teammate up to
    heal_amt_on_success over dr_duration, reaching the full rate after conn_time;
    the owner does not heal themself."""
    length, angle = round(t["len"]), round(t["init_angle"])
    if not (1 <= length <= 100 and 1 <= angle <= 180):
        raise ValueError(f"len {t['len']} / init_angle {t['init_angle']} out of range")
    heal = t["heal_amt_on_success"]
    return {
        "heal_radius": length + angle / 100000,
        "heal_amt": heal, "heal_duration": t["dr_duration"],
        "cap_healing": True, "max_healing": heal,
        "scale_healing": False, "min_heal_mult": 1,
        "time_to_max_heal": t["conn_time"], "self_heal_mult": 0,
        "unique_healing_only": True,
    }


def gold_particles(effect: bytes, gold=FX_GOLD) -> tuple[bytes, list]:
    """Recolour the green in a particle effect asset (format not mapped, so heuristic),
    each colour to min + (max - min) * gold:

    * rgb triples of floats (4-byte aligned) and of half floats (2-byte aligned) with
      green clearly on top (> 1.2x red and blue) and every channel in range (0.005..4,
      half floats 0.004..8: real colours carry a little red and blue, unlike the
      velocities and ranges around them; a half triple whose 4-byte words read as
      ordinary floats is two floats, not a colour). Colours sit back to back, so a window can
      straddle two of them (0.349 0.577 | 0.01 1 0.04): the greenest triples win and
      no two chosen triples overlap. The pure green (0.01, 1, 0.04) is the beam's own
      colour, in every emitter;
    * 8-bit colours: 4-byte aligned words with a zero top byte (as a float that would
      be a denormal, which no real value here is) and green clearly on top, e.g. the
      light green 7f ff 7f."""
    out = bytearray(effect)
    changed = []
    span = lambda c: [min(c) + (max(c) - min(c)) * k for k in gold]

    def pick(step, size, fmt, lo, hi):
        found = []
        for o in range(0, len(out) - 3 * size + 1, step):
            vals = struct.unpack_from(fmt, out, o)
            if all(lo <= v <= hi for v in vals) and vals[1] >= 0.05 \
                    and vals[1] > 1.2 * vals[0] and vals[1] > 1.2 * vals[2]:
                found.append((vals[1] - max(vals[0], vals[2]), o, vals))
        taken = []
        for _, o, vals in sorted(found, reverse=True):
            if all(o + 3 * size <= t or t + 3 * size <= o for t, _ in taken):
                taken.append((o, vals))
        return taken

    floats = pick(4, 4, "<3f", 0.005, 4)
    used = [(o, o + 12) for o, _ in floats]
    def floaty(o):      # the 4-byte words inside the triple read as ordinary floats
        words = [w for w in range(o + (-o % 4), o + 6 - 3, 4)]
        return words and all(1e-4 <= abs(struct.unpack_from("<f", out, w)[0]) <= 1e4 for w in words)
    halves = [(o, v) for o, v in pick(2, 2, "<3e", 0.004, 8)
              if all(o + 6 <= a or b <= o for a, b in used) and not floaty(o)]
    for o, vals in floats:
        struct.pack_into("<3f", out, o, *span(vals))
        changed.append((o, vals))
    for o, vals in halves:
        struct.pack_into("<3e", out, o, *span(vals))
        changed.append((o, vals))
    for o in range(0, len(out) - 3, 4):
        c0, c1, c2, top = out[o:o + 4]
        if top == 0 and c2 < 0x80 and c1 >= 0x40 and c1 > 1.3 * c0 and c1 > 1.3 * c2:
            out[o:o + 3] = bytes(min(255, round(v)) for v in span((c0, c1, c2)))
            changed.append((o, (c0 / 255, c1 / 255, c2 / 255)))
    return bytes(out), sorted(changed)


def gold_particle_refs(script: bytes) -> bytes:
    """Point the buff script's particle spawns at the recoloured copies."""
    out = bytearray(script)
    for old, new in PARTICLES.items():
        o = struct.pack("<Q", old)
        if out.count(o) == 0:
            raise ValueError(f"heal script: no reference to particle effect {old:#x}")
        out = bytearray(bytes(out).replace(o, struct.pack("<Q", new)))
    return bytes(out)


def read_buff_tuning(script: bytes) -> bytes:
    """Point the copied heal script's bubble tuning lookups at ability_properties.buff."""
    out = bytearray(script)
    for old, new in ((HEAL_PREFIX, BUFF_PREFIX), (HEAL_UNIQUE, BUFF_UNIQUE)):
        o, n = struct.pack("<Q", old), struct.pack("<Q", new)
        if out.count(o) != 1:
            raise ValueError(f"heal script: expected one {old:#x}, found {out.count(o)}")
        i = out.find(o)
        out[i:i + 8] = n
    return bytes(out)


def buff_marker(dr: float, seconds: float, rez: bool = False) -> float:
    """The heal amount PowerBoost.dll reads as "dr for seconds", plus REZ_FLAG when linked
    teammates also cheat death once (see plugin/powerboost.cpp). Exact as a float."""
    permille, secs = round(dr * 1000), round(seconds)
    if not (0 <= permille <= 999 and 1 <= secs <= 999):
        raise ValueError(f"dr {dr} / dr_duration {seconds} out of the marker's range")
    return float(MARKER_BASE + permille * 1000 + secs + (REZ_FLAG if rez else 0))


#: what marker_stub snapshots around the heal: the execute context (state at +18h,
#: data block pointer at +B0h, flags up to +DBh) and the node data block it points to
CTX_SAVE, DATA_SAVE = 0xE0, 0x100


# --- --visual-preview: one of Repair Matrix's visuals per use ---------------------------
#: The heal script's visual nodes, by group (read from the script: execute_node_<id>,
#: its rva, its first instructions -- replayed by the hook). Use N shows group N
#: (then round again); every other group's nodes are skipped. Sounds always play.
PREVIEW_GROUPS = [
    ("beam particle effect 39424707bb2df316 (one per linked teammate)",
     [(0xAD60, "48897c2418"), (0xD9B0, "48897c2418"), (0xE320, "48895c2410"), (0xEB80, "48897c2418")]),
    ("hand particle effect be696d7d300cbaf7 (two sizes)", [(0xF0F0, "48895c2408"), (0xF3E0, "48895c2408")]),
    ("full-screen tint (0.6, 1, 0.6)", [(0xB750, "4883ec48 80b9db00000000"), (0xF8A0, "4883ec48 80b9db00000000")]),
    ("model 127705d644e32e78 shown, and its light colour", [(0xB7C0, "4c8bdc 4883ec58"), (0xB2E0, "4881ecb8000000")]),
    ("model 9425ffc9d7797400 shown, and its light colour", [(0xB840, "4c8bdc 4883ec58"), (0xBE20, "4881ecb8000000")]),
    ("material colours (4 nodes, on 09f1312f49418925)",
     [(0xC900, "4055 488bec"), (0xCB10, "4055 488bec"), (0xCD10, "4055 488bec"), (0xE070, "4055 488bec")]),
]
#: the preview's use counter (per machine): spare bytes past echovr.exe's .data, after
#: POINT's (veil_fx.POINT_PREVIEW_RVA + 4)
PREVIEW_COUNT_RVA = 0x2104CFC


def preview_hooks(pe: PE) -> None:
    """Hook every PREVIEW_GROUPS node: it runs only when its group is this use's."""
    groups = len(PREVIEW_GROUPS)
    stubs = []
    for g, (_, nodes) in enumerate(PREVIEW_GROUPS):
        for rva, old in nodes:
            old = bytes.fromhex(old)
            if pe.read(rva, len(old)) != old:
                raise ValueError(f"heal script node at {rva:#x} differs: wrong heal script build")
            stubs.append(((g + 1) % groups, rva, old))
    size = sum(64 for _ in stubs)
    va = add_section(pe, b".prev\0\0\0", size)
    blob = bytearray(size)
    for k, (want, rva, old) in enumerate(stubs):
        at = va + 64 * k
        b = bytearray(bytes.fromhex("6548a16000000000000000 488b4010 8b80") + struct.pack("<I", PREVIEW_COUNT_RVA))
        b += bytes.fromhex("31d2 41b8") + struct.pack("<I", groups) + bytes.fromhex("41f7f0")   # edx = count % groups
        b += bytes.fromhex("83fa") + bytes([want]) + bytes.fromhex("7403 31c0 c3")              # not this group: done
        b += old + b"\xe9" + rel32(at + len(b) + len(old) + 5, rva + len(old))
        assert len(b) <= 64
        blob[64 * k:64 * k + len(b)] = b
        pe.write(rva, b"\xe9" + rel32(rva + 5, at) + b"\x90" * (len(old) - 5))
    pe.write(va, bytes(blob))


def marker_stub(at: int, ctor: int, execute: int, amount: float, resume: int, count: bool = False) -> bytes:
    """execute_node replacement: one R15NetDamageableHeal on "self" of `amount`, then the
    original execute_node (its first 6 bytes replayed here, then a jump to `resume`), so
    the heal bubble still activates and the ability ends and recharges as before.

    Every node function keeps its progress in the shared context: a state at +18h
    (0 = not entered yet) and a data block at [+B0h]. The heal runs its whole state
    machine there, so left alone it hands the bubble node a finished state and a data
    block in the heal's layout (the crash on use). So the heal runs only on the node's
    first entry (state <= 0), and the context and data block are snapshotted before it
    and put back after it, exactly as the bubble node would have found them."""
    b = bytearray(bytes.fromhex("53 56 57 4881ec30020000 4889cb"))   # 3 pushes + 230h: aligned
    jumps = []
    b += bytes.fromhex("80bbdb00000000 0f85"); jumps.append(len(b)); b += bytes(4)   # aborting
    b += bytes.fromhex("48837b1800 0f8f"); jumps.append(len(b)); b += bytes(4)       # already entered
    if count:                                                        # --visual-preview: a new use
        b += bytes.fromhex("6548a16000000000000000 488b4010 f0ff80") + struct.pack("<I", PREVIEW_COUNT_RVA)
    b += bytes.fromhex("4889de 488d7c2450 b9") + struct.pack("<I", CTX_SAVE // 8) + bytes.fromhex("f348a5")
    b += bytes.fromhex("488bb3b0000000 488dbc2430010000 b9") + struct.pack("<I", DATA_SAVE // 8) \
        + bytes.fromhex("f348a5")
    b += bytes.fromhex("488d4c2420 e8") + rel32(at + len(b) + 10, ctor)  # node (30h bytes) at rsp+20h
    b += b"\x48\xb8" + struct.pack("<Q", SELF) + bytes.fromhex("4889442438")   # node+18 actor symbol
    b += bytes.fromhex("c7442448") + struct.pack("<f", amount)                  # node+28 heal amount
    b += bytes.fromhex("488d4c2420 4889da e8") + rel32(at + len(b) + 13, execute)
    b += bytes.fromhex("488bbc2400010000 488db42430010000 b9") + struct.pack("<I", DATA_SAVE // 8) \
        + bytes.fromhex("f348a5")                                    # data block back (saved ptr)
    b += bytes.fromhex("488d742450 4889df b9") + struct.pack("<I", CTX_SAVE // 8) + bytes.fromhex("f348a5")
    for j in jumps:
        b[j:j + 4] = struct.pack("<i", len(b) - (j + 4))
    b += bytes.fromhex("4889d9 4881c430020000 5f 5e 5b")              # rcx=rbx; undo our frame
    b += ACTIVATE_OLD + b"\xe9" + rel32(at + len(b) + len(ACTIVATE_OLD) + 5, resume)
    return bytes(b)


def add_buff(gold_pe: bytes, wraith_pe: bytes, marker: float, preview: bool = False) -> bytes:
    """Phase 1: using POWER BOOST heals yourself with the marker (PowerBoost.dll then
    buffs you), then activates the heal bubble as before (which ends the ability)."""
    pe, wraith = PE(gold_pe), PE(wraith_pe)
    if pe.read(HEAL_BIND_CALL, 5) != b"\xe8" + rel32(HEAL_BIND_CALL + 5, HEAL_BIND_TARGET) \
            or pe.read(ACTIVATE_NODE, 6) != ACTIVATE_OLD:
        raise ValueError("unexpected heal script build")
    blob, fixups = bytearray(), []
    node = transplant(wraith, HEAL_NODE, blob, fixups)
    blob += bytes(-len(blob) % 16)
    bind_off = len(blob)
    blob += bytes(48)
    blob += bytes(-len(blob) % 16)
    stub_off = len(blob)
    blob += bytes(256)
    va = add_section(pe, b".buff\0\0\0", len(blob))
    for d, target in fixups:
        blob[d:d + 4] = rel32(va + d + 4, va + target)
    at = va + bind_off
    stub = bytearray(bytes.fromhex("4883ec28 e8") + rel32(at + 9, HEAL_BIND_TARGET))
    stub += bytes.fromhex("488b5710 488b0f e8") + rel32(at + len(stub) + 12, va + node["bind"])
    stub += bytes.fromhex("4883c428 c3")
    blob[bind_off:bind_off + len(stub)] = stub
    s_ = marker_stub(va + stub_off, va + node["ctor"], va + node["exec"], marker, ACTIVATE_NODE + len(ACTIVATE_OLD),
                     preview)
    blob[stub_off:stub_off + len(s_)] = s_
    pe.write(va, bytes(blob))
    pe.write(HEAL_BIND_CALL, b"\xe8" + rel32(HEAL_BIND_CALL + 5, at))
    pe.write(ACTIVATE_NODE, b"\xe9" + rel32(ACTIVATE_NODE + 5, va + stub_off) + b"\x90")
    if preview:
        preview_hooks(pe)
    return bytes(pe.d)


def d32(v): return struct.pack("<i", v)


def recolor_stub(at: int, entry: int, field: int, mode: str, consts: int) -> bytes:
    """rcx = node: recolour node[field..field+8] if green is its strongest
    channel (Repair Matrix's other colours, e.g. its reds, stay), then
    `mov [rsp+8], rbx; jmp entry+5`. Uses xmm0-xmm3 only (volatile; Execute
    takes no float arguments)."""
    b = bytearray()
    b += bytes.fromhex("f30f1081") + d32(field)                       # movss xmm0, r
    b += bytes.fromhex("f30f5f81") + d32(field + 4)                   # maxss xmm0, g
    b += bytes.fromhex("f30f5f81") + d32(field + 8)                   # maxss xmm0, b  (hi)
    b += bytes.fromhex("f30f1099") + d32(field + 4)                   # movss xmm3, g
    b += bytes.fromhex("0f2ed8")                                      # ucomiss xmm3, xmm0
    skip = len(b)
    b += bytes.fromhex("0f8200000000")                                # jb done: green is not the strongest
    if mode == "span":
        b += bytes.fromhex("f30f1091") + d32(field)                   # movss xmm2, r
        b += bytes.fromhex("f30f5d91") + d32(field + 4)               # minss xmm2, g
        b += bytes.fromhex("f30f5d91") + d32(field + 8)               # minss xmm2, b  (lo)
        b += bytes.fromhex("f30f5cc2")                                # subss xmm0, xmm2
    for k in range(3):
        b += bytes.fromhex("f30f10c8")                                # movss xmm1, xmm0
        b += bytes.fromhex("f30f590d") + rel32(at + len(b) + 8, consts + 4 * k)   # mulss xmm1, [c_k]
        if mode == "span":
            b += bytes.fromhex("f30f58ca")                            # addss xmm1, xmm2
        b += bytes.fromhex("f30f1189") + d32(field + 4 * k)           # movss [rcx+field+4k], xmm1
    b[skip + 2:skip + 6] = struct.pack("<i", len(b) - (skip + 6))
    b += ENTRY + b"\xe9" + rel32(at + len(b) + len(ENTRY) + 5, entry + 5)
    return bytes(b)


def gold_script(heal_pe: bytes, gold=GOLD, tint=TINT) -> bytes:
    pe = PE(heal_pe)
    if any(s[1] == GOLD_SECTION.rstrip(b"\0") for s in pe.sections()):
        raise ValueError("already recoloured")
    for entry, _, _ in CLASSES:
        if pe.read(entry, 5) != ENTRY:
            raise ValueError(f"unexpected colour node Execute at {entry:#x}: wrong heal script build")
    blob = bytearray(struct.pack("<3f", *gold) + bytes(4) + struct.pack("<3f", *tint) + bytes(4))
    stubs = []
    for _ in CLASSES:
        blob += bytes(-len(blob) % 16)
        stubs.append(len(blob))
        blob += bytes(256)
    va = add_section(pe, GOLD_SECTION, len(blob))
    for (entry, field, mode), off in zip(CLASSES, stubs):
        stub = recolor_stub(va + off, entry, field, mode, va + (0 if mode == "max" else 16))
        blob[off:off + len(stub)] = stub
        pe.write(entry, b"\xe9" + rel32(entry + 5, va + off))
    pe.write(va, bytes(blob))
    return bytes(pe.d)


def attach_buff_script(blob: bytes):
    """Add a buff-script entry after each player actor's heal-script entry."""
    stride, hdr = 720, 0x38
    count = u64(blob, 0x28)
    if u64(blob, 0x08) != count * stride or u64(blob, 0x30) != count:
        raise ValueError("unexpected CScriptCR framing")
    entries = [blob[hdr + stride * i:hdr + stride * (i + 1)] for i in range(count)]
    pool = blob[hdr + stride * count:]
    out, added = [], 0
    for e in entries:
        out.append(e)
        if u64(e, 8) in PLAYER_ACTORS and u64(e, 32) == HEAL_SCRIPT:
            if any(u64(x, 8) == u64(e, 8) and u64(x, 32) == BUFF_SCRIPT for x in entries):
                continue                              # already attached
            for t in (48, 104, 160, 216, 272, 328, 384, 440, 496, 552, 608, 664):
                if u64(e, t + 8):
                    raise ValueError("heal entry carries pool data")
            new = bytearray(e)
            struct.pack_into("<Q", new, 0, BUFF_SCRIPT)
            struct.pack_into("<Q", new, 32, BUFF_SCRIPT)
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
    ap.add_argument("--gold", default=",".join(map(str, GOLD)), help="r,g,b for colours (x their brightness)")
    ap.add_argument("--fx-test", action="store_true",
                    help="test: the beam copy becomes the stun mine's field effect (shows whether the copy is used)")
    ap.add_argument("--charge", type=float, default=40,
                    help="recharge time in seconds (ability_properties.buff.required_charge)")
    ap.add_argument("--dr", type=float, default=0.09,
                    help="damage reduction while boosted (written into ability_properties.buff.dr)")
    ap.add_argument("--no-rez", action="store_true",
                    help="linked teammates do not cheat death (sets ability_properties.buff.do_rez_buff to 0)")
    ap.add_argument("--tint", default=",".join(map(str, TINT)), help="r,g,b for the fullscreen tint")
    ap.add_argument("--visual-preview", action="store_true",
                    help="each use shows one group of Repair Matrix's visuals (PREVIEW_GROUPS), in order; "
                         "implies --stock-visuals")
    ap.add_argument("--stock-visuals", action="store_true",
                    help="POWER BOOST shows Repair Matrix's visuals exactly as they are (no recolour, the stock "
                         "particle effects): to check them in game before changing them")
    args = ap.parse_args(argv[1:])
    args.stock_visuals |= args.visual_preview
    gold = tuple(float(v) for v in args.gold.split(","))
    tint = tuple(float(v) for v in args.tint.split(","))

    eq_path, equipment = load(args.base, EQUIPMENT)
    tacmods = equipment["gear_table"]["tacmods"]
    if not any(t["name"] == "buff" for t in tacmods):
        tacmods.append(dict(BUFF_GEAR))
    print(save(args.out, EQUIPMENT, eq_path, equipment))
    print("tacmods:", [t["name"] for t in tacmods])

    heal = open(os.path.join(args.src, SCRIPTS, f"{HEAL_SCRIPT:x}"), "rb").read()
    wraith = open(os.path.join(args.src, SCRIPTS, WRAITH_SCRIPT), "rb").read()
    ws_path, settings = load(args.base, WEAPON_SETTINGS)
    tuning = settings["ability_properties"]["buff"]
    tuning["dr"] = args.dr
    tuning["required_charge"] = args.charge
    tuning.update(link_tuning(tuning))
    print(save(args.out, WEAPON_SETTINGS, ws_path, settings))
    if args.no_rez:
        tuning["do_rez_buff"] = 0
    rez = bool(tuning.get("do_rez_buff"))
    marker = buff_marker(tuning["dr"], tuning["dr_duration"], rez)
    heal = read_buff_tuning(heal) if args.stock_visuals else gold_particle_refs(read_buff_tuning(heal))
    for old, new in ({} if args.stock_visuals else PARTICLES).items():
        src_fx = FX_TEST_EFFECT if args.fx_test and old == BEAM else old
        effect = open(os.path.join(args.src, PARTICLE_TYPE, f"{src_fx:x}"), "rb").read()
        gold_effect, changed = gold_particles(effect)
        for folder, data in ((PARTICLE_TYPE, gold_effect),
                             (PARTICLE_COMPANION, open(os.path.join(args.src, PARTICLE_COMPANION, f"{src_fx:x}"), "rb").read())):
            os.makedirs(os.path.join(args.out, folder), exist_ok=True)
            open(os.path.join(args.out, folder, f"{new:x}"), "wb").write(data)
        if src_fx != old:
            print(f"particle {old:x}: FX TEST, copy {new:x} is the stun field effect {src_fx:x}")
        print(f"particle {old:x} -> recoloured copy {new:x}: {len(changed)} colour(s) "
              + ", ".join("(%.2f %.2f %.2f)" % c for _, c in changed))
    mz = heal.find(b"MZ")
    os.makedirs(os.path.join(args.out, SCRIPTS), exist_ok=True)
    open(os.path.join(args.out, SCRIPTS, f"{BUFF_SCRIPT:x}"), "wb").write(
        heal[:mz] + add_buff(heal[mz:] if args.stock_visuals else gold_script(heal[mz:], gold, tint),
                             wraith[wraith.find(b"MZ"):], marker, args.visual_preview))
    print(f"buff: dr {tuning['dr']} for {tuning['dr_duration']} s (marker {marker:.0f}); link "
          f"{tuning['len']} m / {tuning['init_angle']} deg (bubble radius {tuning['heal_radius']}), "
          f"heal {tuning['heal_amt_on_success']}, cheat death {'on' if rez else 'off'} (needs PowerBoost.dll on server and clients)")
    os.makedirs(os.path.join(args.out, SCRIPT_RESOURCE), exist_ok=True)
    open(os.path.join(args.out, SCRIPT_RESOURCE, f"{BUFF_SCRIPT:x}"), "wb").write(bytes(4))
    if args.visual_preview:
        print("VISUAL PREVIEW: each POWER BOOST use shows one group of Repair Matrix's visuals:")
        for k, (name, nodes) in enumerate(PREVIEW_GROUPS):
            print(f"   use {k + 1} (and {k + 1 + len(PREVIEW_GROUPS)}, ...): {name}")
    print(f"{SCRIPTS}/{BUFF_SCRIPT:x}: mp_combat_ability_buff (" + ("Repair Matrix's visuals, unchanged)"
          if args.stock_visuals else f"Repair Matrix recoloured to {gold}, tint {tint})"))

    os.makedirs(os.path.join(args.out, SCRIPT_CR), exist_ok=True)
    staged = os.path.join(args.out, SCRIPT_CR, GLOBAL_LEVEL)
    src = staged if os.path.exists(staged) else os.path.join(args.src, SCRIPT_CR, GLOBAL_LEVEL)
    fixed, added = attach_buff_script(open(src, "rb").read())
    open(staged, "wb").write(fixed)
    print(f"global level: buff script attached to {added} player actor(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
