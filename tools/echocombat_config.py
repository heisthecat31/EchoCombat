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
        f"self_damage={b.get('self_damage_per_tick', 5)}\n"
        f"self_damage_tick_ms={round(b.get('self_damage_tick_seconds', 1.0) * 1000)}\n"
        f"self_damage_lethal={1 if b.get('self_damage_lethal', False) else 0}\n"
        "[rez]\n"
        f"seconds={b.get('cheat_death_seconds', 5)}\n"
        f"grace_ms={b.get('cheat_death_grace_ms', 1500)}\n"
        "[cone]\n"
        "axis=+z\n"
        f"aim={b.get('aim', 'head')}\n"
        f"link_window_ms={b.get('link_window_ms', 500)}\n"
        + medigun_ini()
        # read by VeilNet.dll on a server: MEDIGUN is offered to its clients only when 1
        + "[server]\n"
        + f"medigun={1 if section('medigun').get('enabled', False) else 0}\n"
    )


def repair_matrix_rate() -> float:
    """Repair Matrix's heal per second (ability_properties.heal, the gun patch's settings)."""
    from json_resource import read
    path = os.path.join(local()["gunpatch"], "607d858c90268f9a", "11a8523ed4724ca7")
    if not os.path.exists(path):
        path = os.path.join(ROOT, "data", "gunpatch", "607d858c90268f9a", "11a8523ed4724ca7")
    heal = json.loads(read(open(path, "rb").read())[1])["ability_properties"]["heal"]
    return heal["heal_amt"] / heal["heal_duration"]


def medigun_ini() -> str:
    """PowerBoost.ini's [medigun] (ability_properties.medigun)."""
    m = section("medigun")
    rate = repair_matrix_rate() * m.get("heal_scale", 0.85)
    seconds = m.get("beam_seconds", 40)
    return (
        "[medigun]\n"
        f"heal_per_second={rate:.4f}\n"
        f"beam_seconds={seconds}\n"
        f"overheat_seconds={m.get('overheat_seconds', 3)}\n"
        f"cool_seconds={m.get('cool_seconds', 5)}\n"
        f"cone_angle={m.get('cone_angle', 20)}\n"
        f"range={m.get('range', 20)}\n"
        f"cone_slack={m.get('cone_slack', 5)}\n"
        f"hand={m.get('hand', 'auto')}\n"
        f"gun_axis={m.get('gun_axis', '+z')}\n"
        f"hand_offset={m.get('hand_offset', '0,0,0')}\n"
        f"hand_offset_left={m.get('hand_offset_left', m.get('hand_offset', '0,0,0'))}\n"
        f"aim={m.get('aim', 'head')}\n"
        f"beam_bone={m.get('beam_bone', 'ToolAttach1')}\n"    )


# --- this machine's paths: local.json (gitignored; copy local.example.json) -------------
LOCAL = os.path.join(ROOT, "local.json")


def local() -> dict:
    """Paths for this machine. extract / gunpatch default to the repo's data/ folders;
    server_install / client_install (the Echo VR installs to deploy into) and
    content_overlay (NvrContentOverlay.dll) have no default and are None until set in
    local.json or passed on the command line."""
    cfg = {}
    if os.path.exists(LOCAL):
        with open(LOCAL, encoding="utf-8") as fh:
            cfg = json.load(fh)
    return {
        "extract": cfg.get("extract") or os.path.join(ROOT, "data", "extract"),
        "gunpatch": cfg.get("gunpatch") or os.path.join(ROOT, "data", "gunpatch"),
        "server_install": cfg.get("server_install"),
        "client_install": cfg.get("client_install"),
        # NvrContentOverlay.dll, the nEVR plugin that serves the content pack; deploys copy it
        # into each install's plugins/ when set (the launcher installs it for players)
        "content_overlay": cfg.get("content_overlay"),
    }
