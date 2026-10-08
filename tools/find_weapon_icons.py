"""Find the texture atlas that holds the weapon icons (gear table + HUD) and copy it,
with the other likely candidates, into data/extract/weapon_icons/ for Claude.

Echo's UI is made of canvases (CUICanvasResourceWin10): each is a table of elements,
every element a rectangle cut from a shared texture atlas. The icons are elements of
such a canvas. This reads every canvas in the extract with lone_echo_blender's
evr_ui_extract (and rebuilds the atlas DDS with evr_texture_resource), then ranks
each atlas texture by:

* name hits: the canvases that use it mention a weapon / gear name (CSymbol64 of
  "assault", "pulsar", "icon_assault", ... anywhere in the canvas file);
* combat: those canvases are placed in a combat level (or the combat lobby);
* elements: how many icon-sized rectangles it holds.

The best candidates are copied as DDS (and PNG previews if Pillow can read them),
with report.txt listing every atlas and why. collect_for_claude.py then pushes them.

    python tools/find_weapon_icons.py [--extract H:\\pcvr-extracted] [--blender ..\\lone_echo_blender]
"""

from __future__ import annotations

import argparse
import os
import shutil
import struct
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "extract" / "weapon_icons"
EXTRACT = r"H:\pcvr-extracted"
BLENDER = ROOT.parent / "lone_echo_blender"

#: combat levels (as collect_for_claude.py) -- the arenas, plus whatever else holds UI
COMBAT_LEVELS = {"42670f2bed45703c", "43e2da7914642604", "43e2da7a0c623a19",
                 "cb9977f7fc2b4526", "df5ca7b7dfa383d4"}

GEAR = {
    "weapons": [("assault", "PULSAR"), ("blaster", "NOVA"), ("scout", "COMET"), ("rocket", "METEOR"),
                ("magnum", "PROTOSTAR"), ("smg", "QUARK"), ("chain", "BLAZAR"), ("rifle", "STARBURST")],
    "ordnances": [("det", "DETONATOR"), ("stun", "STUN FIELD"), ("arc", "ARC MINE"), ("burst", "INSTANT REPAIR"),
                  ("loc", "TRANSLOCATOR"), ("dot", "DOT FIELD"), ("drone", "DRONE")],
    "tacmods": [("heal", "REPAIR MATRIX"), ("sensor", "THREAT SCANNER"), ("shield", "ENERGY BARRIER"),
                ("wraith", "PHASE SHIFT"), ("smoke", "UMBRAL VEIL"), ("buff", "POWER BOOST")],
}
MAX_COPIES = 25
MAX_BYTES = 48 << 20


def name_variants() -> list:
    out = set()
    for items in GEAR.values():
        for name, display in items:
            for n in (name, display.lower(), display.lower().replace(" ", "_")):
                out.add(n)
                for fmt in ("icon_{}", "{}_icon", "weapon_{}", "ui_{}", "icon_weapon_{}", "hud_{}",
                            "loadout_{}", "gear_{}", "{}_weapon", "mp_weapon_{}", "ui_icon_{}"):
                    out.add(fmt.format(n))
    return sorted(out)


