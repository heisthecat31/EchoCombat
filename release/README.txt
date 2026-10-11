EchoCombat
==========

New and fixed gear for Echo VR's Echo Combat (PC build 631547.rad15_live).
Everything is prebuilt: the content pack (content\echocombat\: the game data and
script code EchoCombat changes) and the plugins (plugins\).

What it adds
  * DOT FIELD (ordnance): the unfinished damage-over-time grenade, working. Throw,
    trigger, 3.5 m damage field.
  * DRONE (ordnance): the cut auto-targeting drone, working (a shot every 0.15 s).
  * UMBRAL VEIL (tac mod): a wall of smoke clouds.
  * OVERCHARGE (tac mod, was POWER BOOST): aim at teammates and use it. You get a
    small heal, damage reduction and +1 body / +2 head damage on your gun hits for
    10 s. The teammates in your aim cone when you use it get the heal, damage
    reduction and cheat death (a killing hit leaves them on 1 health) for 5 s.
  * NEUTRON (tac mod, was POINT): place a wall that goes off as a stun field.
  * TRANSLOCATOR: a teleport effect and sound everyone sees and hears.
  * STARBURST: fixes a stock bug that wrote ~120 log lines a second while the gun
    was out.
  * Station and HUD icons for the new gear.

Install
  In the Echo VR launcher: Mods, More mods, EchoCombat, Get. Switch it off or
  Remove it there too. Install it on the game server as well as on every client:
  several features (OVERCHARGE, UMBRAL VEIL, NEUTRON, TRANSLOCATOR) run partly on the
  server, and a player without it can't play in a match with it (and the other way
  round).

Where you play it
  A match only has EchoCombat when its game server runs it, so EchoCombat plays on
  servers of its own. In the launcher: Settings, Launch options, EchoCombat server,
  Server...: the address and key its host gives you, and your account there (a
  Discord ID and a password). While EchoCombat is on, the game signs in and finds
  matches there; switched off (or with the address empty) it's EchoVRCE as always.

Nothing in the game's own files changes
  The launcher puts plugins\ into bin\win10\plugins\ and content\ into
  bin\win10\content\, and lists them in _local\config.yaml for nEVR (the game's
  runtime). While Echo runs, NvrContentOverlay (a plugin the launcher installs
  with it) hands the game EchoCombat's data and scripts in place of the stock
  files. Switched off, the game is stock.
  The pack only works on stock game files: it checks them first and does nothing
  if they were changed (see "Installed with install.bat before?").

Game servers (no launcher)
  Needs nEVR with its early load pass (BugSplat64.dll from the launcher's Beta
  channel or newer) and NvrContentOverlay.dll in bin\win10\plugins\.
  1. Copy plugins\* into bin\win10\plugins\ and content\ into bin\win10\.
  2. Add to the plugins: list in _local\config.yaml (keep the rest of the file):
       - name: "NvrContentOverlay"
         file: "NvrContentOverlay.dll"
         early: true
         args: {"active":"echocombat"}
       - name: "DroneFix"
         file: "DroneFix.dll"
       - name: "PowerBoost"
         file: "PowerBoost.dll"
       - name: "VeilNet"
         file: "VeilNet.dll"
  3. bin\win10\plugin_logs\NvrContentOverlay\NvrContentOverlay.log should say
     "serving the pack", and nEVR's log "Loaded:" for each plugin.

Installed with install.bat before?
  That version repacked the game's own files. The launcher sees it and offers to
  restore the stock files first. By hand: Install in the launcher on that
  version again (it checks and repairs the game files), then delete
  bin\win10\dbgcore.dll if it is still there (nEVR does not start beside it).

UMBRAL VEIL or NEUTRON shows up as an energy barrier, or a TRANSLOCATOR teleport
shows no effect, for other players?
  VeilNet.dll tells the other players' games which wall is the veil or NEUTRON, and
  when someone teleports. It goes through the game's own connection to the server
  (no extra ports), so every player and the server need it. On a server without
  EchoCombat, UMBRAL VEIL, OVERCHARGE and NEUTRON are hidden from the tac mod list.

OVERCHARGE gives no damage bonus or cheat death?
  Those are decided on the server: the server needs EchoCombat installed.

The new gear isn't there?
  bin\win10\plugin_logs\NvrContentOverlay\NvrContentOverlay.log says why: a game
  file that isn't stock, a pack file that changed, or "loaded too late" (nEVR
  without the early load pass, or the entry without early: true).
  (EchoCombat's own plugins write no logs, so they cost slow PCs nothing.)

Tuning (for server hosts building their own)
  Every value EchoCombat changes (drone, DOT FIELD, UMBRAL VEIL, NEUTRON, TRANSLOCATOR
  and OVERCHARGE) comes from one file in the EchoCombat source,
  config/mp_weapon_settings.json, shaped like the game's own mp_weapon_settings.json.
  It is packed into the game data when the release is built: edit it, then build the
  release again (see the source's README.md). mp_weapon_settings.json in this zip
  is the copy this release was built with. OVERCHARGE's plugin-side values are in
  plugins\PowerBoost.ini.
