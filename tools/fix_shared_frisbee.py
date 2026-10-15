"""Stop the shared magazine script enabling a frisbee component the DOT FIELD does not have.

On every throw the shared magazine script (190ed14fe6c74dd3) runs node
93def80d, "magazine type != arc", and if true node e8657155 enables the
magazine's `CR15FrisbeeCR`. The arc is excluded on purpose: without the frisbee
its dampener slows it to a stop. The DOT should fly like the arc, and has no
frisbee component, so every throw logged

    ~ Scriptnode can't find actor/component ~ ... Target Component: 0x84C65832F0B8B181

This rewrites the condition (expression_93def80d_condition) to "type != arc
and type != dot and type != drone" (1.1.7: the drone too). The 23-byte compare

    movabs rax, CSymbol64("arc"); cmp [rsp+0x28], rax; sete cl; test cl, cl; sete al

becomes a compare on the low 32 bits of the type symbol, which are unique among
all seven ordnance types (arc a891f0e9, dot a894edfe, det a894e7fe, loc a89cede9,
stun 29670bbe, burst cc9d57a4, drone cb804ab5):

    mov rax, [rsp+0x28]; cmp eax, arc; je +5; cmp eax, dot; setne al; nop x3

Nothing changes for any other ordnance.

    python tools/fix_shared_frisbee.py --src <extract root> --out <dir>
"""

from __future__ import annotations

import argparse
import os
import struct
import sys

SCRIPTS = "6eace9f64204fd0"            # CSymbol64("StreamingScriptWin10")
SHARED_SCRIPT = "190ed14fe6c74dd3"
RVA = 0x1F2F5
ARC = 0xC8E8D0B1A891F0E9               # CSymbol64("arc")
DOT = 0xC8E8D0B1A894EDFE               # CSymbol64("dot")

OLD = (b"\x48\xb8" + struct.pack("<Q", ARC)            # movabs rax, arc
       + bytes.fromhex("4839442428")                    # cmp [rsp+0x28], rax
       + bytes.fromhex("0f94c1 84c9 0f94c0"))            # sete cl; test cl, cl; sete al
DRONE = 0xE32DC7DECB804AB5             # CSymbol64("drone")
#: the drone has no frisbee either (it logged the same on every throw): the low 16 bits,
#: unique among the seven too (f0e9 edfe e7fe ede9 0bbe 57a4 4ab5), so three compares fit
NEW = (bytes.fromhex("8b442428")                                     # mov eax, [rsp+0x28]
       + bytes.fromhex("663d") + struct.pack("<H", ARC & 0xFFFF)     # cmp ax, arc
       + bytes.fromhex("740a")                                       # je setne (ZF=1 -> 0)
       + bytes.fromhex("663d") + struct.pack("<H", DOT & 0xFFFF)     # cmp ax, dot
       + bytes.fromhex("7404")                                       # je setne
       + bytes.fromhex("663d") + struct.pack("<H", DRONE & 0xFFFF)   # cmp ax, drone
       + bytes.fromhex("0f95c0"))                                    # setne al


def rva_to_raw(pe: bytes, rva: int) -> int:
    e = struct.unpack_from("<I", pe, 0x3C)[0]
    nsec = struct.unpack_from("<H", pe, e + 6)[0]
    opt = struct.unpack_from("<H", pe, e + 20)[0]
    for i in range(nsec):
        so = e + 24 + opt + i * 40
        vsize, va, rsize, raw = struct.unpack_from("<IIII", pe, so + 8)
        if va <= rva < va + max(vsize, rsize):
            return raw + rva - va
    raise ValueError(f"rva {rva:#x} not in any section")


def patch(asset: bytes) -> bytes:
    assert len(OLD) == len(NEW) == 23
    mz = asset.find(b"MZ")
    at = mz + rva_to_raw(asset[mz:], RVA)
    if asset[at:at + 23] == NEW:
        return asset                                  # already patched
    if asset[at:at + 23] != OLD:
        raise ValueError("unexpected bytes at the frisbee condition: wrong shared script build")
    return asset[:at] + NEW + asset[at + 23:]


def main(argv) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--src", required=True, help="extract root")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv[1:])
    asset = open(os.path.join(args.src, SCRIPTS, SHARED_SCRIPT), "rb").read()
    os.makedirs(os.path.join(args.out, SCRIPTS), exist_ok=True)
    open(os.path.join(args.out, SCRIPTS, SHARED_SCRIPT), "wb").write(patch(asset))
    print(f"{SCRIPTS}/{SHARED_SCRIPT}: frisbee enable skipped for arc, dot and drone")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
