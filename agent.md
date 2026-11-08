# EchoCombat: agent notes (handoff)

## CURRENT GOALS (2026-11-08)

### 1. F11 TEAM SWITCH on the game server: BUILT in EchoCombat-server only (2026-11-08, untested)

**User: server-side only, in `J:\EchoVR-Tools-Launcher\EchoCombat-server` (branch server-kit),
not main.** server-kit merged with main (a83b065). VeilNet there: F11 (Tick thread, server only)
opens a topmost Win32 window (list `name TEAM`, To BLUE / To ORANGE / To SPECTATOR, double-click =
blue<->orange, refresh every 2 s). The game thread (recvfrom hook, ApplyTeamSwitch) copies the
list and calls ServerAssignTeam(netgame, user, team) (+0x1AB730), result in the window's top line.
Players: lobby map netgame+0x138+k*4 {u16 user, u16 gen, 0xFFFF free}, user word
+0x178+user*0x250 (bits 0-4 lobby k, 10-12 team), names via GetUserName +0x1C98C0. build_veilnet.bat
links gdi32. Installed into H:\ready-at-dawn-echo-arena (old: VeilNet.dll.before_teamswitch).
Uncommitted. Not tested: whether the player respawns on the new team mid-match.

### 2.0.5 builds (2026-11-08, all uncommitted, none tested by me: user + a tester test them)

- **SERIES-10 ONLY, server side** (F11 tick box, server kit; user meant S10, the S11 attempt is
  reverted everywhere and "didn't work": it needed client mods). The game has its own replicated
  flag **net_standard_chassis** (0x29e261a1df774dd3, a CR15NetVarCS flag) that every stock client's
  LoadAndApplyItem reads (swaps chassis/booster/bracer to standard). Server sets it with
  CR15NetVarCS::SetFlag **+0xD45820** (revault calls it ValidateLoadoutRules; sys, handle, sym, u8),
  sys/handle at netgame +0x2E40/+0x2E48. ApplyStandardChassis (recvfrom hook) re-asserts every 250 ms
  while g_chassis_force or the podium's g_chassis is on (mp_game_server_state also writes the flag).
  Untested; shows from the next loadout apply (spawn).
- **nevr-pack 2.0.5**: `plugin/content.cpp` -> EchoCombatContent.dll (build_content.bat; nlohmann
  json vendored in third_party/nlohmann): NvrContentOverlay's job (CreateFileW/A + module loader
  +0xEB0F0, Detours), pack checks, refuses when loaded late or when NvrContentOverlay is loaded.
  `plugin/content_gate.h`: DroneFix/PowerBoost/VeilNet return 1 from InitEx when the pack isn't
  served or nevr-runtime.dll already hooks their functions. install_nevr_local.ps1 lists
  EchoCombatContent `early: true`, drops the overlay entry (DLL renamed .unused).
  release/EchoCombat-2.0.5.zip (+ mods.json, plugins include EchoCombatContent.dll) and
  release/EchoCombat-2.0.5-nevrlocal.zip. Launcher still forces the overlay: there our DLL stays off.
- **server kit 2.0.5**: release/EchoCombat-2.0.5.zip and release/EchoCombat/ rebuilt (all DLLs, main's
  2.0.4 stage). H:\ready-at-dawn-echo-arena has an earlier F11 VeilNet (no S11); user installs.

### nevrlocal tac mods broken: cause found (2026-11-08, player log J:\OperaGX\nevr-2026-11-08T00-45-57.968.jsonl)

Not the overlay: it loaded early and served (UMBRAL VEIL is in the tac mod list). The player's
**nEVR 6.17.0 has EchoCombat built in** (`[NEVR.COMBAT] module=dronefix / veilnet / powerboost`,
features combat.drone / combat.veil / combat.match_control on by default). It hooks first; then our
2.0.4 plugins load on top: DroneFix and PowerBoost fail their prologue checks and unload, VeilNet
loads half (sendto/recvfrom hooked twice, dispatch/equipment "unexpected build"). Two VeilNets
answer the same tac mod controller ("controller enabled" logged by both) and nEVR.EQUIP re-fires
the tac mod slot. The nevrlocal zip also ships NvrContentOverlay **1.0.0** (log: content_overlay
v1.0.0). Fix to make: our plugins stand down when nEVR's built-in combat module has the hooks
(a jmp at a target into nevr-runtime.dll).

Overlay removal (user asked): the launcher (EchoVR_Launcher packs.rs) reserves
NvrContentOverlay.dll, installs it itself and marks only it `early: true`; a pack's own plugins
load late (after the manifests are read), so EchoCombat can't serve its pack from the launcher
without a launcher change. nevrlocal could list our own early DLL instead.

### (old) F11 research notes

**User:** an experimental server-side tool. Press F11 on the machine running the game server and a
popup lists every user in that server. Click one to move them to the other team (blue <-> orange).

Design:
- Server-only plugin code (VeilNet already runs on the server, or a small plugin of its own). On a
  server only (`-server`); a client does nothing.
- Hotkey: poll `GetAsyncKeyState(VK_F11)` on a thread of its own, the way PerfCapture does F1. The
  server is headless, so the popup is our own Win32 window/dialog (a list box of
  `name - BLUE/ORANGE/SPEC`, then click or a button). It opens on the server machine's desktop.
- The switch itself must run on the game's main thread: queue the request and apply it from a
  per-frame hook. Never touch the lobby from the popup's thread.
- Apply it the way the engine does: call the server's own team assignment so the lobby entrant,
  the team slots and every client are updated, and the player respawns on the new team. Don't
  just write `teamIndex`.

Findings so far (revault, echovr.exe live PC build):
- Players: `Lobby::EntrantData` array at lobby +0x360 (HeapArray, stride 0xD8). Each entrant has
  displayName at +0x3C and teamIndex (u16, 0 blue / 1 orange / 2 spectator) at +0x8E.
  Source: nevr-runtime `src/abi/echovr.h`.
- Messages: `SR15NetUserAssignTeamRequest` / `SR15NetUserAssignTeamResponse`;
  `SNSLobbyEntrantTeamChanged` (symbol 0xceb8759c36184b82).
- `ServerAssignTeam`: the log string "[NETGAME] Server Assigning Team for '%s': %hu" is referenced
  from 0x1401ab814, inside the server's team assignment function. Its other log lines show:
  - same team: early out;
  - "Too many team members ... assigning to other team / spectator";
  - "user changed team so freeing its teamslot";
  - "Dequeing teamslot" / "Grabbing last teamslot";
  - it writes `user[%hu]|team` and `user[%hu]|teamslot`.
- "[NETGAME] UserAssignTeamRequestCB" is referenced from 0x1401c7dde: the server's handler for a
  client's team request (the stock CHANGE TEAM terminal).
- Next: decompile both. Find ServerAssignTeam's arguments (net game, user/entrant index, wanted
  team) and how the request callback calls it. Then call it from the main thread with the other
  team. A full team is the engine's rule: it moves the player to the other team or to spectator,
  so the popup should say so.
- Test: two installs (server + client, see `launcher-mod-sftp` traps), offline only when the user
  says so.

### 2. Sturdier VeilNet: stay off when EchoCombat's game data isn't served

**Why:** a player installed with `release/nevrlocal` (EchoCombat-nevr) reported that tac mods don't
work at all. The likely cause: the Echo VR launcher rewrote `%LOCALAPPDATA%\nevr\echovr\config.yaml`
at its start. With `x-local-plugins: true` it keeps DroneFix / PowerBoost / VeilNet but leaves
out NvrContentOverlay (the launcher has no record of the pack). The plugins then patch STOCK
scripts and data, and that breaks every tac mod, the stock ones included.
(The overlay reporting "loaded too late" would do the same.) Not confirmed: the user hasn't
sent their config.yaml or log yet.

**Want:** VeilNet (and DroneFix / PowerBoost with it) checks that the EchoCombat content is
really the game's data before it installs any hook or byte patch. If it isn't, it installs
nothing, logs one clear line ("EchoCombat's content isn't served: plugins off, stock game"), and
the game stays stock. Ways to check, cheapest first:
- the loaded script DLLs: `bin/win10/scripts/<hash>.dll` as the game mapped it, or the overlay's
  served copy. Compare a byte we patch (e.g. a cave in 6fa8cc9cd721a563 / cff4557b7d2ce426)
  against the EchoCombat build. Do this before the first patch, and again when scripts load,
  because scripts load per level;
- nEVR's plugin-query API (N134): is `content_overlay` loaded, with `active` = echocombat;
- a marker resource in the pack that the plugins look up.
Ship it in both lines (main + nevr-pack). The nevrlocal installer could then also warn when
config.yaml lists our plugins without the overlay.

## PARTY GUNS (CONFETTI / BUBBLE / MONEY GUN): UNFINISHED, HIDDEN (2026-11-05)

**User (2026-11-05): hide all three, mark unfinished.** `tools/fix_party_guns.py`
`PARTY_GUNS_SHOWN = False` keeps them out of gear_table.weapons, so no loadout terminal lists them and
nothing hands them out (the celebration-room assignment was never built). Everything else stays
built and is inert without them. Last in-game state: confetti fires once per pull with 3 s between,
no flash/flame/light/sound; the motion was still "static" for the user (last try: launch 0.4-1.8 m/s,
drag 0.3, untested). To resume: set PARTY_GUNS_SHOWN = True.

The RULES terminal work below is done and confirmed in game (team ready-up, PAUSE, map switch
terminal with 3 buttons). The "very last thing" (user) is Collin Harris' end-of-round FX idea
(https://collin.fyi/echo-combat, "End of Round Celebration Effects"; reference GIFs in
`docs/party_guns_ref/`: confetti_blue, confetti_orange, bubble_gun, money_gun).

**User spec (binding):** in the celebration room everyone ONLY gets a gun: the Pulsar, 0 damage,
no bullet, no muzzle flash; each click (one shot every 2.5 s) bursts confetti out of the barrel
with a small confetti sound. Confetti: blue/purple for blue, orange/red for orange (each piece its
own shade, as in the GIFs: a ~1.5 m forward stream, gone in 1-2 s). One random player per team
gets the BUBBLE GUN, another per team the MONEY GUN, everyone else CONFETTI. For now all three
are on the loadout terminal so the user tests in the Combat lobby (mpl_lobby_b_combat).

**Rules for working on it:** "work offline" = no game launches at all (no clients, no servers) until
the user says so. Preview effects OFFLINE with `tools/rm_preview` (render_billboards.py), not by
launching the game. Bubbles: reuse EchoPorting's converted Summer lobby bubble effects if no old
build has them (old PC builds checked: no party-gun effects exist). Money: a new bill texture.

