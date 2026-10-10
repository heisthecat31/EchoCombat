"""Only the equipped tac mod fires, even right after switching.

Tested (2026-10-10): smoke selected 07:58:29, buff (OVERCHARGE) 07:58:30, used 07:58:32
-> UMBRAL VEIL. On every switch the controller (4b65d1b009973281) re-runs its chain of
"enable <script> = (equipped == <name>)" calls, one latent call per tac mod, in order
sensor -> heal -> barrier -> wraith -> smoke -> buff -> point; ours come last and the
chain takes ~2 s, so until it gets there the old tac mod's script is still enabled.

Worse (tested 08:24: point selected last, the controller never saw it, OVERCHARGE
fired): a selection starts a child thread at the query node (CTRL_QUERY_NODE) only when
no chain is running (the trigger node waits on a running one instead), so a selection
made mid-chain is dropped and the chain ends on a stale tac mod. So:

  * VeilNet.dll reads the real selection from the client's own profile update
    ("[NSUSER] sent profile update: {"ability":...}": it hooks the game's log) and
    stores it at EQUIP_RVA +00 (and zeroes the re-run count at +20h);
  * the controller's query node also stores what it saw at +18h (+08: which controller);
  * at the end of the chain (after the last tac mod branch), if +18h differs from the
    selection, the chain goes back to the query node and runs again (at most
    MAX_RERUNS times per selection), so the selected tac mod does get enabled;
  * each guarded script's node dispatcher skips its use nodes (returns "done", nothing
    happens) while the selection is another tac mod, and counts the skip at +10h:
      - veil / POINT (barrier script copies): the custom-param node and the wall create
        node, so no wall and no veil / point token;
      - OVERCHARGE / Repair Matrix (heal script copies): the heal bubble activate node
        (OVERCHARGE's is fix_buff's marker stub).
    EQUIP_RVA = 0 (nothing seen yet) lets everything through, as before.
"""

from __future__ import annotations

import struct

from fix_smoke import PE, rel32
from veil_fx import add_section

#: spare bytes past echovr.exe's .data (see veil_fx's map): +00 u64 selected (VeilNet),
#: +08 u64 the controller that last queried, +10 u32 uses skipped, +14 u32 1 on a server
#: (VeilNet.dll sets it: the guard is off), +18 u64 what the controller's chain last
#: queried, +20 u32 chain re-runs for this selection
EQUIP_RVA = 0x2104E80
SECTION = b".eqgd\0\0\0"

SMOKE = 0xE32DC7C9D4804FB5      # CSymbol64("smoke")
POINT = 0xE32DC7CAD6864AA4      # CSymbol64("point")
BUFF = 0xC8C33E48386618B6       # CSymbol64("buff")
HEAL = 0xC8C33E4832761FBC       # CSymbol64("heal"): Repair Matrix

MAX_RERUNS = 3
CTRL_QUERY_NODE = 0x52A8D314    # the chain's first node (execute_node_52a8d314, the query)
# controller: the query node's store of the equipped tac mod
CTRL_QUERY = 0x13634            # mov [rcx+0F0h], rax ; then xor eax, eax
CTRL_QUERY_OLD = bytes.fromhex("488981f0000000 33c0")

# barrier script (and its copies): execute_node dispatcher, use nodes
BARRIER_DISPATCH = 0x5BE0
BARRIER_DISPATCH_OLD = bytes.fromhex("488b4110 bafc1694a6")
BARRIER_USE_NODES = (0xD11498F0, 0x6FB98E2C)   # custom param, wall create

# heal script (and its copies)
HEAL_DISPATCH = 0xA200
HEAL_DISPATCH_OLD = bytes.fromhex("488b4110 ba28acd680")
HEAL_USE_NODES = (0xFB9E3F50,)                 # R15NetHealBubbleActivate

BASE = bytes.fromhex("65488b142560000000 488b5210")   # rdx = echovr.exe base


def jmp(at, target):
    return b"\xe9" + rel32(at + 5, target)


def controller(pe_bytes: bytes) -> bytes:
    pe = PE(pe_bytes)
    if pe.read(CTRL_QUERY, len(CTRL_QUERY_OLD)) != CTRL_QUERY_OLD:
        raise ValueError("unexpected controller query node: wrong controller build")
    va = add_section(pe, SECTION, 0x40)
    b = bytearray(bytes.fromhex("488981f0000000"))                     # the original store
    b += BASE
    b += bytes.fromhex("488982") + struct.pack("<I", EQUIP_RVA + 0x18)  # [base+EQUIP+18] = queried
    b += bytes.fromhex("48898a") + struct.pack("<I", EQUIP_RVA + 8)     # [base+EQUIP+8] = writer
    b += jmp(va + len(b), CTRL_QUERY + 7)                               # back to xor eax, eax
    pe.write(va, bytes(b))
    pe.write(CTRL_QUERY, jmp(CTRL_QUERY, va) + b"\x90" * 2)
    return bytes(pe.d)


