# Handoff: where things stand

Branch `claude/zealous-wright-z8znnu`. Deploy with `tools/deploy_and_launch.py`.

## Working
- UMBRAL VEIL (smoke tac mod), networked through `VeilNet.dll` (`plugin/veilnet.cpp`, `tools/veil_fx.py`, `tools/fix_smoke.py`).
- POWER BOOST (buff tac mod), `tools/fix_buff.py` + `PowerBoost.dll`.
- Gear icons (`tools/gear_icons.py`, art in `ICONS/hd`).
- TRANSLOCATOR teleport effect + sound (`tools/fix_loc_fx.py`; sound event added by `tools/veil_sound.py`).
- POINT (`tools/fix_point.py`, wall mode in `veil_fx.network_wall(point=...)`, `VeilNet` 'P' packets):
  stun works, effect goes off as the wall appears (show node), barrier sounds muted on POINT walls.

## Open
1. **POINT sound**: was silent (the events tried were *stop* events). Now plays arc mine event
   `0x9B54488D` (stops its hum, plays the detonation). Untested. `--point-sound-preview` cycles
   `veil_fx.ARC_EVENTS` one per use.
2. **POINT icon on the equipment station** (grid and big panel) is empty; the HUD shows it.
   Adding an element and reusing `GRENADE_MINE` did not help, so the station's UI script likely
   picks the element from a list without POINT. `collect_for_claude.py` now searches for scripts
   naming `ABILITY_*` elements / listing ability types: run it, then find that list.
3. **Quick tap deploys an energy barrier** for UMBRAL VEIL and POINT (also POINT's 3rd use right
   after recharge). The wall took no token. Suspects: another wall consuming the token, or a pooled
   wall keeping its old decision (`[[ctx]+68h]+158h`). Needs `VeilNet.log` (client + server) from a
   repro: it logs every use and every wall's decision.
4. **POWER BOOST -> OVERCHARGE look**: user wants an offline preview of Repair Matrix's visuals
   reconstructed from game data, then to recolour from there.
   - Visual inventory (from the heal script 6a0f689e5b91c666): `fix_buff.PREVIEW_GROUPS`.
   - `tools/collect_visuals.py` (run by `collect_for_claude.py`) copies every asset they use and
     writes `data/extract/visuals.txt`. Run it on the full extract, then build the preview.
   - In-game helpers: `--buff-stock-visuals` (Repair Matrix look unchanged),
     `--buff-visual-preview` (one visual group per use).

## Notes
- Spare exe memory used (echovr.exe rva): veil tokens `0x2104CC0`, POINT tokens `0x2104CE0`,
  POINT sound preview counter `0x2104CF8`, buff visual preview counter `0x2104CFC`, node records
  `0x2104D00..0x2104FE8` (veil use counter `0x2104F00`, POINT use counter `0x2104F80`).
- Script DLLs embed debug symbols (S_PUB32 / S_GPROC32): function names and addresses can be
  read from the script asset itself.