**Built (uncommitted):**
- `tools/fix_party_guns.py`: confetti_gun / bubble_gun / money_gun in gear_table.weapons before
  medigun (VeilNet trims MEDIGUN as the last entry); the round-win confetti resources added to
  the lobby / Fission / Gauss level archives (copied from Dyson's).
- VeilNet: `kPartyGuns` always allowed by the LOADOUTS swap (ClassicSwap reset any unknown gun to
  PULSAR: that was why they could not be picked).
- PowerBoost: Hooked_Slot reads them as "assault" at the enable manager (the player holds the
  Pulsar); item catalogue hooks (purchased 0x177860 -> 1, unlock levels 0x178500/560/5c0 -> 0:
  the station treated unknown items as locked); Hooked_GunFire lets one shot through per 2.5 s;
  local bullet dropped for 300 ms after it (Hooked_BulletSpawn on 0xce2020, chained on DroneFix's
  jmp); Hooked_Apply (server) drops party-gun hits; PartySwap in the CreateParticleEffect node
  handler **0xdda7f0** (read from a loaded script's `?nodefunction@CREATEPARTICLEEFFECTNODE` slot;
  0x10aba30 is a different node class): node data = thread+B0h: +0 effect, +24h rot (deg),
  +30h scale, +48h attached actor (the gun actor + 1, its model), +B8h the team tint pair;
  the Pulsar's breaker flame (5859d9f1deba8f62) is scaled to 0 for party guns.
- `tools/rm_preview/render_billboards.py`: offline billboard renderer (game shaders move the
  particles; material/blend estimated). `tools/rm_preview/party_fx.py`: gun-sized burst copy of
  the round-win confetti (fx_party_confetti_orange 3116554e1e6b17b3 / _blue 31121feed13ae191:
  64 max, 50-70 per shot, 5 cm box, 30 deg cone, 3-6 m/s, 1.5-2.5 s life). Shader dumps:
  `particle_shaders.py --src H:/pcvr-extracted/77fc096173af254c --only <graph>` and
  `--src .../635f6220ae85fd46` into `<shaders>/global`.

**State (2026-11-05 evening, working in game, uncommitted):** confetti fires from the Pulsar.
- `tools/fix_party_fx.py` patches the Pulsar script cff4557b7d2ce426 itself (caves asking PowerBoost
  via the RULES mailbox: +38h PartyEffect, +40h PartyGunActor; the gun actor is script instance
  +3B0h, NOT +3A8h = space id). Muzzle node (0x32384): party shot -> fx_party_confetti_<team>, other
  frames return 0 by the node exit 0x3246B (spawn nothing). 4 breaker nodes -> fx_party_empty, 3
  muzzle_flash_light_0 nodes -> a light name no gun has, shot sound (imm32 0x24624) -> event 1.
- PowerBoost: one shot per trigger pull, 3 s apart, by shaping the LibOVR trigger the game sees
  (60 ms pull); one burst per gun per 2 s; bullets dropped ([party] drop_bullet, default 1).
- Confetti = `tools/rm_preview/party_fx.py`: own piece sheets per team (BC7) + own numbers in the
  round-win container 1432f4f2b0f840df. Param blob (system array +18h): +16h alpha, +2Ch brightness,
  +56h drag, +5Eh/+8Eh fall along -Y, +64h size, +6Ch/+78h/+84h rgb, +92h..+A6h noise (halves).
  Emitter +44h/+48h = re-burst interval (16 s stock: looked like the gun firing by itself).
- Offline preview: render_billboards.py with a root holding the effect + textures as plain DDS;
  shaders from particle_shaders.py (635f6220ae85fd46 -> global, graph 8c13dbccabbf7ae3).

**Wrong turns (party guns):** swapping CreateParticleEffect data+0 at state 1; a separate party
script component (never hears the trigger: only `ncaScript` does); the Pulsar dispatcher (0x17180)
handing nodes to a copy's dispatcher (gun stops firing even with an identical copy); nodes returning
0 at entry or -1 (early exit) -> graph stalls / auto-fire; an empty effect on non-shot frames (the
node's single effect slot replaces the confetti); dropping shots in GunFire (the script queues them
and fires them later).

**Open / next:** GIF-like motion test (drag 5, speeds 1.5-10, no noise); confetti sound (none in the
banks); bubble + money effects; celebration-room-only + random per-team assignment; confetti is
attached to the gun (moves with it).

Keep this file current: findings with their evidence, dead ends under **Wrong turns**. The
design notes for the paged screen are in `docs/combat_rules_screen.md`.

## State (2026-11-04)

**Nothing for the rules work is committed.** The user chose to skip the commit and go
straight to page 2. Rules-work files (all uncommitted):

| file | what |
|---|---|
| `tools/fix_rules_terminal.py` | podium script d4653fc2065e8184: Combat reads as Arena so RULES opens; canvas b655c5c7eaa080d7 rows renamed (MINUTES -> POINT UNLOCK, SECONDS -> CAPTURE TIME), `:00` pieces blanked |
| `tools/fix_capture_points.py` | game-mode script 6fa8cc9cd721a563 + capture-point script b7d10bcffcb2a780: starting points, unlock time, capture time via the mailbox (code caves) |
| `tools/fix_rules_netsettings.py` | adds actor `mp_combat_rules_netsettings` (settings file `combat_custom_rules`) to Dyson's stock level data |
| `tools/level_actor_table.py` | level actor table codec (32/32 stock levels byte-exact) |
| `config/combat_custom_rules.json` | the paged rules file (page 1: POINT UNLOCK, CAPTURE TIME, BLUE SCORE, ORANGE SCORE; page 2: CLASSIC GEAR flag). Deploy copies it into `sourcedb/rad15/json/r14/config/uisettings/` |
| `plugin/veilnet.cpp` | capture-time frame scaling, 'R' packet (server -> clients: rules T), instant capture |
| `tools/deploy_and_launch.py` | runs the three fix scripts, installs the rules JSON, checks the new resource |
| `docs/combat_rules_screen.md` | design notes / formats |
| `data/extract/...` (new dirs) | stock copies of the patched scripts, canvas and level resources |

**Not ours, never commit:** `data/gunpatch/607d858c90268f9a/11a8523ed4724ca7` (user's weapon
settings, currently has invalid `00` values) and its `.bak`, `plugin/loader.cpp`, `ICONS/hd.zip`.

## Confirmed working in game (old Combat screen, page 1)

- RULES button opens in Combat private matches.
- BLUE / ORANGE SCORE = capture-point starting points (75 wins; HUD shows points/100 as %).
- POINT UNLOCK = seconds until the point unlocks; announcer "point unlocking in" and the 5..1
  countdown follow it on every client.
- CAPTURE TIME = seconds to fill the bar; 0 = instant.

## How it works

- **Mailbox** = spare bytes after echovr.exe `.data` (page_end - 0x20 = 0x2104fe0 on the
  current exe; veil uses page_end - 0x10). `+0` blue float, `+4` red float, `+8` T =
  unlock*60 + capture (float, 0 = unset -> map defaults 45 / 4), `+0xC` capture float.
  Script caves reach the exe base through the PEB (`gs:[60h]` -> `+10h`).
- 6fa8 handler writes store T and T mod 60. b7d10 reads of `capture_point_lock_time` (+0xEC)
  are patched to T/60 (patching the reads worked; there are too many writers).
- **Capture speed:** VeilNet patches the capture-volume tick (echovr+0xD649C6) on the server:
  frame time *= vol+0x48 (map time) / capture. Changing vol+0x48 or the compare only =
  "fills normally, then sits at 99".
- **Instant capture:** VeilNet (server, every tick) writes 0.001f to `+0xC` while T is set
  and T%60 == 0. The 6fa8 write cave can't grow: `.text` has no address space left.
- **Unlock audio is client-side.** b7d10 countdown +0xDC = lock_time - (now - start +0xF4)
  and the script builds `"lock_countdown_feedback_" + ceil(countdown)` events to itself
  (7 = "point unlocking in", 5..1 = countdown VO, 16 = music). Clients never had T (only the
  server's handlers write it), so they counted from 45 s. Fix: the VeilNet server sends 'R'
  (id = T float bits) with every hello answer; the client copies it to its `+8`.
- Known gap: unlock 0 + capture 0 = T 0 = treated as unset.

## Next: page 2 (step 2 of `docs/combat_rules_screen.md`)

User decisions, binding:
- Use **Arena's paged rules screen** (canvas f78023bba28da241, script 3c096b2c8606446d,
  settings actor `mp_arena_rules_netsettings`). **Arena must stay untouched**: Combat gets its
  own copies.
- **No new levels / .kfclvl**: patch the stock levels' own data in the package.
- **Do not open the EchoConstruct app** (its source at `J:\EchoVR-Tools-Launcher\EchoConstruct`
  is fine as a format reference).
- Dyson first (mpl_combat_dyson 43e2da7914642604), then Combustion 42670f2bed45703c,
  Gauss 43e2da7a0c623a19, Fission df5ca7b7dfa383d4. Arena = mpl_arena_a 576ed3f8428ebc4b.
- Full screen (the paged one), not the old one extended.

Done: step 1, the settings actor on Dyson (server memory showed the parsed file).
To do:
1. Copy Arena's paged canvas into Dyson's terminal; a renamed copy of 3c096b2c8606446d that
   looks up `mp_combat_rules_netsettings`; its buttons; the podium RULES opening it.
   Resources likely touched: CCanvasUICR, CScriptCR, CR15UIPageCR, CR15UILayoutCR,
   CR15ButtonInteractCR, CTransformCR (sizes in the design doc).
2. Server applies the synced values (write the mailbox from the settings).
3. **CLASSIC GEAR** rule: only the 12 stock items (Pulsar, Nova, Comet, Meteor; Repair Matrix,
   Threat Scanner, Energy Barrier, Phase Shift; Detonator, Stun Field, Arc Mine, Instant
   Repair). Hide new gear in the gear lists (weapons 0x20d3420, ordnances 0x20d3428, tac mods
   0x20d3430; VeilNet already trims lists by count for MEDIGUN / tac mods); switch players on
   new gear to stock.
4. Extend to the other Combat levels.

### Findings for step 1 (2026-11-04, nothing written yet)

- **Arena's paged screen is Arena's whole podium**, not a canvas on a podium. Prefab
  11e16a275c42efb3 (blue, at 0,-3.42,73.4) and 390a5b6d9ed1df24 (orange), 51 actors each:
  root (script ed165e99b0031ae5 mpl_arena_match_rules_page_sm, actordata -> the two pages),
  85e862909281f035 team options page (dce0b402b8a996b5), d1716acaee4ac823 rules settings page
  (3c096b2c8606446d; actordata -> d027b0076ee8a721, d74886e696e6f031, root, canvas
  808c79fab7c4a9e1), layout groups d027 (2 buttons), 30e056 (4), d74886 (8 row buttons).
  Each button = 3 actors (button / press part / label canvas) with CInstanceModelCRx2,
  CComponentLODCR, CFrustumCullCR, COcclusionCullCR, CBoundingSphereCR, CR15ButtonInteractCR,
  CR15UILayoutCR, script prp_itt_screen_button_logic 55e66d39171b2ba3 (actordata -> press part,
  label, its layout group, projector e08125b8d0a3be07).
- **Dyson's podium** 0612e085c1afbe86 (prefab badf50087a4cc6c9; orange 1791ee4df29ab404,
  prefab a9b1a136b8c473b8): 17 actors, script mpl_arena_match_podium_manager (d4653), 3 holo
  buttons (prp_itt_holo_button_station_logic) + **10 private holo buttons**
  (mpl_mm_holo_private_btn_logic; CModelCR + CAnimationCR, no instance models), rules canvas
  e1851cd39d3b9f57.
- CScriptCR codec: 720-byte records, then per record 12 child tables in order (realdata ...
  assetelementdata), each aligned; actordata rows are 32 bytes {key, -1, actor nodeid, 0}.
  Walk ends at EOF on both levels (scratchpad script_cr.py; not in the repo yet).
- Script DLLs are not in revault; their strings are all hashed.
- Copying Arena's kiosk means writing a generic actor-subtree copier over ~20 component
  types, including render/culling data (instance models, LOD, frustum/occlusion cull). That is
  what EchoConstruct's kit system does. Asked the user: full copy vs paged canvas on Dyson's
  own podium with its 10 holo buttons.

### Page 2 on Dyson's own podium (2026-11-04, tools/fix_rules_pages.py, installed, uncommitted)

Works in game: RESTART reads NEXT on the rules page and flips the page; page 2 hides the row
labels (HideMenuSettingsLabels with its value nodes skipped) and row 1's value reads
"CLASSIC GEAR ON/OFF"; row-1 -/+ asks VeilNet ('C') and the server echoes ('G') to every
client (checked live: classic=1 after one request). RULES/BACK reset to page 1.
- **Never write the row label items (custom<N>a)**: every way tried (second pass in the node,
  separate thread steps, page byte only) made the canvas texts jump between rows at random.
  Value-only writes are stable. Writing NEXT on the button canvas is fine.
