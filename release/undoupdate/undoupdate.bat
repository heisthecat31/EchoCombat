@echo off
rem Puts nEVR 6.16.4 back in place of 6.17. Drop your Echo VR game folder on this file, or run it
rem and give the folder when asked. Close Echo VR and stop all hosted servers first.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0undoupdate.ps1" %*
echo.
pause
