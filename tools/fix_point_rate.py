"""Capture point: POINT RATE, a multiplier on how fast a team's points rise.

The capture-point script `b7d10bcffcb2a780` raises each team's points (blueteamcharge
+F8h, orangeteamcharge +F0h) every tick in an expression (blue 5cd8c247, orange
76d52a0f): points + dt * rate, clamped to required_charge (+FCh). dt is the thread's
time step (microseconds at +50h, divided by 1e6 by a divss); the rate is the slow one
while the team holds the point with nobody on it, the fast one while someone stands on it
(+E4h / +E0h, picked by the script). Scaling dt scales both.

Right after each divss, dt is multiplied by mailbox+2Dh / 4 (a byte VeilNet.dll keeps:
the server's RULES page 2 POINT RATE in quarters, 4 = x1; 0 = not set, dt as before).

    python tools/fix_point_rate.py --src <extract root> --out <stage dir> --mailbox <rules mailbox rva>
"""

from __future__ import annotations

import argparse
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fix_smoke import PE, rel32  # noqa: E402

SCRIPTS = "6eace9f64204fd0"
CAPTURE_SCRIPT = "b7d10bcffcb2a780"
RATE = 0x2D                                 # mailbox +2Dh: POINT RATE in quarters (4 = x1)
PAUSED = 0x2E                               # mailbox +2Eh: PAUSE (VeilNet): the points stand still
#: (site of `divss dt, [rip+1e6]`, its bytes before the rel32, the dt register's
#: `mulss dt, xmm3` and `xorps dt, dt` encodings)
SITES = ((0x231BF, bytes.fromhex("f30f5e0d"), bytes.fromhex("f30f59cb"), bytes.fromhex("0f57c9")),        # blue: xmm1
         (0x22506, bytes.fromhex("f3440f5e05"), bytes.fromhex("f3440f59c3"), bytes.fromhex("450f57c0")))  # orange: xmm8


def patch(pe_bytes: bytes, mailbox: int) -> tuple:
    pe = PE(pe_bytes)
    if all(pe.read(site, 1) == b"\xe9" for site, *_ in SITES):
        return pe_bytes, "already patched"
    for site, head, *_ in SITES:
        if pe.read(site, len(head)) != head:
            raise ValueError(f"{CAPTURE_SCRIPT}: unexpected code at {site:#x}: wrong build")
    _, _, vsize, va, _, _ = pe.section(b".text")
    at = (va + vsize + 15) & ~15
    c = bytearray()
    tenth_fix = []                              # offsets of the rel32s to the 0.25 constant
    starts = []
    for site, head, mul, zero in SITES:
        n = len(head) + 4
        const = site + n + struct.unpack("<i", pe.read(site + len(head), 4))[0]   # the 1e6
        start = at + len(c)
        starts.append(start)
        c += head + rel32(start + n, const)                     # divss dt, [1e6] (as before)
        c += bytes.fromhex("654c8b1c2560000000 4d8b5b10")       # r11 = echovr.exe (PEB)
        c += bytes.fromhex("4180bb") + struct.pack("<I", mailbox + PAUSED) + b"\x00"   # cmp byte [paused], 0
        jp = len(c); c += bytes.fromhex("7500")                 # jne: paused
        c += bytes.fromhex("450fb69b") + struct.pack("<I", mailbox + RATE)   # r11d = rate byte
        c += bytes.fromhex("4585db")                            # test r11d, r11d
        j = len(c); c += bytes.fromhex("7400")                  # jz back: not set
        c += bytes.fromhex("f3410f2adb")                        # cvtsi2ss xmm3, r11d
        c += bytes.fromhex("f30f591d"); tenth_fix.append(len(c)); c += bytes(4)   # mulss xmm3, [0.25]
        c += mul                                                # mulss dt, xmm3
        jb = len(c); c += bytes.fromhex("eb00")                 # jmp back
        c[jp + 1] = len(c) - (jp + 2)
        c += zero                                               # paused: dt = 0
        c[j + 1] = len(c) - (j + 2)
        c[jb + 1] = len(c) - (jb + 2)
        c += bytes([0xE9]) + rel32(at + len(c) + 5, site + n)    # back
    c += bytes((-len(c)) % 4)
    tenth = at + len(c)
    c += struct.pack("<f", 0.25)
    for off in tenth_fix:
        c[off:off + 4] = struct.pack("<i", tenth - (at + off + 4))
    pe.grow_text(at + len(c) - va)
    pe.write(at, bytes(c))
    for (site, head, *_), start in zip(SITES, starts):
        n = len(head) + 4
        pe.write(site, bytes([0xE9]) + rel32(site + 5, start) + bytes([0x90]) * (n - 5))
    return bytes(pe.d), f"points rise with dt * mailbox+{RATE:#x}/4 ({len(c)} bytes of code)"


def main(argv) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--mailbox", required=True, type=lambda v: int(v, 0))
    args = ap.parse_args(argv)
    staged = os.path.join(args.out, SCRIPTS, CAPTURE_SCRIPT)
    path = staged if os.path.exists(staged) else os.path.join(args.src, SCRIPTS, CAPTURE_SCRIPT)
    asset = open(path, "rb").read()
    mz = asset.find(b"MZ")
    try:
        pe, what = patch(asset[mz:], args.mailbox)
    except ValueError as e:
        sys.exit(str(e))
    os.makedirs(os.path.dirname(staged), exist_ok=True)
    open(staged, "wb").write(asset[:mz] + pe)
    print(f"{CAPTURE_SCRIPT}: {what}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
