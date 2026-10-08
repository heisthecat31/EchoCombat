@echo off
cd /d "%~dp0"
rem Runs the tools in this folder as they are: no git fetch / pull, so local edits are
rem what gets deployed. Arguments go to tools\deploy_and_launch.py (e.g. --kill).
git log -1 --format="tools at %%h: %%s" 2>nul
python tools\deploy_and_launch.py %*
pause
