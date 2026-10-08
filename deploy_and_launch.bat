@echo off
cd /d "%~dp0"
rem Pass --gunpatch <folder> the first time, e.g.  deploy_and_launch.bat --gunpatch J:\combatGunPatchFiles
python tools\deploy_and_launch.py %*
pause
