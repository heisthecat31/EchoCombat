"""Record a combat map's orbs and walkable routes for CombatBots, from your own play.

Run it while you play the map (windowed client, any team):

    python tools/record_nav.py                 # client API on 127.0.0.1:6721

Walk the routes you want bots to use, and use every teleport orb in both war rooms
(die or switch team to get back). Every 50 ms it reads your player's position from
the client's session API:

  - a jump of more than TELEPORT_JUMP metres in one sample is an orb use: the
    position before is the orb, the position after is where it lands;
  - everything else is walking, kept as route samples.

Ctrl+C saves data/nav/<map>.json (merged with what is already there), which
deploy_and_launch.py copies next to CombatBots.dll as CombatBots_<map>.json.
"""
from __future__ import annotations

import argparse
import json
import math
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAV_DIR = ROOT / "data" / "nav"
TELEPORT_JUMP = 12.0     # metres in one sample: a teleport, not a walk
SAMPLE_SPACING = 1.0     # keep a route sample every this many metres
BREAK_GAP = 4.0          # a gap this big between kept samples starts a new route
SAVE_EVERY = 5.0         # seconds between saves


def get(url: str):
    try:
        with urllib.request.urlopen(url, timeout=1) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except Exception:
        return None


def me(session):
    name = session.get("client_name")
    for team in session.get("teams", []):
        for p in team.get("players", []) or []:
            if p.get("name") == name:
                pos = (p.get("body") or p.get("head") or {}).get("position")
                if pos:
                    return team.get("team", ""), [round(v, 3) for v in pos]
    return None, None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=6721, help="client session API port (default 6721)")
    args = ap.parse_args()
    url = f"http://127.0.0.1:{args.port}/session"

    map_name = None
    routes: list[list[list[float]]] = []
    orbs: list[dict] = []
    route: list[list[float]] = []
    last = None
    last_team = None
    next_save = time.time() + SAVE_EVERY
    print(f"recording from {url} -- saves every {SAVE_EVERY:.0f} s; Ctrl+C to stop")
    try:
        while True:
            if map_name and time.time() >= next_save:
                next_save = time.time() + SAVE_EVERY
                save(map_name, orbs, routes + ([route] if len(route) > 1 else []), quiet=True)
            s = get(url)
            if s and s.get("map_name"):
                map_name = s["map_name"]
                team, pos = me(s)
                if pos:
                    if last and team == last_team and math.dist(pos, last) > TELEPORT_JUMP:
                        orbs.append({"team": team, "orb": last, "to": pos})
                        print(f"orb ({team}): {last} -> {pos}")
                        if len(route) > 1:
                            routes.append(route)
                        route = []
                    elif not route or math.dist(pos, route[-1]) >= SAMPLE_SPACING:
                        if route and math.dist(pos, route[-1]) > BREAK_GAP:
                            if len(route) > 1:
                                routes.append(route)
                            route = []
                        route.append(pos)
                    last, last_team = pos, team
            time.sleep(0.05)
    except KeyboardInterrupt:
        pass
    if len(route) > 1:
        routes.append(route)
    if not map_name:
        print("no session seen: nothing saved")
        return
    save(map_name, orbs, routes)


_base: dict[str, dict] = {}


def save(map_name: str, orbs: list, routes: list, quiet: bool = False) -> None:
    """Write data/nav/<map>.json: what was there when this run started, plus this run."""
    NAV_DIR.mkdir(parents=True, exist_ok=True)
    out = NAV_DIR / f"{map_name}.json"
    if map_name not in _base:
        _base[map_name] = json.loads(out.read_text()) if out.exists() else {"map": map_name, "orbs": [], "routes": []}
    base = _base[map_name]
    data = {**base, "orbs": base["orbs"] + orbs, "routes": base["routes"] + routes}
    text = json.dumps(data, indent=1)
    if out.exists() and out.read_text() == text:
        return
    tmp = out.with_suffix(".tmp")
    tmp.write_text(text)
    tmp.replace(out)
    # and straight to the running server: CombatBots reloads it when it changes
    from deploy_and_launch import SERVER_INSTALL
    live = Path(SERVER_INSTALL) / "bin" / "win10" / "plugins" / f"CombatBots_{map_name}.json"
    if live.parent.is_dir():
        tmp = live.with_suffix(".tmp")
        tmp.write_text(text)
        tmp.replace(live)
    if not quiet:
        print(f"saved {out}: {len(data['orbs'])} orb use(s), {len(data['routes'])} route(s), "
              f"{sum(len(r) for r in data['routes'])} samples")


if __name__ == "__main__":
    main()