- The podium script's dispatcher inlines some nodes (3827adbc: MenuPage = 1): check
  `execute_node` jumps before hooking a node's function.
- Live check tool idea: read the RULES mailbox from the client with ReadProcessMemory
  (scratch peek.py); debug counters at mailbox +24h (NEXT flips) / +28h (label steps).
- Still to do: layout (user: row 1's right-aligned "CLASSIC GEAR ON" looks wrong; needs a
  static page-2 label element in the canvas, shown by alpha), and the rule itself.
- The rule: classic = the first 4 of each gear list (weapons assault/blaster/scout/rocket,
  ordnances det/stun/arc/burst, tac mods heal/sensor/shield/wraith; new: magnum, smg, chain,
  rifle, medigun / loc, dot, drone / smoke, buff, point). Hiding = VeilNet count trim (as
  for MEDIGUN). Switching a player off new gear: loadout terminal uses
  CR15NetPlayerSetEquipmentNode (Enter 0x140f32e80) -> deferred FUN_140d45990(equipment
  component, slot, item) which sets slot +0x28 and replicates; the client's selection goes
  out as "[NSUSER] sent profile update: {"weapon"|"grenade"|"ability":...}" (VeilNet hooks
  that log line already). Profile fields: ability / weapon / grenade.

Open checks: the 2-3 s delay before the point notices a player (not UpdateClaims, not the
xmm7 threshold); whether override_game_timer (+0xFA) makes overtime copy override_time
(+0xA4) into the match clock.

## Build / test routine

- Build + install (close Echo first, install, relaunch; don't ask the user first). The user's
  gun patch file is invalid, so build from a scratch copy that holds HEAD's version: point
  `local.json` `gunpatch` at it, run
  `python tools/deploy_and_launch.py --gunpatch <scratch>/gunpatch --kill --no-launch`, then
  restore `local.json` (`--gunpatch` alone doesn't reach `echocombat_config.py`).
- Test: the user's relay up on port 777 (`J:\EchoVR-Tools-Launcher\EchoRelay`, db
  `J:\echo-summer-clean\DB`, needs admin; the user starts it). NOT `H:\Desktop\EchoRelay-main`:
  its db equips an unknown custom chassis, so the client spawns bodiless = black screen. Client `_local/config.json`
  pointing at 127.0.0.1:777, then
  `python tools/deploy_and_launch.py --launch-only --headless 2 "--client-args=-windowed -level mpl_combat_dyson -region euw -gametype echo_combat_private"`.
  The user goes to the terminal and checks.
- Shipped plugin DLLs write no logs; build with `/DECHOCOMBAT_LOG` to debug.
- Script disassembly helpers from this session (disasm_dll.py, edges.py, walk.py) were in
  the session scratchpad, not the repo. Name lookup:
  `H:\EchoVR\pc-latest\ready-at-dawn-echo-arena\_local\echo-symbols.json`.

## MEDIGUN (answered 2026-11-04)

**DISABLED (user, 2026-11-07):** `tools/fix_medigun.py` `MEDIGUN_SHOWN = False` keeps it out of
gear_table.weapons (no terminal lists it, whatever the server switch says), like the party guns.
Release 2.0.0 ships without it. Set True to bring it back (the server switch below then applies).

Off unless the server's build has `medigun.enabled: true` in `config/mp_weapon_settings.json`
(-> `PowerBoost.ini [server] medigun=1`; missing = off). The repo has `false`. Clients show it
only while their current server's answer carries the flag; a selected MEDIGUN elsewhere is a
plain COMET. It can show for up to 250 ms after load before the first check hides it.

## Wrong turns

- Hiding MINUTES with alpha: the script resets the colour. Superseded by POINT UNLOCK.
- Capture time by compare only / by setting vol+0x48: unresponsive point, stuck at 99, or no
  effect on clients. The frame-time scale works.
- Patching lock-time writers: the bulk loader (0x7B98) and others kept 45. Patch the reads.
- Growing the 6fa8 write cave for "0 = instant": no address space after `.text`.

## LOADOUTS (2026-11-04, replaces CLASSIC GEAR; installed, untested, uncommitted)

User decision: the page-2 rule is **WEAPON LOADOUTS: ALL / CLASSIC / NEW**, weapons only.
CLASSIC = Pulsar Nova Comet Meteor; NEW = Protostar Quark Blazar Starburst (+ MEDIGUN if the
server allows); tac mods and ordnances are never limited. Mailbox +11 = mode 0/1/2; row-1 -/+
step back / on (mod 3). Swaps: CLASSIC -> PULSAR, NEW -> PROTOSTAR; a server with MEDIGUN off
swaps MEDIGUN -> COMET at the slot setters.
- **Why trimming the gear lists never changed the equipment station:** the station reads the gear
  type table `*(echovr+0x20d3440)` (3 rows of 98h: +00 list header ptr, +08 item count, +10 name,
  +50 sym, +58 display), filled once by +0xC4EBA0 with the counts the lists had at load. VeilNet
  `StationView` now writes the row's count, and for NEW points the row at a header of its own
  (entries + 4 items). Unverified: that the station reads the row (not the list) for both.
- Bug found in test: StationView matched a row by "points at our own header" for any list, so
  in NEW the ordnance update moved the weapon row onto the ordnance list (ordnances shown as
  guns; picking Arc Mine saved weapon "arc" -> CR15NetProfileSymbolLookup error). Fixed: own
  header remembers its list. Slot guard: a weapon that isn't one of the 9 guns -> PULSAR.
- User corrections: row text is "LOADOUTS: ALL/CLASSIC/NEW" (the long text overran the - button);
  CLASSIC = the stock 12 (tac mods / ordnances cut + swapped to REPAIR MATRIX / DETONATOR too);
  NEW = new guns only, every tac mod and ordnance.
- Station redraw: its script (e0fdfda9a944e8ff) runs setupicons on delegate_onlobbysettingsreceived
  (0xaf4b0aa6bf6e258a), raised by CR15NetGame::OnLobbySettings via DispatchEventToSession
  (+0x1A9FE0, (netgame, event)). VeilNet hooks it to learn the net game and re-raises that event
  from the recvfrom hook whenever StationView changed a row. Before this, the grid only redrew on
  pressing change-gun (stale cells, overlapping icons).
- Tested: LOADOUTS works (user). Then: overlapping station icons = several redraws at once (one per
  changed row, setupicons threads overlapped) -> one redraw 400 ms after the last change. Row text
  centred with trailing spaces (value field is right-aligned): "LOADOUTS: ALL   " etc. Untested.
- Overlap was NOT concurrency: setupicons only visits cells 0..min(total_num + locks, max_icons)
  (d45bb367 / cece9480 counts; 53a83cf4 = idx < total+locks), so cells a longer layout used keep
  their old place. tools/fix_station_cells.py (e0fdf, in deploy after fix_rules_pages): position
  loop over max_icons; 34396d3 newposition -> (1e5,1e5) when cell idx >= mailbox[0x14 + type]
  (VeilNet StationView writes count + 1 lock). Cells are named by type + index (lookupicon), not
  by list item. Untested. e0fdf stock copied into data/extract.
- Still overlapping CLASSIC->NEW + first cells showing the empty lock: each grid cell
  (<type>_icon_<n>) holds one element per item + lock + frame; setupicon only shows the current
  item's, never hides the previous. VeilNet now hooks CCanvasUICS::SetAlpha (+0x37B2D0: cs,
  comp index, key, float alpha) for the 900 grid item/lock keys (plugin/station_icon_keys.h from
  tools/station_icon_keys.py over the staged station canvas), keeps those shown, hides them all
  right before each redraw; one redraw also after each level load (new type table). Untested.
- User: station grid fixed. Loadout bar (3 icons on the station's front) overlapped after the auto
  swap. No other canvas has an element index, so that bar is assumed to use plain element keys
  (CSymbol64("WEAPON_ASSAULT") ...): VeilNet's SetAlpha hook keeps one shown gear icon per kind per
  (canvas system, component) and hides the previous one (kGearElements in station_icon_keys.h).
  Unverified that the bar's keys are plain; if it still overlaps, find the bar's script/keys.
- Blank bar gun icon CLASSIC->NEW (log build, out_log\VeilNet.dll): the bar's script hides every
  gun of the station row and shows the one in hand only if it is in the row; VeilNet swapped to
  PROTOSTAR on the rule change while the rows were still CLASSIC's (list update came 140 ms later
  from the tick thread). Fix: UpdateGearLists() (lock-guarded) runs on the game thread before
  EnforceLocal. The bar's keys ARE plain element names (WEAPON_assault ... confirmed in the log).
- RULES / BACK slow (user: NEXT fine): the press chain ran menupage*_on/off before
  mainmenutransition, and menupage1_off/on run 8-9 activate/deactivatebutton calls (each two
  EXTERNALFUNCTION calls btn_on/btn_enable on the button actor) before Show/HideMenuSettingsLabels.
  fix_rules_pages.py PRESS_ORDER (table-driven in the next_node cave; d4653 .text has ~170 bytes
  left after it): transition first, old page's buttons off, then the new page's; while a press
  runs (mailbox +17h: 1 BACK, 2 RULES, set at the MenuPage check) the labels go first inside
  menupage1_off/on. NEXT keeps the stock exits (flag clear). Untested.

## SERIES-10 ONLY (2026-11-04, rules page 2 row 2; installed, untested, uncommitted)

User: "Series-10 Only" on/off; everyone's chassis shown as rwd_chassis_body_s10_a.
- Rule: server g_chassis; 'G' id = LOADOUTS (bits 0-1) | S10 (bit 2); client shows it at mailbox
  +2Ch. Row-2 -/+ (custom_rules_btn_right_2 ec7326ac / left_2 73d7f40b) write +13h = 80h | !shown,
  +12h += 1; VeilNet sends 'C' with 80h|v.
- Swap: client hook on ApplyItem (+0xCABF10: cs, player idx, item sym, slot sym, int flag; also logs
  "Apply Chassis %s for user %s"); any rwd_chassis_* item (32 syms from echo-symbols) -> s10. Last
  chassis call per (cs, player) kept; rule change re-applies them on the game thread.
- d4653 .text: 2918 of 2963 bytes used now; almost nothing left for more page code.
- First test: no change; game log "Item rwd_chassis_body_s10_a not loaded while trying to apply":
  ApplyItem only applies loaded items. Moved the swap to CR15NetCustomizationCS::LoadAndApplyItem
  (+0xD0D170, same args; loads then applies; the game's own net_standard_chassis swap sits at its
  top). ApplyItem called directly with another chassis is redirected to LoadAndApplyItem(S10);
  rule changes replay through LoadAndApplyItem. Untested. Check r14logs for "Load and apply".

## POINT RATE (2026-11-04, rules page 2 row 3; installed, untested, uncommitted)

User: multiplier on how fast a held point's points rise; steps 0.25 0.5 0.75 1.0 1.25 1.5 1.75
2.0 5 10 (x). Points (blueteamcharge +F8 / orangeteamcharge +F0) rise in b7d10 expressions
5cd8c247 (blue) / 76d52a0f (orange): points + dt * rate (rate +E4 holding / +E0 on point, picked by
the script), dt = [thread+50h] us / 1e6. tools/fix_point_rate.py: after each divss, dt *= mailbox
+2Dh / 4 (0 = unscaled). VeilNet: server g_rate (quarters, default 4), 'C' 40h|up, 'G' bits 8-15;
client writes +2D and the row text (static buffer, pointer at mailbox +24h; the page's two debug
counters there were removed). Row 3 -/+ = right_3 9dfc89dd (up) / left_3 8eae68db (down).
d4653 .text: 2930 of 2963 bytes used.
- User: steps now 0.25..2.0 then 2.5 (no 5x/10x). Skipping steps = the client sends each 'C' twice
  (against loss) and POINT RATE was sent as a relative step; now the client sends the target value
  (40h | quarters << 8), so duplicates are harmless (LOADOUTS / SERIES-10 were already absolute).

