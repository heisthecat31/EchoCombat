"""Preview the game's particle effects one by one on the stun mine, to pick UMBRAL VEIL's smoke.

The game ships 81 particle effects (type folder 3ae7c41914252baa) and none has a
readable name, so the smoke dome's effect is picked by eye. The stun mine's
script (mp_combat_grenade_stun, 190ed14ff6dc4ad8) has two CreateParticleEffect
nodes, d5c9ffb3 and 8ff76ff9, each loading its effect with

    movabs rax, <effect hash>; ... mov [node+8], rax

This replaces each `movabs` with a call into a stub that hands out the next
effect from the list below, one per call, wrapping around. Each node has its
own counter, so the Nth stun mine the client sees going off shows effect
number N (counting from --start, default 1) on both nodes. The counters live in
two dwords appended to .data's zero-filled tail; the stubs and the table go in
.text's free space.

Stun mines still stun: only their look changes. Not part of a normal deploy:

    python tools/deploy_and_launch.py --fx-preview 1
    python tools/fx_preview.py --src <extract root> --out <dir> [--start N]
    python tools/fx_preview.py --list
"""

from __future__ import annotations

import argparse
import os
import struct
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from fix_smoke import PE, rel32, u32

SCRIPTS = "6eace9f64204fd0"            # CSymbol64("StreamingScriptWin10")
STUN_SCRIPT = "190ed14ff6dc4ad8"
#: rva of `movabs rax, <effect>` in execute_node_d5c9ffb3 and execute_node_8ff76ff9
SITES = [(0xCFD4, 0xDE22B615C9C69CDD), (0xE204, 0x4CE12AE42C1B6269)]

#: Every particle effect asset, in the order the preview shows them (number 1 first).
EFFECTS = [
    "093b30a30cf4aa33", "0d38076b5a71fa9f", "13bbad2a1bb49665", "1432f4f2b0f840df",
    "14578d2c8f5af6cd", "1842386e1a3a999d", "1ae1638486be29d9", "1f40a2c559b179ca",
    "27dfaf5baf03d6a3", "2869b2320808f879", "288f3d22586342d5", "2d065eb0d9ce1614",
    "32e0bdb6be54df9d", "36109ccf42b87f9c", "3842014fecda4ef3", "39424707bb2df316",
    "3c089de4756014e0", "3db472928b4d7c45", "3e0d00b4de4d893b", "400fd23ed78f3bc4",
    "413d710284c73629", "47c3dcb5363e6f3f", "4ce12ae42c1b6269", "53f159f2eba38153",
    "56f6f9d8f5238854", "5859d9f1deba8f62", "591588d170a43fab", "5edc28be693da6d7",
    "6089d3e04ce94bb3", "66497bb68e458216", "688a871c9bfe6b0a", "688a871c9ffe6d5c",
    "688a871c9ffe6d5f", "6d2370a007d231ff", "7519175b4e041801", "75db6596e0af110d",
    "7676880776a1f757", "76db6596e0af110d", "7c26d0ec0007bf41", "81cf9270aa39a8fe",
    "83976b2ec1de4a57", "841ea4083a661cbc", "8c7eef93937c7638", "9123cc1d742c604b",
    "99e95eca20f0a225", "99e95eca20fdb52f", "a1aca9b4b0f8789b", "a700f72d7ef654de",
    "a8cd797f5e8693fe", "a90293992ea6423b", "aa3af51a4dbc0ab3", "b599e02d3574c219",
    "b6b1b15243f2f689", "b6b1b15243f2f68a", "b6b1b1524ae5fadc", "b6b1b1524ee5fc89",
    "b6b1b1524ee5fc8a", "b9e607923cff12f3", "baa5f4b2d485183f", "baa5f4b2de8f1d22",
    "bae607923cff12f3", "bb84112e901de67a", "bc00df715c05ea8f", "be696d7d300cbaf7",
    "bff34ce49d120472", "c9eb32d35038eb4c", "cafac4e20c24d233", "d3d9a8de7ddf96d9",
    "d5a96e946f0f349f", "dc8adf1c3054b91f", "dda76a1d71438bd6", "dda76a1d7f4596c3",
    "de22b615c9c69cdd", "e67a13813d60f085", "e92a9dad8fa4ddd1", "ec92211825dda4ae",
    "f206c60fa64d4490", "f27fb4ac493ab9ed", "f41851241fc581d1", "f677d365ee22d7ac",
    "fffe21ce6aa21695",
]