def chain_tail(last: int) -> bytes:
    """next_node(rcx = node, rdx = port) code for the chain's last node (fix_smoke's
    add_branches tail): its `out` goes back to the query node while what the chain
    queried differs from the selection, else the chain ends (or rax, -1). Any other
    node falls through past the end of this code."""
    from fix_smoke import OUT_PORT
    body = bytearray()
    port = b"\x48\xb8" + struct.pack("<Q", OUT_PORT) + bytes.fromhex("483bd0")   # mov rax, out; cmp
    body += bytes.fromhex("4885d2 74") + bytes([len(port) + 6])           # port 0: check
    body += port
    body += b"\x0f\x85"; j_end1 = len(body); body += bytes(4)             # other port: end
    body += bytes.fromhex("65488b042560000000 488b4010")                  # rax = echovr.exe base
    body += bytes.fromhex("488b90") + struct.pack("<I", EQUIP_RVA)        # rdx = selected
    body += bytes.fromhex("4885d2 0f84"); j_end2 = len(body); body += bytes(4)   # none: end
    body += bytes.fromhex("483b90") + struct.pack("<I", EQUIP_RVA + 0x18)  # == queried?
    body += bytes.fromhex("0f84"); j_same = len(body); body += bytes(4)
    body += bytes.fromhex("f0ff80") + struct.pack("<I", EQUIP_RVA + 0x20)  # count the re-run
    body += bytes.fromhex("83b8") + struct.pack("<I", EQUIP_RVA + 0x20) + bytes([MAX_RERUNS])
    body += bytes.fromhex("0f87"); j_end3 = len(body); body += bytes(4)   # too many: end
    body += b"\xb8" + struct.pack("<I", CTRL_QUERY_NODE) + b"\xc3"        # again, from the query
    same = len(body)
    body += bytes.fromhex("c780") + struct.pack("<I", EQUIP_RVA + 0x20) + bytes(4)  # agreed: reset
    end = len(body)
    body += bytes.fromhex("4883c8ff c3")                                  # end of the chain
    for j, t in ((j_end1, end), (j_end2, end), (j_same, same), (j_end3, end)):
        body[j:j + 4] = struct.pack("<i", t - (j + 4))
    assert len(body) < 128
    head = b"\x48\x81\xf9" + struct.pack("<I", last)                      # cmp rcx, last
    return head + b"\x75" + bytes([len(body)]) + bytes(body)              # jne past this code


def guard_dispatch(pe_bytes: bytes, dispatch: int, old: bytes, nodes, own: int) -> bytes:
    """execute_node(rcx = thread): a use node of a script whose tac mod is not the
    equipped one returns 0 (done) without running; everything else as before."""
    pe = PE(pe_bytes)
    if pe.read(dispatch, len(old)) != old:
        raise ValueError(f"unexpected execute_node dispatcher at {dispatch:#x}: wrong script build")
    va = add_section(pe, SECTION, 0x80)
    b = bytearray(bytes.fromhex("488b4110"))                           # rax = node id
    j_use = []
    for n in nodes:
        # mov edx, id; cmp rax, rdx (a cmp rax, imm32 would sign-extend ids >= 80000000h)
        b += b"\xba" + struct.pack("<I", n) + b"\x48\x3b\xc2\x74"; j_use.append(len(b)); b += b"\0"
    run = len(b)
    b += old[4:] + jmp(va + len(b) + len(old) - 4, dispatch + len(old))  # mov edx, ...; jmp back
    use = len(b)
    b += BASE + bytes.fromhex("83ba") + struct.pack("<I", EQUIP_RVA + 0x14) + b"\x00"   # server (VeilNet): off
    b += b"\x75" + bytes([(run - (len(b) + 2)) & 0xFF])                 # jne run
    b += bytes.fromhex("488b92") + struct.pack("<I", EQUIP_RVA)          # rdx = equipped
    b += bytes.fromhex("4885d2 74")                                     # none seen: run
    b += bytes([(run - (len(b) + 1)) & 0xFF])
    b += b"\x49\xb8" + struct.pack("<Q", own) + bytes.fromhex("4c39c2 74")   # equipped == own: run
    b += bytes([(run - (len(b) + 1)) & 0xFF])
    b += BASE + bytes.fromhex("f0ff82") + struct.pack("<I", EQUIP_RVA + 0x10)  # count the skip
    b += bytes.fromhex("31c0 c3")                                       # done, nothing ran
    for j in j_use:
        assert 0 <= use - (j + 1) < 128
        b[j] = use - (j + 1)
    assert len(b) - run < 128
    pe.write(va, bytes(b))
    pe.write(dispatch, jmp(dispatch, va) + b"\x90" * (len(old) - 5))
    return bytes(pe.d)


def barrier_copy(pe_bytes: bytes, own: int) -> bytes:
    return guard_dispatch(pe_bytes, BARRIER_DISPATCH, BARRIER_DISPATCH_OLD, BARRIER_USE_NODES, own)


def heal_copy(pe_bytes: bytes, own: int) -> bytes:
    return guard_dispatch(pe_bytes, HEAL_DISPATCH, HEAL_DISPATCH_OLD, HEAL_USE_NODES, own)
