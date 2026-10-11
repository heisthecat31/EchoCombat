"""UMBRAL VEIL's smoke: the smoke script spawns detonator smoke clouds instead of a wall.

The smoke script starts as a copy of the barrier script (fix_smoke.py), whose
graph runs, on use, ... -> custom param -> R15NetPooledActorCreate (node
6fb98e2c, the wall) -> ... This module makes that node spawn `count`
detonator explosion smoke effects (particle effect c9eb32d35038eb4c) around
the player instead (and the barrier's priming hologram is never shown), larger and longer-lived than the detonator's, left behind
where the veil was used. No wall is created, so there is nothing to collide
with, and both teams see the smoke.

The barrier script has no particle node, so the detonator script's
(190ed14fe3da5ed1) SPAWNPARTICLEEFFECTNODE is transplanted into it:

* a new section, `.veil` (read/write/execute, appended after the last one),
  holds the node's 85 static slots (the engine fills its function and offset
  slots at bind time), its 42 parameter name strings, byte copies of its
  constructor, Execute and Bind with every rip-relative reference re-aimed at
  the new slots and strings, and two stubs:
* setup_bindings' call to R15NETPOOLEDACTORCREATENODE::Bind (rdi = the
  binding table) goes to a stub that runs it, then the transplanted Bind
* execute_node_6fb98e2c's entry jumps to the spawn stub: for each cloud it
  builds a node (detonator's settings: actor "self", left behind, kill at end)
  with the asset, an offset on a ring of radius `spread` around the player,
  then the look: `scale` (cloud size), `life` (particle lifetime multiplier),
  `emission` (particle count multiplier), `particle_scale` (size of each puff),
  `alpha` (opacity multiplier) and `shade` (colour multiplier: lower = darker,
  so it hides more), then runs Execute.
* the custom-param node just before it (d11498f0) now plays `sound_event` (UMBRAL VEIL's 14 s smoke sound,
  see veil_sound.py) on the player with a transplanted PLAYSOUNDNODE (the
  detonator's too, with its constructor's defaults: the sound component every
  player and magazine uses, a temporary emitter, no waiting).
* with a mailbox (the default deploy), the wall IS created, as an invisible,
  collision-free "smoke wall" that plays the sound where it stands, so the
  sound stays put (see anchor_wall); the clouds take the custom-param node.
"""

from __future__ import annotations

import hashlib
import math
import struct

from fix_smoke import PE, rel32, u16, u32

DET_FX = 0xC9EB32D35038EB4C            # the detonator's explosion smoke
SELF = 0xC8C33E48297612B6              # CSymbol64("self")

#: UMBRAL VEIL's sound: event 2092801294 -> action 752655010 -> sound 1028260926
#: -> media 19531070, in bank 03f1464db1fe49b5 (its audio replaced by veil_sound.py).
VEIL_EVENT = 2092801294

# --- detonator script (190ed14fe3da5ed1), checked by SHA-256 ------------------
#: Per node class: (rva, size, sha256, rip-relative disp32 offsets) of its
#: constructor, Execute and Bind. Each disp32 is the last 4 bytes of its
#: instruction; its target is a .data slot or a .rdata string.
SPN_EXEC_DISPS = [
    0x1e, 0x36, 0x47, 0x4d, 0x5e, 0x64, 0x75, 0x7b, 0x8c, 0x92, 0xa3, 0xa9, 0xba, 0xc0,
    0xd1, 0xd7, 0xe8, 0xee, 0xff, 0x105, 0x116, 0x11c, 0x12d, 0x133, 0x144, 0x14a, 0x15b,
    0x161, 0x172, 0x178, 0x189, 0x18f, 0x1a0, 0x1a6, 0x1b7, 0x1bd, 0x1ce, 0x1d4, 0x1e5,
    0x1eb, 0x1fc, 0x206, 0x213, 0x219, 0x22a, 0x230, 0x241, 0x247, 0x258, 0x25e, 0x26f,
    0x275, 0x286, 0x28c, 0x29d, 0x2a3, 0x2b4, 0x2ba, 0x2ce, 0x2d4, 0x2e8, 0x2ee, 0x302,
    0x308, 0x31c, 0x322, 0x336, 0x33c, 0x350, 0x356, 0x36a, 0x370, 0x384, 0x38a, 0x39e,
    0x3a4, 0x3b8, 0x3be, 0x3d2, 0x3d8, 0x3ec, 0x3f2, 0x406, 0x40c, 0x420, 0x436]
SPN_BIND_DISPS = [
    0x22, 0x29, 0x30, 0x37, 0x4e, 0x55, 0x5c, 0x73, 0x7a, 0x81, 0x98, 0x9f, 0xa6, 0xbd,
    0xc4, 0xcb, 0xe2, 0xe9, 0xf0, 0x107, 0x10e, 0x115, 0x12c, 0x133, 0x13a, 0x151, 0x158,
    0x15f, 0x176, 0x17d, 0x184, 0x19b, 0x1a2, 0x1af, 0x1c0, 0x1c7, 0x1ce, 0x1e5, 0x1ec,
    0x1f3, 0x20a, 0x211, 0x218, 0x22f, 0x236, 0x23d, 0x254, 0x25b, 0x262, 0x279, 0x280,
    0x287, 0x29e, 0x2a5, 0x2ac, 0x2c3, 0x2ca, 0x2d1, 0x2e8, 0x2ef, 0x2f6, 0x30d, 0x314,
    0x31b, 0x332, 0x339, 0x340, 0x357, 0x363, 0x36a, 0x37c, 0x383, 0x38a, 0x3a1, 0x3a8,
    0x3af, 0x3c6, 0x3cd, 0x3d4, 0x3eb, 0x3f2, 0x3f9, 0x410, 0x417, 0x41e, 0x435, 0x43c,
    0x443, 0x45a, 0x461, 0x468, 0x47f, 0x486, 0x48d, 0x4a4, 0x4ab, 0x4b2, 0x4c9, 0x4d0,
    0x4d7, 0x4ee, 0x4f5, 0x502, 0x513, 0x51a, 0x521, 0x538, 0x53f, 0x546, 0x55d, 0x564,
    0x56b, 0x582, 0x589, 0x590, 0x5a7, 0x5ae, 0x5b5, 0x5cc, 0x5d3, 0x5da, 0x5f1, 0x5f8,
    0x5ff, 0x616, 0x61d, 0x624]
SPAWN_PARTICLE = {
    "ctor": (0x2710, 274, "95f2690cac553ad4eda87a2de734a912fc1567c33456d91d72d763ae93809298", []),
    "exec": (0x2830, 1082, "6b8138e8b0d699133111cdaae35452b8c5e8484bb184496e5f0c75875b016ce7",
             SPN_EXEC_DISPS),
    "bind": (0x20D0, 1600, "c2335899e5939e6f9abfd2cc1785e3a7f535019c0fc3aaf57d02f51c9d06b091",
             SPN_BIND_DISPS),
}
PLAY_SOUND = {
    "ctor": (0x3900, 171, "cb5e3ca71e263fe981a970282d5295c6232dfdc23662d5918bd937894611aac3", [0x70]),
    "exec": (0x39B0, 399, "3711324843bbaeb672ef6644888fe86e480fa8ec0b1d8d99d8243e764f6bbf58", [
        0x1e, 0x36, 0x47, 0x4d, 0x5e, 0x64, 0x75, 0x7b, 0x8c, 0x92, 0xa3, 0xa9, 0xba, 0xc0, 0xd1,
        0xd7, 0xe8, 0xee, 0xff, 0x105, 0x116, 0x11c, 0x12d, 0x133, 0x144, 0x14a, 0x15b, 0x161,
        0x175, 0x18b]),
    "bind": (0x36C0, 564, "57ba993a1e756016e83cb2c784e4f0d2ac09e62864bdd7b9130042551755ac50", [
        0x22, 0x29, 0x30, 0x37, 0x4e, 0x55, 0x5c, 0x73, 0x7a, 0x81, 0x98, 0x9f, 0xa6, 0xbd, 0xc4,
        0xcb, 0xdf, 0xe6, 0xed, 0x104, 0x10b, 0x112, 0x129, 0x130, 0x137, 0x14e, 0x155, 0x15c,
        0x173, 0x17a, 0x181, 0x198, 0x19f, 0x1ac, 0x1bd, 0x1c4, 0x1cb, 0x1e2, 0x1e9, 0x1f0, 0x207,
        0x20e, 0x215]),
}

# --- barrier script (b87ba2039b049d5e) ----------------------------------------
BIND_CALL = 0x3F00                     # call R15NETPOOLEDACTORCREATENODE::Bind
CREATE_BIND = 0x2450
CREATE_NODE = 0x69F0                   # execute_node_6fb98e2c
CREATE_NODE_OLD = bytes.fromhex("48895c2408")   # mov [rsp+8], rbx
#: execute_node_d11498f0: the custom param it sets is for the wall, which is no
#: longer created; it runs just before the create node and now plays the sound.
PARAM_NODE = 0x63D0

#: The two ShowModel nodes that show the barrier's priming hologram while the
#: tac mod is primed (models 24fc2eb812572ff7 and 4aa624c591ce1dda, on the
#: local player): `mov byte ptr [rsp+48h], 1` (show) becomes 0 (hide).
PRIMING_SHOW = [0x74F8, 0x6668]        # execute_node_367b0674, execute_node_b8a054bc
SHOW_ON, SHOW_OFF = bytes.fromhex("c644244801"), bytes.fromhex("c644244800")