## PAUSE / UNPAUSE (2026-11-04, research done, nothing built)

User spec: like Arena private matches, TEAM READY becomes PAUSE / UNPAUSE once both teams are
ready. Pause: everyone back to the war room, no guns / tac mods / ordnances, points and capture
frozen, the pre-match orbs back; unpause: orbs back to the round's behaviour. Defaults taken
(user did not answer): anyone can pause; orbs act as pre-match while paused; the unlock countdown
freezes too; unpause resumes at once.

Findings:
- Combat podium (d4653) has no pause (Arena's pause is Arena's own podium). TEAM READY =
  readybuttonpressed a73a9a4f -> teamready 656dc962 -> nevt_blue/red_team_ready. updateall disables
  middle_palm_btn_a via expression e5264bb8: (own team's netflag blue_team_ready / red_team_ready,
  team by data +1B2) or spectator.
- Orbs: spawn point script e57332952e1cd478, handlespawnaccess 558b94a2 -> node ee90948d (rva
  0x104c0) reads netsymbol spawn_access (0x9de606e496cee8a3, published by 6fa8 +C0) and switches:
  pre_match / team_room / 541c3aa06a228bee / main_loop / default. Patch point: 0x10524
  `mov r8,[rsp+28h]` (the value) -> if paused, r8 = pre_match.
- Cease fire: netflag combat_cease_fire read by every gear script; set by
  mp_combat_weapon_access_controller (d44f62ba114f0cde) on nevt_to_server_enable/disable_combat_
  cease_fire (6fa8 sends them with SENDEVENTGLOBAL).
- SENDEVENTGLOBAL = DispatchComponentEvent(space, event, -1 actor, -1 comp, 1), the same call
  CR15NetGame::DispatchEventToSession (+0x1A9FE0, hooked by VeilNet, client only so far) makes:
  the server can raise those events itself.
- War room: mp_player_teleport_manager (a6c3b7680e367a2c) handles nevt_force_respawn
  (queueplayerteleport reason force_respawn): each client raises it for its player on pause.
- Points: fix_point_rate cave can zero dt on a pause byte; capture progress: InstallCaptureTime
  stub can zero xmm6 on the pause byte (mailbox +2E free).
- d4653 has 33 bytes left: the button needs either a text table through VeilNet (move the page-2
  strings out, ~130 bytes back) or a new PE section.
- BUILT (2026-11-04, untested): VeilNet pause rule (+2E, 'C' 20h|v, 'G' bit 3), ApplyPause on the
  game thread (server: DispatchEventToSession cease fire on/off; client: nevt_force_respawn;
  TEAM READY label through a CCanvasUICS::SetText hook (+0x37D470) that records where
  "TEAM READY" was written), capture stub zeroes the frame time while paused, page-2 texts now a
  VeilNet table (mailbox +24 -> 3 x 48 bytes) instead of script strings; fix_point_rate zeroes dt
  while paused; tools/fix_orb_pause.py (e5733 0x10524: +2F live, pre_match while paused);
  fix_rules_pages: e5264bb8 own-team test removed (0x2FB39 xor edx,edx), TeamReady node 656dc962
  cave: live -> ask 20h|!paused and end. Logging VeilNet installed on client + H: server for the
  first test (redeploy restores the normal one).
- Test 1: PAUSE label shown (SetText hook found 2 TEAM READY labels) but the button greyed: the
  podium disables middle_palm_btn_a in 6 places (each team's ready event, MenuPage0On fa59af35,
  UpdateAll e5264bb8, ...). fix_rules_pages now swaps those 6 call nodes' function id
  DisableButton d7552910 -> EnableButton 9252f6f0 (READY_DISABLE_CALLS).

### PAUSE: test 2 results and the NEW GOAL (2026-11-04, user decisions, binding)

Test 2 (logging VeilNet on client + H: server): PAUSE button press works after the
DisableButton->EnableButton swap. Pressing PAUSE: pre-match orbs come back and teleport works,
the player is sent to the war room, the gun disappears (cease fire works), capture stops.
Wrong: the round still "starts" (round start timer and the point-unlock announcer keep
running), UNPAUSE re-opened the orbs instantly, and passive points kept rising after unpause.

NEW DESIGN for UNPAUSE (user, replaces the earlier ideas; the "99% capture for the last owner"
idea is DROPPED):
1. On PAUSE, remember every player's position (user said "server remembers"; doing it per
   client for its own player is fine: each client owns its body). Players still go to the war
   room and get the pre-match orbs while paused (as now).
2. On UNPAUSE, teleport everyone instantly back to the position they had when the pause began,
   then LOCK them there for 5 seconds (no movement; e.g. re-teleport every frame), while the
   announcer says "Unpausing in 5, 4, 3, 2, 1".
3. After the 5 s: cease fire off (guns / tac mods / ordnances back), players can move, and the
   points / capture progress resume at the same moment (keep them frozen through the 5 s).
4. While paused the round start timer and the point-unlock countdown must not run (still open).

Pieces found so far:
- Teleport: CombatBots.dll already teleports with CncaGame::WorldTeleport (+0x100DB0:
  (game space, SActor, CTransfQ*, reason)); see plugin/combatbots.cpp TeleportBot for how it
  gets the space / actor and builds the transform.
- Announcer: Combat's announcer (mp_combat_voice_announcer 526ae906c49de696, bank
  03f1464db1fe49b5 mp_combat_voice) already has evt_vo_anc_countdown_01..10 (the capture point
  uses them after "point unlocking in"). Arena's pause countdown is driven by
  mp_announcer_client_countdowns (5db0735a60bb1093: nevent_game_paused, nevent_global_countdown_
  01..15, net_game_paused_state, net_game_pause_time) and voiced by Arena's announcer
  (mp_arena_voice 12220d7e7addffd5). The "Unpausing in" line must be found in Arena's voice data
  (PlayDialogueNode / string table) and added to Combat's bank the way tools/fix_vo.py adds
  callouts (event list in the announcer script 7c10e713aec2f12b, bank via veil_sound.py).
  A search for which assets hold nevent_game_paused / nevent_global_countdown_05 was running
  when this was written.
- Code space: tools/veil_fx.py has add_section (a new PE section); use it for d4653 (2925 of
  2963 bytes used) instead of squeezing .text.
- The normal (non-logging) VeilNet must be redeployed before shipping (deploy does it; the test
  copies came from out_log\VeilNet.dll).
- Search result: nevent_game_paused and nevent_global_countdown_NN appear only in
  mp_announcer_client_countdowns (5db0735a60bb1093) and mp_game_server_state (8317e89cc3ae611,
  nevent_game_paused only); nothing else listens for them. So that script voices Arena's pause
  countdown itself (it has PlayDialogueNode / WwiseEvent2DNode / StringTableEntry, "mp_arena_voice",
  "hera"): the "unpausing in" / countdown Wwise events are in its nodes, played from the Arena
  voice bank. Next: read its paused / unpaused branch (graph.py + trace.py on 5db0735a60bb1093) to
  get those Wwise event ids, then find the sounds in the Arena voice bank.
- User: there is no "unpausing in" line; just the 5..1 countdown. Use Combat's own
  evt_vo_anc_countdown_05..01 (Combat announcer lists them; raise them with
  DispatchEventToSession(netgame, sym) on each client, one per second).
- Planned state machine (not built): mailbox +2E = 0 running / 1 paused / 2 resuming (5 s).
  Server: UNPAUSE -> 2, after 5 s -> 0 ('G' carries 2 bits). Cease fire, point and capture
  freezes stay on while +2E != 0 (already "nonzero" checks); the orb cave must change to
  "== 1" so the orbs are normal while resuming. Clients in state 2: teleport to the saved spot
  every frame (the hold) and play the countdown.
## CURRENT GOAL (2026-11-05): MAP SWITCH TERMINAL - user said "Go ahead" with the 2-phase plan

Phase 1 = the terminal (6 buttons), phase 2 = the server + client map switch. Nothing built yet.
Done so far (phase 1 research):
- Terminal found. Canvas ui_display_mpl_arena_postmatch_podium 854a71f21a61be8f (type
  59a9bd6e4525ecc4, 941 bytes, one text: REMATCH). Script ui_podium_post_match_root
  1d84ff70cfdc110c: two palm buttons, layout "2_palm_button_layout"; left = LOBBY
  (left_button_press -> nevt_return_to_lobby_request), right = REMATCH (right_button_press ->
  nevt_match_restart_request); actors actor_switch_button_left / _right, actor_layout_root,
  actor_projector, actor_housing; labels via str_button_label_left / _right + extsetlabel
  (param_label); also enablepodium / disablepodium / EnableButtons / DisableButtons,
  ispostmatch / post_match / new_post_match, action_pending, game_state checks
  (post_match_celebration_*). Sections: .text 0x1000 vsize 0xF21D (next 0x11000: ~3.5 KB free),
  .rdata 0x11000, .data 0x14000, .pdata, .reloc.
Next steps:
1. Find the podium actors in the celebration level / prefab (which level holds the post-match room
   for Combat) and how the 2 buttons are laid out; decide how to get 6 (4 map buttons + REMATCH +
   LOBBY): likely new button actors (copy of the palm button actors) or reuse of another layout.
   NO new levels / no EchoConstruct app (binding rules from the RULES work still apply).
2. Map buttons -> VeilNet request to the server (new packet type), server -> everyone.
3. Phase 2 per the findings below (LoadMap / owner json "level"; clients need their own reload).
Test: Combat private match to the end (celebration room), then the terminal.

### Step 1 findings (2026-11-05)
- The post-match podium is in EVERY Combat level's own data (and Arena's): canvas 854a71f2 is in
  each level's archive + CCanvasUICR (822fd4ccb42e8a3c), script 1d84ff70 in each CScriptCR
  (d99f6bbd8009c92c). No separate celebration level.
- tools/script_cr.py: CScriptCR walker (record header 0x30, 12 descriptors of 56 at +0x30, child
  rows after all records, 8-aligned; ends at EOF on all levels tried).
- Dyson (actor indices in its actor table): root 1929 936cdaaf869beafb at (188, -15.44, 41.75)
  (CModelCR, CCanvasUICR, CR15UIPageCR, CR15NetIdCR, CScriptCR 1d84 = record 429, CSoundCR ...).
  Script actordata (4 rows): a6c9edd2 (1930, layout root: CR15UILayoutCR + UIPage + script),
  ceed21f5 (1939, projector: instance model + ActorLOD), 9dc44f75 (1940, housing: + CPhysicsCR),
  cd5002c9 (1942, CEventCR + region LOD). Buttons under 1930: 1931 (x 188.10) and 1935 (x 187.90),
  each = button (InstanceModel, LOD, frustum/occlusion cull, BoundingSphere, UILayout,
  ButtonInteract, script) -> press part (no UILayout) -> label canvas (CCanvasUICR,
  TextureOverride), plus a 4th actor (1934 / 1938, model + script only). All actors share prefab
  67b4090da34c2983; actor names are unset (0xffff...). Script actordata keys are not CSymbol64 of
  the names the strings show (actor_switch_button_left etc.).
- So 6 real buttons = copying 4 actors x ~10 component types per button (the same generic copier
  the RULES work avoided). User chose: copy the buttons (6 real ones).

### Button copier (2026-11-05, built + installed on C: and H:, UNTESTED)
- tools/cr_rows.py: generic single-table CR walker (port of EchoConstruct cr_ownership.cpp: 56-byte
  descriptor, rows owned at +8, per-type nested tables). 58 of 70 Dyson CR types walk; the failures
  are multi-table types (InstanceModel, StaticInstanceModel, Event, Model, Animation, ...).
