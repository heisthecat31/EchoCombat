"""Post-match terminal: three more buttons (the other Combat maps) beside LOBBY / REMATCH.

The celebration room's podium (script ui_podium_post_match_root 1d84ff70cfdc110c, canvas
854a71f21a61be8f) is in each Combat level's own data. Its two palm buttons are 4-actor
subtrees under the layout root (button -> press part -> label canvas, + one more model). This
copies the REMATCH button's subtree three times (actor_copy.py) into a row of smaller map buttons
(every Combat map but the level's own: REMATCH is for that one),
and shrinks REMATCH / LOBBY into a row under them, all on the podium's screen. What the new buttons do is VeilNet's business (it sees their presses).

    python tools/fix_map_terminal.py --src <extract root> --out <stage dir> [--level <hash>]
"""

from __future__ import annotations

import argparse
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from actor_copy import ACTORS, Place, copy_subtree, level_files, move_subtree, subtree  # noqa: E402
from cr_rows import spans  # noqa: E402
from le_symbol_names import symbol64  # noqa: E402
from level_actor_table import ActorTable  # noqa: E402

LEVELS = {   # level -> (the button to copy: REMATCH, the other stock button: LOBBY); each level's
             # only prp_itt_screen_button_logic pair sending left_ / right_button_press
    "43e2da7914642604": (0xA33EA7534AD8A095, 0x4F4012B16746E848),   # mpl_combat_dyson
    "42670f2bed45703c": (0x7D982FF3D83BC503, 0x91E69A11F5A58DDE),   # mpl_combat_combustion
    "df5ca7b7dfa383d4": (0x3330E9CA0147CC25, 0xDF4E5C282CD984F8),   # mpl_combat_fission
    "43e2da7a0c623a19": (0x075E6ED4E2BE6885, 0xEB20DB36CF202058),   # mpl_combat_gauss
}
#: the layout in the podium's frame (x across the panel; the viewer's left is -x here, y up the
#: panel), metres from the middle of the stock pair, and each button's scale. Stock buttons are
#: 0.126 x 0.23 at scale 1, 0.2 apart; the screen behind them reaches ~0.085 above their centres
#: and ~0.18 below (test 1 screenshot).
MAPS = ("dyson", "combustion", "fission", "gauss")
#: each level's own map: its button is left out (REMATCH replays it)
LEVEL_MAP = {"43e2da7914642604": "dyson", "42670f2bed45703c": "combustion",
             "df5ca7b7dfa383d4": "fission", "43e2da7a0c623a19": "gauss"}
#: three buttons across where four were (4 at 0.096 apart, scale 0.6): wider apart and bigger
MAP_X = (-0.125, 0.0, 0.125)
#: the label on each map's button (Gauss is called SURGE in game; its level stays mpl_combat_gauss)
LABELS = {"dyson": "DYSON", "combustion": "COMBUSTION", "fission": "FISSION", "gauss": "SURGE"}
MAP_Y, MAP_SCALE = 0.055, 0.7
STOCK_Y, STOCK_SCALE = -0.085, 0.5
STOCK_X = {"rematch": -0.07, "lobby": 0.07}

#: Each palm button runs prp_itt_screen_button_logic; its own script data (the CScriptCR record's
#: child tables) holds the event it sends the podium when pressed (table 5, a symbol at row +16:
#: REMATCH's is left_button_press) and its default label (table 8, 80-byte rows, a 64-byte string
#: at +16: "LEFT"; the podium overwrites the stock pair's with REMATCH / LOBBY, not ours). The
#: copies get an event of their own, which the podium ignores and VeilNet.dll hears (mapswitch_<map>),
#: and the map's name as their label.
SCRIPT = "d99f6bbd8009c92c"
PRESS_TABLE, LABEL_TABLE = 5, 8
LEFT_BUTTON_PRESS = 0x052C36430F4094CD

def rotate(q, v):
    """v by unit quaternion q = (x, y, z, w)."""
    x, y, z, w = q
    ux, uy, uz = v
    tx = 2 * (y * uz - z * uy)
    ty = 2 * (z * ux - x * uz)
    tz = 2 * (x * uy - y * ux)
    return (ux + w * tx + (y * tz - z * ty), uy + w * ty + (z * tx - x * tz), uz + w * tz + (x * ty - y * tx))


