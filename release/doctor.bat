@echo off
setlocal
rem Why won't Echo VR start on this PC? Checks the plugin loader and plugins can
rem load here (Visual C++ runtime), that echovr.exe is the build they were made
rem for, what is in plugins\, and shows the end of the plugin logs.
cd /d "%~dp0"
if not exist "%~dp0evrtool.exe" (
    echo evrtool.exe is missing next to doctor.bat: extract the whole zip, and check
    echo your antivirus did not remove it.
    pause
    exit /b 1
)
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
"%~dp0evrtool.exe" doctor "%GAME%" "%~dp0."
echo.
pause