def stub(at: int, table: int, counter: int) -> bytes:
    """rax = table[counter]; counter = (counter + 1) % len(table). Keeps every other register."""
    b = bytearray(b"\x51")                                            # push rcx
    b += b"\x8b\x0d" + rel32(at + len(b) + 6, counter)                # mov ecx, [counter]
    b += b"\x48\x8d\x05" + rel32(at + len(b) + 7, table)              # lea rax, [table]
    b += bytes.fromhex("488b04c8 ffc1")                               # mov rax,[rax+rcx*8]; inc ecx
    b += b"\x81\xf9" + struct.pack("<I", len(EFFECTS))                # cmp ecx, n
    b += bytes.fromhex("7202 31c9")                                   # jb +2; xor ecx, ecx
    b += b"\x89\x0d" + rel32(at + len(b) + 6, counter)                # mov [counter], ecx
    b += b"\x59\xc3"                                                  # pop rcx; ret
    return bytes(b)


def patch(asset: bytes, start: int) -> bytes:
    mz = asset.find(b"MZ")
    pe = PE(asset[mz:])
    for rva, old in SITES:
        head = pe.read(rva, 10)
        if head[:1] == b"\xe8":
            raise ValueError("stun script already has the preview patch")
        if head != b"\x48\xb8" + struct.pack("<Q", old):
            raise ValueError("unexpected effect load in the stun script: wrong build")

    # Counters: two dwords past the end of .data's (zero-filled) virtual size.
    o, _, dvsize, dva, _, _ = pe.section(b".data")
    counters = dva + ((dvsize + 7) & ~7)
    if counters + 8 > min(s[3] for s in pe.sections() if s[3] > dva):
        raise ValueError("no room after .data for the counters")
    struct.pack_into("<I", pe.d, o + 8, counters + 8 - dva)

    rot = start % len(EFFECTS)
    table = b"".join(struct.pack("<Q", int(h, 16)) for h in EFFECTS[rot:] + EFFECTS[:rot])
    _, _, vsize, text_va, _, _ = pe.section(b".text")
    table_rva = (text_va + vsize + 15) & ~15
    stubs = []
    at = table_rva + len(table)
    for k in range(len(SITES)):
        at = (at + 15) & ~15
        s = stub(at, table_rva, counters + 4 * k)
        stubs.append((at, s))
        at += len(s)
    pe.grow_text(at - text_va)
    pe.write(table_rva, table)
    for (rva, _), (srva, s) in zip(SITES, stubs):
        pe.write(srva, s)
        pe.write(rva, b"\xe8" + rel32(rva + 5, srva) + bytes.fromhex("0f1f440000"))
    return asset[:mz] + bytes(pe.d)


def main(argv) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--src", help="extract root")
    ap.add_argument("--out")
    ap.add_argument("--start", type=int, default=1, help="effect number the first stun mine shows")
    ap.add_argument("--list", action="store_true", help="print the numbered effect list")
    args = ap.parse_args(argv[1:])
    if args.list:
        for i, h in enumerate(EFFECTS, 1):
            print(f"{i:3}  {h}")
        return 0
    if not (args.src and args.out):
        ap.error("--src and --out are required")
    if not 1 <= args.start <= len(EFFECTS):
        ap.error(f"--start must be 1..{len(EFFECTS)}")
    asset = open(os.path.join(args.src, SCRIPTS, STUN_SCRIPT), "rb").read()
    os.makedirs(os.path.join(args.out, SCRIPTS), exist_ok=True)
    open(os.path.join(args.out, SCRIPTS, STUN_SCRIPT), "wb").write(patch(asset, args.start - 1))
    print(f"{SCRIPTS}/{STUN_SCRIPT}: stun mine N shows particle effect {args.start} + N - 1 "
          f"(of {len(EFFECTS)}, wrapping)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
