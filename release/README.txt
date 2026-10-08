EchoCombat
==========

DOT FIELD, DRONE, UMBRAL VEIL (smoke tac mod) and POWER BOOST (tac mod).
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

UMBRAL VEIL shows up as an energy barrier for other players?
  VeilNet.dll tells the other players' games which wall is the veil, through the
  game server, over its own UDP ports 6970-6977. On the PC that runs the game
  server, let echovr.exe receive UDP on those ports (Windows asks the first time;
  allow it) and, if players connect from outside your network, forward UDP
  6970-6977 to that PC like the game's own port. bin\win10\plugins\VeilNet.log
  on the server and on each player's PC shows what was sent and received. To use
  other ports, or if a client cannot find the server by itself, create
  bin\win10\plugins\VeilNet.ini on each PC:
      [veil]
      port=6970
      server=203.0.113.5      (clients only: the game server's IP address)

Echo will not start on a PC (e.g. the server)?
  Look at bin\win10\plugins\loader.log first, then run doctor.bat there. It
  checks that the plugin loader and plugins can load on that PC, that echovr.exe
  is the build they were made for, what is in bin\win10\plugins\, and shows the
  plugin logs.

Notes
  * The drone's bullet effects are patched at install time from your own game
    files, so they always match your install.
