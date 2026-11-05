"""TEAM READY works with more than one player.

Combat's game-mode script (`6fa8cc9cd721a563`) handles nevt_blue_team_ready / nevt_red_team_ready
(threads 92d92401 / 08c5ce5a): pass the event on to the other peers (node 64c052df / 3a7292cf),
then R15NetSetFlag blue_team_ready / red_team_ready (node 7b6a5f5f / 79460fd8) with the value

    expression_7b6a5f5f_value  0x26480:  !blue_team_ready
    expression_79460fd8_value  0x265D0:  !red_team_ready

so every delivery FLIPS the flag. With one client the server gets the event once (flag true; the
start test cdb25b0f = both ready, or one team empty and the other ready, passes). With more clients
the event comes back to the server again, the flag flips back to false and the match sits in
pre_match_wait_for_ready. Fix: both values are a constant true (idempotent). The flags are still
cleared by the round reset (nodes 1971efec / 842802b3).

The same handlers only run when expression_<thread>_shouldexecute (red 0x2B150, blue 0x25730) says

    private && isserver && (sender is the server || (!sender.demo && sender on that team))

so a demo account (a -noovr client, "AccountName [DEMO]") can never ready its team: with one on
blue, blue stays unready forever. The demo test (sete sil after output_demo) becomes true.

    python tools/fix_team_ready.py --src <extract root> --out <stage dir>
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fix_smoke import PE  # noqa: E402

SCRIPTS = "6eace9f64204fd0"
MODE_SCRIPT = "6fa8cc9cd721a563"
#: xor eax,eax; cmp byte [rsp+28h], al; sete al   ->   mov al, 1; nop x7
OLD = bytes.fromhex("33c0384424280f94c0")
NEW = bytes.fromhex("b001") + bytes([0x90]) * 7
SITES = (0x264E4, 0x26634)   # blue, red
#: sete sil (sender not demo)   ->   mov sil, 1; nop   (flags unused: a call follows)
DEMO_OLD = bytes.fromhex("400f94c6")
DEMO_NEW = bytes.fromhex("40b60190")
DEMO_SITES = (0x259BC, 0x2B3DC)   # blue, red


def patch(pe_bytes: bytes) -> tuple:
    pe = PE(pe_bytes)
    todo = [(s, OLD, NEW) for s in SITES] + [(s, DEMO_OLD, DEMO_NEW) for s in DEMO_SITES]
    if all(pe.read(s, len(new)) == new for s, _, new in todo):
        return pe_bytes, "already patched"
    for s, old, new in todo:
        if pe.read(s, len(new)) == new:
            continue
        if pe.read(s, len(old)) != old:
            raise ValueError(f"{MODE_SCRIPT}: unexpected bytes at {s:#x}: wrong build")
        pe.write(s, new)
    return bytes(pe.d), "team ready sets blue/red_team_ready true (was a toggle); demo accounts can ready"


def main(argv) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    staged = os.path.join(args.out, SCRIPTS, MODE_SCRIPT)
    path = staged if os.path.exists(staged) else os.path.join(args.src, SCRIPTS, MODE_SCRIPT)
    asset = open(path, "rb").read()
    mz = asset.find(b"MZ")
    try:
        pe, what = patch(asset[mz:])
    except ValueError as e:
        sys.exit(str(e))
    os.makedirs(os.path.dirname(staged), exist_ok=True)
    open(staged, "wb").write(asset[:mz] + pe)
    print(f"{MODE_SCRIPT}: {what}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
