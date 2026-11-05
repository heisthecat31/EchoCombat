"""Equipment station: grid cells past what a column shows go off the canvas.

The equipment station's script `e0fdfda9a944e8ff` lays its three icon grids out in
`setupicons`: per gear type, `setupicon` and then `positionicon` for cells
0 .. min(total_num + locks_to_show, max_icons) - 1. Cells past that are never touched.
In the stock game a column never shrinks, so that was fine; with LOADOUTS (VeilNet.dll
changes a column's item count while the match runs) the cells a longer layout used stayed
where they were and showed over the new layout.

This makes the position loop (node d45bb367) run over every cell (max_icons), and the
position of each cell (expression 34396d3 newposition, in positionicon: thread data
+00 type index, +04 cell index) go far off the canvas when the cell index is at or past
the cell count VeilNet publishes for that type in the RULES mailbox (+14h + type, one
byte: items + the lock; 0 = not published, every cell placed as before).

    python tools/fix_station_cells.py --src <extract root> --out <stage dir> --mailbox <rules mailbox rva>
"""

from __future__ import annotations

import argparse
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fix_smoke import PE, rel32  # noqa: E402

SCRIPTS = "6eace9f64204fd0"
STATION_SCRIPT = "e0fdfda9a944e8ff"
CELLS = 0x14                                # mailbox +14h..+16h: cells shown per gear type

#: d45bb367's count: min(total_num + locks, max_icons) -> max_icons (edx)
LOOP_MIN = 0x1683F
LOOP_MIN_OLD = bytes.fromhex("442bc2" "418bc0" "c1f81f" "4123c0" "03c2")
#: 34396d3 newposition's end: mov rax,[rsp+90h]; mov [rbx],rax (r10 = the thread data)
POS_END = 0x1D272
POS_END_OLD = bytes.fromhex("488b842490000000" "488903")
POS_BACK = POS_END + len(POS_END_OLD)
FAR = struct.pack("<ff", 100000.0, 100000.0)


def patch(pe_bytes: bytes, mailbox: int) -> tuple:
    pe = PE(pe_bytes)
    if pe.read(POS_END, 1) == b"\xe9":
        return pe_bytes, "already patched"
    if pe.read(LOOP_MIN, len(LOOP_MIN_OLD)) != LOOP_MIN_OLD or pe.read(POS_END, len(POS_END_OLD)) != POS_END_OLD:
        raise ValueError(f"{STATION_SCRIPT}: unexpected code at the patch sites: wrong build")
    _, _, vsize, va, _, _ = pe.section(b".text")
    cave = (va + vsize + 15) & ~15
    c = bytearray()
    c += bytes.fromhex("488b842490000000")                     # mov rax, [rsp+90h] (the position)
    c += bytes.fromhex("418b0a")                               # mov ecx, [r10] (type index)
    c += bytes.fromhex("83f902")                               # cmp ecx, 2
    j_type = len(c); c += bytes.fromhex("7700")                # ja done
    c += bytes.fromhex("65488b142560000000")                   # mov rdx, gs:[60h] (PEB)
    c += bytes.fromhex("488b5210")                             # mov rdx, [rdx+10h] (echovr.exe)
    c += bytes.fromhex("0fb6940a") + struct.pack("<I", mailbox + CELLS)   # movzx edx, byte [rdx+rcx+cells]
    c += bytes.fromhex("85d2")                                 # test edx, edx
    j_zero = len(c); c += bytes.fromhex("7400")                # jz done: not published
    c += bytes.fromhex("41395204")                             # cmp [r10+4], edx
    j_shown = len(c); c += bytes.fromhex("7c00")               # jl done: a cell in use
    c += bytes.fromhex("48b8") + FAR                           # mov rax, far away
    done = len(c)
    c += bytes.fromhex("488903")                               # mov [rbx], rax
    c += b"\xe9" + rel32(cave + len(c) + 5, POS_BACK)
    for j in (j_type, j_zero, j_shown):
        c[j + 1] = done - (j + 2)
    pe.grow_text(cave + len(c) - va)
    pe.write(cave, bytes(c))
    pe.write(POS_END, b"\xe9" + rel32(POS_END + 5, cave) + b"\x90" * (len(POS_END_OLD) - 5))
    pe.write(LOOP_MIN, bytes.fromhex("8bc2") + b"\x90" * (len(LOOP_MIN_OLD) - 2))   # mov eax, edx
    return bytes(pe.d), f"every grid cell placed; cells past the count at mailbox+{CELLS:#x} off the canvas"


def main(argv) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", required=True, help=f"dir with {SCRIPTS}/<script>")
    ap.add_argument("--out", required=True, help="stage directory")
    ap.add_argument("--mailbox", required=True, type=lambda v: int(v, 0), help="rva of the RULES mailbox")
    args = ap.parse_args(argv)
    staged = os.path.join(args.out, SCRIPTS, STATION_SCRIPT)
    path = staged if os.path.exists(staged) else os.path.join(args.src, SCRIPTS, STATION_SCRIPT)
    asset = open(path, "rb").read()
    mz = asset.find(b"MZ")
    try:
        pe, what = patch(asset[mz:], args.mailbox)
    except ValueError as e:
        sys.exit(str(e))
    os.makedirs(os.path.dirname(staged), exist_ok=True)
    open(staged, "wb").write(asset[:mz] + pe)
    print(f"{STATION_SCRIPT}: {what}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
