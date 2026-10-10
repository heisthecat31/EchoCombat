# EchoCombat game server setup: makes an Echo VR install a normal (non-nEVR) EchoRelay game
# server with EchoCombat on it.
#
# An nEVR game server never sends EchoRelay a login (nEVR injects it through its own service
# bridge), so it stays at "Logging in..." and never hosts. Players on nEVR (the launcher's
# EchoCombat mod) play fine on a normal server. This:
#   1. puts the stock BugSplat64.dll back in place of nEVR's (echovr.exe needs one; nEVR's is ~30 MB)
#   2. moves nEVR's plugins (Nvr*.dll, the nEVR builds of EchoCombat's) and _local\config.yaml aside
#   3. makes sure EchoRelay's game patch (EchoRelay.Patch: server login, headless) is there
#   4. runs install.bat: EchoCombat's game data, plugins and plugin loader (dbgcore.dll)
# Everything moved goes to bin\win10\_nevr_backup_<time>\ (see RESTORE.txt there).
#
#   fix_server.bat                                   asks for the folders
#   fix_server.bat "C:\...\ready-at-dawn-echo-arena" ["C:\...\a normal install\bin\win10\BugSplat64.dll"]
param([string]$Game, [string]$StockBugSplat)
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$NevrBugSplatMin = 5MB          # stock BugSplat64.dll is ~0.6 MB, nEVR's ~30 MB

function Resolve-Game([string]$p) {
    if (-not $p) { return $null }
    $p = $p.Trim('"', ' ')
    if ($p -like '*echovr.exe') { $p = Split-Path (Split-Path (Split-Path $p)) }
    elseif (Test-Path (Join-Path $p 'echovr.exe')) { $p = Split-Path (Split-Path $p) }
    if (Test-Path (Join-Path $p 'bin\win10\echovr.exe')) { return (Resolve-Path $p).Path }
    return $null
}

function Test-EchoRelayPatch([string]$dll) {
    # EchoRelay.Patch logs to echorelay_patch.log: the name is in the DLL.
    $bytes = [IO.File]::ReadAllBytes($dll)
    return [Text.Encoding]::ASCII.GetString($bytes).Contains('echorelay_patch')
}

$GameDir = Resolve-Game $Game
while (-not $GameDir) {
    $answer = Read-Host 'Echo VR folder the game servers run from (ready-at-dawn-echo-arena; drag it in here)'
    $GameDir = Resolve-Game $answer
    if (-not $GameDir) { Write-Host '  No bin\win10\echovr.exe there.' }
}
$bin = Join-Path $GameDir 'bin\win10'
Write-Host "Game server folder: $GameDir"

if (Get-Process echovr -ErrorAction SilentlyContinue) {
    Write-Host 'Close every Echo VR / game server first (echovr.exe is running).' -ForegroundColor Red
    exit 1
}

