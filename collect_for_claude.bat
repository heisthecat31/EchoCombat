@echo off
cd /d "%~dp0"
set "BRANCH=claude/zealous-wright-z8znnu"
rem Always run the latest tools: switch to the working branch and fetch them first.
rem out\ holds build outputs that are also committed (PowerBoost.dll, ...): a local
rem rebuild would block the pull and leave the old tools running, so it is dropped.
git checkout -- out 2>nul
git fetch origin %BRANCH%
git checkout %BRANCH% 2>nul || git checkout -b %BRANCH% origin/%BRANCH%
git pull --no-rebase --no-edit origin %BRANCH%
if errorlevel 1 (
    echo.
    echo git pull FAILED: the tools were NOT updated. Fix the error above and run this again.
    pause
    exit /b 1
)
git log -1 --format="tools at %%h: %%s"
rem UMBRAL VEIL networking: every script that uses a pooled-actor node (the wall's
rem custom params are read back by one of them). Copied into data\extract;
rem collect_for_claude.py below commits and pushes it with everything else.
python tools\find_scripts.py --no-commit
rem The weapon icon atlas (gear table + HUD): candidates into data\extract\weapon_icons.
python tools\find_weapon_icons.py
rem The equipment station grid: the scripts that show the LOCK slot.
python tools\find_scripts.py --no-commit --symbol LOCK --symbol GRENADE_DOT --symbol ABILITY_HEAL
python tools\collect_for_claude.py %*
pause
