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
python tools\deploy_and_launch.py %*
pause