- tools/instance_model_cr.py: CInstanceModelCR (568-byte header, 10 slots; round trip on all 5).
- tools/scene_resource.py: CGSceneResource walk (round trip on Dyson). Not used by the copier.
- tools/actor_copy.py: copies a subtree: actors appended at the END of the actor table (Dyson's
  scene graph covers only actors 0..1947 as a prefix; the 744 after it - static geometry, a pooled
  touch actor, a canvas actor - have no scene node, so ours have none either). Rows owned by source
  actors are copied in every table, every 8-byte word naming a source actor remapped to its copy;
  CTransformCR +0x30 and ButtonInteract +0x80 (world positions) and the actor table transform
  moved by the offset. Row actorid/numpooled are 0xffff in stock rows (unset), so no index fixes.
  Transforms are world; CTransformCR parentxf is -1 (hierarchy = actor table parents).
- tools/fix_map_terminal.py (deploy, after every other level-table fix): Dyson, 4 copies of the
  right (REMATCH) button 1931 subtree, nodeids symbol64("mapswitch_<map>_<part>"), podium frame
  (quat x,y,z,w; local x = world -x here) at local x -0.3/-0.1/0.1/0.3, y +0.11 (above the pair;
  guessed: nothing is known yet about the panel's free space). Labels still read REMATCH; presses
  do nothing yet (the podium script only knows its own two). Not in the layout root's UILayout list.
- Stock copies of Dyson's 9 extra tables added to data/extract; deploy MAP_TERMINAL_TYPES/LEVELS.
- TEST 1 asks: level loads (no black screen / crash), the 4 buttons show and sit right, press
  animation. If they show nothing: suspect the missing scene nodes (then insert at index 1948 and
  add nodes + +816 rows; scene node ids are the signed-sorted key order, so other sections that
  name nodes by index would shift).
- TEST 1 (user screenshot): level loads, the 4 copies SHOW (labels read "LEFT", the label canvas
  default) but overlap the stock pair and the outer ones stick out past the screen. Stock buttons
  ~0.126 x 0.23 m, screen ~0.41 m wide. Layout v2 (installed, untested): actor_copy Place(pivot,
  offset, scale) scales actor + CTransformCR init_scale (ButtonInteract box left alone: it looks
  local); move_subtree moves stock buttons in place. Maps scale 0.6 in a row at y +0.02 (x
  +-0.048 / +-0.144), REMATCH / LOBBY scale 0.5 at y -0.125, x -+0.07. Unknown: whether scale
  reaches the render / touch volume, and whether the podium's UILayout re-places the stock pair.
- Same test: user said the point "won't capture", later captured ~2 min late. Server mailbox then:
  T 300 (unlock 5 s, CAPTURE TIME 0 = instant path, cap 0.001), pause 0, rate 10. Cause unknown;
  not yet known whether it predates the map-terminal build.
- TEST 2 (screenshot): layout v2 fits. User: move REMATCH/LOBBY and the map row up a bit ->
  STOCK_Y -0.085, MAP_Y +0.045 (installed, untested).
- 2026-11-07: F8 END MATCH REMOVED from VeilNet (test-only code; WANT_END, the capture point scan,
  EndMatchCapture/Step, GameOverSeen). Map buttons did nothing on the hosted server: SawLog's
  private-match test was strstr(gametype, "private"), but without SymbolNames.dll (not shipped)
  the engine logs the gametype as its hash ("0x33BBF6842DF97A3F" = echo_combat_private), so the
  server took every match as public and refused silently. IsPrivateGametype() now accepts the
  hash form (echo_combat_private / echo_arena_private) and any-case "private".
- END MATCH (user: "get to this terminal quicker, end matches instantly"; built, installed,
  untested): F8 with the Echo window in front -> 'C' WANT_END (0x10000000) -> server, private
  matches only (g_private_match from its "[NETLOBBY] Starting session (gametype " log line; the
  echovr.exe logger hook now runs on the server too), raises nevt_cbt_round_win_blue
  (0x22cc233f89802b89, handled by 6fa8) through DispatchEventToSession every 3 s until
  nevt_game_over (0xe2d5eb48e0d8a7c4) is seen (HookedDispatch / inner dispatch / DCE), give up 90 s.
  Manual alternative used in test: the live point data = b7d10 data found by symbol
  "capturepoint" (0xeedeff1586bd8846) at +0x100 (regions > 256 MB must be scanned too):
  +F0 orange, +F8 blue, +FC required (75). The win check only runs for the CHARGING team.
- END MATCH TEST 1: raising nevt_cbt_round_win_blue only moved 6fa8 to the next round (no
  winner, score dots 0-0, "ROUND 4!"). Rebuilt (installed, untested): END MATCH now makes blue OWN
  the point each round, as the engine's capture tick does (FUN_140d63da0: volumes = *(cs+100h) +
  dense*50h; +08 per-team {short count, float progress}, +40 flags (4 = replicate), +44 owner
  (2 none, 0 blue assumed), +46 capturing (ffff none), +48 capture time; on capture: owner set,
  flag 4, FUN_140ccfb20 = raise delegate_OnPossessionChanged), every 500 ms, with POINT RATE 255
  quarters and T 61 (unlock 1 s) meanwhile; restored at nevt_game_over / 120 s. Capture point
  maps only (payload: nothing happens).
- END MATCH TEST 2: the owner-forcing version never wrote anything (no "given to blue" line:
  capture tick CS not current). User: "just force 999 points and insta capture". Rebuilt
  (installed, untested): on F8 the server's tick thread finds the point script data in its own
  memory (symbol scan, cached, rescan every 2 s), writes +F0 / +F8 = 999 every 300 ms and sets
  T = 60 (unlock 1 s, capture instant) until nevt_game_over (then T restored) or 180 s. A team
  must still step on the point (the win check runs only for the charging team).
- END MATCH TEST 3 (user): still no end; and the point "took long to capture even on 0".
  Server/client logs not read yet (the user stopped the read).
- TEST (user at terminal, screenshot): layout v3 fits on Dyson. Pressing the far-right copy did a
  REMATCH. The client log had stopped at 01:35:36: Log() capped at 2000 lines per process and the
  research logging used them up (cap now 20000; the EVT / SetText research logging is behind
  ECHOCOMBAT_LOG_EVENTS now).
- FOUND in the level data (CScriptCR record of each palm button, script prp_itt_screen_button_logic
  0x55e66d39171b2ba3): child table 5 (24-byte rows, symbol at +16) = the event it sends the podium
  (REMATCH button: left_button_press 0x052c36430f4094cd, LOBBY: right_button_press), table 8
  (80-byte rows, 64-byte string at +16) = its default label ("LEFT" / "RIGHT"; the podium
  overwrites the stock pair's, not ours: SetText "LEFT" on canvas handles 0x19a..0x19d = our
  CCanvasUICR rows 410..413, element "text" c8c33e482e7606a4). fix_map_terminal.py now sets each
  copy's event to mapswitch_<map> and its label to the map name (DYSON / COMBUSTION / FISSION /
  GAUSS). The podium ignores the new events.
- All four Combat levels now (each has exactly one REMATCH/LOBBY pair, found by that script +
  event): LEVELS in fix_map_terminal.py, MAP_TERMINAL_LEVELS in deploy, stock tables copied into
  data/extract. Full stage() run offline: OK for all four. NOT installed (user: work offline).
- MAP SWITCH (VeilNet, built in out/ and out_log/, NOT installed, untested): client hears
  mapswitch_<map> (inner dispatch hooks now on clients in every build) -> 'C' WANT_MAP|k
  (0x20000000|k) -> server (private matches only): owner JSON "level" = mpl_combat_<map> via
  CNSLobby owner setter +0x615E60 (lobby, key, symbol) [the call LobbySessionStartingCB makes;
  lobby = *(netgame+40h)+18h, which LoadMap reads; client lobby +0x468 cache too], then the
  engine's "Session Started" +0x17D8A0 (players reset, LoadMap; leaving state 9 clears owner
  "ingame" via OwnerJson_SetBool), then 'L' k to clients 1.5 s later (x3). Client: once its
  owner JSON "level" (GetSymbol +0x60D3D0) is the map -> SetGameState(netgame, 6) (+0x1B8650):
  Update loads the owner level when the server's "ingame" comes back. Prologues checked before
  calling. Risks: leaving state 9 on a client (cleanup), whether Session Started on a live
  dedicated server keeps clients connected.
- END MATCH v4 (user: "add a blue person to the point, instant capture, 9999 points"; built,
  NOT installed, untested): game thread, every 500 ms: each capture volume not owned by blue gets
  the engine's capture-complete writes (owner 0, capturing ffff, progress 0, flag 4) +
  delegate_OnPossessionChanged; tick thread: blue +F8 = 9999 (orange untouched); T = 60. Logs
  "no capture point ticking yet (cs ...)" every 3 s if the capture CS is not current: that was
  the silent skip in v2. Team 0 = blue is assumed.
