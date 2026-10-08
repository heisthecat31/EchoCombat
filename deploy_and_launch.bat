@echo off
cd /d "%~dp0"
set "BRANCH=claude/zealous-wright-z8znnu"
rem Always run the latest tools: switch to the working branch and fetch them first.
git fetch origin %BRANCH%
git checkout %BRANCH% 2>nul || git checkout -b %BRANCH% origin/%BRANCH%
git pull --no-rebase --no-edit origin %BRANCH%
python tools\deploy_and_launch.py %*
pause