# --- the smoke wall: an invisible, collision-free barrier wall that carries the sound ---
#: The smoke script stamps a "mailbox" (8 spare bytes past echovr.exe's .data,
#: located per exe by veil_mailbox()) with the time just before it creates the
#: wall; the wall script, whose two spawn nodes ask decide(), claims a stamp
#: under 2 s old and remembers it is a smoke wall in 8 bytes it adds to its
#: global data. Assembled with keystone; 0x11223344 marks the mailbox rva.
MAILBOX_MARK = struct.pack("<I", 0x11223344)
#: rcx = node ctx: unless the node is aborting, mailbox = now;
#: then the create node's own first instruction (mov [rsp+8], rbx).
STAMP = bytes.fromhex(
    "80b9db00000000752450526548a16000000000000000488b401048c7c20800fe7f488b1248899044"
    "3322115a5848895c2408")
#: decide(rcx = ctx) -> eax 1 smoke wall / 0 not; first call per wall decides.
DECIDE = bytes.fromhex(
    "4c8b114d8b5268418b925801000081fa534d4f4b745381fa4e4f524d745c6548a1600000000000000"
    "04c8b40104d8d804433221149c7c10800fe7f4d8b09498b004885c074294c89ca4829c24881fa002d"
    "3101771a31d2f0490fb110751141c78258010000534d4f4bb801000000c341c782580100004e4f524d"
    "31c0c3")
#: ShowModel hook, called in place of `mov byte [rsp+48h], 1`: show = !decide(rbx),
#: every register and the flags kept. SHOW_PRE, call decide, SHOW_POST.
SHOW_PRE = bytes.fromhex("9c50515241504151415241534883ec284889d9")
SHOW_POST = bytes.fromhex("3401888424b80000004883c428415b415a415941585a59589dc3")
#: EnablePhysics node entry: PHYS_PRE, call decide, PHYS_MID, jmp node+8; smoke: jmp sound.
PHYS_PRE = bytes.fromhex("514883ec20")
PHYS_MID = bytes.fromhex("4883c4205984c0750d4989e3534883ec50")
GLOBAL_LEN = 0x158                     # wall script_get_global_data_len: mov eax, 158h; ret
SMOKE_FLAG = GLOBAL_LEN                # the 8 bytes it gains

# --- wall script (ac4e9374a146d3a4), shared with the energy barrier ------------
WALL_GLOBAL_LEN_FN = 0x5CC0
WALL_SHOW = 0x6D78                     # execute_node_fac8332c: mov byte [rsp+48h], 1 (show)
WALL_PHYS = 0x7190                     # execute_node_ddd4137d: EnablePhysics(on), at spawn
WALL_PHYS_FLAG = 0x71E9                # its mov byte [rsp+48h], 1 (on), as WALL_SHOW's
WALL_PHYS_OLD = bytes.fromhex("4c8bdc534883ec50")
WALL_SOUND_CTOR, WALL_SOUND_EXEC = 0x2720, 0x27D0   # the wall's own PLAYSOUNDNODE


def mailbox_rva(exe: bytes) -> int:
    """8 spare bytes at the end of echovr.exe's .data page (past its VirtualSize,
    so the game never touches them; mapped read/write with the rest of .data)."""
    pe = PE(exe)
    _, _, vsize, va, _, _ = pe.section(b".data")
    page_end = (va + vsize + 0xFFF) & ~0xFFF
    if page_end - (va + vsize) < 0x20:
        raise ValueError("no spare bytes after echovr.exe's .data")
    return page_end - 0x10


def anchor_wall(wall_pe: bytes, mailbox: int, event: int = None) -> bytes:
    """The barrier wall script, made to turn a wall the smoke script just created
    into the veil's sound anchor: no model, no collision, plays `event` where
    it stands. Every other wall (the energy barrier's) is untouched."""
    event = VEIL_EVENT if event is None else event
    pe = PE(wall_pe)
    if any(s[1] == VEIL.rstrip(b"\0") for s in pe.sections()):
        raise ValueError("wall script already patched")
    if pe.read(WALL_GLOBAL_LEN_FN, 6) != b"\xb8" + struct.pack("<I", GLOBAL_LEN) + b"\xc3" \
            or pe.read(WALL_SHOW, 5) != bytes.fromhex("c644244801") \
            or pe.read(WALL_PHYS, 8) != WALL_PHYS_OLD:
        raise ValueError("unexpected wall script build")
    mb = struct.pack("<I", mailbox)
    blob = bytearray()
    decide = len(blob)
    blob += DECIDE.replace(MAILBOX_MARK, mb)
    blob += bytes(-len(blob) % 16)
    show = len(blob)
    blob += SHOW_PRE + bytes(5) + SHOW_POST              # call decide at show+len(SHOW_PRE)
    blob += bytes(-len(blob) % 16)
    sound = len(blob)
    blob += bytes(128)
    blob += bytes(-len(blob) % 16)
    phys = len(blob)
    blob += PHYS_PRE + bytes(5) + PHYS_MID + bytes(5) + bytes(5)
    va = add_section(pe, VEIL, len(blob))
    c = show + len(SHOW_PRE)
    blob[c:c + 5] = b"\xe8" + rel32(va + c + 5, va + decide)
    s_ = sound_stub(va + sound, WALL_SOUND_CTOR, WALL_SOUND_EXEC, event)
    blob[sound:sound + len(s_)] = s_
    c = phys + len(PHYS_PRE)
    blob[c:c + 5] = b"\xe8" + rel32(va + c + 5, va + decide)
    c += 5 + len(PHYS_MID)
    blob[c:c + 5] = b"\xe9" + rel32(va + c + 5, WALL_PHYS + 8)     # not smoke: on into EnablePhysics
    blob[c + 5:c + 10] = b"\xe9" + rel32(va + c + 10, va + sound)  # smoke: the sound instead
    pe.write(va, bytes(blob))
    pe.write(WALL_GLOBAL_LEN_FN, b"\xb8" + struct.pack("<I", GLOBAL_LEN + 8) + b"\xc3")
    pe.write(WALL_SHOW, b"\xe8" + rel32(WALL_SHOW + 5, va + show))
    pe.write(WALL_PHYS, b"\xe9" + rel32(WALL_PHYS + 5, va + phys) + b"\x90" * 3)
    return bytes(pe.d)


VEIL = b".veil\0\0\0"
RWX_CODE = 0xE0000020


