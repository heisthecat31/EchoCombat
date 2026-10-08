@echo off
setlocal
rem EchoCombat installer: DOT field, DRONE, UMBRAL VEIL, POWER BOOST.
rem   install.bat                    asks where Echo VR is
rem   install.bat "D:\path\to\ready-at-dawn-echo-arena"
rem Other mods already repacked into the install (packages _3, _4, ... with a
rem manifests\*.bak) are kept: EchoCombat is merged on top of them.
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
    echo wrote scripts\%%~nxf
)

rem POWER BOOST's damage reduction and the drone crash guard are plugins.
set "PLUGINS=%GAME%\bin\win10\plugins"
if not exist "%PLUGINS%" mkdir "%PLUGINS%"
copy /y "%~dp0bin\win10\plugins\PowerBoost.dll" "%PLUGINS%\" >nul
copy /y "%~dp0bin\win10\plugins\DroneFix.dll" "%PLUGINS%\" >nul
echo wrote plugins\PowerBoost.dll, DroneFix.dll

echo.
echo EchoCombat installed. Install it on the game server too: POWER BOOST needs PowerBoost.dll there.
pause
