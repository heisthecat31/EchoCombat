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
  * bin\win10\plugins\PowerBoost.dll, DroneFix.dll
  * bin\win10\dbgcore.dll: the plugin loader, which loads bin\win10\plugins\.
    A dbgcore.dll that was already there (another mod) is moved into plugins\
    so it still loads. The loader needs the Visual C++ 2015-2022 x64 runtime.

Notes
  * The drone's bullet effects are patched at install time from your own game
    files, so they always match your install.
