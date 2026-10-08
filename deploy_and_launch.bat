@echo off
cd /d "%~dp0"
python tools\deploy_and_launch.py %*
pause
