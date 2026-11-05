"""Private Combat matches: the RULES page's starting scores become capture-point points.

The podium terminal's RULES page (unlocked for Combat by fix_rules_terminal.py) sets a
starting score per team. Combat's game-mode script `6fa8cc9cd721a563` already takes
those -/+ presses: it keeps the values in its variables blue_point_score (+F0h of its
data) and red_point_score (+D0h) and publishes them as the netvars
net_match_settings_blue_score / _red_score. But the capture point script
`b7d10bcffcb2a780` keeps each team's points itself (blueteamcharge +F8h,
orangeteamcharge +F0h, floats; required_charge = points_to_win, 75) and starts every
round from 0, so the setting did nothing.

The two scripts are joined through a mailbox: spare bytes past echovr.exe's .data
(the RULES mailbox: the page end - 140h, deploy_and_launch.RULES_MAILBOX_BELOW_VEIL),
reached through the PEB's image base as fix_smoke's veil stamp does.

* `6fa8`: each of its six nodes that publishes a starting score (on every -/+ press
  and at match start) first copies blue_point_score to mailbox+0 and red_point_score
  to mailbox+4, as floats.
* `b7d10`: its variable initializer (every variable to its default, run when the
  script is set up for a round) and its two nodes that zero a team's points load that
  team's starting points from the mailbox instead. Two copies of the same zeroing,
  inlined in its node dispatcher, are sent to those nodes. Its two nodes that zero the
  HUD's score netvars (netBlue/OrangeTeamChargeProgress) at round start publish the
  starting points instead, so the score shows them before a team first charges.

A mailbox of zeros is the stock behaviour. On a server without these scripts nothing
changes.

    python tools/fix_capture_points.py --src <extract root> --out <stage dir> --mailbox <rva>
"""

from __future__ import annotations

import argparse
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fix_smoke import PE, rel32  # noqa: E402

SCRIPTS = "6eace9f64204fd0"
MODE_SCRIPT = "6fa8cc9cd721a563"       # Combat game mode: keeps the RULES values
POINT_SCRIPT = "b7d10bcffcb2a780"      # capture point: keeps each team's points

#: 6fa8 nodes that set net_match_settings_blue_score / _red_score; each starts
#: with sub rsp, 0A8h (7 bytes)
PUBLISH_NODES = (0xCB60, 0xCCA0, 0xD480, 0x16380, 0x16A60, 0x184A0)
PUBLISH_PROLOGUE = bytes.fromhex("4881eca8000000")
BLUE_VAR, RED_VAR = 0xF0, 0xD0         # blue_point_score, red_point_score (int32)

#: The RULES page's time rows (the podium terminal's round minutes / seconds) drive 6fa8's
#: game_timer (+A8h), Combat's own match clock, as one MM:SS value. In Combat that value
#: is T = point unlock * 60 + capture time instead (mailbox+8, a float; 0 = unset): the
#: top row is the point's unlock time (capture_point_lock_time), the second row its time
#: to capture. Every read of game_timer for the page (cvttss2si reg, [r+A8h], in the
#: handlers, their helpers and the publishers) reads T (DEFAULT_TOTAL while unset); every
#: handler write (movss [r+A8h], xmm0) writes T and also the capture time, T mod 60, as a
#: float at mailbox+0Ch for VeilNet (0 = the map's own, or, while T is set, an instant
#: capture: VeilNet tells the two apart). The clock is never touched.
TOTAL_SLOT, CAPTURE_SLOT = 8, 0xC
#: both capture point maps' (dyson, combustion) capture_point_lock_time and time_to_capture
DEFAULT_UNLOCK, DEFAULT_CAPTURE = 45, 4
DEFAULT_TOTAL = DEFAULT_UNLOCK * 60 + DEFAULT_CAPTURE
#: (rva, instruction bytes, destination register)
TIME_READS = ((0xFF89, "f3450f2c81a8000000", "r8d"), (0x10A59, "f3450f2c81a8000000", "r8d"),
              (0x161DB, "f30f2c8aa8000000", "ecx"), (0x13E7B, "f30f2c8aa8000000", "ecx"),
              (0x128DB, "f30f2c8aa8000000", "ecx"), (0x1200B, "f30f2c8aa8000000", "ecx"),
              (0x160CB, "f30f2c8aa8000000", "ecx"),
              (0x28964, "f3440f2c89a8000000", "r9d"), (0x23274, "f3440f2c89a8000000", "r9d"))  # minutes helpers
