@echo off
setlocal
rem EchoCombat installer: DOT field, DRONE, UMBRAL VEIL, POWER BOOST.
rem   install.bat                    the Oculus install
rem   install.bat "D:\path\to\ready-at-dawn-echo-arena"
rem Other mods already repacked into the install (packages _3, _4, ... with a
rem manifests\*.bak) are kept: EchoCombat is merged on top of them.
cd /d "%~dp0"
set "GAME=%~1"
if not defined GAME if exist "%~dp0..\bin\win10\echovr.exe" for %%i in ("%~dp0..") do set "GAME=%%~fi"
if not defined GAME if exist "C:\Program Files\Oculus\Software\Software\ready-at-dawn-echo-arena\bin\win10\echovr.exe" set "GAME=C:\Program Files\Oculus\Software\Software\ready-at-dawn-echo-arena"
if not defined GAME set "GAME=C:\Oculus\Games\Software\Software\ready-at-dawn-echo-arena"
if not exist "%GAME%\bin\win10\echovr.exe" (
    echo Echo VR not found at "%GAME%".
    echo Run: install.bat "path\to\ready-at-dawn-echo-arena"
    pause
    exit /b 1
)
tasklist /FI "IMAGENAME eq echovr.exe" | find /i "echovr.exe" >nul && (
    echo Close Echo VR first.
    pause
    exit /b 1
)
set "DATA=%GAME%\_data\5932408047\rad15\win10"
echo Installing into %GAME%

evrtool.exe install "%DATA%" "%~dp0stage"
if errorlevel 1 (
    echo.
    echo Package merge FAILED, nothing else was changed.
    pause
    exit /b 1
)

rem Echo loads script code from bin\win10\scripts\<hash>.dll, not the package.
rem Each original is kept once as <hash>.dll.orig (uninstall.bat puts it back).
set "SCRIPTS=%GAME%\bin\win10\scripts"
if not exist "%SCRIPTS%" mkdir "%SCRIPTS%"
for %%f in ("%~dp0bin\win10\scripts\*.dll") do (
    if exist "%SCRIPTS%\%%~nxf" if not exist "%SCRIPTS%\%%~nxf.orig" copy /y "%SCRIPTS%\%%~nxf" "%SCRIPTS%\%%~nxf.orig" >nul
    copy /y "%%f" "%SCRIPTS%\%%~nxf" >nul
    echo wrote %SCRIPTS%\%%~nxf
)

rem POWER BOOST's damage reduction and the drone crash guard are plugins.
set "PLUGINS=%GAME%\bin\win10\plugins"
if not exist "%PLUGINS%" mkdir "%PLUGINS%"
copy /y "%~dp0bin\win10\plugins\PowerBoost.dll" "%PLUGINS%\" >nul
copy /y "%~dp0bin\win10\plugins\DroneFix.dll" "%PLUGINS%\" >nul
echo wrote %PLUGINS%\PowerBoost.dll, DroneFix.dll

echo.
echo EchoCombat installed. Install it on the game server too: POWER BOOST needs PowerBoost.dll there.
pause