def main(argv) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--extract", default=EXTRACT)
    ap.add_argument("--blender", default=str(BLENDER), help="lone_echo_blender checkout (its scripts/ is used)")
    args = ap.parse_args(argv[1:])
    root = Path(args.extract)
    scripts = Path(args.blender) / "scripts"
    if not root.is_dir():
        print(f"weapon icons: no extract at {root} (pass --extract)")
        return 1
    if not (scripts / "evr_ui_extract.py").exists():
        print(f"weapon icons: lone_echo_blender scripts not found at {scripts} (pass --blender)")
        return 1
    sys.path.insert(0, str(scripts))
    import evr_ui_extract as ui                     # noqa: E402
    import evr_texture_resource as tex              # noqa: E402
    from le_symbol_names import symbol64            # noqa: E402
    from evr_resource_types import UI_CANVAS_RESOURCE, resolve_type_dir   # noqa: E402

    names = {struct.pack("<Q", int(symbol64(n), 16)): n for n in name_variants()}
    canvas_dir = resolve_type_dir(root, UI_CANVAS_RESOURCE)
    canvases = sorted(ui.canvas_hashes(root))
    print(f"weapon icons: {len(canvases)} canvases in {canvas_dir}")

    # where each canvas is placed, and per-placement texture overrides
    levels_of = defaultdict(set)
    override = defaultdict(set)
    for level in ui.levels_with_ui(root):
        try:
            for p in ui.placements(root, level):
                levels_of[p.canvas].add(level)
                if getattr(p, "texture", ""):
                    override[p.canvas].add(p.texture)
        except Exception as exc:                    # one odd level must not stop the rest
            print(f"   level {level}: {exc}")

    tex_info = defaultdict(lambda: {"canvases": set(), "hits": set(), "combat": False, "elements": 0, "levels": set()})
    for c in canvases:
        path = next((p for p in (canvas_dir / c, canvas_dir / f"{c}.bin") if p.exists()), None)
        data = path.read_bytes() if path else b""
        hits = {n for b, n in names.items() if b in data}
        try:
            canvas = ui.read_canvas(root, c)
        except Exception as exc:
            print(f"   canvas {c}: {exc}")
            continue
        if canvas is None:
            continue
        per_tex = defaultdict(int)
        for e in canvas.elements:
            per_tex[e.texture] += 1
        for t in override.get(c, ()):
            per_tex[t] += len(canvas.elements)
        for t, n in per_tex.items():
            info = tex_info[t]
            info["canvases"].add(c)
            info["hits"] |= hits
            info["elements"] += n
            info["levels"] |= levels_of.get(c, set())
            info["combat"] |= bool(levels_of.get(c, set()) & COMBAT_LEVELS)

    def score(item):
        t, i = item
        return (len(i["hits"]), i["combat"], i["elements"])

    ranked = sorted(tex_info.items(), key=score, reverse=True)
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.iterdir():
        if old.is_file():
            old.unlink()
    try:
        from PIL import Image                       # optional previews
    except Exception:
        Image = None

    lines = [f"{len(canvases)} canvases, {len(tex_info)} atlas textures; name hits = gear names found in "
             f"the canvases that use the texture; combat = used in a combat level", ""]
    copied = 0
    for t, i in ranked:
        note = ""
        if copied < MAX_COPIES and (i["hits"] or i["combat"]):
            try:
                blob, how = tex.rebuild_dds(root, t)
            except Exception as exc:
                blob, how = None, str(exc)
            if blob and len(blob) <= MAX_BYTES:
                (OUT / f"{t}.dds").write_bytes(blob)
                copied += 1
                note = f"copied ({len(blob) >> 10} KB)"
                if Image is not None:
                    try:
                        im = Image.open(OUT / f"{t}.dds")
                        im.thumbnail((1024, 1024))
                        im.save(OUT / f"{t}.png")
                        note += ", png"
                    except Exception as exc:
                        note += f", no png ({exc})"
            else:
                note = f"not copied: {how if not blob else 'too big'}"
        lines.append(f"{t}  hits={len(i['hits'])} combat={'yes' if i['combat'] else 'no'} "
                     f"elements={i['elements']} canvases={len(i['canvases'])} levels={len(i['levels'])}  {note}")
        if i["hits"]:
            lines.append("      names: " + ", ".join(sorted(i["hits"])[:20]))
        lines.append("      canvases: " + ", ".join(sorted(i["canvases"])[:12]))
    (OUT / "report.txt").write_text("\n".join(lines) + "\n")
    # the canvases behind the top candidates, for reading the icon rectangles
    for t, i in ranked[:MAX_COPIES]:
        if not (i["hits"] or i["combat"]):
            continue
        for c in i["canvases"]:
            src = next((p for p in (canvas_dir / c, canvas_dir / f"{c}.bin") if p.exists()), None)
            if src:
                (OUT / "canvases").mkdir(exist_ok=True)
                shutil.copy2(src, OUT / "canvases" / c)
    print(f"weapon icons: {copied} candidate atlas texture(s) copied to {OUT} (see report.txt)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