TIME_WRITES = ((0xFFDA, "f3410f1181a8000000"), (0x10AA9, "f3410f1181a8000000"),   # seconds +/-
               (0x14FDA, "f30f1181a8000000"), (0xFA8A, "f30f1181a8000000"))        # minutes +/-
CLOCK_WRITES = ()

#: b7d10 writes of capture_point_lock_time (+ECh): from the map's JSON (node 0x18000F960)
#: and node 0x180016910: movss [rcx+ECh], xmm0 (rcx = its data). They store T / 60 while
#: T is set.
LOCK_WRITES = (0xF98A, 0x16961)
LOCK_WRITE = bytes.fromhex("f30f1181ec000000")
#: Its JSON loader sets capture_point_lock_time through the script's set-variable-by-name
#: functions instead: mov [rcx+ECh], eax; mov eax, 1; ret (12 bytes, rcx = its data).
#: Those too store T / 60 (as a float) while T is set.
SETTER_LOCK_WRITES = (0x17ECC, 0x183EE)
SETTER_LOCK_WRITE = bytes.fromhex("8981ec000000b801000000c3")
#: More writers exist (a bulk variable loader among them), so every READ of it uses
#: T / 60 while T is set as well: the countdown (lock time - elapsed) and its neighbour
#:   movss xmm0, [r8+ECh]                                   (rva)
LOCK_READS_XMM = (0x1009B, 0x1F193)
LOCK_READ_XMM = bytes.fromhex("f3410f1080ec000000")
#: and the copies out (the state block the script packs, its get-by-name):
#:   mov dest, [base+ECh]                                   (rva, bytes, dest)
LOCK_READS_REG = ((0x4CF1, "8b81ec000000", "eax"), (0x91D8, "8b88ec000000", "ecx"),
                  (0x179E2, "8b88ec000000", "ecx"))

#: b7d10 nodes zeroing a team's points: (rva, charge offset, mailbox slot)
#:   mov rax,[rcx]; mov rcx,[rax+68h]; xor eax,eax; mov dword [rcx+off], 0; ret
RESET_NODES = ((0x14780, 0xF8, 0), (0x14E90, 0xF0, 4))   # blueteamcharge, orangeteamcharge
#: the same zeroing inlined in the dispatcher: (rva, charge offset)
#:   mov rax,[rcx]; mov rcx,[rax+68h]; xor eax,eax; mov [rcx+off], eax; add rsp,28h; ret
INLINE_RESETS = ((0xB9C1, 0xF8), (0xB8DE, 0xF0))
#: the script's variable initializer (every variable to its default; it runs when the
#: script is set up for a round) writes both charges as 0 from r8d:
#:   mov rax,[rcx+68h]; mov [rax+off], r8d          (11 bytes): (rva, charge offset, slot)
INIT_WRITES = ((0x1CE53, 0xF0, 4), (0x1CE69, 0xF8, 0))


#: nodes that zero the HUD's score netvars (netBlueTeamChargeProgress /
#: netOrangeTeamChargeProgress: points / 100, which the HUD shows as a percentage, so
#: a full capture of 75 points shows 75%) at round start; each starts
#:   sub rsp, 58h; xorps xmm0, xmm0   and sets the netvar from xmm0: (rva, mailbox slot)
PROGRESS_RESETS = ((0xFA40, 0), (0x11180, 4))
PROGRESS_PROLOGUE = bytes.fromhex("4883ec580f57c0")
HUNDRED = struct.pack("<f", 100.0)