$backup = Join-Path $bin ('_nevr_backup_' + (Get-Date -Format 'yyyyMMdd_HHmmss'))
$moved = @()
function Move-Aside([string]$path) {
    if (-not (Test-Path $path)) { return }
    if (-not (Test-Path $backup)) { New-Item -ItemType Directory $backup | Out-Null }
    $rel = $path.Substring($GameDir.Length).TrimStart('\')
    $dest = Join-Path $backup $rel
    New-Item -ItemType Directory (Split-Path $dest) -Force | Out-Null
    Move-Item $path $dest -Force
    $script:moved += $rel
    Write-Host "  moved aside: $rel"
}

# 1. BugSplat64.dll
$bugsplat = Join-Path $bin 'BugSplat64.dll'
if ((Test-Path $bugsplat) -and (Get-Item $bugsplat).Length -lt $NevrBugSplatMin) {
    Write-Host 'BugSplat64.dll is the stock one (no nEVR).'
} else {
    $candidates = @($StockBugSplat) + @('BugSplat64.dll.stock', 'BugSplat64.dll.orig', 'BugSplat64.dll.bak' | ForEach-Object { Join-Path $bin $_ })
    $stock = $candidates | Where-Object { $_ -and (Test-Path $_) -and (Get-Item $_).Length -lt $NevrBugSplatMin } | Select-Object -First 1
    while (-not $stock) {
        Write-Host 'nEVR is installed here (BugSplat64.dll is nEVR''s). The stock BugSplat64.dll is needed instead:'
        $answer = (Read-Host 'a normal Echo VR install, or its bin\win10\BugSplat64.dll (drag it in here)').Trim('"', ' ')
        if ($answer -and (Test-Path (Join-Path $answer 'bin\win10\BugSplat64.dll'))) { $answer = Join-Path $answer 'bin\win10\BugSplat64.dll' }
        elseif ($answer -and (Test-Path (Join-Path $answer 'BugSplat64.dll'))) { $answer = Join-Path $answer 'BugSplat64.dll' }
        if ($answer -and (Test-Path $answer) -and (Get-Item $answer).Length -lt $NevrBugSplatMin) { $stock = $answer }
        else { Write-Host '  That is not a stock BugSplat64.dll (it must be under 5 MB).' }
    }
    $stockCopy = Join-Path $env:TEMP 'echocombat_stock_BugSplat64.dll'
    Copy-Item $stock $stockCopy -Force
    Move-Aside $bugsplat
    Copy-Item $stockCopy $bugsplat -Force
    Remove-Item $stockCopy -Force
    Write-Host "  stock BugSplat64.dll from $stock"
}

# 2. nEVR's plugins and config
$plugins = Join-Path $bin 'plugins'
if (Test-Path $plugins) {
    Get-ChildItem $plugins -Filter 'Nvr*' -File | ForEach-Object { Move-Aside $_.FullName }
    foreach ($name in 'DroneFix.dll', 'PowerBoost.dll', 'VeilNet.dll', 'CombatBots.dll') {
        $p = Join-Path $plugins $name
        if ((Test-Path $p) -and [Text.Encoding]::ASCII.GetString([IO.File]::ReadAllBytes($p)).Contains('NvrPluginGetInfo')) {
            Move-Aside $p                                   # nEVR's build; install.bat puts the normal one in
        }
    }
}
Move-Aside (Join-Path $GameDir '_local\config.yaml')

# 3. EchoRelay's game patch: one copy. (A bin\win10\dbgcore.dll that is the patch, install.bat
# moves into plugins\. Two copies in plugins\ would both load and patch the game twice.)
$relayPatches = @(@(Join-Path $bin 'dbgcore.dll') + @(if (Test-Path $plugins) { Get-ChildItem $plugins -Filter '*.dll' -File | ForEach-Object FullName }) |
    Where-Object { (Test-Path $_) -and (Test-EchoRelayPatch $_) })
$inPlugins = @($relayPatches | Where-Object { $_ -like "$plugins\*" } | Sort-Object { (Get-Item $_).LastWriteTime } -Descending)
if ($inPlugins.Count -gt 1 -or ($inPlugins.Count -and $relayPatches.Count -gt $inPlugins.Count)) {
    $keep = if ($inPlugins.Count) { $inPlugins[0] } else { $null }
    $relayPatches | Where-Object { $_ -ne $keep } | ForEach-Object { Move-Aside $_ }   # extra copies
    Write-Host "EchoRelay.Patch: kept $keep"
    $relayPatches = @($keep)
}
if ($relayPatches.Count) {
    Write-Host 'EchoRelay.Patch is there.'
} else {
    New-Item -ItemType Directory $plugins -Force | Out-Null
    Copy-Item (Join-Path $here 'EchoRelay.Patch.dll') (Join-Path $plugins 'EchoRelay.Patch.dll') -Force
    Write-Host '  added plugins\EchoRelay.Patch.dll (EchoRelay''s game patch: server login, headless)'
}

if ($moved.Count) {
    @("Moved here by EchoCombat's fix_server.bat on $(Get-Date). To go back to nEVR, move each file back to",
      "the same place under $GameDir (BugSplat64.dll replaces the stock one):", '') + $moved |
        Set-Content (Join-Path $backup 'RESTORE.txt')
    Write-Host "nEVR's files are in $backup"
}

# 4. EchoCombat
Write-Host ''
& cmd /c "`"$(Join-Path $here 'install.bat')`" `"$GameDir`""
if ($LASTEXITCODE) { Write-Host 'install.bat failed: see above.' -ForegroundColor Red; exit 1 }

Write-Host ''
Write-Host 'Done. Start the game servers (EchoRelay.Host) again. To check one is right, in PowerShell:' -ForegroundColor Green
Write-Host '  Get-Process echovr | Select-Object -First 1 | ForEach-Object { $_.Modules | ForEach-Object { $_.FileName } } | Where-Object { $_ -match ''plugins|dbgcore|BugSplat'' }'
Write-Host 'It should list dbgcore.dll, EchoRelay.Patch.dll, DroneFix.dll, PowerBoost.dll, VeilNet.dll and BugSplat64.dll.'