- TEST (v4 + map switch): labels DYSON..GAUSS show; presses reach the server ("MAP SWITCH to
  GAUSS asked"); F8 wrote 9999 but blue never captured. CAUSE of both (and of v2's silent skip):
  entry-byte checks. Live server bytes: DispatchComponentEvent starts e9 (VeilNet's OWN Detours
  hook), SetGameState starts e9 (another plugin hooks it), DispatchEventToSession e9 (ours).
  Fixed (installed with the logging VeilNet, untested): DceFn() calls g_real_dce (trampoline);
  EntryOk() accepts a leading jmp if the bytes after +5 are stock; MapSwitchCallable logs which
  entry fails; ApplyMapSwitch logs "no net game seen yet".
- TEST (hooked-entry fix): "blue captured capture point 0" at F8, but the point was still LOCKED
  (flags 1); no round win; afterwards blue already owned it, so the user (blue, claims 1/0) could
  not capture it. v5 (installed, untested): only unlocked volumes; blue's ownership re-announced
  (OnPossessionChanged) every 1 s while END MATCH runs.
- TEST (v5): point stayed LOCKED after F8 (user waited the 45 s): T only sets the lock time a
  round STARTS with; the running round keeps its countdown. v6 (installed, untested): the tick
  thread also moves the point script's countdown start (+F4) back by what is left (+DC) whenever
  +DC > 0.2 while END MATCH runs ("point unlock countdown ... cut to 0").
- F8 v6 WORKS (user).
- MAP SWITCH TEST 1: server did "owner level = GAUSS; session restarting", LoadMap ran, but the
  load failed: "There can be only one instance of R15NetBalanceSettings" (Gauss loaded on top of
  the still-loaded Dyson); EchoRelay's server patch ("[ECHORELAY.PATCH] Dedicated server failed to
  load level. Resetting session") removed all users -> client "Server was shut down". User: the
  client should go to the transition screen. v2 (installed, untested): UnloadLevel() = what
  LeaveGame does: PopLevelSet(*(netgame+8)) (+0x114C20) and clear bit 37 of *(netgame+2DA0h)
  (LoadMap sets it), on the server before the owner level + Session Started, and on the client
  before SetGameState(6) ("server loading"). 'L' now 300 ms after. Unknown: whether the unload
  (queued through FUN_1404fc6d0) finishes before the queued load.
- MAP SWITCH TEST 2: SERVER WORKS (r14: Session Started -> unload celebration rooms / dyson /
  war room -> load gauss + sections + rooms, ~1 s). The CLIENT followed ON ITS OWN at once (engine:
  in game -> server loading = the grey transition screen, unloads its levels, LoadMap owner
  level). VeilNet's client step then ran again on the 2nd 'L' (unload + state 6) mid-load ->
  two Gauss loads -> crash (CFiber::StaticRun). v3 (installed, untested): client only logs 'L';
  server sends 'L' once.
- CORRECTION, TEST 3 (client only logs): the client did NOT move (only "restart celebration").
  So in test 2 the client's "in game -> server loading" WAS VeilNet's SetGameState(6) (leaving
  state 9 disables/unloads its levels by itself); the crash was the second run + PopLevelSet.
  v4 (installed, untested): client, once its owner level is the target and only while its state
  (*(u32*)netgame) is 9: SetGameState(6) once; no PopLevelSet on the client.
- TEST 4 (client SetGameState(6) once): client "in game -> server loading" then LoadMap Gauss at
  once (server's ingame already back) with NO unload -> crash. Test 2's good client path was the
  ENGINE: on LobbyOwnerDataChangedCB with owner "ingame" false it disabled its levels, enabled
  mnu_master (the menu transition screen the user wants), went to server loading, unloaded, then
  loaded the owner level. Tests 3/4 the server reloaded in ~1 s so the client never saw false.
  v5 (installed, untested): server step 1 = owner "level" + OwnerJson_SetBool(lobby, "ingame", 0)
  (+0x615B50); step 2 after MAP_LEAVE_MS (2 s) = UnloadLevel + Session Started; client only logs.
- TEST 5: owner "ingame" off for 2 s: client got LobbyOwnerDataChangedCB and did NOTHING (the
  engine does not move a client on it). v6 (installed, untested): server step 1 also sends 'L'
  at once; client (state 9, owner level = target) SetGameState(6) while the server still waits
  (ingame false, so Update does not LoadMap yet); 1 s later, if still state 6, server not in game
  and its level-loaded bit set -> UnloadLevel (PopLevelSet). Server reloads after 3 s.
- MAP SWITCH v6 WORKS (user, Dyson -> Gauss). Client log: in game -> server loading, disables its
  levels, enables mnu_master, PickRandomTip (same tip context as a normal join), unloads, then on
  the server's ingame: loads mnu_master_mp_ingame + gauss, ready -> in game. User wants the
  "transitioning" UI during the gap (now a blank grey mnu_master void). A normal join goes
  lobby -> server loading -> loading level with the same mnu_master + tip; what UI it shows and
  what triggers it not found yet (asked the user for a screenshot of the wanted screen).
- "TRANSITIONING" = menu popup ui_mnu_popup (674f3b71da94770c, in mnu_master): texts LOGGING IN /
  LOADING / MATCHMAKING / TRANSITIONING / WAITING FOR SERVER TO LOAD, driven by the net game
  delegates SetGameState raises per state (4 loadingmultiplayer, 5 ?, 6 serverloading, 7
  loadingmap, 9 ingame). Normal joins pass state 4; the switch goes 9 -> 6 and mnu_master is only
  enabled after it. v7 (installed, untested): client raises delegate_onnetgameloadingmultiplayer
  (0x60433466edf3937a) via DispatchEventToSession at the 1 s unload check and again 0.7 s later.
- v7 popup event did NOT show TRANSITIONING (raised 1 s in, same second mnu_master was enabled).
  ui_ar_mp_state_mgr (156208a7bf6bcfec) does not listen for net game delegates; what opens the
  popup page (delegate_onpageelementenabled?) is still open. Next idea: find what enables the
  popup page in a normal join.
- User: GAUSS button label -> SURGE (fix_map_terminal LABELS; level stays mpl_combat_gauss;
  VeilNet kMapNames too). Map buttons grey once a switch starts: GreyMapButtons() (client game
  thread, on the press and on 'L'): FindActor (+0x4FF1A0, space *(netgame+2B08h), the space's
  sorted {nodeid,index} table at +370h -> link 0x0000ffffffff<idx>) for symbol64("mapswitch_<map>_0"),
  then DispatchComponentEvent(space, evt_btn_disable 0x8f0791ddb90b611d, link, -1). Installed
  (full deploy + logging VeilNet), untested.
- TEST: SURGE shows; buttons did NOT grey (no "greyed" line at all: a silent early return; each
  return now logs, and the lookup result + link per button are logged); TRANSITIONING still not.
- NORMAL JOIN EVENT LOG (ECHOCOMBAT_LOG_EVENTS build, scratchpad build_veilnet_events.bat): the
  popup texts go to canvas handles 0x10/0x39/0x09 (element "text" c8c33e482e7606a4): "LOADING"
  right after MultiplayerStart (0x816707342bddf95c) + delegate_onnetgameloadingmultiplayer, then
  "WAITING FOR SERVER TO LOAD PRIVATE COMBAT MATCH", "LOADING PRIVATE COMBAT MATCH", and
  "TRANSITIONING" right after delegate_onnetgamereadyforgame (0xe0e81b25f76105a3). Before LOADING
  the popup's page is enabled: delegate_OnPage2Enabled (0xd64f3478683e4a9c) on an R15UIPage2
  (0x85d5432be2bdb1d6). Installed now (events build, untested): the switch also raises
  MultiplayerStart before the loading event. If the page still stays hidden: find who sends
  OnPage2Enabled for the popup page (link 0x40 in that log) and do that.
- MultiplayerStart before delegate_onnetgameloadingmultiplayer WORKS: the menu popup shows (user:
  "the menu is correct now"). Grey buttons: client log "no DispatchComponentEvent": on the client
  another plugin hooks DCE before VeilNet (so no g_real_dce); the entry is a Detours jmp + int3
  pad (e9 .. cc cc cc), so DceFn() now also accepts e9 at +0 with the stock third instruction
  48 89 54 24 20 at +8. Installed (events build), untested.
- Two-client test (second client: -noovr -windowed -lobbyid "<id from the first client's log>"):
  both teams readied but the match never started (server stayed pre_match_wait_for_ready; cause
  not proven). User's spec for TEAM READY: grey after ready as stock, grey until both teams
  ready, PAUSE 2 s after. Built + installed (untested): fix_rules_pages: the six DisableButton
  call sites (mov eax, d7552910; mov [rcx+10h], rax) jump to caves that use EnableButton only
  while mailbox +35h ("PAUSE allowed") is set; the own-team test (0x2FB39) is stock again.
  VeilNet client: +35h = 1 two seconds after +2Fh (live), then raises nevt_all_update_state
  (0x2bcc9f98038227ff) so the podium redraws; the TEAM READY / PAUSE label follows +35h.
- TWO-TEAM READY TEST (server log of ready events, logging build): BOTH arrive at the server:
  nevt_red_team_ready (14:25:14, from the -noovr orange client) and nevt_blue_team_ready
  (14:25:21); the game mode answers each (evt_vo_anc_squad_ready_orange / _blue to the
  gamemode_script link), yet the server stays in pre_match_wait_for_ready. Mailboxes all 0 (no
  pause / live / T). Single-team matches start fine (wait_for_ready -> round_start). Unknown
  whether stock does the same with two teams or one of our 6fa8 patches (fix_capture_points
  game_timer reads -> T, fix_clock_pause dt caves) blocks the start. Next: a run with stock 6fa8.
- Logging build, server: TraceCapture logs each capture volume once a second when it changes
  (flags, owner, capturing team, claims, progress, capture time, T, cap) for the slow capture.
- Logging VeilNet (out_log, installed on C: and H: for this test; redeploy restores the normal one):
  client logs every distinct SetText (cs/handle/element/text) and every distinct (event, link)
  through DCE + both inner dispatchers ("EVT ... (first seen)"), for the button press path and
  the label keys. Logs: _local\echoCombatBetaLogs.
- Next after it shows: labels (DYSON ...), the press -> VeilNet (hook the button's event), the map
  switch (phase 2), "big" buttons (scale), other levels.

## MAP SWITCH TERMINAL (2026-11-05, research only, nothing built)

User spec: in private matches the celebration room's terminal (stock: BACK TO LOBBY / REMATCH)
becomes 6 buttons: 4 big ones for the Combat maps (Dyson, Combustion, Fission, Gauss), then
REMATCH and LOBBY. A map press sends EVERYONE on the same server to that map (server unloads /
loads, everyone rejoins). NO EchoRelay changes (binding). User hint: hook what BACK TO LOBBY uses.
Findings so far:
- Clients get no level from the relay (LobbySessionSuccess has gametype + endpoint only); the level
  is the lobby OWNER JSON key "level" (CNSLobby+0x310, set by the game server = lobby owner).
- CR15NetGame::LoadMap +0x17A050 (server and client): reads owner json "level", sets loading flag,
  loads via scene vtable +0x330, game state 7. Callers: LobbyJoinAccepted +0x17C810 (owner -> load;
  client -> load if owner json "ingame", else state 6 "server loading"), Session Started +0x17D8A0
  (resets players, then LoadMap), CR15NetGame::Update +0x1BBDB0 (state 6 + "ingame" -> LoadMap).
- Server session start: CR15NetClientLobby::LobbySessionStartingCB +0x1AD040 (gametype/level from
  the session settings, "[NETLOBBY] Starting session (gametype %s, level %s)"); "Ending session"
  at +0x162243. "[NETGAME] Return to lobby" / "Scheduling return to lobby" exist (client path).
- Client ApplyLobbyOwnerJson +0x17CD90 (owner data changed) only re-applies users / teams /
  alignments: a level change in owner data alone does NOT reload clients.
- The celebration-room terminal itself not located yet (string search for REMATCH was cut off).

## CHECKPOINT USED: DROPPED (2026-11-05, user: "ditch this rule")

Removed from VeilNet (code before removal: scratchpad veilnet_before_cp_removal.cpp, not in the
repo). Kept: PAYLOAD SPEED, the payload PAUSE queue (server inner-dispatch hooks + PAUSED edge feed
its checkpoint hits), the hold while paused. Row 4 on payload maps is empty; the podium's row-4
asks (10h) are ignored by the client. What was learned, for anyone retrying it: the payload's start
point is mover entry +10 (the game's reset places it there - worked); the payload script accepts
raised ext_major_checkpoint_* events (clock, music, autodrive) but orbs follow each objective
actor's own "complete" flag (tst_dsn_robby_cbt_utility_objective; evt_cbt_net_set_complete /
_incomplete, aimed at the actor), and even sending set_complete to the recorded targets on server
and client did not move the orbs. Unsolved; do not resume unless the user asks.

## PAYLOAD RULES (2026-11-04, built, untested; test running on Fission)

User spec: on Fission / Gauss the RULES page loses BLUE / ORANGE SCORE, POINT UNLOCK, CAPTURE
TIME and POINT RATE; new rules PAYLOAD SPEED and CHECKPOINT USED (0 normal, 1..3 = George starts
from / moves to that checkpoint; both maps have 3). TEMP for testing: orb timers 0 on both.
- Orb timers: balance JSONs mpl_combat_fission_map_settings e885fd337739bea3 / gauss
  158ef86fd84ef3dd (type 607d858c90268f9a, spawn_timers). deploy `--zero-orb-timers` (TEST switch,
  off by default) stages them with every value 0, same length. Stock copies in data/extract.
- Engine: CR15NetPayloadCS updates UpdatePreTrackMover +0xD84FF0 / UpdatePostTrackMover +0xD84220.
  Payload data 58h bytes (cs+100h, sparse->dense cs+D0h, count u16 cs+FCh): +14 time w/o attackers,
  +18 current speed, +1C autodrive speed, +20 max speed, +28/+29 attackers/defenders on it, +30
  flags (1 PAUSED = checkpoint buffer [SetPaused deferred fn +0xD47AF0], 2 autodrive, 8 LOCKED =
  before attackers start [SetLocked +0xD46960], 20h dirty), +38 multipliers per attacker count.
  Final speed -> track mover entry: +0xD858ED movss [rax+rdx*8], xmm3 (r14 = payload data).
- VeilNet: InstallPayloadSpeed hooks that store (stub near the exe, 5-byte jmp) -> PayloadSpeed():
  speed x PAYLOAD SPEED quarters/4; server CHECKPOINT USED: armed on LOCKED rising edge, when LOCKED
  drops (attackers let go) drive at 12 m/s counting PAUSED rising edges until = chosen checkpoint
  (cap 120 s); client mirrors the drive while 'G' bit 6. "Payload map" = the hook ran in the last
  second (server) -> 'G' bit 5 -> mailbox +30. 'G' bits 16-23 payload speed, 24-25 checkpoint.
  Asks: row 3 (POINT RATE asks) = PAYLOAD SPEED on payload maps; row 4 = 10h|1 up / 10h down,
  client sends 10h | target << 8. Mailbox +30 payload map, +31 speed, +32 checkpoint, +33 driving.
- Podium (fix_rules_pages.py): caves now in a section of their own (.rules; .text was full).
  Payload map: RULES / MenuPage=1 start on page 2 (page byte = +30), NEXT keeps it (hides labels),
  ShowMenuSettingsLabels' custom1a..4a alpha nodes (0x178C0 0x135C0 0x24020 0x15390) skipped,
  rows 1-4 text from VeilNet's table (4 x 48), row 4 -/+ (26356df8 / ed70639c) ask the checkpoint.
- Risks to check in the test: does the script really set LOCKED at round start and PAUSED at
  every checkpoint (log "PAYLOAD flags ...")? If PAUSED is not set at a checkpoint the drive
  overshoots (cap only). Gauss has extra speed multipliers in its script (s01/s02/s03).
- TEST 1 (Fission): PAYLOAD SPEED works. Bugs: row 4 missing (text table offset 144 emitted as
  add rcx, imm8 = -112 -> now imm32); values showing over the main screen after BACK (page byte
  stayed 2 so HideMenuSettingsLabels skipped the values -> BACK now always sets page 1). Orb timer
  change did NOT take (user: doesn't matter now; unknown why: maybe balance JSON comes from
  elsewhere). Clock already freezes on payload (6fa8 patch covers it; 45e8df51 has no dt clocks).
- PAYLOAD PAUSE (user spec): PAUSE during the match is QUEUED until the payload is held at a
  checkpoint buffer (or before the attackers start); if it already moved on, it waits for the next
  checkpoint. Built: server queues when !(flags & 9), executes in ApplyPayload once flags & 9;
  'G' bit 7 -> mailbox +34 -> TEAM READY label "QUEUED". While paused PayloadSpeed returns 0 on
  server and clients (user saw George still move during a pause). Untested.
- TEST 2: checkpoint drive and queued pause did nothing. Server log: LOCKED (8) only at the round's
  END, PAUSED (1) once and not at the checkpoint, AUTODRIVE (2) ~7 s right before each round (the
  game placing the payload), 10h = delegate_OnReturnedToCheckpoint (rolling back against a
  checkpoint; set at +0xD84641). Engine payload events: OnFurthestDistanceChanged,
  OnReachedFinalDestination, OnReturnedToCheckpoint, OnClaimCountsChanged; no checkpoint event.
  User rule refined: PAUSE is instant if the payload has not moved yet this round; if it has, it
  waits for the next checkpoint hit.
- Rebuilt (logging VeilNet installed, untested): round start = AUTODRIVE seen (moved = 0, drive
  armed); moved = the speed VeilNet hands the mover is non-zero; checkpoint hit = payload script
  global events evt_cbt_obj_complete / nevt_all_major_checkpoint_1|2_reached /
  evt_vo_anc_payload_checkpoint (once per 5 s) seen in HookedDCE; CHECKPOINT USED drive starts at
  the round's first move and stops after N hits (cap 120 s). Logging build also logs every
  distinct global event once ("event ... (first seen)") while on a payload map: use it to pick the
  right checkpoint event if these are wrong.
- TEST 3: pause works (instant before the payload moved). Drive did not stop: NO script checkpoint
  events and NO "first seen" events reached HookedDCE on the server (global script events must go
  another way), but the log showed PAUSED (1) set 3.7 s into the drive = checkpoint 1's hold, which
  the drive overrode, so George ran to the end (09 locked+paused = delivered / round over). User:
  normally a checkpoint stops the payload; tell = the orbs move to the next location for both teams.
- Fix (logging VeilNet installed, untested): checkpoint hit = PAUSED rising edge (CheckpointHit,
  5 s dedupe; events kept as a second source); PAUSE also instant while PAUSED is set; drive at
  8 m/s; LOCKED stops any drive (round over).
- TEST 4: queued pause DID fire at checkpoint 1 (PAUSED hold, server + client logs agree). But only
  checkpoint 1 has a PAUSED hold on Fission: after UNPAUSE the drive (target 2, 1 hit) went on with
  nobody on it and ran from cp1 to the end in 10 s (no hold between) = cp2/cp3 do not hold. Also a
  PAUSE pressed before the round's autodrive queued: "moved" was stale (rollback speed at the start
  counted as moving).
- User's tell: at a checkpoint the orbs move to the next location for both teams. Orb script e5733
  listens for evt_cbt_obj_complete (+ evt_cbt_refresh_spawn_positions, objective_1..3), sent by the
  payload script 45e8df51 (also has quickfinish_checkpoint_on_start: a native way to start at a
  checkpoint? not explored). Script sends bypass DispatchComponentEvent: now the server also hooks
  DispatchComponentEventInternal +0x50FED0 and +0x50FB60 ((space, SComponentEvent* {+0 event, +10
  link, +18 param}, flags)) and counts evt_cbt_obj_complete / major checkpoint 1|2 as checkpoints.
  PAUSE cancels a running drive. moved = forward speed > 0.05 only, reset on LOCKED (round end) and
  AUTODRIVE. Logging VeilNet installed, untested. "first seen" event log printed nothing (filter
  link/param == -1 probably wrong); irrelevant to the counting.
- TEST 5: checkpoint events now arrive (nevt_all_major_checkpoint_1_reached c768.., _2_ ba83..) and
  the queued PAUSE fired on cp1. But AUTODRIVE (2) also happens at EVERY checkpoint (same instant as
  the cp event): the old code re-armed the drive there, so after UNPAUSE the first grab drove from
  cp1 to the end. User wants the round's STATE at the chosen checkpoint (orbs / objective), not a
  drive ("ROUND STARTING IN" still at the beginning).
- Rebuilt (logging VeilNet installed, untested): the speed drive is GONE. CHECKPOINT USED N = the
  server raises the payload script's own event quickfinish_checkpoint_on_start (0x142c040b5023c176;
  45e8df51 handler 0x197ae starts thread a7eeb05c, one at a time) N times, 1 s after the round's
  placement then every 4 s. Round start = first AUTODRIVE after LOCKED (round end) or a map change
  (g_round_over); checkpoint AUTODRIVEs only reset "moved". Unknown: what the quickfinish thread
  really does and whether it accepts the event outside its intended phase.
- TEST 6: quickfinish raised twice (1 s after placement, during ROUND STARTING IN); at the launch
  (~11 s later) the payload went into AUTODRIVE and crawled forward on its own (claims ignored),
  i.e. quickfinish = the script autodrives it to the next checkpoint; state stays cp0 until it
  arrives. It also moved during PAUSE: PayloadSpeed returned the autodrive speed before the pause
  check. The major_checkpoint_1 event fires at the round's placement too (counted as a hit).
- Rebuilt (logging VeilNet installed, untested): PAUSE holds autodrive too; skips sequential
  (QF_IDLE -> raised -> AUTODRIVE rising = driving -> falling = arrived, next after 4 s; give up
  after 60 s); our skip's autodrive x6 (server, and clients via 'G' bit 6 while autodriving).
- TEST 7 + user correction (binding): CHECKPOINT USED must NOT make the payload drive itself; the
  round's whole state (payload, orbs, objective) must BE at the chosen checkpoint at once. The
  quickfinish skip is switched off (`if (false && ...)`). x6 autodrive never got there (31 s).
- Track mover (CR15NetTrackMoverCS UpdatePrePhysics +0xD847A0): per entry (48h) +00 speed; step =
  dt*speed, advanced by FUN_140d118b0(cs, entry, &step) trackpoint to trackpoint; on a crossing it
  checks the point (FUN_140a61390 / 61150 / 61ac0 / 61440 on cs+140h) and may zero the step (the
  checkpoint stop). Accessors DistFromOrig / DistToDest exist. No script node sets a position
  (payload nodes: SetPaused/AutoDrive/Irreversible/ResetToStart/SetMaxMPS/SetLocked/Spoofed).
- Event naming is misleading: nevt_all_major_checkpoint_1_reached fires at the round's PLACEMENT,
  _2_ fired at the first real checkpoint (test 5, 48 m in); nothing seen after that to the end.
- Plan: data run (logging build installed): LogTrack logs the mover's trackpoints (+14 / +18
  handles, +04/+08 distances) on every change, and every distinct event once ("first seen", filter
  removed). User pushes George start -> end; then build the jump: during the pre-round countdown
  cross the trackpoints to the chosen checkpoint in a few frames (script registers each crossing)
  and stop exactly on it.
