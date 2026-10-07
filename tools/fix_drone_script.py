"""Give the DRONE ordnance the shared magazine script every other ordnance has.

In each combat level's `CScriptCR`, every ordnance magazine actor runs TWO
scripts: the shared magazine script `190ed14fe6c74dd3` (grab / throw / trigger
-> magazine state) followed by its own (`mp_combat_grenade_arc`, `_stun`,
`_dot`, `_translocator`, `_burst`, and det's `190ed14fe3da5ed1`). The drone
actor `10e40287a9bf5a13` has only its own, `mp_combat_ordnance_drone`, and that
script has no grab, release, trigger or impact handler -- it only reacts to the
magazine state changing. With nothing to change the state, the drone is never
activated: it sits where it is thrown and its auto-target never runs.

The shared script's entries carry no inline-table data (all twelve table sizes
are 0) and differ only in the actor field, so the fix is one 720-byte entry --
a copy of another ordnance's shared entry with the drone as its actor --
inserted just before the drone's own entry, the order every other ordnance
uses. The trailing pool is untouched.

    python tools/fix_drone_script.py --src <extract root> --out <dir>
"""

from __future__ import annotations

import argparse
import os
import struct
import sys

SCRIPT_CR = "d99f6bbd8009c92c"            # CSymbol64("CScriptCRWin10")
LEVELS = {
    "42670f2bed45703c": "mpl_combat_combustion",
    "43e2da7914642604": "mpl_combat_dyson",
    "43e2da7a0c623a19": "mpl_combat_gauss",
    "cb9977f7fc2b4526": "mpl_lobby_b_combat",
    "df5ca7b7dfa383d4": "mpl_combat_fission",
}
SHARED_SCRIPT = 0x190ED14FE6C74DD3
DRONE_ACTOR = 0x10E40287A9BF5A13
DRONE_SCRIPT = 0x221A0A3A2E56D247

HDR = 0x38
STRIDE = 720
TABLE_OFFSETS = (48, 104, 160, 216, 272, 328, 384, 440, 496, 552, 608, 664)


def u64(blob: bytes, offset: int) -> int:
    return struct.unpack_from("<Q", blob, offset)[0]


def patch(blob: bytes) -> bytes:
    count = u64(blob, 0x28)
    if u64(blob, 0x08) != count * STRIDE or u64(blob, 0x30) != count:
        raise ValueError("unexpected CScriptCR framing")
    entries = [blob[HDR + STRIDE * i:HDR + STRIDE * (i + 1)] for i in range(count)]
    pool = blob[HDR + STRIDE * count:]

    def is_drone(entry, script):
        return u64(entry, 8) == DRONE_ACTOR and u64(entry, 32) == script

    if any(is_drone(e, SHARED_SCRIPT) for e in entries):
        return blob                                   # already patched
    own = [i for i, e in enumerate(entries) if is_drone(e, DRONE_SCRIPT)]
    donors = [e for e in entries if u64(e, 0) == SHARED_SCRIPT and u64(e, 32) == SHARED_SCRIPT]
    if len(own) != 1 or not donors:
        raise ValueError("drone entry or shared-script donor not found")
    donor = donors[-1]
    if any(u64(donor, t + 8) for t in TABLE_OFFSETS):
        raise ValueError("shared-script entry carries pool data; a plain copy is not enough")

    entry = bytearray(donor)
    struct.pack_into("<Q", entry, 8, DRONE_ACTOR)
    entries.insert(own[0], bytes(entry))

    head = bytearray(blob[:HDR])
    struct.pack_into("<Q", head, 0x08, len(entries) * STRIDE)
    struct.pack_into("<Q", head, 0x28, len(entries))
    struct.pack_into("<Q", head, 0x30, len(entries))
    return bytes(head) + b"".join(entries) + pool


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--src", required=True, help="extract root holding d99f6bbd8009c92c/")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv[1:])
    os.makedirs(os.path.join(args.out, SCRIPT_CR), exist_ok=True)
    for level, name in LEVELS.items():
        blob = open(os.path.join(args.src, SCRIPT_CR, level), "rb").read()
        fixed = patch(blob)
        with open(os.path.join(args.out, SCRIPT_CR, level), "wb") as f:
            f.write(fixed)
        print(f"{name}: {u64(blob, 0x28)} -> {u64(fixed, 0x28)} script entries")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
