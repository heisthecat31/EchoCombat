# EchoCombat

A mod for Echo VR's **Echo Combat** mode (PC build `631547.rad15_live`). It adds and
fixes gear, ships as a zip that players install from the Echo VR launcher's Mods page,
and builds entirely from this repository. It changes none of the game's own files.

| Gear | What it is |
|---|---|
| **DOT FIELD** | The unfinished damage-over-time ordnance, registered and working: stick, trigger, damage. |
| **DRONE** | The cut drone ordnance, working: auto-targets and fires from its gun. Looks like the sidearm mounted on a CubeSat (`assets/drone/Drone4.glb`, built by `tools/fix_drone_model.py`). |
| **UMBRAL VEIL** | New tac mod: a wall of smoke clouds (networked). |
| **OVERCHARGE** | New tac mod (was POWER BOOST): a cone link to teammates. User: heal, damage reduction, +1 body / +2 head damage on guns. Linked teammates: heal, damage reduction, cheat death. Shown in purple (`--no-buff-purple-fx` for Repair Matrix's look). |
| **NEUTRON** | New tac mod (was POINT): a placed wall that goes off as a stun field. |
| **TRANSLOCATOR** | A teleport effect and sound that everyone sees and hears. |
| **STARBURST** | Fix for the stock divide-by-zero log spam while the gun is out. |
| **MEDIGUN** | A gun that heals one teammate with a blue beam (held on COMET's gun). Off unless the server's build has `medigun.enabled: true`; anywhere else a selected MEDIGUN is a plain COMET. |
| Gear icons | Station / HUD and spectator HUD icons for the new gear. |

Combat private matches also get a **RULES** screen, **PAUSE**, and map buttons on the
post-match terminal: see [Private match rules](#private-match-rules) below.

Work in progress, not in the release:

* **CombatBots** (`plugin/combatbots.cpp`), AI bots for `-bots N` servers; see `docs/bots_phase2.md`.
* **Party guns** (CONFETTI / BUBBLE / MONEY GUN, end-of-round celebration guns on the Pulsar):
  unfinished and hidden. `tools/fix_party_guns.py` keeps them off the loadout terminals
  (`PARTY_GUNS_SHOWN = False`); the confetti (own pieces and burst, `tools/rm_preview/party_fx.py`)
  and the Pulsar script steps (`tools/fix_party_fx.py`) are built but do nothing without them.

## How it works

Echo VR loads its gameplay from packed resources (JSON tuning tables, compiled
script DLLs, sound banks, textures). The build:

1. takes the game files it needs from `data/extract/` and `data/gunpatch/`,
2. patches them with the `tools/fix_*.py` / `veil_*.py` / `gear_icons.py` scripts into
   `build/stage/`, merging in every tunable value from `config/mp_weapon_settings.json`,
3. packs the stage into a **content pack** with `evrtool pack` (Go, `evrtool/`): the
   stock manifests with the stage packed on top, the packages that adds, and the script
   DLLs, read from an install's stock files (`content/echocombat/`, with `content.json`),
4. builds the native plugins (C++, `plugin/`, hooked in with Microsoft Detours).

Both run under nEVR (`BugSplat64.dll`), the runtime the Echo VR launcher installs:

* **NvrContentOverlay** (a separate nEVR plugin, not in this repo) serves the content
  pack while Echo runs: the game's opens of its manifests and of the packages they add
  get the pack's files, and its script loader gets the pack's script DLLs. Nothing on
  disk changes; with the pack switched off the game is stock. It has to load before the
  game reads its data, so nEVR lists it `early: true` (nEVR with the early load pass).
* The plugins are nEVR plugins (`plugin/nevr_plugin.h`): nEVR loads the ones
  `_local/config.yaml` lists and calls `NvrPluginInitEx`, where the hooks go in, and
  `NvrPluginShutdown`, where they come out. They log through nEVR's host log, not a file of their own (see Logs below).

| Plugin | Runs on | Does |
|---|---|---|
| `PowerBoost.dll` | server + clients | OVERCHARGE: links, damage reduction, cheat death, damage bonus; MEDIGUN; the party guns' trigger / confetti (hidden) |
| `DroneFix.dll` | server + clients | drone fixes: no follow-update crash, bullets from the gun's muzzle, the CubeSat shown / hidden with the gun |
| `VeilNet.dll` | server + clients | relays UMBRAL VEIL / NEUTRON / TRANSLOCATOR / OVERCHARGE events between players; on a server without EchoCombat the client hides UMBRAL VEIL, OVERCHARGE and NEUTRON. Also the private match rules: the server keeps RULES / LOADOUTS / PAUSE / map switch and tells every client |
| `CombatBots.dll` | server | AI bots (work in progress, not released) |

## Requirements

* Windows 10/11 x64
* **Python 3.11+** with `pip install -r requirements.txt` (numpy, Pillow)
* **Go 1.25+** (builds `evrtool`; its dependencies are vendored in `evrtool/vendor/`)
* **Visual Studio 2022** (or its Build Tools) with *Desktop development with C++*
  (the `build_*.bat` scripts find MSVC with `vswhere`)
* An **Echo VR PC install** of build `631547.rad15_live` to deploy into and test with
  (two installs work best: one for headless servers, one for the VR client; one is
  fine for both), with nEVR that has the early load pass, and **NvrContentOverlay.dll**

Everything else (game files, Detours, the CSymbol64 hash) is in the repo.

## Setup

```
pip install -r requirements.txt
copy local.example.json local.json
```

Edit `local.json` (it is gitignored) with your installs:

```json
{
 "server_install": "D:/Games/ready-at-dawn-echo-arena",
 "client_install": "C:/Program Files/Oculus/Software/Software/ready-at-dawn-echo-arena"
}
```

`server_install` is where the headless test servers run from; `client_install` is the
one your headset plays. They can be the same folder. `content_overlay` is the path of
NvrContentOverlay.dll, copied into each install's `plugins/`. Optional keys `extract`
and `gunpatch` override `data/extract` and `data/gunpatch`.

## Build and deploy

```
deploy_and_launch.bat --kill --client-args=-mp
```

(or `python tools/deploy_and_launch.py ...`). That

1. builds the plugins (`build_*.bat`) into `out/`,
2. stages every patch into `build/stage/` from `config/mp_weapon_settings.json`,
3. for both installs: takes out an old repack (`evrtool clean`: an install.bat from
   before the content pack, or an old deploy), builds the content pack from the
   install's stock files into `bin/win10/content/echocombat/`, writes the plugins and
   `PowerBoost.ini`, and lists them in `_local/config.yaml` (the rest of the file is
   kept),
4. launches 2 headless servers from `server_install` and the VR client from
   `client_install`.

Useful options:

| Option | |
|---|---|
| `--kill` | close running `echovr.exe` first (it must not run while deploying) |
| `--stage-only` | only stage `build/stage/` (any OS, no installs): what a release packs |
| `--no-launch` | build and deploy only |
| `--launch-only` | just start the servers and client again |
| `--no-build` | skip MSVC; use the DLLs already in `out/` |
| `--client-args=-mp` | arguments for the VR client (`=` needed when they start with `-`) |
| `--headless N` / `--headless-args "..."` | number of servers / their arguments |
| `--bots N` | adds `-bots N` to the servers |
| `--server-install` / `--client-install` | override `local.json` |
| `--no-drone`, `--no-drone-model`, `--no-smoke`, `--no-buff`, `--veil-*`, `--buff-*` | leave gear out / override values for one run |

Run `python tools/deploy_and_launch.py --help` for the rest.

Logs: DroneFix, PowerBoost and VeilNet write no log file of their own (CombatBots, which is not
released, still writes its own file under `plugin_logs` in the game folder). Each of their lines goes through nEVR's host log and is
tagged with the plugin's name, for example `[NEVR.PLUGIN] plugin=DroneFix ...`, in nEVR's run log.
This needs an nEVR whose plugin context carries the log function (plugin API 6 or newer); on an older nEVR,
whose context does not carry it, the lines go to stderr, which that nEVR does not collect. The
build needs `NEVR_SDK_INCLUDE` set to the `sdk/include` folder of nevr-runtime (the build scripts stop
with an error when it is unset or the header is missing).
`ECHOCOMBAT_LOG` (add `/DECHOCOMBAT_LOG` to the `cl.exe` line of a `build_*.bat`) adds the extra diagnostic lines.
The overlay (NvrContentOverlay 1.2.0 and newer) logs the same way, tagged `plugin=NvrContentOverlay`.
The game writes its own logs to `<install>/_local/r14logs/`.

## Tuning: `config/mp_weapon_settings.json`

Every value EchoCombat changes is in one file, shaped like the game's own
`mp_weapon_settings.json`:

* `grenade_properties.drone` / `.dot` / `.loc` (translocator effect and loudness)
* `ability_properties.buff` (OVERCHARGE), `.smoke` (UMBRAL VEIL, `veil_*`), `.point`
* `medigun` (MEDIGUN: `enabled` and its tuning; `enabled` is written into `PowerBoost.ini
  [server] medigun`, which the server tells its clients)

The build merges it into the game's settings, so it is packed with the game data
(change a value, then deploy or release again). OVERCHARGE's plugin-side values
(`damage_bonus_*`, `head_body_part`, `cheat_death_*`, `link_window_ms`) are also
written into `PowerBoost.ini`. The full merged settings of the last build are in
`build/stage/` (and `build/patched/mp_weapon_settings.json` holds the DOT step's copy).

## Private match rules

Needs EchoCombat on the server; players on a stock server just get stock Combat. Every
client shows the server's values (VeilNet carries them).

* **RULES** on the podium terminal (like Arena's), changed with **- / +**, **NEXT** for page 2:
  * page 1: **POINT UNLOCK** (seconds before the point unlocks; the announcer follows it),
    **CAPTURE TIME** (0 = instant), **BLUE / ORANGE SCORE** (starting points, 75 wins);
  * page 2: **LOADOUTS** (ALL / CLASSIC: the 12 stock items / NEW: only the new guns; players on
    banned gear are swapped), **SERIES-10 ONLY** (everyone shows the Series-10 chassis),
    **POINT RATE** (0.25x to 2.5x).
* **PAUSE / UNPAUSE**: once both teams are ready, TEAM READY becomes PAUSE. Pause sends everyone
  to the war room with gear disabled and every clock frozen; unpause counts down 5..1.
* **Payload maps** (Fission, Gauss): a single page with LOADOUTS, SERIES-10 ONLY and **PAYLOAD
  SPEED**; PAUSE waits for the next checkpoint while the payload moves.
* **Post-match terminal**: buttons for the other Combat maps beside LOBBY / REMATCH.

How it is built: `tools/fix_rules_*.py`, `fix_capture_points.py`, `fix_point_rate.py`,
`fix_station_cells.py`, `fix_team_ready.py`, `fix_clock_pause.py`, `fix_orb_pause.py`,
`fix_map_terminal.py` patch the levels' scripts and data; the scripts and VeilNet share a few
spare bytes past `echovr.exe`'s `.data` (the "RULES mailbox"). Design notes:
`docs/combat_rules_screen.md`; the player write-up: `docs/combat_rules_discord.md`.

## Release

```
python tools/deploy_and_launch.py --stage-only --buff-purple-fx   # fresh build/stage
build_dronefix.bat & build_powerboost.bat & build_veilnet.bat     # out/ (MSVC)
python tools/make_release.py [--install <a stock install>]        # -> release/EchoCombat-<version>.zip
```

The zip holds `content/echocombat/` (the pack, built from the install's stock files:
every live install has the same ones), `plugins/` (the plugins and `PowerBoost.ini`),
`README.txt` (the player and server-host instructions, in `release/`) and the config it
was built with. CombatBots is left out. `release/echocombat.mods.json` is the zip's
entry for the launcher's mod catalog (sha256 and size filled in). The version is
`ECHOCOMBAT_VERSION_*` in `plugin/nevr_plugin.h`, which the plugins also report to nEVR.

**Servers.** A match only has EchoCombat when its game server runs it too. The launcher's
Settings → Launch options → **EchoCombat server** points a player's game at a server of
EchoCombat's own while the pack is on (its address and key, and an account there); empty,
EchoCombat plays on EchoVRCE.

## CombatBots (work in progress)

`build_combatbots.bat` builds it; the deploy installs it on the servers. Bots need a
per-map nav file (`data/nav/<map>.json`: war room orbs and walkable routes), recorded
from your own play with:

```
python tools/record_nav.py          # while you play the map; Ctrl+C to stop
```

## nEVR (EchoVR Launcher pack)

The launcher's mod pack is built from the **`nevr-pack`** branch (nEVR plugin API, content
overlay instead of repacking the game's files; `main` is merged into it). Its `build_*.bat`
need `NEVR_SDK_INCLUDE` set to nevr-runtime's `sdk/include`; then
`deploy_and_launch.py --stage-only` and `make_release.py`.

## Offline effect preview

`tools/rm_preview/` runs an effect's own GPU particle shaders on the CPU and draws the
result (`render_billboards.py`), so particle effects can be tuned without launching the game.
Shader dumps come from `particle_shaders.py` (needs `dxc`).

## Repository layout

```
config/            mp_weapon_settings.json: every EchoCombat value; combat_custom_rules.json
data/extract/      the game files the build patches (by type/name hash)
data/gunpatch/     the combat gun patch the build starts from
data/nav/          CombatBots nav per map
assets/            UMBRAL VEIL / NEUTRON sounds (wav)
ICONS/             gear icon art
plugin/            C++ nEVR plugins (nevr_plugin.h: the ABI they share)
evrtool/           Go content-pack builder (vendor/ holds its dependencies)
third_party/       Microsoft Detours (MIT)
tools/             the build: deploy_and_launch.py, make_release.py, fix_*.py, ...
tools/rm_preview/  offline particle effect preview (game shaders on the CPU)
release/           README.txt: the player and server-host instructions
docs/              notes: CombatBots, the rules screen, party gun reference GIFs
agent.md           working notes / handoff (state, findings, wrong turns)
build_*.bat        MSVC builds of each plugin into out/
deploy_and_launch.bat
local.example.json copy to local.json
```

Generated (gitignored): `build/`, `obj/`, `out/`, `obj_log/`, `out_log/`, `evrtool/evrtool.exe`,
`release/EchoCombat-*.zip`, `release/echocombat.mods.json`, `local.json`.
