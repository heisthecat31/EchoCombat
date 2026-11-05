# Combat private-match rules: the paged screen (design notes)

Status 2026-11-04: page 1 works on the old Combat screen (tools/fix_rules_terminal.py,
tools/fix_capture_points.py, VeilNet's capture-time patch). This note is the plan for
moving Combat onto Arena's paged rules screen so a page 2 (classic gear, ...) is possible.

## Rules the user set
- Patch the STOCK levels' own data in the package. No new levels / .kfclvl exports.
- Do not open the EchoConstruct app. Its source (J:\EchoVR-Tools-Launcher\EchoConstruct)
  is a format reference only; the patching is Python in tools/, run by deploy_and_launch.
- Arena stays untouched: Combat gets its own copies (actor, settings file, canvas, script).
- Prototype on Dyson (mpl_combat_dyson, 43e2da7914642604) first, then Combustion, Gauss, Fission.

## How Arena does it (mpl_arena_a, 576ed3f8428ebc4b)
- Settings file: sourcedb/rad15/json/r14/config/uisettings/arena_private_rules.json
  (loose, shipped). "networked": true. pages[] of 4 rows; row types INT, INT FORMAT
  (printf "format"), FLAG, STRING ARRAY ("values", "idx"); "path", "name", "value",
  "min", "max".
- Actor mp_arena_rules_netsettings (e3b8354d79b3d383) with components
  CR15NetUISettingsCR (515bf2b6e2687c68; SR15UISettingsCD::SProperties, 88 bytes:
  name, actornodeid, actorid, numpooled, lookup_flags, component_flags, pad, then a
  child table "filename" = the settings file name), CR15NetVarCR (ac05e44816844a00),
  CR15NetIdCR (c29715d62e039402).
- Screen: canvas ui_display_mpl_mm_custom_rules_arena (f78023bba28da241, nested
  rulescanvas) driven by script 3c096b2c8606446d (BACK/NEXT, page_count, page_idx,
  left_1..4 / right_1..4 button presses, IncrementSetting / UpdateSetting / UpdatePage;
  reads mp_arena_rules_netsettings).
- Arena's mode script 08317e89cc3ae611 (mp_game_server_state) reads the same settings.

## What Dyson has
- Old screen: ui_display_mpl_mm_custom_rules1 (b655c5c7eaa080d7) + podium script
  d4653fc2065e8184. No netsettings actor, no CR15NetUISettingsCR resource at all.
- Per-level resources Dyson would need changed (sizes from H:\pcvr-extracted):
  CActorDataResource 282872, CTransformCR 973336, CComponentSpaceResource 1184,
  CR15NetVarCR 88, CR15NetIdCR 5592, CCanvasUICR 36136, CScriptCR 412392,
  CR15UIPageCR 336, CR15UILayoutCR 200, CR15ButtonInteractCR 153384, + a new
  CR15NetUISettingsCR resource (and its manifest entry).

## Formats (from EchoConstruct source)
- CActorDataResource: 784-byte header with 13 RadTable descriptors at
  {0,64,128,184,240,296,352,408,464,528,592,656,720}; bit counts at
  {520,584,648,712,776}. Slots: headers {nodeid, actor_index} 16/8, prefabgroups 64/8
  (nested table), nodeids 8, names 8, prefabids 8, transforms 48/4 (quat, pos, scale,
  2 pad), numpooled u16, parents u16, five bitfield word arrays.
  src/codecs/level_tables.cpp (decode/encode), src/codecs/include (codec_bytes RadTableDesc).
- Component tables: src/codecs/cr_table.cpp (generic), spec shapes in
  src/spec-registry/cr_shapes.gen.cpp (slots: lookup, bitwords, <props>, properties spine).
- Adding actors + components: src/persistence/kit_insert.cpp, kit_closure.cpp,
  src/codecs/level_table_patches.cpp. Stock screens: src/persistence/stock_kiosks.cpp,
  src/codecs/ui_canvas_add.cpp.

## Plan
1. Settings actor on Dyson: combat_custom_rules.json (page 1 = POINT UNLOCK, CAPTURE
   TIME, BLUE SCORE, ORANGE SCORE; page 2 = CLASSIC GEAR flag, ...), actor
   mp_combat_rules_netsettings with the three components. Test: Dyson loads, the
   settings exist and sync (read from memory).
2. Screen: copy Arena's paged canvas into Dyson's terminal, a renamed copy of
   3c096b2c8606446d that looks up mp_combat_rules_netsettings, its buttons, and the
   podium's RULES opening it instead of the old page.
3. Server: read the synced values and drive the existing mechanisms (mailbox: starting
   points, capture time, unlock), then the classic-gear rule (stock 12 only; hide new
   gear in the gear lists; players on new gear switched to stock).
