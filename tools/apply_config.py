"""Merge config/mp_weapon_settings.json into the staged mp_weapon_settings (the last stage
step), so every EchoCombat value -- the ones the game reads and the ones only our tools
and plugins read -- is packed into the game's own settings.

    python tools/apply_config.py --base build/stage --out build/stage
"""

from __future__ import annotations

import argparse
import sys

from echocombat_config import load as load_config
from fix_drone import WEAPON_SETTINGS, load, save


def merge(into: dict, src: dict, path: str, changes: list) -> None:
    for key, value in src.items():
        if key.startswith("_"):
            continue
        if isinstance(value, dict):
            merge(into.setdefault(key, {}), value, f"{path}{key}.", changes)
        elif into.get(key) != value:
            into[key] = value
            changes.append(f"{path}{key} = {value}")


def main(argv) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", required=True, help="dir holding the staged settings")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv[1:])
    ws_path, settings = load(args.base, WEAPON_SETTINGS)
    changes: list = []
    merge(settings, load_config(), "", changes)
    print(save(args.out, WEAPON_SETTINGS, ws_path, settings))
    print(f"config/mp_weapon_settings.json: {len(changes)} value(s) set" +
          "".join(f"\n  {c}" for c in changes))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
