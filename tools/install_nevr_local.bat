@echo off
rem EchoCombat for nEVR, without the launcher. Put EchoCombat-<version>.zip next to this file and
rem double-click it. "install_nevr_local.bat -Uninstall" removes it.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_nevr_local.ps1" %*
pause
