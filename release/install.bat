@echo off
setlocal
rem EchoCombat installer: DOT field, DRONE, UMBRAL VEIL, POWER BOOST, POINT.
rem   install.bat                    asks where Echo VR is
rem   install.bat "D:\path\to\ready-at-dawn-echo-arena"
rem Other mods already repacked into the install (packages _3, _4, ... with a
rem manifests\*.bak) are kept: EchoCombat is merged on top of them.
cd /d "%~dp0"
rem Everything ships next to this file; it is missing when the bat is run from
rem inside the zip (Windows extracts only the bat) or antivirus removed evrtool.exe.
if not exist "%~dp0stage\" goto unzipped
if not exist "%~dp0evrtool.exe" goto noevrtool
set "GAME=%~1"
if defined GAME goto check
rem Suggest the first install found, then ask.
set "GUESS="
if exist "%~dp0..\bin\win10\echovr.exe" for %%i in ("%~dp0..") do set "GUESS=%%~fi"
if not defined GUESS if exist "C:\Program Files\Oculus\Software\Software\ready-at-dawn-echo-arena\bin\win10\echovr.exe" set "GUESS=C:\Program Files\Oculus\Software\Software\ready-at-dawn-echo-arena"
if not defined GUESS if exist "C:\Oculus\Games\Software\Software\ready-at-dawn-echo-arena\bin\win10\echovr.exe" set "GUESS=C:\Oculus\Games\Software\Software\ready-at-dawn-echo-arena"
:ask
echo.
echo Where is Echo VR installed? (the ready-at-dawn-echo-arena folder; you can drag it in here)
if defined GUESS echo Press Enter for: %GUESS%
set "GAME="
set /p "GAME=> "
if not defined GAME set "GAME=%GUESS%"
if not defined GAME goto ask
set "GAME=%GAME:"=%"
:check
rem Accept the folder itself, its bin\win10 folder or echovr.exe.
if /i "%GAME:~-10%"=="echovr.exe" for %%i in ("%GAME%\..\..\..") do set "GAME=%%~fi"
if exist "%GAME%\echovr.exe" for %%i in ("%GAME%\..\..") do set "GAME=%%~fi"
if "%GAME:~-1%"=="\" set "GAME=%GAME:~0,-1%"
if exist "%GAME%\bin\win10\echovr.exe" goto found
echo No bin\win10\echovr.exe in "%GAME%".
goto ask
:found
tasklist /FI "IMAGENAME eq echovr.exe" | find /i "echovr.exe" >nul && (
    echo Close Echo VR first.
    pause
    exit /b 1
)
echo Installing into %GAME%
echo.
"%~dp0evrtool.exe" setup "%GAME%" "%~dp0."
if errorlevel 1 (
    echo.
    echo Install FAILED, see the message above.
    pause
    exit /b 1
)

echo.
echo EchoCombat installed. Install it on the game server too: POWER BOOST needs PowerBoost.dll there.
pause
exit /b 0

:unzipped
echo The EchoCombat files are not next to install.bat.
echo Extract the WHOLE zip first (right-click it, Extract All...), then run
echo install.bat from the extracted folder, not from inside the zip.
pause
exit /b 1

:noevrtool
echo evrtool.exe is missing from %~dp0
echo Your antivirus most likely removed it. Restore it from quarantine (Windows
echo Security, Protection history) or allow it, or extract the zip again.
pause
exit /b 1
