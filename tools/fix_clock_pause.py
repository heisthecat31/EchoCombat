"""PAUSE freezes Combat's clocks.

Combat's game-mode script (`6fa8cc9cd721a563`) runs its own clocks, published as the replicated
game_timer / countdown_timer that the war room's "PREPARE FOR ROUND" HUD (cbt_gamestate_info_ui_koth)
and the round flow read:

    game_timer      (+A8h)  expression 0x28CA0: max(game_timer - dt, 0)
    lobbylock_timer (+B0h)  nodes 0xFAB0, 0x23300
    countdown_timer (+B4h)  12 state nodes (0xE5F8 ... 0x28045)

Every one of them takes the frame time as  cvtsi2ss xmmN, [rX+50h]  (thread microseconds; then
divss by 1e6). While VeilNet's PAUSE byte (RULES mailbox +2Eh: 1 paused, 2 resuming) is set, that
load gives 0 instead, so those clocks stand still. Only these sites change; dt elsewhere is left
alone. The caves live in a section of their own (.text has no room left).

(mp_game_server_state 8317e89cc3ae611 has the same clocks for Arena; Combat does not count with it,
so it is left untouched.)

    python tools/fix_clock_pause.py --src <extract root> --out <stage dir> --mailbox <rules mailbox rva>
"""

from __future__ import annotations

import argparse
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fix_smoke import PE, rel32  # noqa: E402
from veil_fx import add_section  # noqa: E402

SCRIPTS = "6eace9f64204fd0"
MODE_SCRIPT = "6fa8cc9cd721a563"
PAUSED = 0x2E
SECTION = b".clock\0\0"
#: (rva of the dt load, its 6 bytes, the xmm register it loads)
SITES = (
    (0x28CC3, "f3490f2a4150", 0),   # game_timer
    (0x0FAC5, "f3490f2a4950", 1),   # lobbylock_timer
    (0x23315, "f3490f2a4850", 1),
    (0x0E5F8, "f3480f2a4050", 0),   # countdown_timer
    (0x0F258, "f3480f2a4050", 0),
    (0x12B85, "f3490f2a4950", 1),
    (0x134C5, "f3490f2a4950", 1),
    (0x137E5, "f3490f2a4950", 1),
    (0x145F5, "f3490f2a4950", 1),
    (0x220D8, "f3480f2a4950", 1),
    (0x22A78, "f3480f2a4950", 1),
    (0x26515, "f3490f2a4850", 1),
    (0x26D85, "f3490f2a4850", 1),
    (0x26F15, "f3490f2a4850", 1),
    (0x28045, "f3490f2a4850", 1),
)
XORPS = {0: bytes.fromhex("0f57c0"), 1: bytes.fromhex("0f57c9")}


def cave(mailbox: int, orig: bytes, xmm: int, back: int, at: int) -> bytes:
    """dt = 0 while paused, else the original load. Every register but xmmN kept; the flags are
    redefined right after the site (divss, then a test) before anything reads them."""
    c = bytearray()
    c += bytes.fromhex("4153")                                          # push r11
    c += bytes.fromhex("654c8b1c2560000000")                            # mov r11, gs:[60h] (PEB)
    c += bytes.fromhex("4d8b5b10")                                      # mov r11, [r11+10h]: echovr.exe
    c += bytes.fromhex("4180bb") + struct.pack("<I", mailbox + PAUSED) + bytes(1)   # cmp byte [paused], 0
    c += bytes.fromhex("415b")                                          # pop r11 (flags kept)
    c += bytes([0x75, len(orig) + 5])                                   # jne: paused
    c += orig
    c += bytes([0xE9]) + rel32(at + len(c) + 5, back)
    c += XORPS[xmm]                                                     # paused: dt = 0
    c += bytes([0xE9]) + rel32(at + len(c) + 5, back)
    return bytes(c)


def patch(pe_bytes: bytes, mailbox: int) -> tuple:
    pe = PE(pe_bytes)
    if all(pe.read(s, 1) == bytes([0xE9]) for s, _, _ in SITES):
        return pe_bytes, "already patched"
    for s, old, _ in SITES:
        if pe.read(s, 6) != bytes.fromhex(old):
            raise ValueError(f"{MODE_SCRIPT}: unexpected dt load at {s:#x}: wrong build")
    size = 64 * len(SITES)
    va = add_section(pe, SECTION, size)
    blob = bytearray()
    jumps = []
    for s, old, xmm in SITES:
        at = va + len(blob)
        blob += cave(mailbox, bytes.fromhex(old), xmm, s + 6, at)
        jumps.append((s, at))
    assert len(blob) <= size
    pe.write(va, bytes(blob))
    for s, to in jumps:
        pe.write(s, bytes([0xE9]) + rel32(s + 5, to) + bytes([0x90]))
    return bytes(pe.d), (f"game_timer / lobbylock_timer / countdown_timer stand still while PAUSE "
                         f"(mailbox+{PAUSED:#x}; {len(SITES)} dt loads)")


def main(argv) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--mailbox", required=True, type=lambda v: int(v, 0))
    args = ap.parse_args(argv)
    staged = os.path.join(args.out, SCRIPTS, MODE_SCRIPT)
    path = staged if os.path.exists(staged) else os.path.join(args.src, SCRIPTS, MODE_SCRIPT)
    asset = open(path, "rb").read()
    mz = asset.find(b"MZ")
    try:
        pe, what = patch(asset[mz:], args.mailbox)
    except ValueError as e:
        sys.exit(str(e))
    os.makedirs(os.path.dirname(staged), exist_ok=True)
    open(staged, "wb").write(asset[:mz] + pe)
    print(f"{MODE_SCRIPT}: {what}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
