EchoCombat
==========

DOT FIELD, DRONE, the UMBRAL VEIL, OVERCHARGE (was POWER BOOST) and POINT tac mods,
TRANSLOCATOR's teleport effect and sound, gear icons for the new items, and a fix
for the STARBURST's divide-by-zero log spam (a stock bug that wrote ~120 log lines
a second while the gun was out).
Everything is prebuilt: the patched package files and script code (stage\),
the plugins (bin\win10\plugins\) and the plugin loader (bin\win10\dbgcore.dll).

Install
  Close Echo VR, then run install.bat. It asks where Echo VR is installed
  (the ready-at-dawn-echo-arena folder; drag it into the window, or press
  Enter to take the install it found).
  Install on the game server as well as on clients.

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
  * bin\win10\plugins\PowerBoost.dll, DroneFix.dll, VeilNet.dll
  * bin\win10\dbgcore.dll: the plugin loader, which loads bin\win10\plugins\.
    A dbgcore.dll that was already there (another mod) is moved into plugins\
    so it still loads; an older plugin loader is replaced (kept as .bak). The
    loader logs every plugin it loads, or why it could not, to
    bin\win10\plugins\loader.log.

UMBRAL VEIL or POINT shows up as an energy barrier, or a TRANSLOCATOR teleport
shows no effect, for other players?
  VeilNet.dll tells the other players' games which wall is the veil or POINT, and
  when someone teleports. It goes
  through the game's own connection to the server (no extra ports), so every
  player and the server need it: install EchoCombat on all of them.
  bin\win10\plugins\VeilNet.log on the server and on each player's PC shows
  what was sent and received.

Echo will not start on a PC (e.g. the server)?
  Look at bin\win10\plugins\loader.log first, then run doctor.bat there. It
  checks that the plugin loader and plugins can load on that PC, that echovr.exe
  is the build they were made for, what is in bin\win10\plugins\, and shows the
  plugin logs.

Notes
  * The drone's bullet effects are patched at install time from your own game
    files, so they always match your install.

Tuning
  Every value EchoCombat changes (drone, DOT FIELD, OVERCHARGE: damage reduction,
  heal, recharge, damage bonus, cheat death, link window) comes from one file,
  config/mp_weapon_settings.json in the EchoCombat source, shaped like the game's own
  mp_weapon_settings.json. It is merged into the game's settings and packed when the
  release is built, so to change a value, edit that file and build/deploy again.
  mp_weapon_settings.json in this zip is the copy this release was built with.
