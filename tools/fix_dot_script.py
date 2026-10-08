"""Patch the DOT FIELD's own script: stun sounds, and no missing-scene-set errors.

1. Sound.

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

2. Scene-set errors. The DOT script's setup chain (balance reads) runs three
EnableModelSceneSet nodes (9507dc91, cd089ec5, 878f54cb) on model component
51b9f7653ecac7cb / scene set 678a17b53bd64695. The DOT has no such model
component (its eight CModelCR records are the grenade's meshes) and no actor
anywhere defines it: the field's scene-set model was never built. Each spawn
logged three "Scriptnode can't find actor/component" errors. next_node is
rewired so 393f4ada continues straight to 013166c6, skipping the three; nothing
they could toggle exists, so nothing visible changes.

Echo loads script code from `bin/win10/scripts/<hash>.dll`, so the patched
script must go there as well as into the package; `deploy_and_launch.py` does both.

    python tools/fix_dot_script.py --src <extract root> --out <dir>
"""

from __future__ import annotations

import argparse
import os
import struct
import sys

SCRIPTS = "6eace9f64204fd0"            # CSymbol64("StreamingScriptWin10")
DOT_SCRIPT = "97d0806e6ea89130"

def _event(old, new):                 # mov dword ptr [rbp-0x11], imm32 (c7 45 ef imm32)
    return b"\xc7\x45\xef" + struct.pack("<I", old), b"\xc7\x45\xef" + struct.pack("<I", new)


def _goto(node):                       # next_node: mov eax, node (b8 imm32)
    return b"\xb8" + struct.pack("<I", node)


#: (rva, old bytes, new bytes)
PATCHES = [
    (0xAA54, *_event(0xF7C92B80, 0x5B47A1CD)),   # play_grenade_stun_active -> _activate
    (0xDDC4, *_event(0xC9CD3996, 0xBDE3209D)),   # stop_grenade_stun_active -> stop_grenade_stun
    (0x116AF, _goto(0x9507DC91), _goto(0x013166C6)),   # 393f4ada: skip the 3 scene-set nodes
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
        if out[at:at + len(new)] == new:
            continue                                  # already patched
        if out[at:at + len(old)] != old:
            raise ValueError(f"unexpected bytes at rva {rva:#x}: wrong DOT script build")
        out[at:at + len(new)] = new
    return bytes(out)


def main(argv) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--src", required=True, help="extract root")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv[1:])
    asset = open(os.path.join(args.src, SCRIPTS, DOT_SCRIPT), "rb").read()
    os.makedirs(os.path.join(args.out, SCRIPTS), exist_ok=True)
    open(os.path.join(args.out, SCRIPTS, DOT_SCRIPT), "wb").write(patch(asset))
    print(f"{SCRIPTS}/{DOT_SCRIPT}: stun sounds, scene-set nodes skipped")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
