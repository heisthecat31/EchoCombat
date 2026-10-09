"""Silence the STARBURST script's divide-by-zero log spam.

`a9db89899292a98f` (the Starburst / "rifle" gun script, stock since before these
mods) has a realdiv node (d9a3e735) evaluated every frame while the gun is out:

    result = clamp(data[+220h] / (data[+1CCh] * 0.50588), 0, 1)

When +1CCh is 0 the node logs "realdiv(d9a3e735) divide by zero" (up to ~120
lines a second, 146,000 in one session) and returns clamp(numerator, 0, 1). The
value is fine; only the log call is the problem. This NOPs that one call, so the
result stays exactly what it was and nothing is written.

    python tools/fix_starburst_div.py --src <extract root> --out <stage dir>
"""

from __future__ import annotations

import argparse
import os
import sys

SCRIPTS = "6eace9f64204fd0"
STARBURST_SCRIPT = "a9db89899292a98f"
LOG_CALL = 0x44EFF                       # file offset in the PE image: call [rip+1B9A3h] (the log)
LOG_CALL_BYTES = bytes.fromhex("ff15a3b90100")
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
    at = mz + LOG_CALL
    if asset[at:at + 6] == b"\x90" * 6:
        print(f"{STARBURST_SCRIPT}: log call already removed")
    elif asset[at:at + 6] != LOG_CALL_BYTES or asset[at - 5:at] != BEFORE:
        sys.exit(f"{STARBURST_SCRIPT}: unexpected bytes at the log call ({asset[at - 5:at + 6].hex()}), not patching")
    else:
        asset[at:at + 6] = b"\x90" * 6
        print(f"{STARBURST_SCRIPT}: realdiv(d9a3e735) divide-by-zero log removed")
    os.makedirs(os.path.dirname(staged), exist_ok=True)
    open(staged, "wb").write(asset)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
