@echo off
setlocal
rem Takes EchoCombat back out and leaves any other mods in place.
cd /d "%~dp0"
set "GAME=%~1"
if not defined GAME if exist "%~dp0..\bin\win10\echovr.exe" for %%i in ("%~dp0..") do set "GAME=%%~fi"
if not defined GAME if exist "C:\Program Files\Oculus\Software\Software\ready-at-dawn-echo-arena\bin\win10\echovr.exe" set "GAME=C:\Program Files\Oculus\Software\Software\ready-at-dawn-echo-arena"
if not defined GAME set "GAME=C:\Oculus\Games\Software\Software\ready-at-dawn-echo-arena"
if not exist "%GAME%\bin\win10\echovr.exe" (
    echo Echo VR not found at "%GAME%". Run: uninstall.bat "path\to\ready-at-dawn-echo-arena"
    pause
    exit /b 1
)
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
