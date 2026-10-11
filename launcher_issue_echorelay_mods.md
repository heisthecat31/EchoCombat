# EchoRelay mode (Game server plugin) drops every mod, including content packs

**Launcher:** 0.11.12 (beta, `3f55aa9`), Game server plugin 0.2.0, Windows, live build (`pc-latest`)

## What happens

When the Game server plugin plays the live build on an EchoRelay server, none of the player's mods load. With EchoCombat 1.1.1 installed and switched on, players get stock Echo: no new gear, the DRONE in its stock look, and the new tac mods hidden. The same install on EchoVRCE (nEVR mode) loads EchoCombat fine: the overlay logs `serving the pack`, and all plugins load.

## Why

`src/core/launcher/relay.rs`, `install_live()` / `LIVE_LOADER_CONFIG_JSON`:

- EchoLoader 2 goes into the `BugSplat64.dll` slot (nEVR is moved aside to `BugSplat64.nevr.dll`).
- `echoloader.json` sets `"plugins_dir": "plugins-echorelay"`, and the only file written there is `EchoRelay.Patch.dll`.
- The comment on `LIVE_PLUGINS` says nEVR's mods in `plugins/` "stay out (they're nEVR's)".

With nEVR out of the slot, nothing reads `config.yaml`. So:

- **The content overlay never loads.** `NvrContentOverlay` writes no log for these sessions, so no content pack is served.
- **The mods' plugins never load**, for example DroneFix, PowerBoost and VeilNet.

## Suggested fix

In EchoRelay mode, give EchoLoader the enabled mods too, not just EchoRelay's patch:

1. **Copy the plugins in.** Copy each enabled mod plugin (what `config.yaml` would list for nEVR) into `plugins-echorelay/`, next to `EchoRelay.Patch.dll`. `leave_live()` already removes the folder when going back to nEVR.
2. **Load content packs.** When a content pack is on, also put `NvrContentOverlay.dll` in, with its args `{"active":"<content>"}`. EchoLoader loads its plugins before any game code runs, which is the early load the overlay needs. Its strings show it calls `NvrPluginInitEx(args)` and reports "args configured but it has no InitEx/PluginInit". So if `echoloader.json` can carry per-plugin args, the overlay can be given its `active` pack that way. Otherwise the args need another route.
3. **Plugin ABI.** EchoCombat's plugins export `NvrPluginGetInfo`, `NvrPluginGetApiVersion`, `NvrPluginInitEx` and `NvrPluginShutdown` (nEVR API v5), which EchoLoader 2 appears to support.

## Related: things that confuse players

- **The Mods page shows "Unknown BugSplat64.dll · Not ours" while EchoRelay mode is set up.** That's `src/ui/launcher/mods.rs`, `Loader::Unknown`: it only recognises the game's DLL and nEVR, and EchoLoader is the launcher's own. Players then re-download nEVR's BugSplat to "fix" it, the next Play swaps EchoLoader back in, and they go round in a loop. The fix: recognise EchoLoader (`LOADER_SHA256`) as "EchoRelay mode".
- **Settings → "EchoCombat server" with an EchoRelay address** writes `services.socket_uri: ws://<relay>/ws?format=evr` into `config.yaml`. EchoRelay has no nEVR bridge endpoint, so login hangs at "Logging in…". That field only works with an nEVR / Nakama backend, and the UI could say so, or send EchoRelay addresses to the Game server plugin.
- **nEVR clients on EchoRelay without EchoLoader** (nEVR mode, `config.json` pointing at the relay) work from EchoRelay 0.9.7. nEVR logs in through EchoVRCE, and 0.9.7 accepts that session for accounts without an account lock.

## Workaround for now

EchoRelay players run the EchoCombat server kit's `install.bat` (`EchoCombat-Server-1.1.1.zip`). It writes EchoCombat into the game files with its own `dbgcore.dll` loader, so it works under EchoLoader. The drawbacks:

- the launcher then reports "game files changed" and keeps the pack off;
- Verify removes EchoCombat again;
- updates are manual.
