@echo off
rem EchoCombat game server setup (see fix_server.ps1): nEVR off, EchoRelay.Patch in, EchoCombat installed.
rem   fix_server.bat                                   asks for the folders
rem   fix_server.bat "C:\...\ready-at-dawn-echo-arena" ["C:\...\normal install\bin\win10\BugSplat64.dll"]
cd /d "%~dp0"
if not exist "%~dp0install.bat" (
    echo Extract the whole zip first, then run fix_server.bat from the extracted folder.
    pause
    exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0fix_server.ps1" %*
pause
