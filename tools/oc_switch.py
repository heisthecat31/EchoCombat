"""OVERCHARGE's own look, chosen at run time inside Repair Matrix's script.

RETIRED: since OVERCHARGE has its own heal bubble (fix_buff.OC_BUBBLE) its own script draws
it, and this is no longer applied; only OC_COUNTER_RVA / OC_TOKEN_RVA are still used.

Tested in game (2026-10-10): whichever tac mod is used, the heal bubble's visuals are
drawn by Repair Matrix's script (mp_combat_ability_heal, 6a0f689e5b91c666); the buff
script's visual nodes never show. So the choice is made there, per player:

  * the buff script's use stub (fix_buff.marker_stub, count=True) bumps OC_COUNTER_RVA;
  * VeilNet.dll sees the bump and sends an 'O' packet: every machine (the user's too)
    gets an OVERCHARGE token at OC_TOKEN_RVA (VeilNet's token layout);
  * in Repair Matrix's script every heal-bubble visual node (OC_NODES: beam, hand, tint,
    light and material colours) first runs `decide`: the node's script instance
    ([[ctx]+68h], one per player) is an OVERCHARGE bubble if it took a token in the last
    OC_LIFE, else it is one if an OVERCHARGE token is live (VeilNet keeps one for 1.5 s
    after each use). The token is not used up: every heal script instance drawing that
    bubble runs its visual nodes in that window (tested: with one take per use, the
    other instance's beam stayed green next to the purple one). The node then runs with a
    flag set (cleared when it returns), and while it is set:
      - the particle effect loads (OC_EFFECT_LOADS) give OVERCHARGE's copies
        (fix_buff.PARTICLES: purple up arrows, purple sparks);
      - the three colour node classes (fix_buff.CLASSES: material property colour,
        model light colour, fullscreen tint) run with their colour recoloured to purple
        (fix_buff.recolor_stub's formula) for that one call, and the node's own colour
        is put back afterwards, so Repair Matrix's colours never change.
Every node of every other instance runs exactly as stock.
"""

from __future__ import annotations

import struct

from fix_smoke import PE, rel32
from veil_fx import add_section

OC_COUNTER_RVA = 0x2104CA4                 # u32, bumped by each OVERCHARGE use on this machine
OC_TOKEN_RVA = 0x2104CA8                   # +00 tokens +08 expiry (interrupt time) +10 taken here
OC_LIFE = 150_000_000                      # 15 s in 100 ns: one bubble's life
OC_SLOTS = 16
BEAM, HAND = 0x39424707BB2DF316, 0xBE696D7D300CBAF7
#: the visual nodes (execute_node_*) and their first instructions (replayed by the wrapper)
OC_NODES = [
    (0xAD60, "48897c2418"), (0xD9B0, "48897c2418"), (0xE320, "48895c2410"), (0xEB80, "48897c2418"),  # beam x4
    (0xF0F0, "48895c2408"), (0xF3E0, "48895c2408"),                                                  # hand x2
    (0xB750, "4883ec4880b9db00000000"), (0xF8A0, "4883ec4880b9db00000000"),                          # tint on
    (0xB2E0, "4881ecb8000000"), (0xBE20, "4881ecb8000000"),                                          # light colours
    (0xC900, "4055488bec"), (0xCB10, "4055488bec"), (0xCD10, "4055488bec"), (0xE070, "4055488bec"),  # material colours
]
#: movabs rax, <effect> inside the beam / hand nodes
OC_EFFECT_LOADS = [(0xAD81, BEAM), (0xD9D1, BEAM), (0xE346, BEAM), (0xEBA1, BEAM), (0xF157, HAND), (0xF43A, HAND)]
OC_SECTION = b".ocsw\0\0\0"


def d32(v):
    return struct.pack("<i", v)


def jmp(at, target):
    return b"\xe9" + rel32(at + 5, target)


