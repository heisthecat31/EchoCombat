"""EchoCombat's values: config/mp_weapon_settings.json, shaped like the game's own
mp_weapon_settings.json. The fix tools take their values from here (not from constants)
and merge them into the game's settings before packing; deploy_and_launch.py and
make_release.py write PowerBoost.ini from the same file.

    from echocombat_config import section, powerboost_ini
"""

from __future__ import annotations

import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(ROOT, "config", "mp_weapon_settings.json")


def load() -> dict:
    with open(CONFIG, encoding="utf-8") as fh:
        return json.load(fh)


def section(*path: str) -> dict:
    """A section of the config, e.g. section("grenade_properties", "drone"); {} if absent."""
    node = load()
    for key in path:
        node = node.get(key, {})
    return dict(node)


def powerboost_ini() -> str:
    """PowerBoost.ini from the OVERCHARGE keys (ability_properties.buff)."""
    b = section("ability_properties", "buff")
    return (
        "; Written from config/mp_weapon_settings.json (ability_properties.buff) by every deploy\n"
        "; and release: change the values there, not here.\n"
        "[buff]\n"
        f"body_bonus={b.get('damage_bonus_body', 1)}\n"
        f"head_bonus={b.get('damage_bonus_head', 2)}\n"
        f"head_part={b.get('head_body_part', 5)}\n"
        "[rez]\n"
        f"seconds={b.get('cheat_death_seconds', 5)}\n"
        f"grace_ms={b.get('cheat_death_grace_ms', 1500)}\n"
        "[cone]\n"
        "axis=+z\n"
        f"link_window_ms={b.get('link_window_ms', 500)}\n"
    )


# --- this machine's paths: local.json (gitignored; copy local.example.json) -------------
LOCAL = os.path.join(ROOT, "local.json")


def local() -> dict:
    """Paths for this machine. extract / gunpatch default to the repo's data/ folders;
    server_install / client_install (the Echo VR installs to deploy into) have no
    default and are None until set in local.json or passed on the command line."""
    cfg = {}
    if os.path.exists(LOCAL):
        with open(LOCAL, encoding="utf-8") as fh:
            cfg = json.load(fh)
    return {
        "extract": cfg.get("extract") or os.path.join(ROOT, "data", "extract"),
        "gunpatch": cfg.get("gunpatch") or os.path.join(ROOT, "data", "gunpatch"),
        "server_install": cfg.get("server_install"),
        "client_install": cfg.get("client_install"),
    }