def progress_cave(mailbox: int, slot: int, back: int, at: int) -> bytes:
    """xmm0 = mailbox[slot] / 100 instead of 0 (rax is overwritten right after)."""
    code = (IMAGE_BASE
            + bytes.fromhex("f30f1080") + struct.pack("<I", mailbox + slot)    # movss xmm0,[rax+mb+slot]
            + b"\xb8" + HUNDRED                                        # mov eax, 100.0f
            + bytes.fromhex("660f6ec8")                                # movd xmm1, eax
            + bytes.fromhex("f30f5ec1")                                # divss xmm0, xmm1
            + bytes.fromhex("4883ec58"))                               # sub rsp, 58h
    return code + b"\xe9" + rel32(at + len(code) + 5, back)


def init_write(off: int) -> bytes:
    return bytes.fromhex("488b41684489 80".replace(" ", "")) + struct.pack("<I", off)


def reset_node(off: int) -> bytes:
    return bytes.fromhex("488b01488b486833c0c781") + struct.pack("<I", off) + bytes(4) + b"\xc3"


def inline_reset(off: int) -> bytes:
    return bytes.fromhex("488b01488b486833c08981") + struct.pack("<I", off) + bytes.fromhex("4883c428c3")


#: mov rax, gs:[60h] (the PEB); mov rax, [rax+10h] (echovr.exe's image base)
IMAGE_BASE = bytes.fromhex("6548a16000000000000000") + bytes.fromhex("488b4010")


def publish_cave(mailbox: int, back: int, at: int) -> bytes:
    """rcx = node ctx (node entry: xmm0/xmm1 carry nothing). mailbox = {float(blue_point_score),
    float(red_point_score)}; then the node's own sub rsp, 0A8h and back to the node."""
    code = (bytes.fromhex("50")                                       # push rax
            + bytes.fromhex("488b01488b4068")                         # mov rax,[rcx]; mov rax,[rax+68h]
            + bytes.fromhex("f30f2a80") + struct.pack("<I", BLUE_VAR)  # cvtsi2ss xmm0,[rax+blue]
            + bytes.fromhex("f30f2a88") + struct.pack("<I", RED_VAR)   # cvtsi2ss xmm1,[rax+red]
            + IMAGE_BASE
            + bytes.fromhex("f30f1180") + struct.pack("<I", mailbox)       # movss [rax+mb], xmm0
            + bytes.fromhex("f30f1188") + struct.pack("<I", mailbox + 4)   # movss [rax+mb+4], xmm1
            + bytes.fromhex("58")                                     # pop rax
            + PUBLISH_PROLOGUE)
    return code + b"\xe9" + rel32(at + len(code) + 5, back)


def time_read_cave(mailbox: int, reg: str, back: int, at: int) -> bytes:
    """reg = int(T), or DEFAULT_TOTAL while unset; flags and rax kept."""
    mb = struct.pack("<I", mailbox + TOTAL_SLOT)
    total = struct.pack("<I", DEFAULT_TOTAL)
    if reg == "r8d":
        default = bytes.fromhex("41b8") + total                             # mov r8d, imm
        load = bytes.fromhex("f3440f2c80") + mb                             # cvttss2si r8d,[rax+mb]
    elif reg == "r9d":
        default = bytes.fromhex("41b9") + total                             # mov r9d, imm
        load = bytes.fromhex("f3440f2c88") + mb                             # cvttss2si r9d,[rax+mb]
    else:
        default = b"\xb9" + total                                           # mov ecx, imm
        load = bytes.fromhex("f30f2c88") + mb                               # cvttss2si ecx,[rax+mb]
    code = (bytes.fromhex("9c50") + IMAGE_BASE                              # pushfq; push rax
            + bytes.fromhex("83b8") + mb + b"\x00"                           # cmp dword [rax+mb], 0
            + bytes([0x7F, len(default) + 2])                                # jg load
            + default + bytes([0xEB, len(load)])                             # jmp done
            + load
            + bytes.fromhex("589d"))                                         # done: pop rax; popfq
    return code + b"\xe9" + rel32(at + len(code) + 5, back)


