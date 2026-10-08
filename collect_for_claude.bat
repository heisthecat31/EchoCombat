@echo off
cd /d "%~dp0"
rem Always run the latest tools: fetch them first.
git pull --no-rebase --no-edit origin claude/relaxed-ramanujan-daobqg
python tools\collect_for_claude.py %*
pause
