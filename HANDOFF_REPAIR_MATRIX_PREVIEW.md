# Handoff: offline preview of Repair Matrix's visuals (for OVERCHARGE)

## The goal

The user wants to **see Repair Matrix's visuals offline**: PNG renders (and/or an
interactive page) made by **mimicking how the game engine draws them**, built from the
game's own data. The user will then confirm "that's what it looks like in game", and
only after that do we change the colours / look for **OVERCHARGE** (the POWER BOOST /
`buff` tac mod, which is a copy of Repair Matrix, `tools/fix_buff.py`).

The user was explicit:
- **No more blind guessing.** Earlier, POWER BOOST was recoloured by guesswork (purplish
  red, `fix_buff.GOLD` / `TINT` / `FX_GOLD`) and they didn't like it.
- They don't want an in-game preview mode as the answer (one was built anyway:
  `--buff-visual-preview`, see below). They want offline images.
- Be honest about what is decoded and what is estimated: mark estimates on the page.

## What Repair Matrix draws (fully known, read from the script)

Heal script: `mp_combat_ability_heal`, `6eace9f64204fd0/6a0f689e5b91c666`. The visual
nodes, by group (also in `fix_buff.PREVIEW_GROUPS`, with each node's rva):

| # | Visual | Nodes (execute_node_…) | Data |
|---|--------|------------------------|------|
| 1 | Beam particle effect, one per linked teammate (slots 0-3) | ebf3c82c, 5826094f, 399b3d9b, 2856e91b | asset `39424707bb2df316`, attach component `64a149a1d3286ea4`, attachment `b1fda2a83f3debd1`, actor `38ee951a26fb816a` |
| 2 | Hand particle effect, two sizes (scale 2 with 0.75, and 1) | 1a9625fe, 0c3be456 | asset `be696d7d300cbaf7`, attachment `dc009aa0b878fd03` |
| 3 | Full-screen tint on (green) | d509f809, 02361d5d | rgba (0.6, 1, 0.6, 1), duration const 0.5; off nodes b05037dd, 396a3643 |
| 4 | Model `127705d644e32e78` enabled + its light colour | d424de2d (on), 0aa0bcf5 (off), e19ebcf5 (light) | light `ead4957b7d7e8a18`, colour ~(0.01, 1, 0.04), consts 0.04 |
| 5 | Model `9425ffc9d7797400` enabled + its light colour | d23ea09d (on), 3ba54f1a (off), cc7865b9 (light) | light `efdb3fb0bf8b5356`, same green |
| 6 | Material colours (4 nodes) | 95431717, 8c77c640, 85faf1a0, 3da7c452 | on `09f1312f49418925`, properties `cae7edfdaf2dcb52` / `1f7c1e4524cb3344`, `d2c1f7dae5a4c87f`; greens incl. 0.4627/0.298, 0.5911/0.2784, 0.5451/0.5906 |
| - | Transform scale reset to 1 | 5c5c55c0 | transform `2e84793fda0cd43b` |
| - | Sounds (5) | cf5b0a90, 9e8cfcf5, 80d6ac28, 56696be2, 277d3b1f | events 769791075, 1755268641, 3020475593, 2680418434, … |

How this was read: the script DLLs embed debug symbols, so node functions and class
methods have names and addresses. Helpers in `tools/re/` (see their docstrings):
`script_procs.py` (functions), `script_publics.py` (symbols), `node_graph.py` (the node
graph from next_node), `node_dump.py` (constants each node is built with). Use objdump
(`objdump -d -M intel`) on the DLL (the asset with everything before `MZ` cut off).

Tuning that shapes it: `ability_properties.heal` / `.buff` in `mp_weapon_settings`
(`11a8523ed4724ca7`), e.g. `heal_radius`, `len`, `init_angle`, `conn_angle`
(`fix_buff.link_tuning`).

## What is still missing (data)

Only the two particle effect files are in the repo (`data/extract/3ae7c41914252baa/`
`39424707bb2df316` 7788 B and `be696d7d300cbaf7` 1312 B, plus their companion assets in
`be45c22fa8c2d3f/`: 64 B half-floats for the beam, empty for the hand). Not collected yet:
- the textures / materials the effects reference. Candidate IDs inside the effect files:
  `2fc4968c4a715ada`, `2fda8a8c567144da` (in both), `33e09d033dfa9636` (recurs),
  `9b472c05055e622d`, `767ecbe8efd2b329`, `72ff6b409626c58e`, `3c23c0a43f13ad94`, …
  (found by scanning for 8-byte values; some may be packed floats, not IDs)
- the two models (meshes) `127705d6…` / `9425ffc9…`, their materials and textures;
  these names are *component* names, so they resolve through the player actor's
  component tables in the global level `3f9915d3001dc28e` (and combat levels).

**`tools/collect_visuals.py`** fetches all of it: from the seeds above it copies every
asset an ID names (any type folder), searches those assets for more IDs (4 levels), and
resolves component names through the levels' component tables. It writes
`data/extract/visuals.txt` (the tree). `collect_for_claude.py` runs it. **It must run where
the full game extract is** (the user's PC: `collect_for_claude.bat`, or a local Claude
Code session that reads the extract directly). On the partial files in the repo it only
found the two effects and one attachment record (`92abd3e1432bf5e8` tables).

## The particle effect format (only partly understood)

`3ae7c41914252baa` = particle effect, `be45c22fa8c2d3f` = its companion. Observations:
- +0x08 u64: a size/offset (0x1c8 for the hand effect, 0x8e8 for the beam).
- The start is a run of 0x38/0x40-byte array descriptors (`01 00 00 00`, `20 00 …`,
  counts, strides `08`, `28`, `20`, …), then blocks of floats and half-floats (e.g. at
  0x350 in the hand effect: 0.4, 0.8, 1, 28.0, 1.0, half-float colour triples like
  `9941 9941 9941` / `cc38 cc38 cc38`), IDs, and repeated `ffff…` sentinels.
- `fix_buff.gold_particles()` already finds and edits colours inside effect files (it
  scans for colour triples of several encodings); its scan is the best existing map of
  where colours live.
- `tools/fx_preview.py` lists the game's 81 effects (no names) and can show any of them
  in game on the stun mine, which helps to tell what a given effect looks like.

Approach that was planned: decode emitters (spawn rate, lifetime, start/end size, colour
over life, velocity, texture / atlas frames, blend mode) from the effect files plus their
textures; simulate the particles in Python (numpy) or an HTML/WebGL page; composite
with the models (green light / material colours) and the full-screen tint; render PNG
frames for each group (bubble around a player, beam to a teammate, hand effect, tint).
Label every parameter that is estimated rather than decoded. The real motion rules live
in `echovr.exe` (also in `data/extract/bin/`), so exactness depends on how much of the
particle runtime gets reverse-engineered there.

## In-game tools already built (for cross-checking the renders)
- `deploy_and_launch.py --buff-stock-visuals`: POWER BOOST looks exactly like Repair Matrix.
- `deploy_and_launch.py --buff-visual-preview`: use N of POWER BOOST shows only group N
  of the table above (counter at echovr.exe rva `0x2104CFC`, bumped as the bubble activates).

## Environment note
The earlier session ran in a cloud container with only the repo; it could not see the
user's game install or extract. A local session on the user's PC can read the extract
directly (and run `tools/collect_visuals.py --extract <extract root>` itself).
