"""Give the DOT FIELD sound: point its two sound events at the stun grenade's.

The DOT script (`mp_combat_grenade_dot`, 97d0806e6ea89130) has two PlaySound
nodes, and the Wwise event each plays is a 32-bit id baked into the node
(`mov dword ptr [rbp-0x11], <id>`). Wwise ids are FNV-1 hashes of the
lower-case event name, which cracks them:

    node f2a71917 (field activates)       0xf7c92b80  play_grenade_stun_active
    node 5fefe254 (magazine deposited)    0xc9cd3996  stop_grenade_stun_active

Neither event is used anywhere else. The stun script plays
`play_grenade_stun_activate` (0x5b47a1cd) and stops with `stop_grenade_stun`
(0xbde3209d). The DOT's names are one word off and evidently absent from the
sound banks, so the field is silent. This repoints both nodes at the stun's
events.

Echo loads script code from `bin/win10/scripts/<hash>.dll`, so the patched
script must go there as well as into the package; `deploy_and_launch.py` does both.

    python tools/fix_dot_sound.py --src <extract root> --out <dir>
"""

from __future__ import annotations

import argparse
import os
import struct
import sys

SCRIPTS = "6eace9f64204fd0"            # CSymbol64("StreamingScriptWin10")
DOT_SCRIPT = "97d0806e6ea89130"

#: (rva, old event, new event) for `mov dword ptr [rbp-0x11], imm32` (c7 45 ef imm32)
PATCHES = [
    (0xAA54, 0xF7C92B80, 0x5B47A1CD),   # play_grenade_stun_active -> play_grenade_stun_activate
    (0xDDC4, 0xC9CD3996, 0xBDE3209D),   # stop_grenade_stun_active -> stop_grenade_stun
]


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
    mz = asset.find(b"MZ")
    out = bytearray(asset)
    for rva, old, new in PATCHES:
        at = mz + rva_to_raw(asset[mz:], rva)
        want_old = b"\xc7\x45\xef" + struct.pack("<I", old)
        want_new = b"\xc7\x45\xef" + struct.pack("<I", new)
        if out[at:at + 7] == want_new:
            continue                                  # already patched
        if out[at:at + 7] != want_old:
            raise ValueError(f"unexpected bytes at rva {rva:#x}: wrong DOT script build")
        out[at:at + 7] = want_new
    return bytes(out)


def main(argv) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--src", required=True, help="extract root")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv[1:])
    asset = open(os.path.join(args.src, SCRIPTS, DOT_SCRIPT), "rb").read()
    os.makedirs(os.path.join(args.out, SCRIPTS), exist_ok=True)
    open(os.path.join(args.out, SCRIPTS, DOT_SCRIPT), "wb").write(patch(asset))
    print(f"{SCRIPTS}/{DOT_SCRIPT}: DOT sounds -> play_grenade_stun_activate / stop_grenade_stun")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
