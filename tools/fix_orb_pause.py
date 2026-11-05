"""Combat spawn orbs: PAUSE gives the players the pre-match orbs.

The spawn point script `e57332952e1cd478` (tst_dsn_josh_cbt_utility_player_spawn_point)
decides what its orb does in `handlespawnaccess`: node ee90948d reads the replicated symbol
spawn_access (mp_combat_server_state's) and switches on it: pre_match, team_room,
541c3aa06a228bee, main_loop. Right after the read (rva 0x10524, `mov r8, [rsp+28h]`, the
value):

* mailbox +2Fh = the match is live (the value is set and is not pre_match), which VeilNet.dll
  uses for the podium's TEAM READY -> PAUSE / UNPAUSE;
* while mailbox +2Eh (PAUSE, VeilNet) is 1 (paused), the value is taken as pre_match; 2
  (the 5 s resume countdown) leaves the round's orbs, so players can spawn back in.

    python tools/fix_orb_pause.py --src <extract root> --out <stage dir> --mailbox <rules mailbox rva>
"""

from __future__ import annotations

import argparse
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fix_smoke import PE, rel32  # noqa: E402

SCRIPTS = "6eace9f64204fd0"
ORB_SCRIPT = "e57332952e1cd478"
PAUSED, LIVE = 0x2E, 0x2F
SITE, SITE_OLD = 0x10524, bytes.fromhex("4c8b442428")      # mov r8, [rsp+28h]
PRE_MATCH = 0x6F6337A43F136354


def patch(pe_bytes: bytes, mailbox: int) -> tuple:
    pe = PE(pe_bytes)
    if pe.read(SITE, 1) == bytes([0xE9]):
        return pe_bytes, "already patched"
    if pe.read(SITE, len(SITE_OLD)) != SITE_OLD:
        raise ValueError(f"{ORB_SCRIPT}: unexpected code at {SITE:#x}: wrong build")
    _, _, vsize, va, _, _ = pe.section(b".text")
    at = (va + vsize + 15) & ~15
    c = bytearray()
    c += SITE_OLD                                                # r8 = spawn_access
    c += bytes.fromhex("654c8b1c2560000000 4d8b5b10")            # r11 = echovr.exe (PEB)
    c += bytes.fromhex("4531d2")                                 # r10d = 0 (not live)
    c += bytes.fromhex("48b8") + struct.pack("<Q", PRE_MATCH)    # rax = pre_match
    c += bytes.fromhex("4939c0")                                 # cmp r8, rax
    j1 = len(c); c += bytes.fromhex("7400")
    c += bytes.fromhex("4983f8ff")                               # cmp r8, -1
    j2 = len(c); c += bytes.fromhex("7400")
    c += bytes.fromhex("41b201")                                 # r10b = 1: live
    c[j1 + 1] = len(c) - (j1 + 2)
    c[j2 + 1] = len(c) - (j2 + 2)
    c += bytes.fromhex("458893") + struct.pack("<I", mailbox + LIVE)        # [live] = r10b
    c += bytes.fromhex("4180bb") + struct.pack("<I", mailbox + PAUSED) + b"\x01"  # cmp byte [paused], 1
    j3 = len(c); c += bytes.fromhex("7500")                      # resuming (2) / running: as is
    c += bytes.fromhex("4989c0")                                 # paused: r8 = pre_match
    c[j3 + 1] = len(c) - (j3 + 2)
    c += bytes([0xE9]) + rel32(at + len(c) + 5, SITE + len(SITE_OLD))
    pe.grow_text(at + len(c) - va)
    pe.write(at, bytes(c))
    pe.write(SITE, bytes([0xE9]) + rel32(SITE + 5, at))
    return bytes(pe.d), f"orbs read pre_match while PAUSE (mailbox+{PAUSED:#x}); match live at +{LIVE:#x}"


def main(argv) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--mailbox", required=True, type=lambda v: int(v, 0))
    args = ap.parse_args(argv)
    staged = os.path.join(args.out, SCRIPTS, ORB_SCRIPT)
    path = staged if os.path.exists(staged) else os.path.join(args.src, SCRIPTS, ORB_SCRIPT)
    asset = open(path, "rb").read()
    mz = asset.find(b"MZ")
    try:
        pe, what = patch(asset[mz:], args.mailbox)
    except ValueError as e:
        sys.exit(str(e))
    os.makedirs(os.path.dirname(staged), exist_ok=True)
    open(staged, "wb").write(asset[:mz] + pe)
    print(f"{ORB_SCRIPT}: {what}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
