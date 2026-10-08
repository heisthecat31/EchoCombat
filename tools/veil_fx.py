"""UMBRAL VEIL's smoke: the smoke script spawns detonator smoke clouds instead of a wall.

The smoke script starts as a copy of the barrier script (fix_smoke.py), whose
graph runs, on use, ... -> custom param -> R15NetPooledActorCreate (node
6fb98e2c, the wall) -> ... This module makes that node spawn `count`
detonator explosion smoke effects (particle effect c9eb32d35038eb4c) around
the player instead, larger and longer-lived than the detonator's, left behind
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
  `scale` and `life` (particle lifetime multiplier), then runs Execute.
"""

from __future__ import annotations

import hashlib
import math
import struct

from fix_smoke import PE, rel32, u16, u32

DET_FX = 0xC9EB32D35038EB4C            # the detonator's explosion smoke
SELF = 0xC8C33E48297612B6              # CSymbol64("self")

# --- detonator script (190ed14fe3da5ed1), checked by SHA-256 ------------------
DET_CTOR = (0x2710, 274, "95f2690cac553ad4eda87a2de734a912fc1567c33456d91d72d763ae93809298")
DET_EXEC = (0x2830, 1082, "6b8138e8b0d699133111cdaae35452b8c5e8484bb184496e5f0c75875b016ce7")
DET_BIND = (0x20D0, 1600, "c2335899e5939e6f9abfd2cc1785e3a7f535019c0fc3aaf57d02f51c9d06b091")
#: Offsets, in each function, of every rip-relative disp32 (always the last 4
#: bytes of its instruction). Targets are .data slots or .rdata name strings.
EXEC_DISPS = [
    0x1e, 0x36, 0x47, 0x4d, 0x5e, 0x64, 0x75, 0x7b, 0x8c, 0x92, 0xa3, 0xa9, 0xba, 0xc0,
    0xd1, 0xd7, 0xe8, 0xee, 0xff, 0x105, 0x116, 0x11c, 0x12d, 0x133, 0x144, 0x14a, 0x15b,
    0x161, 0x172, 0x178, 0x189, 0x18f, 0x1a0, 0x1a6, 0x1b7, 0x1bd, 0x1ce, 0x1d4, 0x1e5,
    0x1eb, 0x1fc, 0x206, 0x213, 0x219, 0x22a, 0x230, 0x241, 0x247, 0x258, 0x25e, 0x26f,
    0x275, 0x286, 0x28c, 0x29d, 0x2a3, 0x2b4, 0x2ba, 0x2ce, 0x2d4, 0x2e8, 0x2ee, 0x302,
    0x308, 0x31c, 0x322, 0x336, 0x33c, 0x350, 0x356, 0x36a, 0x370, 0x384, 0x38a, 0x39e,
    0x3a4, 0x3b8, 0x3be, 0x3d2, 0x3d8, 0x3ec, 0x3f2, 0x406, 0x40c, 0x420, 0x436]