def decide_code(at: int, flag: int, table: int) -> bytes:
    """rax = script instance (0 allowed) -> [flag] = 1 (OVERCHARGE) or 0.
    Keeps every register but rax, r10, r11 and the flags."""
    b = bytearray(bytes.fromhex("51 52"))                                   # push rcx; push rdx
    b += bytes.fromhex("49bb0800fe7f00000000 4d8b1b")                       # r11 = now (KUSER interrupt time)
    b += bytes.fromhex("4c8d15") + rel32(at + len(b) + 7, table)            # lea r10, table
    b += b"\xb9" + struct.pack("<I", OC_SLOTS)                              # mov ecx, slots
    loop = len(b)
    b += bytes.fromhex("493902")                                            # cmp [r10], rax
    b += bytes.fromhex("750a")                                              # jne next
    b += bytes.fromhex("4d395a08")                                          # cmp [r10+8], r11
    b += b"\x0f\x87"; j_found = len(b); b += bytes(4)                       # ja found (still alive)
    b += bytes.fromhex("4983c210 ffc9")                                     # next: r10 += 16; ecx--
    b += b"\x75" + bytes([(loop - (len(b) + 2)) & 0xFF])                    # jnz loop
    b += bytes.fromhex("4885c0 0f84"); j_n1 = len(b); b += bytes(4)         # no instance: not OVERCHARGE
    b += bytes.fromhex("4889c2")                                            # rdx = instance
    b += bytes.fromhex("65488b042560000000 488b4010")                       # rax = echovr.exe base
    b += bytes.fromhex("488d88") + struct.pack("<I", OC_TOKEN_RVA)          # rcx = token record
    b += bytes.fromhex("4c395908 0f86"); j_n2 = len(b); b += bytes(4)       # expiry <= now: none
    b += bytes.fromhex("833900 0f8e"); j_n3 = len(b); b += bytes(4)         # no token: none
    b += bytes.fromhex("f0ff4110")                                          # lock inc [rcx+10h]: shown here
    b += bytes.fromhex("4c8d15") + rel32(at + len(b) + 7, table)
    b += b"\xb9" + struct.pack("<I", OC_SLOTS)
    iloop = len(b)
    b += bytes.fromhex("4d395a08")                                          # cmp [r10+8], r11
    b += b"\x76"; j_put = len(b); b += b"\0"                                # jbe put (free slot)
    b += bytes.fromhex("4983c210 ffc9")
    b += b"\x75" + bytes([(iloop - (len(b) + 2)) & 0xFF])
    b += bytes.fromhex("4c8d15") + rel32(at + len(b) + 7, table)            # all busy: reuse the first
    put = len(b)
    b += bytes.fromhex("498912")                                            # [r10] = instance
    b += b"\x48\xb8" + struct.pack("<Q", OC_LIFE) + bytes.fromhex("4c01d8 49894208")   # [r10+8] = now + life
    found = len(b)
    b += bytes.fromhex("c705") + rel32(at + len(b) + 10, flag) + struct.pack("<I", 1)
    b += b"\xeb"; j_out = len(b); b += b"\0"
    none = len(b)
    b += bytes.fromhex("c705") + rel32(at + len(b) + 10, flag) + struct.pack("<I", 0)
    out = len(b)
    b += bytes.fromhex("5a 59 c3")                                          # pop rdx; pop rcx; ret
    b[j_found:j_found + 4] = d32(found - (j_found + 4))
    b[j_put] = put - (j_put + 1)
    b[j_out] = out - (j_out + 1)
    for j in (j_n1, j_n2, j_n3):
        b[j:j + 4] = d32(none - (j + 4))
    return bytes(b)


def node_wrapper(at: int, rva: int, old: bytes, decide: int, flag: int) -> bytes:
    """execute_node entry -> decide for [[rcx]+68h], run the node, clear the flag."""
    b = bytearray(bytes.fromhex("4883ec28 488b01 4885c0 7404 488b4068"))   # rax = [[ctx]+68h] (or 0)
    b += b"\xe8" + rel32(at + len(b) + 5, decide)
    b += b"\xe8"; ref = len(b); b += bytes(4)                               # call the node
    b += bytes.fromhex("c705") + rel32(at + len(b) + 10, flag) + bytes(4)   # flag = 0
    b += bytes.fromhex("4883c428 c3")
    tramp = len(b)
    b += old + jmp(at + tramp + len(old), rva + len(old))
    b[ref:ref + 4] = rel32(at + ref + 4, at + tramp)
    return bytes(b)


def load_stub(at: int, fx: int, copy: int, flag: int) -> bytes:
    """Replaces `movabs rax, fx`: rax = copy if the flag is set, else fx (flags kept)."""
    b = bytearray(b"\x9c\x48\xb8" + struct.pack("<Q", fx))                  # pushfq; mov rax, fx
    b += bytes.fromhex("833d") + rel32(at + len(b) + 7, flag) + b"\x00"     # cmp dword [flag], 0
    b += b"\x74\x0a\x48\xb8" + struct.pack("<Q", copy)                      # je +10; mov rax, copy
    b += b"\x9d\xc3"                                                        # popfq; ret
    return bytes(b)


