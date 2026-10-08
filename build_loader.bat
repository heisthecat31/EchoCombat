@echo off
setlocal
set "VARS_BAT="
set "VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
if exist "%VSWHERE%" (
    for /f "usebackq tokens=*" %%i in (`"%VSWHERE%" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do (
        if exist "%%i\VC\Auxiliary\Build\vcvars64.bat" set "VARS_BAT=%%i\VC\Auxiliary\Build\vcvars64.bat"
    )
)
if not defined VARS_BAT (
    echo [ERROR] MSVC not found.
    exit /b 1
)
if not defined VSCMD_ARG_TGT_ARCH call "%VARS_BAT%" >nul
cd /d "%~dp0"
if not exist out mkdir out
if not exist obj mkdir obj
rem /MT: the C runtime is linked in, so it loads on PCs (servers) without the Visual C++ runtime.
cl.exe /nologo /LD /MT /O2 /W3 /Foobj\ /Fe"out\dbgcore.dll" plugin\loader.cpp
if %ERRORLEVEL% neq 0 exit /b %ERRORLEVEL%
del /q out\*.exp out\*.lib 2>nul
echo Built out\dbgcore.dll (the plugin loader)