def add_section(pe: PE, name: bytes, size: int) -> int:
    """Append an RWX section of `size` zero bytes after the last one; returns its rva."""
    falign = u32(pe.d, pe.opt + 36)
    salign = u32(pe.d, pe.opt + 32)
    hdr_size = u32(pe.d, pe.opt + 60)
    secs = list(pe.sections())
    if pe.sec0 + (pe.nsec + 1) * 40 > min(hdr_size, min(s[5] for s in secs if s[5])):
        raise ValueError("no room for another section header")
    va = max(s[3] + max(s[2], s[4]) for s in secs)
    va = (va + salign - 1) // salign * salign
    raw = (len(pe.d) + falign - 1) // falign * falign
    rsize = (size + falign - 1) // falign * falign
    pe.d += bytes(raw - len(pe.d) + rsize)
    o = pe.sec0 + pe.nsec * 40
    pe.d[o:o + 40] = name.ljust(8, b"\0")[:8] + struct.pack("<IIIIIIHHI", size, va, rsize, raw, 0, 0, 0, 0,
                                                           RWX_CODE)
    pe.nsec += 1
    struct.pack_into("<H", pe.d, pe.e + 6, pe.nsec)
    struct.pack_into("<I", pe.d, pe.opt + 56, (va + size + salign - 1) // salign * salign)  # SizeOfImage
    return va


def det_function(det: PE, spec) -> bytes:
    rva, size, sha, _ = spec
    code = det.read(rva, size)
    if hashlib.sha256(code).hexdigest() != sha:
        raise ValueError(f"detonator node function at {rva:#x} differs: wrong detonator script build")
    return code


def transplant(det: PE, node: dict, blob: bytearray, fixups: list) -> dict:
    """Copy one node class's ctor/Execute/Bind into `blob` with fresh copies of
    every .data slot and .rdata string they reference. Returns {key: offset};
    `fixups` collects (disp offset in blob, target offset in blob) to resolve
    once the section's rva is known."""
    _, _, dvs, dva, _, _ = det.section(b".data")
    codes = {k: det_function(det, spec) for k, spec in node.items()}
    targets = {}
    for k, (rva, _, _, disps) in node.items():
        for d in disps:
            targets.setdefault(rva + d + 4 + struct.unpack_from("<i", codes[k], d)[0], None)
    for t in sorted(t for t in targets if dva <= t < dva + dvs):     # slots: 8 zero bytes each
        blob += bytes(-len(blob) % 8)
        targets[t] = len(blob)
        blob += bytes(8)
    for t in sorted(t for t in targets if targets[t] is None):        # strings
        s = c_string(det, t)
        blob += bytes(-len(blob) % 8)
        targets[t] = len(blob)
        blob += s
    offs = {}
    for k, (rva, _, _, disps) in node.items():
        blob += bytes(-len(blob) % 16)
        offs[k] = len(blob)
        blob += codes[k]
        for d in disps:
            fixups.append((offs[k] + d, targets[rva + d + 4 + struct.unpack_from("<i", codes[k], d)[0]]))
    return offs


def c_string(pe: PE, rva: int) -> bytes:
    out = bytearray()
    while True:
        c = pe.read(rva + len(out), 1)
        if c == b"\0":
            return bytes(out) + b"\0"
        out += c


#: SPAWNPARTICLEEFFECTNODE float fields (offset in the node) the veil sets.
EMISSION_RATE, LIFE, COLOR_R, COLOR_G, COLOR_B, ALPHA = 0x44, 0x48, 0x4C, 0x50, 0x54, 0x58
PARTICLE_SCALE, SCALE = (0x78, 0x7C, 0x80), (0xA8, 0xAC, 0xB0)
#: its enableduration flag is the byte at node+11h, the duration (s) this float
DURATION = 0x14


def spawn_stub(at: int, ctor: int, execute: int, ring: int, count: int, floats: dict, asset: int = DET_FX,
               duration: float = 0.0) -> bytes:
    """execute_node replacement: `count` SPAWNPARTICLEEFFECTNODEs of particle effect `asset`
    (the detonator's smoke by default), each built at rsp+0x20. With `duration` (s), each
    effect is killed after that long (for effects that loop until killed)."""
    f = lambda v: struct.pack("<f", v)
    b = bytearray(bytes.fromhex("53 56 57 4881ec00010000 4889cb 31f6"))  # push rbx/rsi/rdi; sub rsp,100h; rbx=rcx; esi=0
    b += bytes.fromhex("80bbdb00000000 740c 48c7c0ffffffff e9")      # cmp byte [rbx+0dbh],0; je L; mov rax,-1; jmp done
    jmp_done = len(b)
    b += bytes(4)
    loop = len(b)
    b += bytes.fromhex("488d4c2420 e8") + rel32(at + len(b) + 10, ctor)  # L: lea rcx,[rsp+20h]; call ctor
    b += b"\x48\xb8" + struct.pack("<Q", asset) + bytes.fromhex("4889442428")        # node+08 asset
    b += b"\x48\xb8" + struct.pack("<Q", SELF) + bytes.fromhex("4889442440")         # node+20 actor = self
    b += bytes.fromhex("c644243100 c644243801 66c74424600101")       # enableduration 0, killatend 1, refpoint+leavebehind
    if duration > 0:
        floats = {**floats, DURATION: duration}
        b += bytes.fromhex("c644243101")                             # enableduration 1
    for off, value in sorted(floats.items()):                        # mov dword [rsp+20h+off], value
        b += bytes.fromhex("c78424") + struct.pack("<I", 0x20 + off) + f(value)
    b += bytes.fromhex("488d05") + rel32(at + len(b) + 7, ring)      # lea rax,[ring]
    b += bytes.fromhex("488d3c76")                                   # lea rdi,[rsi+rsi*2]
    for k, disp in enumerate((0xB0, 0xB4, 0xB8)):                    # node+90..98 offset = ring[i]
        b += bytes.fromhex("8b54b8") + bytes([4 * k]) + bytes.fromhex("899424") + struct.pack("<I", disp)
    b += bytes.fromhex("48c7431800000000")                           # ctx state 0: each cloud starts fresh
    b += bytes.fromhex("488d4c2420 4889da e8") + rel32(at + len(b) + 13, execute)  # Execute(node, ctx)
    b += bytes.fromhex("ffc6 83fe") + bytes([count]) + b"\x0f\x82" + rel32(0, 0)
    b[-4:] = struct.pack("<i", loop - len(b))
    done = len(b)
    b[jmp_done:jmp_done + 4] = struct.pack("<i", done - (jmp_done + 4))
    b += bytes.fromhex("4881c400010000 5f 5e 5b c3")
    return bytes(b)


def sound_stub(at: int, ctor: int, execute: int, event: int) -> bytes:
    """execute_node replacement: one PLAYSOUNDNODE for `event` on the script's
    own actor ("self"). (isrefpoint does not pin a sound in place: tested, it
    still followed the player.)

    It takes over a graph node of its own (the custom-param node). Sharing the
    cloud node did not work: two different node classes run on one graph node
    leave its engine state such that only the first one acts."""
    b = bytearray(bytes.fromhex("53 4881ecb0000000 4889cb"))       # push rbx; sub rsp,0b0h; rbx=rcx
    b += bytes.fromhex("80bbdb00000000 7409 48c7c0ffffffff eb")      # cmp byte [rbx+0dbh],0; je L; mov rax,-1; jmp done
    skip = len(b)
    b += b"\0"
    b += bytes.fromhex("488d4c2420 e8") + rel32(at + len(b) + 10, ctor)  # node (0x88 bytes) at rsp+20h
    b += b"\x48\xb8" + struct.pack("<Q", SELF) + bytes.fromhex("4889442438")   # node+18 actor symbol
    b += bytes.fromhex("c7442448") + struct.pack("<I", event)                   # node+28 event id
    b += bytes.fromhex("488d4c2420 4889da e8") + rel32(at + len(b) + 13, execute)
    b[skip] = len(b) - (skip + 1)
    b += bytes.fromhex("4881c4b0000000 5b c3")
    return bytes(b)


def ring_offsets(count: int, spread: float) -> bytes:
    """One cloud on the player, the rest evenly on a ring around them, alternately
    above and below it, so together they fill a ball."""
    pts = [(0.0, 0.0, 0.0)]
    for i in range(count - 1):
        a = 2 * math.pi * i / (count - 1)
        y = 0.0 if count <= 3 else spread * 0.6 * (1 if i % 2 else -1)
        pts.append((spread * math.sin(a), y, spread * math.cos(a)))
    return b"".join(struct.pack("<3f", *p) for p in pts)


def add_smoke_fx(barrier_pe: bytes, det_pe: bytes, count: int = 7, scale: float = 6.0,
                 life: float = 8.0, spread: float = 1.5, emission: float = 8.0,
                 particle_scale: float = 2.5, alpha: float = 10.0, shade: float = 0.9,
                 sound_event: int = VEIL_EVENT, mailbox: int = 0) -> bytes:
    """mailbox != 0: the wall is still created (as the smoke wall, see
    anchor_wall, which plays the sound) and the clouds take the custom-param
    node. mailbox == 0: no wall; clouds on the create node, and the sound,
    following the player, on the custom-param node."""
    if not 1 <= count <= 16:
        raise ValueError("count must be 1..16")
    pe, det = PE(barrier_pe), PE(det_pe)
    if any(s[1] == VEIL.rstrip(b"\0") for s in pe.sections()):
        raise ValueError("smoke script already has the veil section")
    call = pe.read(BIND_CALL, 5)
    if call != b"\xe8" + rel32(BIND_CALL + 5, CREATE_BIND) or pe.read(CREATE_NODE, 5) != CREATE_NODE_OLD \
            or pe.read(PARAM_NODE, 5) != CREATE_NODE_OLD:
        raise ValueError("unexpected barrier script build")
    for rva in PRIMING_SHOW:
        if pe.read(rva, 5) != SHOW_ON:
            raise ValueError("unexpected priming ShowModel node: wrong barrier script build")
    blob, fixups = bytearray(), []
    spn = transplant(det, SPAWN_PARTICLE, blob, fixups)
    if mailbox:
        sound_event = 0                      # the smoke wall plays it
    snd = transplant(det, PLAY_SOUND, blob, fixups) if sound_event else {}
    blob += bytes(-len(blob) % 16)
    ring_off = len(blob)
    blob += ring_offsets(count, spread)
    blob += bytes(-len(blob) % 16)
    bind_stub_off = len(blob)
    blob += bytes(48)                        # placeholder, filled below
    blob += bytes(-len(blob) % 16)
    spawn_off = len(blob)
    blob += bytes(512)                       # placeholder, filled below
    blob += bytes(-len(blob) % 16)
    sound_off = len(blob)
    blob += bytes(128)                       # placeholder, filled below
    blob += bytes(-len(blob) % 16)
    stamp_off = len(blob)
    blob += STAMP.replace(MAILBOX_MARK, struct.pack("<I", mailbox)) + bytes(5)
    va = add_section(pe, VEIL, len(blob))
    for d, target in fixups:                 # re-aim the copied code at the new slots and strings
        blob[d:d + 4] = rel32(va + d + 4, va + target)

    # Bind stub: the create node's Bind, then each transplanted node's (rdi = binding table).
    at = va + bind_stub_off
    stub = bytearray(bytes.fromhex("4883ec28 e8") + rel32(at + 9, CREATE_BIND))
    for offs in (spn, snd):
        if offs:
            stub += bytes.fromhex("488b5710 488b0f e8") + rel32(at + len(stub) + 12, va + offs["bind"])
    stub += bytes.fromhex("4883c428 c3")
    blob[bind_stub_off:bind_stub_off + len(stub)] = stub

    floats = {EMISSION_RATE: emission, LIFE: life, ALPHA: alpha,
              COLOR_R: shade, COLOR_G: shade, COLOR_B: shade}
    floats.update({o: scale for o in SCALE})
    floats.update({o: particle_scale for o in PARTICLE_SCALE})
    spawn = spawn_stub(va + spawn_off, va + spn["ctor"], va + spn["exec"], va + ring_off, count, floats)
    if len(spawn) > 512:
        raise ValueError("spawn stub too long")
    blob[spawn_off:spawn_off + len(spawn)] = spawn
    if sound_event:
        sound = sound_stub(va + sound_off, va + snd["ctor"], va + snd["exec"], sound_event)
        blob[sound_off:sound_off + len(sound)] = sound

    c = stamp_off + len(STAMP)
    blob[c:c + 5] = b"\xe9" + rel32(va + c + 5, CREATE_NODE + 5)   # back into the create node

    pe.write(va, bytes(blob))
    pe.write(BIND_CALL, b"\xe8" + rel32(BIND_CALL + 5, at))
    if mailbox:
        pe.write(CREATE_NODE, b"\xe9" + rel32(CREATE_NODE + 5, va + stamp_off))
        pe.write(PARAM_NODE, b"\xe9" + rel32(PARAM_NODE + 5, va + spawn_off))
    else:
        pe.write(CREATE_NODE, b"\xe9" + rel32(CREATE_NODE + 5, va + spawn_off))
        if sound_event:
            pe.write(PARAM_NODE, b"\xe9" + rel32(PARAM_NODE + 5, va + sound_off))
    for rva in PRIMING_SHOW:
        pe.write(rva, SHOW_OFF)
    return bytes(pe.d)


# --- networked veil: the barrier wall carries it to every machine ---------------
#
# The tac mod graph runs only on the user's client, so clouds and sound spawned
# by the smoke script are seen and heard there alone. The one networked thing it
# does is create the barrier wall (R15NetPooledActorCreate): every machine gets
# the wall, and the wall script runs on every machine. Which wall is the veil
# travels separately, through VeilNet.dll (plugin/veilnet.cpp):
#
# * the smoke script creates the wall as the barrier does; its custom-param node
#   (d11498f0), which runs just before, bumps a use counter (mark_param);
# * VeilNet on that client sees it, takes a "veil token" and sends the veil to the
#   server, which takes one too and relays it to every other client's VeilNet;
# * the wall script's spawn nodes wait a moment for a token (GATE, TOKEN_DECIDE). A
#   wall that takes one hides its model, skips EnablePhysics (no collision), and
#   instead spawns the smoke clouds (detonator SPAWNPARTICLEEFFECTNODE) and plays
#   UMBRAL VEIL's sound (the wall's own PLAYSOUNDNODE). Every other wall -- the
#   energy barrier -- is untouched.
#
# (Custom params do not work for this: the wall script's
# R15NetPooledActorQueryExpression never read back what the veil's param node sent.)

VEIL_MARKER = 0x534D4F4B                      # "SMOK": fits the param node's imm32
PARAM_SYMBOL = 0x63FD                         # barrier param node: mov qword [rbp-29h], -1 (node+40h)
PARAM_SYMBOL_OLD = bytes.fromhex("48c745d7ffffffff")

WALL_BIND_CALL, WALL_BIND_TARGET = 0x3DE0, 0x17F0   # setup_bindings: call <a node's Bind>

# --- the veil's use counter --------------------------------------------------------
#: Spare bytes past echovr.exe's .data (rva 0x2104ca4..0x2105000 in build b6d08277...,
#: mapped read/write with it, never used by the game). Three 0x100-byte records:
#: +000 / +100 the wall's show / physics node (GATE keeps how long it waited at +14h),
#: +200 the veil's custom-param node: count, 3, ctx, the node (0x50). VeilNet.dll
#: watches that count: each bump is a use of the veil on this machine.
DEBUG_RVA = 0x2104D00
RVA_MARK = struct.pack("<I", 0x11223344)
#: param node Execute(rcx = node, rdx = ctx): record 3 = count, 3, ctx, node (0x50)
DEBUG_PARAM = bytes.fromhex(
    "6548a16000000000000000488b4010480544332211ff00c7400403000000488950084531c04e8b0c014e894c"
    "00184983c0084983f85072ed")
PARAM_EXEC_CALL, PARAM_EXEC = 0x64F1, 0x22A0           # param node: call R15NETPOOLEDACTORCUSTOMPARAMNODE::Execute


def mark_param(barrier_pe: bytes, marker: int = VEIL_MARKER, record: int = DEBUG_RVA + 0x200) -> bytes:
    """The smoke script's custom-param node bumps the use counter VeilNet.dll watches
    (the u32 at `record`; POINT's script uses POINT_RECORD), and still sends `marker`
    as the wall's symbol param, harmless."""
    pe = PE(barrier_pe)
    if pe.read(PARAM_SYMBOL, 8) != PARAM_SYMBOL_OLD \
            or pe.read(PARAM_EXEC_CALL, 5) != b"\xe8" + rel32(PARAM_EXEC_CALL + 5, PARAM_EXEC):
        raise ValueError("unexpected barrier param node: wrong barrier script build")
    stub = DEBUG_PARAM.replace(RVA_MARK, struct.pack("<I", record))   # record, then Execute
    va = add_section(pe, VEIL, len(stub) + 5)
    pe.write(va, stub + b"\xe9" + rel32(va + len(stub) + 5, PARAM_EXEC))
    pe.write(PARAM_EXEC_CALL, b"\xe8" + rel32(PARAM_EXEC_CALL + 5, va))
    pe.write(PARAM_SYMBOL, PARAM_SYMBOL_OLD[:4] + struct.pack("<I", marker))
    for rva in PRIMING_SHOW:                  # no priming hologram, as before
        if pe.read(rva, 5) != SHOW_ON:
            raise ValueError("unexpected priming ShowModel node: wrong barrier script build")
        pe.write(rva, SHOW_OFF)
    return bytes(pe.d)


#: VeilNet.dll's veil tokens: spare bytes past echovr.exe's .data, +00 u32 count,
#: +08 u64 expiry (KUSER_SHARED_DATA interrupt time), +10 / +14 u32 walls that became
#: the veil / stayed barriers (VeilNet logs both). See plugin/veilnet.cpp.
TOKEN_RVA = 0x2104CC0
#: decide(rcx = node ctx, edx = 0 just look / else decide for good) -> eax 1 veil,
#: 0 barrier, 2 undecided (no token yet, edx = 0). The decision is kept per wall in 4
#: bytes added to its script's global data ([[ctx]+68h]+158h: "SMOK" / "NORM"), so its
#: show and physics nodes agree and a wall takes at most one token. Taking a token:
#: unexpired, count > 0, lock cmpxchg count - 1. Assembled with keystone; 0x11223344
#: marks TOKEN_RVA.
TOKEN_DECIDE = bytes.fromhex(
    "4c8b114d8b5268418b82580100003d4b4f4d5374503d4d524f4e74636548a16000000000000000488b4010"
    "4805443322114989c049c7c10800fe7f4d8b094d3b48087327418b0085c07e208d48fff0410fb10875ef41"
    "c782580100004b4f4d53f041ff4010b801000000c385d2741341c782580100004d524f4ef041ff401431c0"
    "c3b802000000c3")


# --- POINT: a wall that takes a point token goes off as a stun field ----------------
#
# POINT's script is the barrier script too (mark_param with POINT_RECORD): VeilNet.dll
# sends its uses as 'P' packets and every machine gets a "point token" (POINT_TOKEN_RVA,
# same layout as the veil's). A wall that takes one hides, has no collision, waits the
# charge-up, then shows the stun mine's burst, plays the stun field's sound and
# activates a stun explosion on itself: the stun mine's explosion component, which
# fix_point.py gives the wall actor in every level (radius and stun length from
# ability_properties.point). The explosion node class is transplanted from the stun
# mine's script.

POINT_MARKER = 0x4E494F50                     # "POIN"
#: POINT's use counter: the point script's custom-param node record (VeilNet watches +00)
POINT_RECORD = DEBUG_RVA + 0x280
#: POINT's tokens, after the veil's: +00 count, +08 expiry, +10 walls that went off
POINT_TOKEN_RVA = 0x2104CE0
STUN_SCRIPT = "190ed14ff6dc4ad8"              # mp_combat_grenade_stun
#: R15NETACTIVATEEXPLOSIONNODE, from the stun mine's script. Node: +08 actor (-1 =
#: self), +10 component name, +18 arg1 (the stun length, s), +1C arg2, +20..28 arg3.
ACTIVATE_EXPLOSION = {
    "ctor": (0x4690, 44, "e1e8e4e8c1d796a8aff5e033162ffdba6efc4934dbf6071c1889e9d7880e47a7", []),
    "exec": (0x46C0, 235, "d3096c389afeeff1ffe57d3919a5f445b2d314e5459f858609fe68f5e2990940",
             [0x1e, 0x36, 0x47, 0x4d, 0x5e, 0x64, 0x75, 0x7b, 0x8c, 0x92, 0xa3, 0xa9, 0xba, 0xc0, 0xd1,
              0xe7]),
    "bind": (0x4550, 308, "d4097526d039161edb33cf874d4d9eb35f1351b8bf8eaa9e5f7bba03dd370b36",
             [0x22, 0x29, 0x30, 0x37, 0x4e, 0x55, 0x5c, 0x73, 0x7a, 0x81, 0x98, 0x9f, 0xa6, 0xbd, 0xc4,
              0xcb, 0xe2, 0xe9, 0xf0, 0x107, 0x10e, 0x115]),
}
#: the stun mine's explosion component (its name on the stun mine, and on the wall)
STUN_EXPLOSION = 0x25905B54E61D3F10
#: the stun mine's burst (execute_node_8ff76ff9)
POINT_FX = 0x4CE12AE42C1B6269
#: the arc mine's sounds (mp_combat_grenade_arc's PLAYSOUND nodes, bank c823e2c9bc0168ad),
#: in the order --point-sound-preview plays them; POINT_EVENT is the one it plays
ARC_EVENTS = [0x9BA74430, 0x84545E9B, 0xDA4D002D, 0xD19CD68D, 0xD5D7FDC7, 0x7F295300, 0xB1C3DEA9,
              0xE9ECEA06, 0x9B54488D]
#: POINT's sound: veil_sound.py's event in the veil bank, which every match loads (the arc
#: mine's bank is not, so ARC_EVENTS[0] was silent)
from veil_sound import POINT_SND_EVENT as POINT_EVENT          # noqa: E402
#: what --point-sound-preview cycles through: the stun field's sound first (heard in an
#: earlier build, so a silent #1 means the sound path, not the event, is at fault), then
#: the arc mine's
PREVIEW_EVENTS = [0x7741E93B] + ARC_EVENTS
#: --point-sound-preview's counter (per machine): after POINT's tokens
POINT_PREVIEW_RVA = POINT_TOKEN_RVA + 0x18
#: POINT's charge-up indicator: the stun mine's burst, small. (Its lingering field,
#: de22b615c9c69cdd, loops until its node kills it, and POINT's node moves on: it never
#: went away.)
POINT_CHARGE_FX = POINT_FX
#: the indicator is shown again this often during the charge-up (100 ns)
from echocombat_config import section                             # noqa: E402
CHARGE_REPEAT = int(section("ability_properties", "point").get("charge_indicator_repeat", 0.4) * 10_000_000)
#: POINTs that went off (fired the stun) on this machine: VeilNet.dll logs it
POINT_FIRED_RVA = 0x2104D44
#: decide() with point tokens: as TOKEN_DECIDE, but a point token is tried first and
#: gives "POIN" / eax 3. 0x22334455 marks POINT_TOKEN_RVA, 0x11223344 TOKEN_RVA.
POINT_DECIDE = bytes.fromhex(
    "4c8b114d8b5268418b82580100003d4b4f4d530f848d0000003d504f494e74523d4d524f4e0f849500000065"
    "48a160000000000000004c8b581049c7c10800fe7f4d8b094d8d83554433224d3b48087327418b0085c07e20"
    "8d48fff0410fb10875ef41c78258010000504f494ef041ff4010b803000000c34d8d83443322114d3b480873"
    "27418b0085c07e208d48fff0410fb10875ef41c782580100004b4f4d53f041ff4010b801000000c385d27413"
    "41c782580100004d524f4ef041ff401431c0c3b802000000c3")
POINT_MARK = struct.pack("<I", 0x22334455)
#: the wall's global data has 8 spare bytes (past 158h, inside the heap block's 16-byte
#: rounding; +160h is the next block's header, and writing it crashed the server when
#: the block was freed): +158h the decision byte and the last run (see renew_stub),
#: +15Ch POINT's state
#: (0 not started, 1 gone off, else the charge-up's start, interrupt time low dword | 1)
POINT_STATE = GLOBAL_LEN + 4


def explosion_stub(at: int, ctor: int, execute: int, component: int, stun_length: float) -> bytes:
    """One R15NETACTIVATEEXPLOSIONNODE on the script's own actor (rcx = ctx)."""
    b = bytearray(bytes.fromhex("53 4881ec80000000 4889cb 488d4c2420 e8"))
    b += rel32(at + len(b) + 4, ctor)
    b += b"\x48\xb8" + struct.pack("<Q", component) + bytes.fromhex("4889442430")     # node+10 component
    b += bytes.fromhex("c7442438") + struct.pack("<f", stun_length)                  # node+18 stun length
    b += bytes.fromhex("488d4c2420 4889da e8")
    b += rel32(at + len(b) + 4, execute)
    b += bytes.fromhex("4881c480000000 5b c3")
    return bytes(b)


def preview_sound_stub(at: int, ctor: int, execute: int, table: int, n: int) -> bytes:
    """sound_stub, but each new sound is the next of the `n` events at `table` (a counter
    at POINT_PREVIEW_RVA, bumped on a node's first run only)."""
    b = bytearray(bytes.fromhex("53 4881ecb0000000 4889cb 80bbdb00000000 740c 48c7c0ffffffff e9"))
    done = len(b)
    b += bytes(4)
    b += bytes.fromhex("488d4c2420 e8") + rel32(at + len(b) + 10, ctor)
    b += b"\x48\xb8" + struct.pack("<Q", SELF) + bytes.fromhex("4889442438")       # node+18 actor
    b += bytes.fromhex("6548a16000000000000000 488b4010 4805") + struct.pack("<I", POINT_PREVIEW_RVA)
    b += bytes.fromhex("48837b1800 750b ba01000000 f00fc110 eb04 8b10 ffca")    # first run: xadd; else count-1
    b += bytes.fromhex("89d0 31d2 b9") + struct.pack("<I", n) + bytes.fromhex("f7f1")
    b += bytes.fromhex("488d05") + rel32(at + len(b) + 7, table)
    b += bytes.fromhex("8b0490 89442448")                                     # node+28 = table[count % n]
    b += bytes.fromhex("488d4c2420 4889da e8") + rel32(at + len(b) + 13, execute)
    b[done:done + 4] = struct.pack("<i", len(b) - (done + 4))
    b += bytes.fromhex("4881c4b0000000 5b c3")
    return bytes(b)


#: the wall's PLAYSOUNDNODE::Execute(rcx = node, rdx = ctx): mov [rsp+8], rbx; push rdi
WALL_SOUND_ENTRY = bytes.fromhex("48895c2408")


def mute_stub(at: int) -> bytes:
    """PLAYSOUNDNODE::Execute's entry: a POINT or UMBRAL VEIL wall's own sounds (the
    barrier's, its running-out noise among them) are done at once, silently; POINT's and
    the veil's sounds come through the trampoline instead."""
    b = bytearray(bytes.fromhex("488b02 488b4068 0fb68058010000"))     # al = the decision
    b += bytes.fromhex("3c%02x 7404 3c%02x 7503" % (DECIDED_POINT, DECIDED_VEIL))
    b += bytes.fromhex("31c0 c3") + WALL_SOUND_ENTRY + b"\xe9"
    b += rel32(at + len(b) + 4, WALL_SOUND_EXEC + len(WALL_SOUND_ENTRY))
    return bytes(b)


def show_dispatch(at: int, decide: int, show_tramp: int, point: int) -> bytes:
    """The wall's ShowModel node (rcx = ctx), after its gate: a POINT wall runs the node
    once (hidden: decide is 3), then goes on as POINT (point_block, which keeps the node
    running through the charge-up and the sound); any other wall is the node as before."""
    b = bytearray(bytes.fromhex("53 4883ec20 4889cb 31d2 4889d9 e8"))
    b += rel32(at + len(b) + 4, decide)
    b += bytes.fromhex("3c03 0f85")
    normal = len(b)
    b += bytes(4)
    # a fresh run (node state 0) hides the wall even when the EnablePhysics node has
    # already started POINT (+15Ch set): skipping it left the wall visible
    b += bytes.fromhex("48837b1800 0f85")
    started = len(b)
    b += bytes(4)
    b += bytes.fromhex("4889d9 e8") + rel32(at + len(b) + 8, show_tramp)
    b += bytes.fromhex("48c7431800000000")
    b[started:started + 4] = struct.pack("<i", len(b) - (started + 4))
    b += b"\xe9" + rel32(at + len(b) + 5, point)
    b[normal:normal + 4] = struct.pack("<i", len(b) - (normal + 4))
    b += bytes.fromhex("4889d9 4883c420 5b e9") + rel32(at + len(b) + 13, show_tramp)
    return bytes(b)


#: POINT's effects out of its node. point_block ran the charge-up indicator, the burst, the
#: stun explosion and the sound inside the wall's own node: another node's Execute run
#: from inside a node is what crashed every client when a drone's lifetime ran out
#: (1.1.4), and POINT crashed clients too. On a machine whose DroneFix.dll says so
#: (FX_DEFER_RVA != 0: clients), each goes into FX_QUEUE_RVA instead -- {ctx, stub | kind}
#: x FX_QUEUE_LEN -- and DroneFix runs it on its follow update, outside any node, one per
#: wall per frame, in kind order (charge, burst, explosion, sound; one sound per wall).
#: Elsewhere (the server; a client without that DroneFix) they run in the node as before.
FX_QUEUE_RVA = 0x2104DA0                    # 6 x 16 bytes, to 0x2104E00
FX_QUEUE_LEN = 6
FX_DEFER_RVA = 0x2104E20                    # dword, set by DroneFix.dll on clients
FX_CHARGE, FX_BURST, FX_BOOM, FX_SOUND = range(4)


def defer_stub(at: int, stub: int, kind: int, tail: bool = False) -> bytes:
    """A stand-in for `stub` (rcx = ctx): queued for DroneFix where FX_DEFER_RVA is set, else
    straight on into the stub. `tail`: reached by a jmp in place of the node's own return
    (the sound): queued, the node is done (eax 0); a state a direct run left is cleared."""
    b = bytearray(bytes.fromhex("6548a16000000000000000 4c8b5010 4183ba") + struct.pack("<I", FX_DEFER_RVA)
                  + bytes.fromhex("00 0f84"))
    to_direct = len(b)
    b += bytes(4)
    to_clear = None
    if tail:
        b += bytes.fromhex("48837918 00 0f85")                       # cmp qword [rcx+18h], 0; jne clear
        to_clear = len(b)
        b += bytes(4)
    b += bytes.fromhex("4d8d82") + struct.pack("<I", FX_QUEUE_RVA)   # lea r8, [r10+queue]
    b += bytes.fromhex("41b9") + struct.pack("<I", FX_QUEUE_LEN)     # mov r9d, n
    loop = len(b)
    b += bytes.fromhex("31c0 f0490fb108 74")                         # xor eax, eax; lock cmpxchg [r8], rcx; je got
    to_got = len(b)
    b += b"\0"
    b += bytes.fromhex("4983c010 41ffc9 75")                         # add r8, 16; dec r9d; jnz loop
    b += bytes([(loop - (len(b) + 1)) & 0xFF])
    b += b"\xeb"                                                     # full: dropped
    to_done = len(b)
    b += b"\0"
    b[to_got] = len(b) - (to_got + 1)
    b += bytes.fromhex("488d05") + rel32(at + len(b) + 7, stub)      # lea rax, [stub]
    b += bytes.fromhex("4883c8") + bytes([kind])                     # or rax, kind
    b += bytes.fromhex("49894008")                                   # mov [r8+8], rax
    b[to_done] = len(b) - (to_done + 1)
    b += bytes.fromhex("31c0 c3")
    if tail:
        b[to_clear:to_clear + 4] = struct.pack("<i", len(b) - (to_clear + 4))
        b += bytes.fromhex("48c7411800000000 31c0 c3")               # mov qword [rcx+18h], 0
    b[to_direct:to_direct + 4] = struct.pack("<i", len(b) - (to_direct + 4))
    b += b"\xe9" + rel32(at + len(b) + 5, stub)
    return bytes(b)


def point_block(at: int, delay: int, spawn: int, explode: int, sound: int, charge: int = None) -> bytes:
    """The wall's EnablePhysics node for a POINT wall (rbx = ctx; push rbx; sub rsp, 20h
    done): wait `delay` (100 ns) from the first run (showing `charge`, the charge-up
    indicator, on it), then the burst, the explosion and the sound; later runs carry on
    with the sound."""
    b = bytearray(bytes.fromhex("488b03 488b4068 8b885c010000 83f901 0f84"))
    cont = len(b)
    b += bytes(4)
    to_wait = None
    if charge is None:
        b += bytes.fromhex("48c7c20800fe7f 8b12 85c9 750b 89d1 83c901 89885c010000")
    else:                                   # first run: the start, the indicator, then wait
        b += bytes.fromhex("48c7c20800fe7f 8b12 85c9 7520 89d1 83c901 89885c010000")
        b += bytes.fromhex("48c7431800000000 4889d9 e8") + rel32(at + len(b) + 16, charge)
        b += b"\xe9"
        to_wait = len(b)
        b += bytes(4)
    # elapsed = (now | 1) - start: the start is kept as now | 1 (never 0), and without
    # the | 1 an even now gave -1, a huge unsigned wait -- POINT went off at once
    b += bytes.fromhex("83ca01 29ca 81fa") + struct.pack("<I", delay) + b"\x0f\x82"
    wait = len(b)
    b += bytes(4)
    b += bytes.fromhex("c7805c01000001000000")                       # gone off
    b += bytes.fromhex("6548a16000000000000000 488b4010 f0ff80") + struct.pack("<I", POINT_FIRED_RVA)  # counted
    for stub in (spawn, explode):
        b += bytes.fromhex("48c7431800000000 4889d9 e8") + rel32(at + len(b) + 16, stub)
    b += bytes.fromhex("48c7431800000000 eb")
    fire = len(b)
    b += b"\0"
    # gone off already: carry on with a sound still playing (ctx+18h its state); a fresh
    # run of the node (state 0) just finishes, so the sound never plays twice
    b[cont:cont + 4] = struct.pack("<i", len(b) - (cont + 4))
    # (a node that was still waiting out the charge-up -- the other node fired -- holds
    # the busy marker, not a sound's state: it just finishes, its state cleared)
    # (the busy marker is 20000000h in the high dword, the last indicator's time below)
    # A node still waiting when the other fired plays the sound: the firing node has run
    # the burst and the stun explosion, and a sound after those stayed silent (only the
    # explosion's own fizzle was heard).
    b += bytes.fromhex("488b4318 4885c0 7419 4889c2 48c1ea20 81fa00000020 7512 48c7431800000000 eb08"
                       "31c0 4883c420 5b c3")
    b[fire] = len(b) - (fire + 1)
    b += bytes.fromhex("4889d9 4883c420 5b e9") + rel32(at + len(b) + 13, sound)
    b[wait:wait + 4] = struct.pack("<i", len(b) - (wait + 4))
    if to_wait is not None:
        b[to_wait:to_wait + 4] = struct.pack("<i", len(b) - (to_wait + 4))
    # still charging: busy (ctx+18h below the gate's 4000...h, so the gate lets it straight back in)
    if charge is None:
        b += bytes.fromhex("48b80000000000000020 48894318 48c7c0ffffffff 4883c420 5b c3")
        return bytes(b)
    # busy = 20000000h:<time of the last indicator>; the indicator (a short burst) is shown
    # again every CHARGE_REPEAT until POINT goes off, so it lasts the whole charge-up
    b += bytes.fromhex("488b4318 48c7c20800fe7f 8b12 4889c1 48c1e920 81f900000020 0f85")
    to_set = len(b)
    b += bytes(4)
    b += bytes.fromhex("89d1 29c1 81f9") + struct.pack("<I", CHARGE_REPEAT) + b"\x0f\x82"
    to_keep = len(b)
    b += bytes(4)
    b += bytes.fromhex("48c7431800000000 4889d9 e8") + rel32(at + len(b) + 16, charge)
    b += bytes.fromhex("48c7c20800fe7f 8b12")
    b[to_set:to_set + 4] = struct.pack("<i", len(b) - (to_set + 4))
    b += bytes.fromhex("89d0 48b90000000000000020 4809c8 48894318")
    b[to_keep:to_keep + 4] = struct.pack("<i", len(b) - (to_keep + 4))
    b += bytes.fromhex("48c7c0ffffffff 4883c420 5b c3")
    return bytes(b)


#: Wait gate at a wall node's entry (rcx = ctx). On remote machines the veil's
#: token and the wall come by different routes (VeilNet's UDP relay, the game's own
#: messages), so a node asks decide() (edx = 0: just look) every frame, returning -1
#: (still running; the engine calls it again next frame, as it does a delay node)
#: with ctx+18h = 4000000000000000h | the start time, until the wall is decided or
#: GATE_LIMIT has passed. Then it records the wait (ms + 1, record+14h), resets the
#: state to 0 and goes on into the node as if it had just started. Assembled with
#: keystone: the call (decide), 0x55667788 (the limit), 0x11223344 (the record field
#: rva) and the final jmp (where to go on) are filled in by gate_stub().
GATE = bytes.fromhex(
    "53564883ec284889cb488b43184885c0741348ba00000000000000404839d00f8cb500000080bbdb00000000"
    "755b4889d931d2e8c80f000083f802754c48c7c00800fe7f488b00488b53184885d2751348ba000000000000"
    "00404809d048894318eb1848b9ffffffffffffff3f4821ca4829d0483d88776655730e48c7c0ffffffff4883"
    "c4285e5bc331f6488b53184885d2742748c7c00800fe7f488b0048b9ffffffffffffff3f4821ca4829d031d2"
    "b91027000048f7f18d70016548a16000000000000000488b4010480544332211893048c74318000000004889"
    "d94883c4285e5be9181f0000")
GATE_LIMIT = 2_500_000                        # 0.25 s, in 100 ns (KUSER_SHARED_DATA interrupt time)
#: where the wall waits for its params: execute_node_fac8332c (ShowModel, its entry
#: push rbx; sub rsp, 50h -- replayed by the gate) and the EnablePhysics node.
WALL_SHOW_NODE, WALL_SHOW_NODE_OLD = 0x6D30, bytes.fromhex("4053 4883ec50")


#: The barrier wall is a pooled actor: a wall the pool hands out again keeps its script's
#: global data, so on its own it kept its last decision and POINT's state (+15Ch), never
#: took another token, and a POINT use could come up as UMBRAL VEIL (or a plain
#: barrier). The dword at +158h is the decision byte (DECIDED_*, 0 undecided) and, above
#: it, the last time the wall's nodes ran (24 bits of interrupt time >> 20, ~0.1 s units,
#: wrapping after 20 days). Both spawn nodes (ShowModel, EnablePhysics) pass through
#: renew_stub on every entry: after RENEW_AFTER without a run the wall is in a new life,
#: so the decision, POINT's state and the node's own state (ctx+18h, left over when the
#: pool cut the last life short) are cleared and the gate waits for a token again. The
#: headless server does not always give the ShowModel node a fresh run, hence both nodes
#: and a time rule. A wall lives 15 s (ability_properties.shield.duration) and a tac mod
#: recharges in 30 s or more, so no live wall ever goes RENEW_AFTER without a run.
DECIDED_VEIL, DECIDED_POINT, DECIDED_NORM = ord("S"), ord("P"), ord("N")
TIME_SHIFT = 20                               # 2^20 x 100 ns = 0.105 s
RENEW_AFTER = 8 * 10_000_000 >> TIME_SHIFT    # 8 s
#: the EnablePhysics node runs seconds after the ShowModel node (once the wall is
#: solid): a reset there would turn a hidden veil / POINT wall into an invisible solid
#: barrier, so it waits longer. Still under the gap between two lives of a wall (its
#: last run, the veil's 14 s sound at most, to the next use, 30 s+ after the last).
RENEW_AFTER_PHYS = 14 * 10_000_000 >> TIME_SHIFT    # 14 s


def renew_stub(at: int, cont: int, after: int = RENEW_AFTER) -> bytes:
    """At a spawn node's entry (rcx = ctx, kept): a new life clears the wall's decision,
    then on to `cont` (the gate)."""
    b = bytearray(bytes.fromhex("80b9db000000 00 75"))                 # cmp byte [rcx+0DBh], 0; jne done
    j1 = len(b)
    b += b"\0" + bytes.fromhex("4c8b01 4d8b4068")                     # r8 = [[ctx]+68h], the global data
    b += bytes.fromhex("49c7c10800fe7f 4d8b09 49c1e9") + bytes([TIME_SHIFT])   # r9 = now, in units
    b += bytes.fromhex("418b8058010000 c1e808")                        # eax = last run
    b += bytes.fromhex("4589cb 4129c3 4181e3ffffff00")                 # r11d = (now - last run) & 24 bits
    b += bytes.fromhex("410fb68058010000 41c1e108 4409c8 41898058010000")  # last run = now, decision kept
    b += bytes.fromhex("4181fb") + struct.pack("<I", after) + b"\x72"   # jb done
    j2 = len(b)
    b += b"\0" + bytes.fromhex("41c6805801000000")                    # decision = undecided
    b += bytes.fromhex("41c7805c01000000000000")                       # POINT state = 0
    b += bytes.fromhex("48c7411800000000")                             # node state = 0: a fresh run
    for j in (j1, j2):
        b[j] = len(b) - (j + 1)
    b += b"\xe9" + rel32(at + len(b) + 5, cont)
    return bytes(b)


#: The last token any wall on this machine took: +00 u64 interrupt time, +08 u32 its
#: decision (DECIDED_*). Spare bytes after POINT_RECORD's 0x50.
LAST_TAKE_RVA = 0x2104FE0
#: One use can bring two copies of its wall to a machine (VeilNet.log: a wall takes the
#: token, a second finds none 0.27 s later and stands as a plain barrier; when the copy
#: that took it is the one never seen, nothing shows at all). A wall that finds no
#: token within ADOPT_WINDOW of the last take makes the same decision.
ADOPT_WINDOW = 10_000_000                     # 1 s, in 100 ns


def decide_code(point: bool) -> bytes:
    """decide(rcx = node ctx, edx = 0 just look / else decide for good) -> eax 1 veil,
    3 point, 0 barrier, 2 undecided (edx = 0 only). Kept per wall, the byte at +158h. A point
    token (point builds) is tried first, then a veil token, then the last take
    (ADOPT_WINDOW). Taking: unexpired, count > 0, lock cmpxchg count - 1; a take is
    counted at +10h of its token block (VeilNet logs it), a barrier at +14h of the
    veil's."""
    code, labels, fix = bytearray(), {}, []

    def emit(h, *imm):
        code.extend(bytes.fromhex(h))
        for i in imm:
            code.extend(struct.pack("<I", i & 0xFFFFFFFF))

    def jump(op, name):                         # op: "0f8x" (jcc rel32) or "e9"
        emit(op)
        fix.append((len(code), name))
        code.extend(bytes(4))

    def label(name):
        labels[name] = len(code)

    def set_decision(mark):
        code.extend(bytes.fromhex("41c68258010000") + bytes([mark]))   # mov byte [r10+158h], mark

    emit("4c8b11 4d8b5268 410fb68258010000")                           # r10 = global data; eax = decision
    emit("3c%02x" % DECIDED_VEIL); jump("0f84", "r1")
    emit("3c%02x" % DECIDED_POINT); jump("0f84", "r3")
    emit("3c%02x" % DECIDED_NORM); jump("0f84", "r0")
    emit("6548a16000000000000000 4c8b4010")                            # r8 = image base
    emit("49c7c10800fe7f 4d8b09")                                       # r9 = now
    takes = ([(POINT_TOKEN_RVA, DECIDED_POINT, 3)] if point else []) + [(TOKEN_RVA, DECIDED_VEIL, 1)]
    for n, (rva, mark, ret) in enumerate(takes):
        emit("4d8d98", rva)                                             # r11 = token block
        emit("4d3b4b08"); jump("0f83", f"fail{n}")                      # now >= expiry: expired
        label(f"loop{n}")
        emit("418b03 85c0"); jump("0f8e", f"fail{n}")                   # count <= 0
        emit("8d48ff f0410fb10b"); jump("0f85", f"loop{n}")             # lock cmpxchg [r11], count - 1
        emit("f041ff4310")                                              # lock inc dword [r11+10h]
        set_decision(mark)
        emit("4d8988", LAST_TAKE_RVA)                                   # last take = now, mark
        emit("41c780", LAST_TAKE_RVA + 8, mark)
        emit("b8", ret); emit("c3")
        label(f"fail{n}")
    emit("4c89c8 492b80", LAST_TAKE_RVA)                                # rax = now - last take
    emit("483d", ADOPT_WINDOW); jump("0f83", "none")
    emit("418b80", LAST_TAKE_RVA + 8)                                   # eax = its decision
    for rva, mark, ret in takes:
        emit("3d", mark); jump("0f84", f"adopt{ret}")
    jump("e9", "none")
    for rva, mark, ret in takes:
        label(f"adopt{ret}")
        set_decision(mark)
        emit("4d8d98", rva); emit("f041ff4310")                         # counted as a take
        emit("b8", ret); emit("c3")
    label("none")
    emit("85d2"); jump("0f84", "r2")                                    # just looking: undecided
    set_decision(DECIDED_NORM)
    emit("4d8d98", TOKEN_RVA); emit("f041ff4314")                       # walls that stayed barriers
    label("r0"); emit("31c0 c3")
    label("r1"); emit("b8", 1); emit("c3")
    label("r2"); emit("b8", 2); emit("c3")
    label("r3"); emit("b8", 3); emit("c3")
    for at, name in fix:
        code[at:at + 4] = struct.pack("<i", labels[name] - (at + 4))
    return bytes(code)


def gate_stub(at: int, decide: int, record: int, cont: int, prologue: bytes = b"") -> bytes:
    """GATE at `at`: waits on decide(), writes the wait to record `record` (1/2), then
    runs `prologue` and jumps to `cont` (rcx = ctx)."""
    b = bytearray(GATE[:-5])
    c = GATE.find(bytes.fromhex("31d2e8")) + 2
    b[c:c + 5] = b"\xe8" + rel32(at + c + 5, decide)
    b = bytearray(bytes(b).replace(struct.pack("<I", 0x55667788), struct.pack("<I", GATE_LIMIT)))
    b = bytearray(bytes(b).replace(RVA_MARK, struct.pack("<I", DEBUG_RVA + (record - 1) * 0x100 + 0x14)))
    b += prologue + b"\xe9" + rel32(at + len(b) + len(prologue) + 5, cont)
    return bytes(b)


def network_wall(wall_pe: bytes, det_pe: bytes, count: int = 7, scale: float = 6.0,
                 life: float = 8.0, spread: float = 1.5, emission: float = 8.0, particle_scale: float = 2.5,
                 alpha: float = 10.0, shade: float = 0.9, event: int = None, point: dict = None,
                 stun_pe: bytes = None) -> bytes:
    """The barrier wall script: a wall that takes a veil token (VeilNet.dll) becomes
    UMBRAL VEIL, on every machine. With `point` (charge_up_time, stun_duration, and
    optionally fx, scale, event) and the stun mine's script, a wall that takes a point
    token goes off as POINT's stun field instead."""
    event = VEIL_EVENT if event is None else event
    if not 1 <= count <= 16:
        raise ValueError("count must be 1..16")
    pe, det = PE(wall_pe), PE(det_pe)
    if any(s[1] == VEIL.rstrip(b"\0") for s in pe.sections()):
        raise ValueError("wall script already patched")
    if pe.read(WALL_SHOW, 5) != SHOW_ON or pe.read(WALL_PHYS, 8) != WALL_PHYS_OLD \
            or pe.read(WALL_SHOW_NODE, 6) != WALL_SHOW_NODE_OLD \
            or pe.read(WALL_BIND_CALL, 5) != b"\xe8" + rel32(WALL_BIND_CALL + 5, WALL_BIND_TARGET) \
            or pe.read(WALL_GLOBAL_LEN_FN, 6) != b"\xb8" + struct.pack("<I", GLOBAL_LEN) + b"\xc3":
        raise ValueError("unexpected wall script build")

    blob, fixups = bytearray(), []
    spn = transplant(det, SPAWN_PARTICLE, blob, fixups)
    exp = transplant(PE(stun_pe), ACTIVATE_EXPLOSION, blob, fixups) if point else {}
    # POINT's sound: the detonator's PLAYSOUNDNODE (a temporary emitter, the standard sound
    # component, as the translocator's), not the wall's own -- through the wall's sound
    # component it came out muffled to a fizzle
    psnd = transplant(det, PLAY_SOUND, blob, fixups) if point else {}
    blob += bytes(-len(blob) % 16)
    ring_off = len(blob)
    blob += ring_offsets(count, spread)
    parts = {}
    sizes = {"bind": 64, "decide": 1024, "show": 64, "spawn": 512, "sound": 128, "phys": 96,
             "gate_show": 256, "gate_phys": 256, "renew": 128, "renew_phys": 128,
             "phys_flag": 96, "phys_tramp": 16, "phys_off": 48}
    if point:
        sizes.update({"bind": 96, "phys": 192, "point": 384, "point_spawn": 512, "point_charge": 512, "point_boom": 96,
                      "point_sound": 192, "d_charge": 112, "d_burst": 112, "d_boom": 112,
                      "d_sound": 128, "show_disp": 96, "show_tramp": 16, "mute": 48, "snd_tramp": 16,
                      "events": 4 * len(ARC_EVENTS) + 4})
    for name, size in sizes.items():
        blob += bytes(-len(blob) % 16)
        parts[name] = len(blob)
        blob += bytes(size)
    va = add_section(pe, VEIL, len(blob))
    for d, t in fixups:
        blob[d:d + 4] = rel32(va + d + 4, va + t)
    at = {k: va + o for k, o in parts.items()}

    def put(name, code):
        if len(code) > sizes[name]:
            raise ValueError(f"{name} stub too long")
        blob[parts[name]:parts[name] + len(code)] = code

    # Bind: the wall's own call, then the particle node's Bind. rdi = setup_bindings'
    # table: nodes bind with ([rdi], [rdi+10h]).
    b = bytearray(bytes.fromhex("4883ec28 e8") + rel32(at["bind"] + 9, WALL_BIND_TARGET))
    for bind in [spn["bind"]] + ([exp["bind"], psnd["bind"]] if point else []):
        b += bytes.fromhex("488b5710 488b0f e8") + rel32(at["bind"] + len(b) + 12, va + bind)
    b += bytes.fromhex("4883c428 c3")
    put("bind", bytes(b))
    put("decide", decide_code(bool(point)))
    pre = SHOW_PRE + bytes.fromhex("ba01000000")                       # edx = 1: decide for good
    # al = show: unless veil (1) or point (3), i.e. unless decide is odd
    post = bytes.fromhex("a801 0f94c0") + SHOW_POST[2:]
    s = pre + b"\xe8" + rel32(at["show"] + len(pre) + 5, at["decide"]) + post
    put("show", s)
    # The EnablePhysics node's on flag is decided the same way (WALL_PHYS_FLAG): off for a
    # veil / POINT wall. Those walls also run the node once (phys_off, on their first
    # run), so a pooled wall that was a solid barrier in an earlier life does not keep
    # its collision -- the floating invisible collision.
    s = pre + b"\xe8" + rel32(at["phys_flag"] + len(pre) + 5, at["decide"]) + post
    put("phys_flag", s)
    put("phys_tramp", WALL_PHYS_OLD + b"\xe9" + rel32(at["phys_tramp"] + len(WALL_PHYS_OLD) + 5, WALL_PHYS + 8))
    o = bytearray(bytes.fromhex("53 4883ec20 4889cb 4889d9 e8"))
    o += rel32(at["phys_off"] + len(o) + 4, at["phys_tramp"])
    o += bytes.fromhex("48c7431800000000 4883c420 5b c3")
    put("phys_off", bytes(o))
    floats = {EMISSION_RATE: emission, LIFE: life, ALPHA: alpha, COLOR_R: shade, COLOR_G: shade, COLOR_B: shade}
    floats.update({o: scale for o in SCALE})
    floats.update({o: particle_scale for o in PARTICLE_SCALE})
    put("spawn", spawn_stub(at["spawn"], va + spn["ctor"], va + spn["exec"], va + ring_off, count, floats))
    # past the mute (point builds), which silences the veil wall's barrier sounds
    put("sound", sound_stub(at["sound"], WALL_SOUND_CTOR, at["snd_tramp"] if point else WALL_SOUND_EXEC, event))
    # The node runs again each frame while its EnablePhysics / sound is still busy
    # (ctx+18h != 0): decide again, without a record, and spawn no more clouds.
    p = bytearray(bytes.fromhex("53 4883ec20 4889cb ba02000000 48837b1800 7402 31d2 e8"))  # edx = 2 (for good) / 0
    p += rel32(at["phys"] + len(p) + 4, at["decide"])
    if point:
        p += bytes.fromhex("3c03 0f84")                                     # decide == 3: point
        to_point = len(p)
        p += bytes(4)
    p += bytes.fromhex("3c01 74")                                           # decide == 1: veil
    jnz = len(p)
    p += b"\0"
    p += bytes.fromhex("4889d9 4883c420 5b 4989e3 53 4883ec50 e9")         # not veil: EnablePhysics as before
    p += rel32(at["phys"] + len(p) + 4, WALL_PHYS + 8)
    p[jnz] = len(p) - (jnz + 1)
    # veil: clouds (first run), then the sound. The particle node's Execute leaves its
    # engine state in ctx+18h; PlaySound must start from 0 or it takes the particle
    # node's data for its own and crashes, so the state is reset in between.
    p += bytes.fromhex("48837b1800 7518 4889d9 e8")
    p += rel32(at["phys"] + len(p) + 4, at["phys_off"])                     # collision off
    p += bytes.fromhex("4889d9 e8")
    p += rel32(at["phys"] + len(p) + 4, at["spawn"])
    p += bytes.fromhex("48c7431800000000")                                  # mov qword [rbx+18h], 0
    p += bytes.fromhex("4889d9 4883c420 5b e9")
    p += rel32(at["phys"] + len(p) + 4, at["sound"])
    if point:
        # POINT goes off from the ShowModel node, which runs as the wall appears. Where
        # that node never starts it (the headless server: no stun there, so nobody was
        # stunned), the EnablePhysics node does: it carries on a POINT it is running
        # (ctx+18h busy) or starts one not started yet (+15Ch = 0), else just finishes.
        # Whichever node sees the charge-up end first fires; the other then finishes.
        skip = len(p)
        p += bytes.fromhex("48837b1800 7508 4889d9 e8")                     # first run: collision off
        p += rel32(at["phys"] + len(p) + 4, at["phys_off"])
        p += bytes.fromhex("48837b1800 0f85")
        busy = len(p)
        p += bytes(4)
        p += bytes.fromhex("488b03 488b4068 83b85c01000000 0f84")
        fresh = len(p)
        p += bytes(4)
        p += bytes.fromhex("31c0 4883c420 5b c3")
        for j in (busy, fresh):
            p[j:j + 4] = rel32(at["phys"] + j + 4, at["point"])
        p[to_point:to_point + 4] = struct.pack("<i", skip - (to_point + 4))
        put("point", point_block(at["point"], int(point["charge_up_time"] * 1e7), at["d_burst"],
                                 at["d_boom"], at["d_sound"], at["d_charge"]))
        put("d_charge", defer_stub(at["d_charge"], at["point_charge"], FX_CHARGE))
        put("d_burst", defer_stub(at["d_burst"], at["point_spawn"], FX_BURST))
        put("d_boom", defer_stub(at["d_boom"], at["point_boom"], FX_BOOM))
        put("d_sound", defer_stub(at["d_sound"], at["point_sound"], FX_SOUND, tail=True))
        put("show_tramp", WALL_SHOW_NODE_OLD + b"\xe9" + rel32(at["show_tramp"] + 11, WALL_SHOW_NODE + 6))
        put("show_disp", show_dispatch(at["show_disp"], at["decide"], at["show_tramp"], at["point"]))
        put("mute", mute_stub(at["mute"]))
        put("snd_tramp", WALL_SOUND_ENTRY + b"\xe9" + rel32(at["snd_tramp"] + 10,
                                                          WALL_SOUND_EXEC + len(WALL_SOUND_ENTRY)))
        fx_scale = point.get("scale", 2.0)
        pf = {EMISSION_RATE: 1.0, LIFE: point.get("life", 1.0), ALPHA: 1.0, COLOR_R: 1.0, COLOR_G: 1.0,
              COLOR_B: 1.0}
        pf.update({o: fx_scale for o in SCALE})
        pf.update({o: fx_scale for o in PARTICLE_SCALE})
        put("point_spawn", spawn_stub(at["point_spawn"], va + spn["ctor"], va + spn["exec"], va + ring_off, 1,
                                      pf, asset=point.get("fx", POINT_FX), duration=point.get("time", 2.5)))
        # the charge-up indicator (POINT_CHARGE_FX), at the stun mine's own size
        # (the burst alone was over well before the charge-up: its particles live x4)
        cf = {EMISSION_RATE: 1.0, LIFE: point.get("charge_life", 4.0), ALPHA: 1.0, COLOR_R: 1.0, COLOR_G: 1.0,
              COLOR_B: 1.0}
        cf.update({o: point.get("charge_scale", 1.0) for o in SCALE})
        cf.update({o: 1.0 for o in PARTICLE_SCALE})
        put("point_charge", spawn_stub(at["point_charge"], va + spn["ctor"], va + spn["exec"], va + ring_off, 1,
                                       cf, asset=POINT_CHARGE_FX, duration=point["charge_up_time"]))
        put("point_boom", explosion_stub(at["point_boom"], va + exp["ctor"], va + exp["exec"], STUN_EXPLOSION,
                                         point["stun_duration"]))
        if point.get("preview"):
            put("events", b"".join(struct.pack("<I", e) for e in PREVIEW_EVENTS))
            put("point_sound", preview_sound_stub(at["point_sound"], WALL_SOUND_CTOR, at["snd_tramp"],
                                                  at["events"], len(PREVIEW_EVENTS)))
        else:
            put("point_sound", sound_stub(at["point_sound"], va + psnd["ctor"], va + psnd["exec"],
                                          point.get("event", POINT_EVENT)))
    put("phys", bytes(p))

    # Both spawn nodes first wait a moment for a token (see GATE).
    if point:
        put("gate_show", gate_stub(at["gate_show"], at["decide"], 1, at["show_disp"]))
    else:
        put("gate_show", gate_stub(at["gate_show"], at["decide"], 1, WALL_SHOW_NODE + 6, WALL_SHOW_NODE_OLD))
    put("gate_phys", gate_stub(at["gate_phys"], at["decide"], 2, at["phys"]))
    put("renew", renew_stub(at["renew"], at["gate_show"]))             # a pooled wall's new life
    put("renew_phys", renew_stub(at["renew_phys"], at["gate_phys"], RENEW_AFTER_PHYS))

    pe.write(va, bytes(blob))
    pe.write(WALL_GLOBAL_LEN_FN, b"\xb8" + struct.pack("<I", GLOBAL_LEN + 8) + b"\xc3")   # + the decision
    pe.write(WALL_BIND_CALL, b"\xe8" + rel32(WALL_BIND_CALL + 5, at["bind"]))
    pe.write(WALL_SHOW, b"\xe8" + rel32(WALL_SHOW + 5, at["show"]))
    pe.write(WALL_SHOW_NODE, b"\xe9" + rel32(WALL_SHOW_NODE + 5, at["renew"]) + b"\x90")
    pe.write(WALL_PHYS, b"\xe9" + rel32(WALL_PHYS + 5, at["renew_phys"]) + b"\x90" * 3)
    if pe.read(WALL_PHYS_FLAG, 5) != SHOW_ON:
        raise ValueError("unexpected EnablePhysics node: wrong wall script build")
    pe.write(WALL_PHYS_FLAG, b"\xe8" + rel32(WALL_PHYS_FLAG + 5, at["phys_flag"]))
    if point:
        if pe.read(WALL_SOUND_EXEC, 5) != WALL_SOUND_ENTRY:
            raise ValueError("unexpected wall PLAYSOUNDNODE::Execute")
        pe.write(WALL_SOUND_EXEC, b"\xe9" + rel32(WALL_SOUND_EXEC + 5, at["mute"]))
    return bytes(pe.d)
