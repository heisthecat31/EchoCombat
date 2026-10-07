"""Identify the `StreamingScriptWin10` resources that hold Echo Combat's logic.

Every gameplay script in this build is a **separately compiled C++ DLL**, not a
node graph blob.  Each `StreamingScriptWin10` asset is a resource header
followed by a full PE image, built by `cl.exe` against
`sourcedb/engine/core/scripts2/includes` and named after its own resource hash
(`<hash>.obj` -> `<hash>.dll`).  Each exports exactly one symbol,
`setup_bindings`.

That makes them the answer to "what says how the ordnances work": the behaviour
of arc / stun / dot / burst / translocator / drone lives in one DLL each, and
those DLLs read their tuning straight out of `mp_weapon_settings.json` using
CSymbol64 of the full path, e.g. `grenade_properties|dot|stick_to_geo`.

The asset hash is `CSymbol64(<script name>)`, so names are recovered by
generating candidates and hashing them.  Harvesting identifiers out of the DLLs
themselves only cracks 20 of 567 -- the scripts barely reference each other by
name -- so the generator below, seeded with the conventions those 20 reveal,
does most of the work.

    python tools/crack_scripts.py            # print the map
    python tools/crack_scripts.py --write    # also write data/script_names.json
"""

from __future__ import annotations

import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_SYMBOL_DIR = os.path.join(
    os.path.dirname(os.path.dirname(_HERE)), "lone_echo_blender", "scripts")
for _p in (_HERE, _SYMBOL_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from le_symbol_names import symbol64

SCRIPTS = r"H:\pcvr-extracted\6eace9f64204fd0"   # StreamingScriptWin10

#: Names recovered by harvesting ASCII identifiers out of the script DLLs.
#: Kept as data because that scan is slow and its yield is small but real.
HARVESTED = [
    "MENU_EULA_NOTIF_WIDGETS", "MENU_EULA_VIEWED_WIDGETS", "empty",
    "itt_transform_jumper", "mp_combat_gamemode_payload", "mp_spectator",
    "mp_spectator_minimap_functions", "mpl_mm_podium",
    "mpl_mm_podium_combat_level_select_page", "mpl_mm_podium_first_match_page",
    "mpl_mm_podium_first_match_vsai_page", "mpl_tutorial_lobby_logic",
    "tut_air_brake", "tut_micro_thrusters", "ui_ar_mp_menu_2",
    "ui_ar_mp_mm_status", "ui_ar_mp_user_list", "ui_mp_arm_mm_interface",
    "ui_mp_helmet_meter_combat", "ui_mp_helmet_meter_common",
]

#: Already present in `hash_lookup.json`.
KNOWN = [
    "Empty", "mp_combat_ability_barrier", "mp_combat_server_state",
    "mp_gbl_player_lock_manager", "tut_air_brake", "tut_boost", "tut_movement",
]

PREFIXES = [
    "mp_combat_grenade_", "mp_combat_ordnance_", "mp_combat_ability_",
    "mp_combat_weapon_", "mp_combat_gun_", "mp_combat_gamemode_",
    "mp_combat_ord_", "mp_combat_tacmod_", "mp_combat_", "mp_arena_",
    "mp_gbl_", "mp_grenade_", "mp_ordnance_", "mp_ability_", "mp_weapon_",
    "mp_", "mpl_mm_podium_", "mpl_", "tut_", "ui_mp_", "ui_ar_mp_", "ui_",
]

WORDS = [
    # ordnances, by internal name and by display name
    "arc", "det", "stun", "dot", "burst", "drone", "loc", "translocator",
    "detonator", "mine", "field",
    # tacmods
    "heal", "sensor", "shield", "wraith", "buff", "smoke", "point", "barrier",
    "repair", "matrix", "scanner", "phase",
    # weapons
    "assault", "blaster", "scout", "rocket", "magnum", "smg", "chain", "rifle",
    "pulsar", "nova", "comet", "meteor", "protostar", "quark", "blazar",
    "starburst",
    # systems
    "payload", "server_state", "player_lock_manager", "spectator", "movement",
    "boost", "air_brake", "micro_thrusters", "scoreboard", "respawn",
    "capture", "round", "team", "hud", "terminal", "loadout", "equipment",
]

SUFFIXES = ["", "_a", "_v2", "_logic", "_functions", "_ordnance", "_grenade",
            "_ability", "_mod", "_gun", "_weapon", "_mine", "_field", "_page",
            "_manager", "_interface"]

#: gear name -> the script that implements it, filled in from what is found.
GEAR = {
    "arc": "ordnance", "det": "ordnance", "stun": "ordnance",
    "dot": "ordnance", "burst": "ordnance", "drone": "ordnance",
    "loc": "ordnance", "translocator": "ordnance",
    "heal": "tacmod", "sensor": "tacmod", "shield": "tacmod",
    "wraith": "tacmod", "barrier": "tacmod",
}


def asset_names() -> dict:
    """`{padded_hash: on_disk_filename}` for every streaming script."""
    return {f.rjust(16, "0"): f for f in os.listdir(SCRIPTS)}


def crack() -> dict:
    """`{padded_hash: script_name}` for every name we can recover."""
    targets = asset_names()
    found = {}

    def offer(name: str) -> None:
        h = symbol64(name)
        if h in targets and h not in found:
            found[h] = name

    for n in KNOWN + HARVESTED:
        offer(n)
    for prefix in PREFIXES:
        for word in WORDS:
            for suffix in SUFFIXES:
                offer(prefix + word + suffix)
    return found


def main(argv: list[str]) -> int:
    targets = asset_names()
    found = crack()
    print(f"streaming scripts: {len(targets)}   named: {len(found)}   "
          f"unidentified: {len(targets) - len(found)}\n")

    gear_rows, other_rows = [], []
    for h, name in sorted(found.items(), key=lambda kv: kv[1]):
        size = os.path.getsize(os.path.join(SCRIPTS, targets[h]))
        row = (name, h, size)
        tail = name.rsplit("_", 1)[-1]
        (gear_rows if tail in GEAR else other_rows).append(row)

    print("== gear behaviour scripts")
    for name, h, size in gear_rows:
        print(f"   {name:<40} {h}  {size:>9,} B")
    print("\n== other named scripts")
    for name, h, size in other_rows:
        print(f"   {name:<40} {h}  {size:>9,} B")

    if "--write" in argv:
        out = os.path.join(os.path.dirname(_HERE), "data", "script_names.json")
        payload = {"0x" + h: n for h, n in sorted(found.items(),
                                                  key=lambda kv: kv[1])}
        with open(out, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(payload, fh, indent=1)
            fh.write("\n")
        print(f"\nwrote {len(payload)} names -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