def time_write_cave(mailbox: int, back: int, at: int) -> bytes:
    """T = xmm0, capture time = float(T mod 60) (xmm0 is dead after the node's write:
    it returns next); flags, rax, rcx, rdx kept."""
    code = (bytes.fromhex("9c505251")                                       # pushfq; push rax, rdx, rcx
            + bytes.fromhex("f30f2cc0")                                     # cvttss2si eax, xmm0
            + bytes.fromhex("99b93c000000f7f9")                             # cdq; mov ecx, 60; idiv ecx
            + IMAGE_BASE
            + bytes.fromhex("f30f1180") + struct.pack("<I", mailbox + TOTAL_SLOT)     # movss [rax+T], xmm0
            + bytes.fromhex("f30f2ac2")                                     # cvtsi2ss xmm0, edx
            + bytes.fromhex("f30f1180") + struct.pack("<I", mailbox + CAPTURE_SLOT)   # movss [rax+capture], xmm0
            + bytes.fromhex("595a589d"))                                    # pop rcx, rdx, rax; popfq
    return code + b"\xe9" + rel32(at + len(code) + 5, back)


UNLOCK = bytes.fromhex("99b93c000000f7f9")            # cdq; mov ecx, 60; idiv ecx  (eax = T / 60)


#: PAUSE (VeilNet, mailbox +2Eh: 1 paused, 2 resuming) freezes the unlock countdown. The countdown
#: node (0x10030) computes, every frame, xmm1 = elapsed = now - start (+F4h), xmm0 = lock time
#: (this read), then [+DCh] = xmm0 - xmm1, unless [ctx(r10)+DBh] is set (it returns early). While
#: paused the cave moves start so elapsed = lock - the last countdown: the countdown stands still
#: on this machine (server and clients alike: the unlock VO is client-side), and an already
#: unlocked point just keeps its negative countdown (nothing re-locks).
PAUSED = 0x2E
FREEZE_SITE = 0x1009B
START, COUNTDOWN = 0xF4, 0xDC


def freeze_tail(mailbox: int) -> bytes:
    """xmm0 = lock time, xmm1 = elapsed, r8 = data, r10 = ctx; all else kept (flags too)."""
    body = (bytes.fromhex("4883ec10f30f7f1424")                         # sub rsp,16; movdqu [rsp],xmm2
            + bytes.fromhex("0f28d1")                                   # movaps xmm2, xmm1   (elapsed)
            + bytes.fromhex("f3410f5890") + struct.pack("<I", START)    # addss xmm2,[r8+F4]  (now)
            + bytes.fromhex("0f28c8")                                   # movaps xmm1, xmm0   (lock)
            + bytes.fromhex("f3410f5c88") + struct.pack("<I", COUNTDOWN)  # subss xmm1,[r8+DC]
            + bytes.fromhex("f30f5cd1")                                 # subss xmm2, xmm1   (new start)
            + bytes.fromhex("f3410f1190") + struct.pack("<I", START)    # movss [r8+F4], xmm2
            + bytes.fromhex("f30f6f14244883c410"))                      # movdqu xmm2,[rsp]; add rsp,16
    code = bytes.fromhex("9c50") + IMAGE_BASE                           # pushfq; push rax
    code += bytes.fromhex("80b8") + struct.pack("<I", mailbox + PAUSED) + b"\x00"   # cmp byte [paused], 0
    skip = bytes.fromhex("41 80 ba db 00 00 00 00".replace(" ", ""))    # cmp byte [r10+DBh], 0
    code += bytes([0x74, len(skip) + 2 + len(body)])                    # je done (running)
    code += skip + bytes([0x75, len(body)])                             # jne done (node returns early)
    code += body
    return code + bytes.fromhex("589d")                                 # done: pop rax; popfq


