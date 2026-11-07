EchoCombat 2.0.3
================

New and fixed gear for Echo VR's Echo Combat (PC build 631547.rad15_live).
Everything is prebuilt: the patched package files and script code (stage\), the
plugins (bin\win10\plugins\) and the plugin loader (bin\win10\dbgcore.dll).

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
  * Station, HUD and spectator HUD icons for the new gear.

New in 2.0.3
  * A new match starts with the default RULES. Before, a server kept the last
    private match's rules (POINT UNLOCK, CAPTURE TIME, ...) for every match after
    it, public ones too. A map switch from the post-match terminal keeps them.
  * RULES and PAUSE only work in private matches.
  Update the game server.

New in 2.0.2
  * Post-match map buttons now work on every EchoCombat server. Before, a server
    without a symbol-name plugin took private matches for public ones and ignored
    the buttons. Update the game server.
  * The F8 END MATCH test key is gone.
  * (Has the fix for the launcher 2.0.0 pack's crash when firing the Pulsar after
    using UMBRAL VEIL.)

New in 2.0.0: private match rules (Combat private matches)
  The game server needs EchoCombat 2.0.0 too; on a stock server you get stock Combat.
  * RULES on the podium terminal (like Arena's): change values with - / +, NEXT for
    page 2. Every player sees the server's values.
      Page 1: POINT UNLOCK (seconds before the point unlocks; the announcer follows
      it), CAPTURE TIME (0 = instant capture), BLUE / ORANGE SCORE (starting points,
      75 wins).
      Page 2: LOADOUTS (ALL / CLASSIC: the 12 stock items / NEW: only the new guns;
      players on banned gear are swapped), SERIES-10 ONLY (everyone shows the
      Series-10 body), POINT RATE (how fast a held point scores, 0.25x to 2.5x).
  * PAUSE / UNPAUSE: once both teams are ready, TEAM READY becomes PAUSE. Pausing
    sends everyone back to the war room with guns, tac mods and ordnances off and
    every clock frozen; unpausing counts down 5..1.
  * Payload maps (Fission, Gauss): LOADOUTS, SERIES-10 ONLY and PAYLOAD SPEED. While
    the payload moves, PAUSE waits for the next checkpoint (QUEUED).
  * Post-match terminal: buttons for the other Combat maps beside LOBBY / REMATCH.

Install
  Close Echo VR, then run install.bat. It asks where Echo VR is installed
  (the ready-at-dawn-echo-arena folder; drag it into the window, or press
  Enter to take the install it found).
  Install on the game server as well as on every client: several features
  (OVERCHARGE, UMBRAL VEIL, NEUTRON, TRANSLOCATOR) run partly on the server.

Other mods are kept
  If another mod already repacked the game (packages\48037dc70b0ecab2_3, _4,
  ... and manifests\48037dc70b0ecab2.bak exist), EchoCombat is MERGED on top:
  their delta packages stay and ours are added after them. Running install.bat
  again replaces EchoCombat's own files instead of stacking more.

Uninstall
  uninstall.bat takes EchoCombat back out and keeps the other mods.
  "evrtool restore <_data\5932408047\rad15\win10>" resets to stock (removes ALL mods).

What it writes into the game
  * the merged package (see above)
  * bin\win10\scripts\<hash>.dll: the patched scripts; each original is kept as
    <hash>.dll.orig
  * bin\win10\plugins\PowerBoost.dll, DroneFix.dll, VeilNet.dll, and PowerBoost.ini
    (OVERCHARGE's damage bonus, cheat death and link settings)
  * bin\win10\dbgcore.dll: the plugin loader, which loads bin\win10\plugins\.
    A dbgcore.dll that was already there (another mod) is moved into plugins\
    so it still loads; an older plugin loader is replaced (kept as .bak).

UMBRAL VEIL or NEUTRON shows up as an energy barrier, or a TRANSLOCATOR teleport
shows no effect, for other players?
  VeilNet.dll tells the other players' games which wall is the veil or NEUTRON, and
  when someone teleports. It goes through the game's own connection to the server
  (no extra ports), so every player and the server need it: install EchoCombat on
  all of them.

OVERCHARGE gives no damage bonus or cheat death?
  Those are decided on the server: the server needs EchoCombat installed.

Echo will not start on a PC (e.g. the server)?
  Run doctor.bat there. It checks that the plugin loader and plugins can load on
  that PC, that echovr.exe is the build they were made for, and what is in
  bin\win10\plugins\. (The plugins write no logs, so they cost slow PCs nothing.)

Notes
  * The drone's bullet effects are patched at install time from your own game
    files, so they always match your install.

Tuning (for server hosts building their own)
  Every value EchoCombat changes (drone, DOT FIELD, UMBRAL VEIL, NEUTRON, TRANSLOCATOR
  and OVERCHARGE) comes from one file in the EchoCombat source,
  config/mp_weapon_settings.json, shaped like the game's own mp_weapon_settings.json.
  It is packed into the game data when the release is built: edit it, then build the
  release again (see the source's README.md). mp_weapon_settings.json in this zip
  is the copy this release was built with.