def nodeid(text: str) -> int:
    return int(symbol64(text), 16)


def set_press_and_label(b: bytes, owner: int, event: int, label: str) -> bytes:
    """The button's CScriptCR record: its press event and default label."""
    s = spans("CScriptCR", b)
    k = s.owners.index(owner)
    row0, _ = s.rows[k]
    cursor, _ = s.nested[k]
    out = bytearray(b)
    done = set()
    for t in range(12):
        size, _, _, _, _, cap, count = struct.unpack_from("<QQIIQQQ", b, row0 + 0x30 + 56 * t + 8)
        if not count:
            continue
        stride = size // cap
        cursor = (cursor + 7) // 8 * 8
        for j in range(count):
            at = cursor + j * stride
            if t == PRESS_TABLE and struct.unpack_from("<Q", b, at + 16)[0] == LEFT_BUTTON_PRESS:
                struct.pack_into("<Q", out, at + 16, event)
                done.add("event")
            if t == LABEL_TABLE and b[at + 16:at + 80].rstrip(b"\0") == b"LEFT":
                out[at + 16:at + 80] = label.encode().ljust(64, b"\0")
                done.add("label")
        cursor += count * stride
    if done != {"event", "label"}:
        raise SystemExit(f"button {owner:016x}: press event / label not found ({sorted(done)})")
    return bytes(out)


def patch_level(src: str, out: str, level: str) -> list:
    rematch_id, lobby_id = LEVELS[level]
    files = level_files(src, out, level)
    table = ActorTable.read(files[ACTORS])
    index = {a.nodeid: i for i, a in enumerate(table.actors)}
    shown = [(name, x) for name, x in zip([m for m in MAPS if m != LEVEL_MAP[level]], MAP_X)]
    if any(nodeid(f"mapswitch_{m}_0") in index for m in MAPS):
        return ["already patched"]
    rematch, lobby = index[rematch_id], index[lobby_id]
    q = struct.unpack_from("<4f", table.actors[rematch].transform, 0)
    pos = {i: struct.unpack_from("<3f", table.actors[i].transform, 16) for i in (rematch, lobby)}
    middle = tuple((a + b) / 2 for a, b in zip(pos[rematch], pos[lobby]))

    def world(x, y):
        return tuple(m + r for m, r in zip(middle, rotate(q, (x, y, 0.0))))

    def offset(i, x, y):
        return tuple(w - p for w, p in zip(world(x, y), pos[i]))

    parts = len(subtree(table, rematch))
    copies = [([nodeid(f"mapswitch_{name}_{j}") for j in range(parts)],
               Place(pos[rematch], offset(rematch, x, MAP_Y), MAP_SCALE)) for name, x in shown]
    changed = copy_subtree(files, rematch, copies)
    files.update(changed)
    script = files[SCRIPT]
    for name, _ in shown:
        script = set_press_and_label(script, nodeid(f"mapswitch_{name}_0"), nodeid(f"mapswitch_{name}"), LABELS[name])
    files[SCRIPT] = changed[SCRIPT] = script
    for i, key in ((rematch, "rematch"), (lobby, "lobby")):
        moved = move_subtree(files, i, Place(pos[i], offset(i, STOCK_X[key], STOCK_Y), STOCK_SCALE))
        files.update(moved)
        changed.update(moved)
    for t, data in changed.items():
        os.makedirs(os.path.join(out, t), exist_ok=True)
        open(os.path.join(out, t, level), "wb").write(data)
    return [f"{len(copies)} map buttons ({', '.join(n for n, _ in shown)}; no {LEVEL_MAP[level]}) x {parts} actors (scale {MAP_SCALE}), REMATCH / LOBBY at "
            f"scale {STOCK_SCALE}, labels + press events mapswitch_<map>", "tables: " + ", ".join(sorted(changed))]


def main(argv) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--level", action="append")
    a = ap.parse_args(argv)
    for level in a.level or LEVELS:
        print(f"fix_map_terminal {level}:", "; ".join(patch_level(a.src, a.out, level)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