def lock_xmm_cave(mailbox: int, back: int, at: int, freeze: bool = False) -> bytes:
    """movss xmm0, [r8+ECh] -> xmm0 = float(T / 60) while T is set; flags, rax, rcx, rdx kept.
    With freeze, the countdown stands still while PAUSE is on (freeze_tail)."""
    head = (bytes.fromhex("9c505251") + IMAGE_BASE
            + bytes.fromhex("f30f2c80") + struct.pack("<I", mailbox + TOTAL_SLOT))     # cvttss2si eax,[rax+T]
    pops = bytes.fromhex("595a589d")
    tail = freeze_tail(mailbox) if freeze else b""
    set_ = UNLOCK + bytes.fromhex("f30f2ac0") + pops + tail             # cvtsi2ss xmm0, eax
    code = head + bytes.fromhex("85c0") + bytes([0x7E, len(set_) + 5]) + set_
    code += b"\xe9" + rel32(at + len(code) + 5, back)
    code += pops + LOCK_READ_XMM + tail
    return code + b"\xe9" + rel32(at + len(code) + 5, back)


def lock_reg_cave(mailbox: int, orig: bytes, dest: str, back: int, at: int) -> bytes:
    """mov dest, [base+ECh] -> dest = the float bits of T / 60 while T is set; every other
    register, xmm0 and the flags kept (the stack: xmm0, rcx, rdx, rax, flags)."""
    slot = {"eax": 0x20, "ecx": 0x10}[dest]
    head = (bytes.fromhex("9c505251") + bytes.fromhex("4883ec10f30f7f0424")   # sub rsp,16; movdqu [rsp],xmm0
            + IMAGE_BASE + bytes.fromhex("f30f2c80") + struct.pack("<I", mailbox + TOTAL_SLOT))
    restore = bytes.fromhex("f30f6f04244883c410595a589d")              # movdqu xmm0,[rsp]; add rsp,16; pops
    set_ = (UNLOCK + bytes.fromhex("f30f2ac0660f7ec0")                  # cvtsi2ss xmm0,eax; movd eax,xmm0
            + bytes.fromhex("894424") + bytes([slot]) + restore)        # mov [rsp+slot], eax
    code = head + bytes.fromhex("85c0") + bytes([0x7E, len(set_) + 5]) + set_
    code += b"\xe9" + rel32(at + len(code) + 5, back)
    code += restore + orig
    return code + b"\xe9" + rel32(at + len(code) + 5, back)


def setter_lock_cave(mailbox: int) -> bytes:
    """The setter's tail: [rcx+ECh] = float(T / 60) while T is set, else eax; returns 1."""
    return (bytes.fromhex("448bc8")                                         # mov r9d, eax
            + IMAGE_BASE
            + bytes.fromhex("f30f2c80") + struct.pack("<I", mailbox + TOTAL_SLOT)     # cvttss2si eax,[rax+T]
            + bytes.fromhex("85c07e13")                                     # test eax,eax; jle keep
            + bytes.fromhex("9941b83c00000041f7f8")                         # cdq; mov r8d, 60; idiv r8d
            + bytes.fromhex("f30f2ac066410f7ec1")                           # cvtsi2ss xmm0,eax; movd r9d,xmm0
            + bytes.fromhex("448989ec000000")                               # keep: mov [rcx+ECh], r9d
            + bytes.fromhex("b801000000c3"))                                # mov eax, 1; ret

def lock_cave(mailbox: int, back: int, at: int) -> bytes:
    """b7d10: xmm0 = float(T / 60) while T is set, then its own movss [rcx+ECh], xmm0."""
    code = (bytes.fromhex("9c505251") + IMAGE_BASE
            + bytes.fromhex("f30f2c80") + struct.pack("<I", mailbox + TOTAL_SLOT)     # cvttss2si eax,[rax+T]
            + bytes.fromhex("85c0") + bytes([0x7E, 0x0C])                   # test eax,eax; jle keep
            + bytes.fromhex("99b93c000000f7f9")                             # cdq; mov ecx, 60; idiv ecx
            + bytes.fromhex("f30f2ac0")                                     # cvtsi2ss xmm0, eax
            + bytes.fromhex("595a589d")                                     # keep: pop rcx, rdx, rax; popfq
            + LOCK_WRITE)
    return code + b"\xe9" + rel32(at + len(code) + 5, back)


