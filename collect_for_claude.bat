@echo off
cd /d "%~dp0"
python tools\collect_for_claude.py %*
pause
