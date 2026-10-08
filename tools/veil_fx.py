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


def spawn_stub(at: int, ctor: int, execute: int, ring: int, count: int, floats: dict) -> bytes:
    """execute_node replacement: `count` SPAWNPARTICLEEFFECTNODEs, each built at rsp+0x20."""
    f = lambda v: struct.pack("<f", v)
    b = bytearray(bytes.fromhex("53 56 57 4881ec00010000 4889cb 31f6"))  # push rbx/rsi/rdi; sub rsp,100h; rbx=rcx; esi=0
    b += bytes.fromhex("80bbdb00000000 740c 48c7c0ffffffff e9")      # cmp byte [rbx+0dbh],0; je L; mov rax,-1; jmp done
    jmp_done = len(b)
    b += bytes(4)
    loop = len(b)
    b += bytes.fromhex("488d4c2420 e8") + rel32(at + len(b) + 10, ctor)  # L: lea rcx,[rsp+20h]; call ctor
    b += b"\x48\xb8" + struct.pack("<Q", DET_FX) + bytes.fromhex("4889442428")       # node+08 asset
    b += b"\x48\xb8" + struct.pack("<Q", SELF) + bytes.fromhex("4889442440")         # node+20 actor = self
    b += bytes.fromhex("c644243100 c644243801 66c74424600101")       # enableduration 0, killatend 1, refpoint+leavebehind
    for off, value in sorted(floats.items()):                        # mov dword [rsp+20h+off], value
        b += bytes.fromhex("c78424") + struct.pack("<I", 0x20 + off) + f(value)
    b += bytes.fromhex("488d05") + rel32(at + len(b) + 7, ring)      # lea rax,[ring]
    b += bytes.fromhex("488d3c76")                                   # lea rdi,[rsi+rsi*2]
    for k, disp in enumerate((0xB0, 0xB4, 0xB8)):                    # node+90..98 offset = ring[i]
        b += bytes.fromhex("8b54b8") + bytes([4 * k]) + bytes.fromhex("899424") + struct.pack("<I", disp)
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