def reset_cave(mailbox: int, off: int, slot: int) -> bytes:
    """rcx = node ctx. team points = mailbox[slot] (a float); returns 0 as the node did."""
    return (bytes.fromhex("488b01488b4868")                           # mov rax,[rcx]; mov rcx,[rax+68h]
            + IMAGE_BASE
            + bytes.fromhex("8b80") + struct.pack("<I", mailbox + slot)    # mov eax,[rax+mb+slot]
            + bytes.fromhex("8981") + struct.pack("<I", off)               # mov [rcx+off], eax
            + bytes.fromhex("31c0c3"))                                     # xor eax,eax; ret


def init_cave(mailbox: int, off: int, slot: int, back: int, at: int) -> bytes:
    """In the variable initializer (rcx = script instance, r8 = 0, rdx live): the charge
    = mailbox[slot] instead of 0; rax ends as [rcx+68h] as before."""
    code = (bytes.fromhex("52")                                       # push rdx
            + bytes.fromhex("65488b142560000000")                     # mov rdx, gs:[60h]
            + bytes.fromhex("488b5210")                               # mov rdx, [rdx+10h]
            + bytes.fromhex("8b92") + struct.pack("<I", mailbox + slot)    # mov edx,[rdx+mb+slot]
            + bytes.fromhex("488b4168")                               # mov rax,[rcx+68h]
            + bytes.fromhex("8990") + struct.pack("<I", off)               # mov [rax+off], edx
            + bytes.fromhex("5a"))                                    # pop rdx
    return code + b"\xe9" + rel32(at + len(code) + 5, back)


#: the caves are packed (6fa8's .text has 1139 bytes to grow into; they take 1088)
CAVE_ALIGN = 1


def append(pe: PE, blobs) -> list:
    """Each blob at the end of .text (16-aligned); returns their rvas."""
    _, _, vsize, va, _, _ = pe.section(b".text")
    at, rvas, out = (va + vsize + 15) & ~15, [], bytearray()
    start = at
    for b in blobs:
        rvas.append(at)
        out += b + bytes(-len(b) % CAVE_ALIGN)
        at = start + len(out)
    pe.grow_text(at - va)
    pe.write(start, bytes(out))
    return rvas