def colour_stub(at: int, entry: int, entry_bytes: bytes, field: int, mode: str, consts: int, flag: int) -> bytes:
    """Execute(rcx = node) entry: stock unless the flag is set; then node[field..+8] is
    recoloured (as fix_buff.recolor_stub does: only when green is the strongest channel),
    Execute runs, and the node's colour is put back."""
    b = bytearray(bytes.fromhex("833d") + rel32(at + 7, flag) + b"\x00")
    b += b"\x75" + bytes([len(entry_bytes) + 5])                            # flag set: recolour
    b += entry_bytes + jmp(at + len(b) + len(entry_bytes), entry + len(entry_bytes))
    b += bytes.fromhex("4883ec38 48894c2420")                               # frame; keep the node
    for k in range(3):                                                      # save the colour
        b += bytes.fromhex("448b91") + d32(field + 4 * k) + bytes.fromhex("44895424") + bytes([0x28 + 4 * k])
    rec = bytearray()
    rec += bytes.fromhex("f30f1081") + d32(field)                           # movss xmm0, r
    rec += bytes.fromhex("f30f5f81") + d32(field + 4)                       # maxss xmm0, g
    rec += bytes.fromhex("f30f5f81") + d32(field + 8)                       # maxss xmm0, b
    rec += bytes.fromhex("f30f1099") + d32(field + 4)                       # movss xmm3, g
    rec += bytes.fromhex("0f2ed8")                                          # ucomiss xmm3, xmm0
    skip = len(rec)
    rec += bytes.fromhex("0f8200000000")                                    # jb: green not strongest
    if mode == "span":
        rec += bytes.fromhex("f30f1091") + d32(field)                       # movss xmm2, r
        rec += bytes.fromhex("f30f5d91") + d32(field + 4)                   # minss xmm2, g
        rec += bytes.fromhex("f30f5d91") + d32(field + 8)                   # minss xmm2, b
        rec += bytes.fromhex("f30f5cc2")                                    # subss xmm0, xmm2
    base = len(b)
    for k in range(3):
        rec += bytes.fromhex("f30f10c8")                                    # movss xmm1, xmm0
        rec += bytes.fromhex("f30f590d") + rel32(at + base + len(rec) + 8, consts + 4 * k)
        if mode == "span":
            rec += bytes.fromhex("f30f58ca")                                # addss xmm1, xmm2
        rec += bytes.fromhex("f30f1189") + d32(field + 4 * k)               # movss [rcx+field+4k], xmm1
    rec[skip + 2:skip + 6] = d32(len(rec) - (skip + 6))
    b += rec
    b += b"\xe8"; ref = len(b); b += bytes(4)                               # call Execute
    b += bytes.fromhex("488b4c2420")                                        # rcx = node
    for k in range(3):                                                      # colour back
        b += bytes.fromhex("448b5424") + bytes([0x28 + 4 * k]) + bytes.fromhex("448991") + d32(field + 4 * k)
    b += bytes.fromhex("4883c438 c3")
    tramp = len(b)
    b += entry_bytes + jmp(at + tramp + len(entry_bytes), entry + len(entry_bytes))
    b[ref:ref + 4] = rel32(at + ref + 4, at + tramp)
    return bytes(b)


def oc_switch(heal_pe: bytes, particles: dict, classes: list, entry_bytes: bytes, gold, tint) -> bytes:
    pe = PE(heal_pe)
    for rva, old in OC_NODES:
        if pe.read(rva, len(old) // 2) != bytes.fromhex(old):
            raise ValueError(f"heal script node at {rva:#x} differs: wrong heal script build")
    for rva, fx in OC_EFFECT_LOADS:
        if pe.read(rva, 10) != b"\x48\xb8" + struct.pack("<Q", fx):
            raise ValueError(f"heal script effect load at {rva:#x} differs")
    for entry, _, _ in classes:
        if pe.read(entry, len(entry_bytes)) != entry_bytes:
            raise ValueError(f"unexpected colour node Execute at {entry:#x}")
    size = 0x2000
    va = add_section(pe, OC_SECTION, size)
    blob = bytearray(size)
    flag, table, consts = va, va + 0x10, va + 0x110
    blob[0x110:0x130] = struct.pack("<3f", *gold) + bytes(4) + struct.pack("<3f", *tint) + bytes(4)
    decide = va + 0x140
    code = decide_code(decide, flag, table)
    blob[0x140:0x140 + len(code)] = code
    at = va + 0x300

    def put(code_bytes):
        nonlocal at
        start = at
        blob[at - va:at - va + len(code_bytes)] = code_bytes
        at = (at + len(code_bytes) + 15) & ~15
        return start

    for rva, old in OC_NODES:
        old = bytes.fromhex(old)
        w = put(node_wrapper(at, rva, old, decide, flag))
        pe.write(rva, jmp(rva, w) + b"\x90" * (len(old) - 5))
    for rva, fx in OC_EFFECT_LOADS:
        m = put(load_stub(at, fx, particles[fx], flag))
        pe.write(rva, b"\xe8" + rel32(rva + 5, m) + b"\x90" * 5)
    for entry, field, mode in classes:
        c = put(colour_stub(at, entry, entry_bytes, field, mode, consts + (0 if mode == "max" else 16), flag))
        pe.write(entry, jmp(entry, c))
    assert at - va <= size
    pe.write(va, bytes(blob))
    return bytes(pe.d)
