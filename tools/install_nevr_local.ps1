<#
Installs EchoCombat (nEVR pack) for the current Windows user, without the launcher. Nothing else is needed:
EchoCombatContent.dll (in the pack) serves EchoCombat's game data; NvrContentOverlay isn't used.

The latest nEVR reads everything from its root, %LOCALAPPDATA%\nevr\echovr (ADR 0012), never from the game folder:
  plugins\                  EchoCombatContent.dll, DroneFix.dll, PowerBoost.dll (+ .ini), VeilNet.dll
  content\echocombat\       the pack's game data and scripts (served by EchoCombatContent)
  config.yaml               the plugins: list (a DLL not listed there is not loaded), plus
                            x-local-plugins: true so the launcher keeps loading unverified plugins

config.yaml is merged: other sections and other plugins stay; our entries are replaced. A backup is kept.
EchoCombatContent goes first and loads early (before the game reads its data). An NvrContentOverlay entry an
older install wrote is taken out (and its DLL, if this installer put it there).

Usage (PowerShell), with the pack zip next to this script:
  powershell -ExecutionPolicy Bypass -File install_nevr_local.ps1
  ... -Pack EchoCombat-2.0.6.zip -Root <nevr root>
  ... -Uninstall      (removes our plugins, content and config entries again)

Note: the Echo VR launcher rewrites config.yaml at every start from its Mods page. Start the game directly
(nEVR), or install EchoCombat in the launcher's Mods page instead.
#>
param(
    [string]$Pack = "",
    [string]$Root = (Join-Path $env:LOCALAPPDATA "nevr\echovr"),
    [switch]$Uninstall
)
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Content = "echocombat"
$ContentDll = "EchoCombatContent.dll"
$PackPlugins = @("DroneFix.dll", "PowerBoost.dll", "VeilNet.dll")
$OverlayDll = "NvrContentOverlay.dll"   # older installs used it: its entry goes
$Ours = @($ContentDll, $OverlayDll) + $PackPlugins

function Fail($m) { Write-Host "ERROR: $m" -ForegroundColor Red; exit 1 }

if (-not (Test-Path (Join-Path $Root "nevr-runtime.dll"))) {
    Fail "no nEVR at $Root (nevr-runtime.dll missing). Start the game once with the latest nEVR, or pass -Root."
}
if (Get-Process echovr, echovr_openxr -ErrorAction SilentlyContinue) { Fail "Echo VR is running: close it first." }

$plugins = Join-Path $Root "plugins"
$contentDir = Join-Path $Root "content\$Content"
$config = Join-Path $Root "config.yaml"
New-Item -ItemType Directory -Force $plugins | Out-Null

# --- config.yaml: keep everything except our plugin entries and the local-plugins line ---
$lines = @()
if (Test-Path $config) {
    Copy-Item $config "$config.bak-$(Get-Date -Format yyyyMMdd-HHmmss)"
    $lines = Get-Content $config
}
$keep = New-Object System.Collections.Generic.List[string]
$entries = New-Object System.Collections.Generic.List[object]   # other plugins' entries, as line lists
$inPlugins = $false; $inCombat = $false; $cur = $null
foreach ($l in $lines) {
    if ($l -match '^\s*x-local-plugins\s*:') { continue }
    if ($l -match '^combat\s*:') { $inCombat = $true; continue }        # ours, written again below
    if ($inCombat -and $l -match '^\S') { $inCombat = $false }
    if ($inCombat) { continue }
    if ($l -match '^plugins\s*:') { $inPlugins = $true; continue }
    if ($inPlugins -and $l -match '^\S') { $inPlugins = $false }   # next top-level key
    if (-not $inPlugins) { $keep.Add($l); continue }
    if ($l -match '^\s*-\s') { $cur = New-Object System.Collections.Generic.List[string]; $entries.Add($cur) }
    if ($null -ne $cur) { $cur.Add($l) }
}
function EntryFile($e) {
    $name = $null; $file = $null
    foreach ($l in $e) {
        if ($l -match '^\s*-?\s*name\s*:\s*"?([^"#]+?)"?\s*$') { $name = $Matches[1] }
        if ($l -match '^\s*-?\s*file\s*:\s*"?([^"#]+?)"?\s*$') { $file = $Matches[1] }
    }
    if ($file) { return $file } elseif ($name) { return "$name.dll" } else { return "" }
}
$others = $entries | Where-Object { $Ours -notcontains (EntryFile $_) }