def patch_mode(pe_bytes: bytes, mailbox: int) -> tuple:
    pe = PE(pe_bytes)
    heads = [pe.read(n, 7) for n in PUBLISH_NODES]
    if all(h[0] == 0xE9 for h in heads):
        return pe_bytes, "already patched"
    if any(h != PUBLISH_PROLOGUE for h in heads):
        raise ValueError(f"{MODE_SCRIPT}: unexpected publish nodes: wrong build")
    for n, old, _ in TIME_READS:
        if pe.read(n, len(old) // 2) != bytes.fromhex(old):
            raise ValueError(f"{MODE_SCRIPT}: unexpected round time read at {n:#x}: wrong build")
    for n, old in TIME_WRITES + CLOCK_WRITES:
        if pe.read(n, len(old) // 2) != bytes.fromhex(old):
            raise ValueError(f"{MODE_SCRIPT}: unexpected round time write at {n:#x}: wrong build")
    _, _, vsize, va, _, _ = pe.section(b".text")
    at = (va + vsize + 15) & ~15
    blobs, sites = [], []                            # sites: (rva, its length)
    for n in PUBLISH_NODES:                          # each cave's size is fixed: lay out first
        blobs.append(publish_cave(mailbox, n + 7, at))
        sites.append((n, 7))
        at += len(blobs[-1]) + (-len(blobs[-1]) % CAVE_ALIGN)
    for n, old, reg in TIME_READS:
        size = len(old) // 2
        blobs.append(time_read_cave(mailbox, reg, n + size, at))
        sites.append((n, size))
        at += len(blobs[-1]) + (-len(blobs[-1]) % CAVE_ALIGN)
    for n, old in TIME_WRITES:
        size = len(old) // 2
        blobs.append(time_write_cave(mailbox, n + size, at))
        sites.append((n, size))
        at += len(blobs[-1]) + (-len(blobs[-1]) % CAVE_ALIGN)
    rvas = append(pe, blobs)
    for (n, size), cave in zip(sites, rvas):
        pe.write(n, b"\xe9" + rel32(n + 5, cave) + b"\x90" * (size - 5))
    for n, old in CLOCK_WRITES:                      # the minutes rows no longer touch the clock
        pe.write(n, b"\x90" * (len(old) // 2))
    return bytes(pe.d), (f"{len(PUBLISH_NODES)} publish nodes copy the starting scores to the mailbox; "
                         f"the page's time is unlock*60 + capture (mailbox+{TOTAL_SLOT:#x}), not the clock")


def patch_point(pe_bytes: bytes, mailbox: int) -> tuple:
    pe = PE(pe_bytes)
    if all(pe.read(n, 1) == b"\xe9" for n, _, _ in RESET_NODES):
        return pe_bytes, "already patched"
    for n, off, _ in RESET_NODES:
        if pe.read(n, 20) != reset_node(off):
            raise ValueError(f"{POINT_SCRIPT}: unexpected reset node at {n:#x}: wrong build")
    for n, off in INLINE_RESETS:
        if pe.read(n, 20) != inline_reset(off):
            raise ValueError(f"{POINT_SCRIPT}: unexpected inline reset at {n:#x}: wrong build")
    for n, off, _ in INIT_WRITES:
        if pe.read(n, 11) != init_write(off):
            raise ValueError(f"{POINT_SCRIPT}: unexpected initializer write at {n:#x}: wrong build")
    for n, _ in PROGRESS_RESETS:
        if pe.read(n, 7) != PROGRESS_PROLOGUE:
            raise ValueError(f"{POINT_SCRIPT}: unexpected score netvar reset at {n:#x}: wrong build")
    for n in SETTER_LOCK_WRITES:
        if pe.read(n, 12) != SETTER_LOCK_WRITE:
            raise ValueError(f"{POINT_SCRIPT}: unexpected lock time setter at {n:#x}: wrong build")
    for n in LOCK_READS_XMM:
        if pe.read(n, 9) != LOCK_READ_XMM:
            raise ValueError(f"{POINT_SCRIPT}: unexpected lock time read at {n:#x}: wrong build")
    for n, old, _ in LOCK_READS_REG:
        if pe.read(n, 6) != bytes.fromhex(old):
            raise ValueError(f"{POINT_SCRIPT}: unexpected lock time copy at {n:#x}: wrong build")
    for n in LOCK_WRITES:
        if pe.read(n, 8) != LOCK_WRITE:
            raise ValueError(f"{POINT_SCRIPT}: unexpected lock time write at {n:#x}: wrong build")
    blobs = [reset_cave(mailbox, off, slot) for _, off, slot in RESET_NODES]
    _, _, vsize, va, _, _ = pe.section(b".text")
    at = (va + vsize + 15) & ~15
    for b in blobs:
        at += len(b) + (-len(b) % CAVE_ALIGN)
    for n, off, slot in INIT_WRITES:                 # their sizes are fixed: lay out after the resets
        cave = init_cave(mailbox, off, slot, n + 11, at)
        blobs.append(cave)
        at += len(cave) + (-len(cave) % CAVE_ALIGN)
    for n, slot in PROGRESS_RESETS:
        cave = progress_cave(mailbox, slot, n + 7, at)
        blobs.append(cave)
        at += len(cave) + (-len(cave) % CAVE_ALIGN)
    for n in LOCK_WRITES:
        cave = lock_cave(mailbox, n + 8, at)
        blobs.append(cave)
        at += len(cave) + (-len(cave) % CAVE_ALIGN)
    for n in SETTER_LOCK_WRITES:
        cave = setter_lock_cave(mailbox)
        blobs.append(cave)
        at += len(cave) + (-len(cave) % CAVE_ALIGN)
    reads = []                                       # (rva, site length, cave)
    for n in LOCK_READS_XMM:
        reads.append((n, 9, lock_xmm_cave(mailbox, n + 9, at, freeze=n == FREEZE_SITE)))
        at += len(reads[-1][2]) + (-len(reads[-1][2]) % CAVE_ALIGN)
    for n, old, dest in LOCK_READS_REG:
        reads.append((n, 6, lock_reg_cave(mailbox, bytes.fromhex(old), dest, n + 6, at)))
        at += len(reads[-1][2]) + (-len(reads[-1][2]) % CAVE_ALIGN)
    blobs += [c for _, _, c in reads]
    rvas = append(pe, blobs)
    for (n, size, _), cave in zip(reads, rvas[len(rvas) - len(reads):]):
        pe.write(n, b"\xe9" + rel32(n + 5, cave) + b"\x90" * (size - 5))
    rvas = rvas[:len(rvas) - len(reads)]
    for n, cave in zip(SETTER_LOCK_WRITES, rvas[len(rvas) - len(SETTER_LOCK_WRITES):]):
        pe.write(n, b"\xe9" + rel32(n + 5, cave) + b"\x90" * 7)
    rvas = rvas[:len(rvas) - len(SETTER_LOCK_WRITES)]
    for n, cave in zip(LOCK_WRITES, rvas[len(rvas) - len(LOCK_WRITES):]):
        pe.write(n, b"\xe9" + rel32(n + 5, cave) + b"\x90" * 3)
    rvas = rvas[:len(rvas) - len(LOCK_WRITES)]
    k = len(RESET_NODES)
    for (n, _, _), cave in zip(INIT_WRITES, rvas[k:k + len(INIT_WRITES)]):
        pe.write(n, b"\xe9" + rel32(n + 5, cave) + b"\x90" * 6)
    for (n, _), cave in zip(PROGRESS_RESETS, rvas[k + len(INIT_WRITES):]):
        pe.write(n, b"\xe9" + rel32(n + 5, cave) + b"\x90\x90")
    rvas = rvas[:k]
    node_of = {}
    for (n, off, _), cave in zip(RESET_NODES, rvas):
        pe.write(n, b"\xe9" + rel32(n + 5, cave))
        node_of[off] = n
    for n, off in INLINE_RESETS:                     # add rsp, 28h; jmp the node (rcx = ctx still)
        jump = bytes.fromhex("4883c428") + b"\xe9" + rel32(n + 9, node_of[off])
        pe.write(n, jump + b"\x90" * (20 - len(jump)))
    return bytes(pe.d), "round-start resets load each team's starting points from the mailbox; point unlock = T / 60"


def main(argv) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", required=True, help=f"dir with {SCRIPTS}/<script>")
    ap.add_argument("--out", required=True, help="stage directory")
    ap.add_argument("--mailbox", required=True, type=lambda v: int(v, 0),
                    help="rva of the RULES mailbox in echovr.exe (veil_fx.mailbox_rva - 130h)")
    args = ap.parse_args(argv)
    for name, fn in ((MODE_SCRIPT, patch_mode), (POINT_SCRIPT, patch_point)):
        staged = os.path.join(args.out, SCRIPTS, name)
        path = staged if os.path.exists(staged) else os.path.join(args.src, SCRIPTS, name)
        asset = open(path, "rb").read()
        mz = asset.find(b"MZ")
        try:
            pe, what = fn(asset[mz:], args.mailbox)
        except ValueError as e:
            sys.exit(str(e))
        os.makedirs(os.path.dirname(staged), exist_ok=True)
        open(staged, "wb").write(asset[:mz] + pe)
        print(f"{name}: {what} (mailbox {args.mailbox:#x})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
