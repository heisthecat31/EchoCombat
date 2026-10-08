@echo off
cd /d "%~dp0"
set "BRANCH=claude/zealous-wright-z8znnu"
rem Always run the latest tools: switch to the working branch and fetch them first.
git fetch origin %BRANCH%
git checkout %BRANCH% 2>nul || git checkout -b %BRANCH% origin/%BRANCH%
git pull --no-rebase --no-edit origin %BRANCH%
rem UMBRAL VEIL networking: every script that uses a pooled-actor node (the wall's
rem custom params are read back by one of them). Copied into data\extract;
rem collect_for_claude.py below commits and pushes it with everything else.
python tools\find_scripts.py --no-commit
python tools\collect_for_claude.py %*
pause
