"""POWER BOOST (the cut `buff` tac mod) as a sixth tac mod: Repair Matrix in dark gold.

The engine has no buff / damage-reduction system a script can drive, but it
has Repair Matrix's: the heal bubble component every player carries
(CR15NetHealBubbleCR), run from `mp_combat_ability_heal` (6a0f689e5b91c666)
through the R15NetHealBubble* nodes. POWER BOOST is that tac mod, same
behaviour and tuning, recoloured from green to dark gold:

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
   The particle effects keep their own (baked-in) colour for now.
3. The script gets its `CScriptResourceWin10` entry and is attached to each
   player actor right after its heal-script entry.
4. The controller's sixth branch (wraith -> smoke -> buff, "equipped == buff")
   comes from fix_smoke.py --with-buff.

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

from fix_drone import EQUIPMENT, load, save
from fix_smoke import PE, rel32, u64, SCRIPTS, SCRIPT_RESOURCE, SCRIPT_CR, GLOBAL_LEVEL, PLAYER_ACTORS
from veil_fx import add_section

HEAL_SCRIPT = 0x6A0F689E5B91C666
BUFF_SCRIPT = 0x4B65D1B0088D2682       # CSymbol64("mp_combat_ability_buff")
BUFF = 0xC8C33E48386618B6              # CSymbol64("buff")
BUFF_GEAR = {"name": "buff", "display_name": "POWER BOOST"}

#: Dark gold. Material / light colours become max(rgb) * GOLD; the fullscreen
#: tint becomes min + (max - min) * TINT.
GOLD = (0.80, 0.56, 0.06)
TINT = (1.00, 0.78, 0.25)

ENTRY = bytes.fromhex("48895c2408")   # mov [rsp+8], rbx: first instruction of each Execute
#: (Execute rva in the heal script, colour field offset in the node, mode)
CLASSES = [
    (0x4990, 0x44, "max"),             # SETMATERIALPROPERTYCOLORNODE::Execute: val_x..z
    (0x5A50, 0x20, "max"),             # SETMODELLIGHTCOLORNODE::Execute: color_x..z
    (0x50E0, 0x08, "span"),            # SETFULLSCREENTINTNODE::Execute: tintr..b
]
GOLD_SECTION = b".gold\0\0\0"


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
        blob += bytes(128)
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
    ap.add_argument("--tint", default=",".join(map(str, TINT)), help="r,g,b for the fullscreen tint")
    args = ap.parse_args(argv[1:])
    gold = tuple(float(v) for v in args.gold.split(","))
    tint = tuple(float(v) for v in args.tint.split(","))

    eq_path, equipment = load(args.base, EQUIPMENT)
    tacmods = equipment["gear_table"]["tacmods"]
    if not any(t["name"] == "buff" for t in tacmods):
        tacmods.append(dict(BUFF_GEAR))
    print(save(args.out, EQUIPMENT, eq_path, equipment))
    print("tacmods:", [t["name"] for t in tacmods])

    heal = open(os.path.join(args.src, SCRIPTS, f"{HEAL_SCRIPT:x}"), "rb").read()
    mz = heal.find(b"MZ")
    os.makedirs(os.path.join(args.out, SCRIPTS), exist_ok=True)
    open(os.path.join(args.out, SCRIPTS, f"{BUFF_SCRIPT:x}"), "wb").write(
        heal[:mz] + gold_script(heal[mz:], gold, tint))
    os.makedirs(os.path.join(args.out, SCRIPT_RESOURCE), exist_ok=True)
    open(os.path.join(args.out, SCRIPT_RESOURCE, f"{BUFF_SCRIPT:x}"), "wb").write(bytes(4))
    print(f"{SCRIPTS}/{BUFF_SCRIPT:x}: mp_combat_ability_buff (Repair Matrix in gold {gold}, tint {tint})")

    os.makedirs(os.path.join(args.out, SCRIPT_CR), exist_ok=True)
    staged = os.path.join(args.out, SCRIPT_CR, GLOBAL_LEVEL)
    src = staged if os.path.exists(staged) else os.path.join(args.src, SCRIPT_CR, GLOBAL_LEVEL)
    fixed, added = attach_buff_script(open(src, "rb").read())
    open(staged, "wb").write(fixed)
    print(f"global level: buff script attached to {added} player actor(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
