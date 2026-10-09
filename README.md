# EchoCombat

A mod for Echo VR's **Echo Combat** mode (PC build `631547.rad15_live`). It adds and
fixes gear, ships as a zip that players install with one double-click, and builds
entirely from this repository.

| Gear | What it is |
|---|---|
| **DOT FIELD** | The unfinished damage-over-time ordnance, registered and working: stick, trigger, damage. |
| **DRONE** | The cut drone ordnance, working: auto-targets and fires. |
| **UMBRAL VEIL** | New tac mod: a wall of smoke clouds (networked). |
| **OVERCHARGE** | New tac mod (was POWER BOOST): a cone link to teammates. User: heal, damage reduction, +1 body / +2 head damage on guns. Linked teammates: heal, damage reduction, cheat death. |
| **POINT** | New tac mod: a placed wall that goes off as a stun field. |
| **TRANSLOCATOR** | A teleport effect and sound that everyone sees and hears. |
| **STARBURST** | Fix for the stock divide-by-zero log spam while the gun is out. |
| Gear icons | Station / HUD icons for the new gear. |

Work in progress, not in the release: **CombatBots** (`plugin/combatbots.cpp`), AI bots
for `-bots N` servers; see `docs/bots_phase2.md`.

## How it works

Echo VR loads its gameplay from packed resources (JSON tuning tables, compiled
script DLLs, sound banks, textures). The build:

1. takes the game files it needs from `data/extract/` and `data/gunpatch/`,
2. patches them with the `tools/fix_*.py` / `veil_*.py` / `gear_icons.py` scripts into
   `build/stage/`, merging in every tunable value from `config/mp_weapon_settings.json`,
3. packs the stage into the game's package with `evrtool` (Go, `evrtool/`),
4. builds the native plugins (C++, `plugin/`, hooked in with Microsoft Detours) that
   the game loads at startup through a small plugin loader (`dbgcore.dll`).

| Plugin | Runs on | Does |
|---|---|---|
| `dbgcore.dll` (`plugin/loader.cpp`) | everyone | loads every DLL in `bin/win10/plugins/` |
| `PowerBoost.dll` | server + clients | OVERCHARGE: links, damage reduction, cheat death, damage bonus |
| `DroneFix.dll` | server + clients | drone fixes |
| `VeilNet.dll` | server + clients | relays UMBRAL VEIL / POINT / TRANSLOCATOR events between players |
| `CombatBots.dll` | server | AI bots (work in progress, not released) |

## Requirements

* Windows 10/11 x64
* **Python 3.11+** with `pip install -r requirements.txt` (numpy, Pillow)
* **Go 1.25+** (builds `evrtool`; its dependencies are vendored in `evrtool/vendor/`)
* **Visual Studio 2022** (or its Build Tools) with *Desktop development with C++*
  (the `build_*.bat` scripts find MSVC with `vswhere`)
* An **Echo VR PC install** of build `631547.rad15_live` to deploy into and test with
  (two installs work best: one for headless servers, one for the VR client; one is
  fine for both)

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
one your headset plays. They can be the same folder. Optional keys `extract` and
`gunpatch` override `data/extract` and `data/gunpatch`.

## Build and deploy

```
deploy_and_launch.bat --kill --client-args=-mp
```

(or `python tools/deploy_and_launch.py ...`). That

1. builds the plugins (`build_*.bat`) into `out/`,
2. stages every patch into `build/stage/` from `config/mp_weapon_settings.json`,
3. repacks both installs with `evrtool` (from their stock manifests, so the stage always
   holds everything), writes the script DLLs, plugins and `PowerBoost.ini`,
4. launches 2 headless servers from `server_install` and the VR client from
   `client_install`.

Useful options:

| Option | |
|---|---|
| `--kill` | close running `echovr.exe` first (it must not run while repacking) |
| `--no-launch` | build and deploy only |
| `--launch-only` | just start the servers and client again |
| `--no-build` | skip MSVC; use the DLLs already in `out/` |
| `--client-args=-mp` | arguments for the VR client (`=` needed when they start with `-`) |
| `--headless N` / `--headless-args "..."` | number of servers / their arguments |
| `--bots N` | adds `-bots N` to the servers |
| `--server-install` / `--client-install` | override `local.json` |
| `--no-drone`, `--no-smoke`, `--no-buff`, `--veil-*`, `--buff-*` | leave gear out / override values for one run |

Run `python tools/deploy_and_launch.py --help` for the rest.

Logs: each plugin writes `<install>/bin/win10/plugins/<Plugin>.log`; the game writes
`<install>/_local/r14logs/`.

## Tuning: `config/mp_weapon_settings.json`

Every value EchoCombat changes is in one file, shaped like the game's own
`mp_weapon_settings.json`:

* `grenade_properties.drone` / `.dot` / `.loc` (translocator effect and loudness)
* `ability_properties.buff` (OVERCHARGE), `.smoke` (UMBRAL VEIL, `veil_*`), `.point`

The build merges it into the game's settings, so it is packed with the game data
(change a value, then deploy or release again). OVERCHARGE's plugin-side values
(`damage_bonus_*`, `head_body_part`, `cheat_death_*`, `link_window_ms`) are also
written into `PowerBoost.ini`. The full merged settings of the last build are in
`build/stage/` (and `build/patched/mp_weapon_settings.json` holds the DOT step's copy).

## Release

```
python tools/deploy_and_launch.py --kill --no-launch     # fresh build/stage and out/
python tools/make_release.py                             # -> release/EchoCombat.zip
```

The zip holds the stage, the plugins and loader, `PowerBoost.ini`, `evrtool.exe`
(cross-built), `install.bat` / `uninstall.bat` / `doctor.bat`, `README.txt` (the
player instructions, in `release/`) and the config it was built with. CombatBots is
left out.

## CombatBots (work in progress)

`build_combatbots.bat` builds it; the deploy installs it on the servers. Bots need a
per-map nav file (`data/nav/<map>.json`: war room orbs and walkable routes), recorded
from your own play with:

```
python tools/record_nav.py          # while you play the map; Ctrl+C to stop
```

## Repository layout

```
config/            mp_weapon_settings.json: every EchoCombat value
data/extract/      the game files the build patches (63 assets, by type/name hash)
data/gunpatch/     the combat gun patch the build starts from
data/nav/          CombatBots nav per map
assets/            UMBRAL VEIL / POINT sounds (wav)
ICONS/             gear icon art
plugin/            C++ plugins + loader
evrtool/           Go packer / installer (vendor/ holds its dependencies)
third_party/       Microsoft Detours (MIT)
tools/             the build: deploy_and_launch.py, make_release.py, fix_*.py, ...
release/           player-facing install scripts and README.txt
docs/              notes (CombatBots)
build_*.bat        MSVC builds of each plugin into out/
deploy_and_launch.bat
local.example.json copy to local.json
```

Generated (gitignored): `build/`, `obj/`, `out/`, `evrtool/evrtool.exe`,
`release/EchoCombat/`, `release/EchoCombat.zip`, `local.json`.