- DATA RUN (Fission, 2026-11-05): trackpoints 0x00..0x44. tp 0x20: ext_major_checkpoint_1_reached
  (6f44..), evt_global_freeze_clock, nevt_all_major_checkpoint_1_reached, evt_cbt_obj_complete
  (orbs move), AUTODRIVE through the gate (speed 0.15, evt_linear_anim_start) to tp 0x21:
  ext_major_checkpoint_1_passed (f54d..), unfreeze clock. tp 0x23 cargo_tunnels_mid_reached
  (marker). tp 0x26: ext_major_checkpoint_2_reached (12af..), nevt_all_major_checkpoint_2_reached,
  PAUSED hold ~12 s, then checkpoint_2_door_opened. tp 0x30 chasm_tunnel_reached (marker). tp 0x44:
  OnReachedFinalDestination, LOCKED, delivered. => Fission has TWO checkpoints. Round flow events:
  nevt_round_restart, evt_round_start, team_room_wait_enter, pre_launch_enter (+15 s),
  main_loop_enter / nevt_new_round_started (+45 s, the round is live). Mover +04/+08 = distances
  from / to the trackpoints, +14/+18 prev/next trackpoint index.
- Built (logging VeilNet installed, untested): CHECKPOINT USED 0..2; at main_loop_enter the server
  returns JUMP_MPS 150 for the payload (through holds / autodrive) until ext_major_checkpoint_1_passed
  (1) or _2_reached (2) arrives, cap 4 s / LOCKED. Gauss not mapped yet (its events may differ).
- User (binding, angry): NO pushing, NO teleporting; "the orbs need to be right and he just needs to
  be there", instantly at game start, done properly. Jump code REMOVED.