$out = New-Object System.Collections.Generic.List[string]
$out.Add("x-local-plugins: true")
foreach ($l in $keep) { $out.Add($l) }
while ($out.Count -gt 1 -and $out[$out.Count - 1].Trim() -eq "") { $out.RemoveAt($out.Count - 1) }
if (-not $Uninstall) {
    # nEVR 6.17+ has its own copy of EchoCombat built in ([NEVR.COMBAT]). Running with ours, the two
    # fight over the same tac mods; alone, its copy is older than the pack and hides tac mods on our
    # servers. So its features go off here and the pack's plugins run them. (Uninstall drops this
    # block: nEVR's defaults come back.) clean_exit (a shutdown crash fix) stays as nEVR has it.
    $out.Add("combat:")
    foreach ($k in "drone", "overcharge", "medigun", "veil", "match_control", "balance") { $out.Add("  ${k}: false") }
}
$out.Add("plugins:")
if (-not $Uninstall) {
    $out.Add("  - name: `"EchoCombatContent`"")
    $out.Add("    file: `"$ContentDll`"")
    $out.Add("    enabled: true")
    $out.Add("    early: true")
}
foreach ($e in $others) { foreach ($l in $e) { $out.Add($l) } }
if (-not $Uninstall) {
    foreach ($p in $PackPlugins) {
        $out.Add("  - name: `"$([IO.Path]::GetFileNameWithoutExtension($p))`"")
        $out.Add("    file: `"$p`"")
        $out.Add("    enabled: true")
    }
}

if ($Uninstall) {
    foreach ($f in @($Ours + "PowerBoost.ini")) { Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $plugins $f) }
    if (Test-Path $contentDir) { Remove-Item -Recurse -Force $contentDir }
    [IO.File]::WriteAllLines($config, $out, (New-Object Text.UTF8Encoding $false))
    Write-Host "EchoCombat removed from $Root (local plugins stay on)." -ForegroundColor Green
    exit 0
}

# --- the files ---
if (-not $Pack) {
    $Pack = Get-ChildItem $here -Filter "EchoCombat-*.zip" | Sort-Object LastWriteTime -Descending |
        Select-Object -First 1 -ExpandProperty FullName
}
if (-not $Pack -or -not (Test-Path $Pack)) { Fail "no EchoCombat pack zip (put EchoCombat-<version>.zip next to this script, or pass -Pack)." }

$tmp = Join-Path ([IO.Path]::GetTempPath()) ("echocombat-" + [guid]::NewGuid())
Add-Type -AssemblyName System.IO.Compression.FileSystem
[IO.Compression.ZipFile]::ExtractToDirectory((Resolve-Path $Pack), $tmp)
try {
    foreach ($p in @($ContentDll) + $PackPlugins) {
        if (-not (Test-Path (Join-Path $tmp "plugins\$p"))) { Fail "$Pack has no plugins\${p}: not an nEVR EchoCombat pack." }
    }
    if (-not (Test-Path (Join-Path $tmp "content\$Content\content.json"))) { Fail "$Pack has no content\$Content\content.json." }

    Copy-Item -Force (Join-Path $tmp "plugins\*") $plugins
    $oldOverlay = Join-Path $plugins $OverlayDll
    if (Test-Path $oldOverlay) { Move-Item -Force $oldOverlay "$oldOverlay.unused" }   # not loaded any more
    if (Test-Path $contentDir) { Remove-Item -Recurse -Force $contentDir }   # no stale files from an older pack
    New-Item -ItemType Directory -Force (Split-Path $contentDir) | Out-Null
    Copy-Item -Recurse (Join-Path $tmp "content\$Content") $contentDir
    $ver = (Select-String -Path (Join-Path $tmp "README.txt") -Pattern '^EchoCombat (\S+)' -ErrorAction SilentlyContinue |
        Select-Object -First 1).Matches.Groups[1].Value
} finally { Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue }

[IO.File]::WriteAllLines($config, $out, (New-Object Text.UTF8Encoding $false))
Write-Host "EchoCombat $ver installed in $Root" -ForegroundColor Green
Write-Host "  plugins: $((@($ContentDll) + $PackPlugins) -join ', ')"
Write-Host "  content: $contentDir"
Write-Host "  config.yaml: local plugins on, EchoCombatContent early (no NvrContentOverlay), nEVR's built-in combat off"
Write-Host "Start Echo VR with nEVR. (A launcher start rewrites config.yaml from its Mods page.)"
