@echo off
setlocal
rem Takes EchoCombat back out and leaves any other mods in place.
cd /d "%~dp0"
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
set "DATA=%GAME%\_data\5932408047\rad15\win10"
evrtool.exe unmerge "%DATA%"
if errorlevel 1 (
    pause
    exit /b 1
)
set "EVR_PKG=2b47aab238f60515"
evrtool.exe unmerge "%DATA%"
set "EVR_PKG="

set "SCRIPTS=%GAME%\bin\win10\scripts"
for %%f in ("%~dp0bin\win10\scripts\*.dll") do (
    if exist "%SCRIPTS%\%%~nxf.orig" (
        move /y "%SCRIPTS%\%%~nxf.orig" "%SCRIPTS%\%%~nxf" >nul
    ) else (
        del /q "%SCRIPTS%\%%~nxf" 2>nul
    )
)
del /q "%GAME%\bin\win10\plugins\PowerBoost.dll" "%GAME%\bin\win10\plugins\DroneFix.dll" 2>nul
echo EchoCombat removed.
pause
