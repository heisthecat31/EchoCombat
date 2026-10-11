# EchoRelay: EchoLoader loads the mods that are on too, content packs included

## Problem

When the Game server plugin plays the live build on an EchoRelay server, `relay::install_live` puts EchoLoader 2 in the `BugSplat64.dll` slot. It points EchoLoader at `plugins-echorelay/`, which holds only `EchoRelay.Patch.dll`. Every mod is left out, because nothing reads `config.yaml` without nEVR:

- **content packs aren't served:** the overlay never loads;
- **the mods' plugins don't load.**

With EchoCombat this means no new gear, the DRONE in its stock look, and the new tac mods hidden, although the same install works on EchoVRCE.

The Mods page also shows the launcher's own EchoLoader as **"Unknown BugSplat64.dll · Not ours"**. Players then re-download nEVR's BugSplat to "fix" it, and the next Play swaps EchoLoader back in.

## Change

- **`mods::echorelay_plugins(v)`:** the plugin list `prepare()` gives nEVR (`config_lines`). The only difference: the pack check doesn't require nEVR's early load pass, because EchoLoader loads every plugin before the game's code runs.
- **`relay::sync_live_mods(v, lines)`,** run at every EchoRelay start on both the Windows path (`play.rs`) and the Linux one (`--play`):
  - copies each enabled plugin from `plugins/` into `plugins-echorelay/`, with its files of the same name (e.g. `PowerBoost.ini`), only when they differ;
  - removes what an earlier start left there that isn't listed now (`EchoRelay.Patch.dll` stays);
  - writes the plugins' args (the overlay's `{"active": "<content>"}`) into **`echoloader.local.json`** as `overrides`, marked with `x-echovr-launcher: echorelay`. `echoloader.json` itself stays byte for byte as `live_in_place` expects it.
  - leaves a player's own (unmarked) `echoloader.local.json` alone.
- **`leave_live`** also removes the launcher's `echoloader.local.json`; the plugins go with the `plugins-echorelay` folder.
- **`Loader::EchoRelay`:** `classify` recognises `relay::LOADER_SHA256`. The Mods page shows "EchoLoader · EchoRelay" with a line explaining it, instead of "Not ours". `editable()` stays false for it, so mods are still switched on and off in EchoVRCE mode, and the next EchoRelay start follows.

## Tested

- **Real EchoLoader 2.0.0** (`c04b0bbb…`, the pinned build), set up exactly as `install_live` does, with EchoCombat 1.1.1's plugins and `NvrContentOverlay` in `plugins-echorelay` and the marked `echoloader.local.json`. Its log:
  - `echoloader.local.json: applied`
  - `5 of 5 plugin(s) loaded` (DroneFix, PowerBoost, VeilNet, NvrContentOverlay, EchoRelay.Patch)
  - `Init content_overlay: NvrPluginInitEx({"active":"echocombat"})`

  The overlay itself logged `serving the pack`. The marker key doesn't stop EchoLoader applying the file.
- **Unit tests:** two added in `relay.rs`:
  - `the_mods_go_beside_the_patch_on_echorelay`: copy, stale removal, overrides, `leave_live` cleanup;
  - `a_players_own_loader_settings_stay`.
- **Not compiled here:** I don't have a Rust toolchain on this machine, so please run `cargo test` before merging.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
