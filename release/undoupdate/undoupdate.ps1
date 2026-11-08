# Puts nEVR 6.16.4 back in place of 6.17 (6.17 carries a built-in EchoCombat that breaks the
# EchoCombat pack's tac mods, RULES and PAUSE). nEVR is two files that must match:
#   nevr-runtime.dll  (in the nEVR folder: %LOCALAPPDATA%\nevr\echovr, the launcher's nevr\<build>,
#                      each hosted server's appdata\nevr\echovr)
#   BugSplat64.dll    (nEVR's loader stub, in the game's bin\win10, and each hosted server's root\bin\win10)
# Every copy found that isn't 6.16.4 is replaced; the old file is kept beside it as <name>.6.17.bak.
# Game folders: dropped on undoupdate.bat / given as arguments, or typed when asked.
param([switch]$IgnoreRunning, [Parameter(ValueFromRemainingArguments = $true)][string[]]$GameFolders = @())

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$want = '6.16.4'
$src = @{
    'nevr-runtime.dll' = Join-Path $here 'files\nevr-runtime.dll'
    'BugSplat64.dll'   = Join-Path $here 'files\BugSplat64.dll'
}
foreach ($f in $src.Values) {
    if (-not (Test-Path $f)) { Write-Host "Missing $f - unpack the whole zip first." -ForegroundColor Red; exit 1 }
}

# Only the game itself (echovr.exe; echovr_openxr.exe for EchoXR) holds these files: the launcher
# (EchoVR_Launcher.exe) may stay open.
$running = Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -in @('echovr', 'echovr_openxr') }
if ($running -and -not $IgnoreRunning) {
    Write-Host "Echo VR is running: $(($running | ForEach-Object { "$($_.ProcessName).exe (pid $($_.Id))" }) -join ', ')" -ForegroundColor Yellow
    Write-Host "Close the game and stop every server on the launcher's Server host page, then run this again."
    exit 1
}

# A BugSplat64.dll counts only when it is nEVR's stub (it names nevr-runtime), not the real BugSplat.
function Test-NevrStub([string]$path) {
    $text = [Text.Encoding]::ASCII.GetString([IO.File]::ReadAllBytes($path))
    return $text.Contains('nevr-runtime')
}

$found = New-Object System.Collections.Generic.List[string]
$roots = @("$env:LOCALAPPDATA\EchoVR_Launcher", "$env:LOCALAPPDATA\nevr") | Where-Object { Test-Path $_ }
foreach ($r in $roots) {
    Get-ChildItem $r -Recurse -File -Include 'nevr-runtime.dll','BugSplat64.dll' -ErrorAction SilentlyContinue |
        ForEach-Object { $found.Add($_.FullName) }
}

# The launcher's Mod loader card compares the game's bin\win10\BugSplat64.dll (its version is what
# the card shows) with %LOCALAPPDATA%\EchoVR_Launcher\nevr\<build>\nevr-runtime.dll. Each such
# folder's structure.json names its game's bin\win10: those slots are found without asking.
$launcherBins = @()
Get-ChildItem "$env:LOCALAPPDATA\EchoVR_Launcher\nevr" -Directory -ErrorAction SilentlyContinue | ForEach-Object {
    $s = Join-Path $_.FullName 'structure.json'
    if (Test-Path $s) {
        try {
            $bin = (Get-Content $s -Raw | ConvertFrom-Json).bin
            if ($bin -and (Test-Path (Join-Path $bin 'BugSplat64.dll'))) {
                $launcherBins += $bin
                $found.Add((Resolve-Path (Join-Path $bin 'BugSplat64.dll')).Path)
                Write-Host "game folder from the launcher: $bin"
            }
        } catch { }
    }
}

if ((-not $GameFolders -or $GameFolders.Count -eq 0) -and $launcherBins.Count -eq 0) {
    Write-Host ""
    Write-Host "Your Echo VR game folder (the one with bin\win10 in it, e.g. ...\ready-at-dawn-echo-arena)."
    $typed = Read-Host "Drag it here or type the path, Enter to skip"
    if ($typed) { $GameFolders = @($typed.Trim('"', ' ')) }
}
foreach ($g in $GameFolders) {
    $g = $g.Trim('"', ' ')
    foreach ($c in @((Join-Path $g 'bin\win10\BugSplat64.dll'), (Join-Path $g 'BugSplat64.dll'))) {
        if (Test-Path $c) { $found.Add((Resolve-Path $c).Path) }
    }
}

$done = 0; $same = 0; $skipped = 0
foreach ($path in ($found | Sort-Object -Unique)) {
    $name = Split-Path -Leaf $path
    $key = $src.Keys | Where-Object { $_ -ieq $name }
    if ($key -ieq 'BugSplat64.dll' -and -not (Test-NevrStub $path)) { $skipped++; continue }
    $ver = (Get-Item $path).VersionInfo.FileVersion
    if ($ver -eq $want) { Write-Host "already $want  $path"; $same++; continue }
    $bak = "$path.6.17.bak"
    Copy-Item $path $bak -Force
    Copy-Item $src[$key] $path -Force
    Write-Host ("{0} -> {1}  {2}" -f $(if ($ver) { $ver } else { '?' }), $want, $path) -ForegroundColor Green
    $done++
}

Write-Host ""
Write-Host "$done file(s) put back to $want, $same already were." -ForegroundColor Cyan
if ($skipped) { Write-Host "$skipped BugSplat64.dll left alone (the real BugSplat, not nEVR's)." }
if ($done -eq 0 -and $same -eq 0) {
    Write-Host "No nEVR files found. Run it again and give your Echo VR game folder." -ForegroundColor Yellow
}
Write-Host "Restart the launcher and your servers. The Mod loader card should read nEVR runtime $want."
Write-Host "Don't press 'Repair game files' or accept a nEVR update: either brings 6.17 back."