BIND_DISPS = [
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

# --- barrier script (b87ba2039b049d5e) ----------------------------------------
BIND_CALL = 0x3F00                     # call R15NETPOOLEDACTORCREATENODE::Bind
CREATE_BIND = 0x2450
CREATE_NODE = 0x69F0                   # execute_node_6fb98e2c
CREATE_NODE_OLD = bytes.fromhex("48895c2408")   # mov [rsp+8], rbx

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
    rva, size, sha = spec
    code = det.read(rva, size)
    if hashlib.sha256(code).hexdigest() != sha:
        raise ValueError("detonator particle node differs: wrong detonator script build")
    return code


def c_string(pe: PE, rva: int) -> bytes:
    out = bytearray()
    while True:
        c = pe.read(rva + len(out), 1)
        if c == b"\0":
            return bytes(out) + b"\0"
        out += c


def spawn_stub(at: int, ctor: int, execute: int, ring: int, count: int, scale: float, life: float) -> bytes:
    """execute_node replacement: `count` SPAWNPARTICLEEFFECTNODEs, node at rsp+0x20."""
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
    b += bytes.fromhex("c7442468") + f(life)                         # node+48 particlelifescale
    for disp in (0xC8, 0xCC, 0xD0):                                  # node+a8..b0 scale
        b += bytes.fromhex("c78424") + struct.pack("<I", disp) + f(scale)
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


def ring_offsets(count: int, spread: float) -> bytes:
    """One cloud on the player, the rest evenly on a horizontal ring around them."""
    pts = [(0.0, 0.0, 0.0)]
    for i in range(count - 1):
        a = 2 * math.pi * i / (count - 1)
        pts.append((spread * math.sin(a), 0.0, spread * math.cos(a)))
    return b"".join(struct.pack("<3f", *p) for p in pts)


def add_smoke_fx(barrier_pe: bytes, det_pe: bytes, count: int = 3, scale: float = 6.0,
                 life: float = 6.0, spread: float = 1.5) -> bytes:
    if not 1 <= count <= 16:
        raise ValueError("count must be 1..16")
    pe, det = PE(barrier_pe), PE(det_pe)
    if any(s[1] == VEIL.rstrip(b"\0") for s in pe.sections()):
        raise ValueError("smoke script already has the veil section")
    call = pe.read(BIND_CALL, 5)
    if call != b"\xe8" + rel32(BIND_CALL + 5, CREATE_BIND) or pe.read(CREATE_NODE, 5) != CREATE_NODE_OLD:
        raise ValueError("unexpected barrier script build")
    ctor, execute, bind = (det_function(det, s) for s in (DET_CTOR, DET_EXEC, DET_BIND))

    # Classify every target: .data slot (statics) or .rdata string (names).
    _, _, dvs, dva, _, _ = det.section(b".data")
    targets = {}
    for (rva, _, _), code, disps in ((DET_EXEC, execute, EXEC_DISPS), (DET_BIND, bind, BIND_DISPS)):
        for d in disps:
            targets.setdefault(rva + d + 4 + struct.unpack_from("<i", code, d)[0], None)
    slots = sorted(t for t in targets if dva <= t < dva + dvs)
    names = sorted(t for t in targets if not dva <= t < dva + dvs)
    if len(slots) != 85 or len(names) != 42:
        raise ValueError(f"unexpected particle node references ({len(slots)} slots, {len(names)} names)")

    # Lay out .veil: slots, names, ring, code.
    blob = bytearray(8 * len(slots))
    for i, t in enumerate(slots):
        targets[t] = i * 8
    for t in names:
        s = c_string(det, t)
        targets[t] = len(blob)
        blob += s + bytes(-len(s) % 8)
    ring_off = len(blob)
    blob += ring_offsets(count, spread)
    funcs = {}
    for key, code in (("ctor", ctor), ("exec", execute), ("bind", bind)):
        blob += bytes(-len(blob) % 16)
        funcs[key] = len(blob)
        blob += code
    blob += bytes(-len(blob) % 16)
    bind_stub_off = len(blob)
    blob += bytes(32)                        # placeholder, filled below
    blob += bytes(-len(blob) % 16)
    spawn_off = len(blob)
    blob += bytes(256)                       # placeholder, filled below
    va = add_section(pe, VEIL, len(blob))

    # Re-aim the copied code at the new slots and names.
    for (rva, _, _), key, disps in ((DET_EXEC, "exec", EXEC_DISPS), (DET_BIND, "bind", BIND_DISPS)):
        base = funcs[key]
        for d in disps:
            old = rva + d + 4 + struct.unpack_from("<i", blob, base + d)[0]
            blob[base + d:base + d + 4] = rel32(va + base + d + 4, va + targets[old])

    # Bind stub: the create node's Bind, then the particle node's (rdi = binding table).
    at = va + bind_stub_off
    stub = bytearray(bytes.fromhex("4883ec28 e8") + rel32(at + 9, CREATE_BIND))
    stub += bytes.fromhex("488b5710 488b0f e8") + rel32(at + len(stub) + 12, va + funcs["bind"])
    stub += bytes.fromhex("4883c428 c3")
    blob[bind_stub_off:bind_stub_off + len(stub)] = stub

    spawn = spawn_stub(va + spawn_off, va + funcs["ctor"], va + funcs["exec"], va + ring_off, count, scale, life)
    if len(spawn) > 256:
        raise ValueError("spawn stub too long")
    blob[spawn_off:spawn_off + len(spawn)] = spawn

    pe.write(va, bytes(blob))
    pe.write(BIND_CALL, b"\xe8" + rel32(BIND_CALL + 5, at))
    pe.write(CREATE_NODE, b"\xe9" + rel32(CREATE_NODE + 5, va + spawn_off))
    return bytes(pe.d)
