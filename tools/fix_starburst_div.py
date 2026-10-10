"""Silence the STARBURST script's divide-by-zero log spam.

`a9db89899292a98f` (the Starburst / "rifle" gun script, stock since before these
mods) has a realdiv node (d9a3e735) evaluated every frame while the gun is out:

    result = clamp(data[+220h] / (data[+1CCh] * 0.50588), 0, 1)

When +1CCh is 0 the node logs "realdiv(d9a3e735) divide by zero" (up to ~120
lines a second, 146,000 in one session) and returns clamp(numerator, 0, 1). The
value is fine; only the log call is the problem. The script has 13 realdiv nodes,
each compiled with its own copy of that log call (the node id comes from the node's
data, so which call is which can't be read off the code); servers also logged
realdiv(4bfa3c0f) in floods. This NOPs every one of them, so each result stays
exactly what it was and nothing is written.

    python tools/fix_starburst_div.py --src <extract root> --out <stage dir>
"""

from __future__ import annotations

import argparse
import os
import sys

SCRIPTS = "6eace9f64204fd0"
STARBURST_SCRIPT = "a9db89899292a98f"
#: file offsets in the PE image of the 13 realdiv log calls (call [rip+...] to the log, each
#: loading "realdiv(%x) divide by zero"); 0x44EFF is d9a3e735's
LOG_CALLS = (0x44EFF, 0x46AD8, 0x4BF48, 0x4C286, 0x4C43E, 0x4C5D1, 0x4C7F8, 0x4DA50, 0x4DC5A,
             0x4DD2D, 0x4F407, 0x50A68, 0x525F8)
# what comes just before it: mov edx, 8 (the log channel) -- checked so a different build isn't patched
BEFORE = bytes.fromhex("ba08000000")


def main(argv) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", required=True, help=f"dir with {SCRIPTS}/<script>")
    ap.add_argument("--out", required=True, help="stage directory")
    args = ap.parse_args(argv)

    staged = os.path.join(args.out, SCRIPTS, STARBURST_SCRIPT)
    path = staged if os.path.exists(staged) else os.path.join(args.src, SCRIPTS, STARBURST_SCRIPT)
    asset = bytearray(open(path, "rb").read())
    mz = asset.find(b"MZ")
    done = removed = 0
    for call in LOG_CALLS:
        at = mz + call
        if asset[at:at + 6] == bytes(6 * [0x90]):
            done += 1
        elif asset[at:at + 2] != bytes([0xFF, 0x15]) or asset[at - 5:at] != BEFORE:
            sys.exit(f"{STARBURST_SCRIPT}: unexpected bytes at +{call:#x} ({asset[at - 5:at + 6].hex()}), not patching")
        else:
            asset[at:at + 6] = bytes(6 * [0x90])
            removed += 1
    print(f"{STARBURST_SCRIPT}: realdiv divide-by-zero logs removed ({removed} now, {done} already)")
    os.makedirs(os.path.dirname(staged), exist_ok=True)
    open(staged, "wb").write(asset)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