- Proper mechanism found: payload ResetToStart (deferred FUN_140d3f250) resets the payload data and
  calls the mover reset FUN_140d3f400(moverCS, handle): prev tp (+14) = START tp (+10), next =
  successor (FUN_140a61b30), +04/+08 from cumulative distances (FUN_140a61340), places the actor
  (moverCS[0x27] physics vtable +3B8 with the entry's +28 transform). Orbs (e5733): objective_1..3
  are actor-ref vars (+860.., 24 bytes each); each evt_cbt_obj_complete moves the orb to its next
  objective (node 7dd16a9a); evt_cbt_refresh_spawn_positions -> node 1c77ee99.
- Built (logging VeilNet installed, untested): PayloadSpeed (server) keeps mover entry +10 = the
  checkpoint's trackpoint (Fission 1 -> 0x21, 2 -> 0x26; 0 -> the original), so the game's own
  round reset places George there. At pre_launch_enter (0x37756d8877ed5768) the server raises
  ext_major_checkpoint_1_reached, _1_passed (, _2_reached), 300 ms apart, through
  DispatchEventToSession so the payload script runs its own checkpoint logic (clock, time, obj
  complete -> orbs). Unknown: whether the script acts on these in pre-launch / with "passed" so soon
  after "reached"; whether +10 survives (nothing else seen writing it). Gauss: table is Fission's.
- TEST 8: start point WORKS (round reset placed George at 0x21; later rolled back to the cp1 point
  0x20 = OnReturnedToCheckpoint floor). Script accepted the raised ext events (freeze/unfreeze clock,
  nevt_all_major_checkpoint_1_reached, autodrive, gate anim) but did NOT raise evt_cbt_obj_complete
  in pre-launch (it did in the live round) -> orbs not moved, wrong barriers. User: must be before
  blue can use their first orb.
- Rebuilt (logging VeilNet installed, untested): trigger = evt_round_start (0xe88e2ed95f05728a,
  right after the reset / team_room_wait_enter); after the ext events, the server raises the missing
  evt_cbt_obj_complete itself (want N, counts the ones seen since the trigger) 700 ms apart.
- TEST 9: raised obj_complete moved nothing. Orb script (e5733, func 0x314E0) counts how many of its
  objective_1..3 ACTORS have their script var "complete" set. Objective actors run
  tst_dsn_robby_cbt_utility_objective (69503a2398bf1523: complete / net_complete,
  obj_element_1..3, requisite_objective, completion_event; events evt_cbt_objective_element_complete,
  evt_cbt_net_set_complete 0x170f97f464f19293, evt_cbt_net_set_incomplete 0x92e179963a1009b3).
  Map config script tst_dsn_robby_cbt_utility_map_config (d15781bbaa4a767f: obj_1..3) sends
  set_incomplete to each objective at nevt_round_restart.
- Rebuilt (logging VeilNet installed, untested): WatchEvent now gets the space; the server records
  the (space, link, param) of each set_incomplete at the restart (assumed obj_1..3 in order), and
  after the ext events sends evt_cbt_net_set_complete to the first N through the original
  DispatchComponentEvent, then evt_cbt_refresh_spawn_positions (global). Obj-complete fill removed.
- TEST 10: server log good (3 set_incomplete targets recorded: links 0000ffffffff051a / ..0518 /
  ..0516, param -1; set_complete sent to obj 1; refresh raised) but orbs unchanged: the orbs and the
  objective actors they read are evaluated on EACH game (in normal play each client sees the payload
  cross the checkpoint itself). Rebuilt (logging VeilNet installed, untested): the inner dispatch
  hooks now run on clients too; ApplyCheckpointState() (server AND clients, from the recvfrom hook)
  runs the sequence; CheckpointRule() / PayloadMapHere() read the server's 'G' on clients.

### PAUSE design v3 (2026-11-04, user, binding; replaces the position-restore design)

- **Capture point:** PAUSE = everyone back to the war room (spawn), pre-match orbs, cease fire,
  frozen points / capture; the point goes **neutral**. UNPAUSE = 5 s countdown (announcer 5..1, no
  "unpausing in" line exists), then cease fire off and freezes off. No position memory / teleport.
- **Payload: PARKED (user: "ignore payload for now").** Rule when resumed: PAUSE only allowed
  before the attackers can start and during checkpoint buffers. Leads: own engine component
  CR15NetPayloadCS (script nodes R15NetPayloadSetLocked/SetPaused, expressions
  R15NetPayloadLockedExpression / IsPausedExpression = probably exactly those two phases; accessor
  RTTI SComponentAccessorCastExpression<...PayloadLocked / IsPaused>); game-mode script
  mp_combat_gamemode_payload 45e8df51b7524e20 (events nevt_all_major_checkpoint_1/2_reached,
  nevt_to_all_pre_launch_enter, time_within_checkpoint, 30_second_padding_active). Payload uses no
  capture volumes, so the capture reset never touches it.

BUILT v3 (installed client + H: server with the LOGGING VeilNet out_log\VeilNet.dll; untested):
- +2E = 0 running / 1 paused / 2 resuming; 'G' bits 3-4. Server: PAUSE ask -> 1 (also from 2);
  UNPAUSE ask -> 2 only from 1, then 0 after 5 s (ApplyPause timer on the recvfrom/game thread).
  The podium cave asks 20h | (state xor 1): pressing during the countdown re-pauses.
- Cease fire on while state != 0. Capture stub and fix_point_rate already freeze on != 0.
- fix_orb_pause: pre_match only while +2E == 1 (resuming = the round's orbs, players spawn back).
- Point neutral: the script's R15NetCaptureVolumeResetNode defers FUN_140d3f520(capture CS,
  handle) (+0xD3F520; sets volume +44 = 0xffff0002, clears claims, raises OnReset, replicates).
  VeilNet's capture tick stub now stores r12 (the CS) + a tick count (g_capture_tick); server calls
  the reset for every volume (count u16 cs+FC, dense->sparse [cs+E0], gen [cs+D0]+si*4+2) on entering
  state 1 and 2, only while the tick count moved in the last second.
- Client state 2: raises evt_vo_anc_countdown_05..01 (0x4ca52f26bec0d5a7 .. d5a3) one per second
  through DispatchEventToSession; the capture script raises the same events globally
  (b7d10 node 0x16a80: event, -1, -1). Label: UNPAUSE only in state 1, else PAUSE.
- TEST 1 (v3): countdown works. Point did NOT go neutral although the server log shows
  "capture point 0 made neutral (cs ..., handle 00000000)" on pause and on resume: the engine reset
  runs, but the point script b7d10 keeps its own possession (pointPossession / net_point_claim_state
  / teamcharging; set from delegate_OnPossessionChanged). Next: find what b7d10 does on
  delegate_OnReset (if anything) and reset its possession vars without initvars (initvars reloads
  the starting scores).
- CONFIRMED (user, test 2): point goes neutral on pause. Fix try 1 below works: the reset raises only delegate_OnReset
  (0xa4c9bef8d3612622); the engine's tick raises OnPlayerEntered/Exited; the script takes its owner
  from delegate_OnPossessionChanged (0xea580f491680c6e0). VeilNet now raises OnPossessionChanged
  for each volume right after the reset (server) and 600 ms after entering state 1/2 (client),
  built like FUN_140d3e9a0: CS vtable+1D8 (cs, out, handle) twice -> link [0] / param [1],
  DispatchComponentEvent(*(cs+80h), event, link, param, 1). Check logs for "possession change
  raised" on both sides. If still owned: the script may keep possession in its own vars
  (pointPossession / blueCharging / orangeCharging) regardless; next look is b7d10's
  OnPossessionChanged handler.
- Discord rules/plans post: docs/combat_rules_discord.md (2316 chars: post as two messages).
- Unlock countdown freeze (built, installed with the NORMAL VeilNet, untested): b7d10 node 0x10030
  computes each frame xmm1 = now([ctx+58h] us/1e6) - start(+F4), xmm0 = lock (+EC, the 0x1009B read
  cave), [+DC] = xmm0 - xmm1 (skipped when [ctx(r10)+DBh] set). fix_capture_points freeze_tail (only
  at 0x1009B): while mailbox +2E != 0, start := now - (lock - last countdown) -> the countdown
  stands still on every machine, no accumulator, an unlocked point keeps its negative countdown
  (no re-lock). Assumed "round start timer" = this unlock countdown (the HUD timer before the point
  opens); if the user meant another clock, candidates: b7d10 match_start_countdown, 6fa8 game_timer.
- User test: the war-room "PREPARE FOR ROUND 1  0:10" clock kept running = a different clock.
  HUD cbt_gamestate_info_ui_koth (b286e82b306a5afe) shows replicated game_timer / countdown_timer
  (session API "game_clock"). The engine never decrements them; mp_game_server_state
  (8317e89cc3ae611, SHARED WITH ARENA; user OK'd patching it since the pause byte is Combat-only)
  does: node 0x16FD0 game_timer (+78) -= dt at 0x17029, node 0x17B90 countdown_timer (+80) at
  0x17BEC. WRONG TURN: patched that, clock still ran (user: "keeps going down"): Combat does not
  count with 8317e. Patch removed, stock 8317e loose DLL put back in both installs.
  Combat's 6fa8 has its own clocks (its get-by-name: +A4 override_time, +A8 game_timer, +AC
  tutorial_timer, +B0 lobbylock_timer, +B4 countdown_timer, +B8 server_state, +C0 spawn_access,
  +C8 game_state) and publishes +A8 as game_timer (node 0x15F20). game_timer = expression 0x28CA0
  max(t - dt, 0); countdown_timer -= dt in 12 state nodes, lobbylock in 2. tools/fix_clock_pause.py
  now patches 6fa8: those 15 `cvtsi2ss xmmN,[rX+50h]` dt loads give 0 while +2E != 0 (caves in a
  new .clock section; .text had 0x30 bytes left). CONFIRMED: clock stops (user).
- Seen once: gun vanished on PAUSE then came straight back. Fix (logging VeilNet installed on client
  + H: server; user test: gun stays away; one-off, so not proof): DispatchComponentEvent (+0x510060) hooked on both sides; while +2E != 0
  it drops nevt_to_server_disable_combat_cease_fire, evt_disable_combat_local_cease_fire
  (0x0ea31347147ad3c3, raised by the point script b7d10) and evt_toggle_combat_local_cease_fire
  unless VeilNet raises it (g_own_cease). Log line "PAUSE: dropped ..." names the culprit. If no such
  line when it recurs, suspect the client's force_respawn retries (0 / 0.8 / 2 s) re-equipping.
- User: "always send people back to the war room" (PAUSE missed the war room ~1 in 2). Client now
  raises nevt_force_respawn at 0, 0.8 s and 2 s after PAUSE (while still paused). Untested.
- mp_game_server_state has Arena's own pause machinery (net_game_paused_state, can_pause,
  nevt_pause_game_blue/orange, net_game_pause_time); not used.
- Ship: redeploy restores the non-logging VeilNet.

- OLD (v2, dropped): reading / teleporting the local player. CombatBots reads positions from the server's
  session HTTP API (head positions of every player) and teleports only server-owned bots
  (WorldTeleport with the component system's +1E0 actor_of and cs+80 game space). For human
  players either (a) each client reads its own player's world transform (engine side of the
  scripts' TransformExpression / CActorSpace transform tables; GetTransform +0x4EB4C0 is a
  lookup by actor ref, not a transform) and calls WorldTeleport through its equipment
  component system (g_equip_cs, local index [cs+130h]), or (b) the server records positions
  from its session API and sends each client its spot (needs a player <-> client address map).

## TEAM READY with two teams: FIXED (2026-11-05, confirmed in game)

- 6fa8 ready handlers (threads 92d92401 blue / 08c5ce5a red) set blue/red_team_ready = !flag (a
  toggle) and run only when expression_<thread>_shouldexecute passes: private && isserver &&
  (sender is server || (!sender.demo && sender on that team)). A -noovr test client is a DEMO
  account ("AccountName [DEMO]"), so its press was ignored: its team never readied. Start test
  cdb25b0f = both ready, or one team empty (blueteamcount / orangeteamcount 0) and the other ready
  (why one player, or both on one team, always started). tools/fix_team_ready.py: flag set true,
  demo test true.
- PAUSE stayed grey after both ready: the podium d4653 has no handler for nevt_all_update_state.
  VeilNet now (1 s after live, PAUSE_OK_DELAY_MS) also raises delegate_onlobbymemberalignmentchanged
  (podium -> UpdateAll f93f24 -> its patched DisableButton site = EnableButton); that handler's
  shouldexecute 22e43fe7 (event user == local player) is patched to true in fix_rules_pages.py
  (ALIGN_CHECK 0x35720). Confirmed: PAUSE usable 1 s after both teams ready; map switch at the end
  works. Fission pause logic being tested by the user.

