# Outpost Luna release gates on Windows: the same checks as `make release-check` on the Mac (docs/RELEASING.md).
# Runs desktop\scripts\release_check.py (stdlib-only Python) against the installer that build-windows.ps1 made.
#
#   powershell -ExecutionPolicy Bypass -File desktop\scripts\release-check.ps1
#   powershell -ExecutionPolicy Bypass -File desktop\scripts\release-check.ps1 -Exe "desktop\dist\Outpost-Luna-win-x64.exe"
#   powershell -ExecutionPolicy Bypass -File desktop\scripts\release-check.ps1 -Gates smoke,golden      # a subset
#   $env:SOAK = "1"; $env:SOAK_MINUTES = "1440"; powershell ... release-check.ps1                       # + the 24 h soak
#
# The installer is never RUN: 7-Zip unpacks it into a temp folder (no registry entries, no Start menu shortcut, the
# owner's installed copy untouched). The test copy runs headless and muted (OUTPOST_HEADLESS / OUTPOST_MUTE_AUDIO), on
# its own data folder (OUTPOST_USER_DATA) and its own free ports, never 47310 / 47210. Its models are hard links to
# %APPDATA%\Outpost Luna\assets when that exists (read only), else it downloads them (510 MB).
# Needs: 7-Zip (winget install --id 7zip.7zip -e; or the 7za.exe electron-builder leaves in desktop\node_modules),
# uv + Node for the unit suites. The libarc ASan fuzzer runs on the Mac only; the protocol fuzzer runs here.
# Exit code: 0 all gates pass, 1 any gate failed. Report: desktop\dist\release-check.json.
param(
  [string]$Exe = "",
  [string]$App = "",            # an unpacked app folder instead (desktop\dist\win-unpacked)
  [string]$Gates = "",          # unit,smoke,golden,fuzz,soak (default: all but soak; soak with $env:SOAK=1)
  [string]$Skip = "",
  [string]$AssetsSeed = "",
  [switch]$Keep,
  [switch]$UpdateBaseline
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $Root
$env:PYTHONUTF8 = "1"
function Have($cmd) { [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }

# 7-Zip: PATH, the default install folder, or electron-builder's copy
if (-not $env:SEVEN_ZIP) {
  foreach ($c in @("$env:ProgramFiles\7-Zip\7z.exe", "$Root\desktop\node_modules\7zip-bin\win\x64\7za.exe")) {
    if (-not (Have 7z) -and (Test-Path $c)) { $env:SEVEN_ZIP = $c; break }
  }
}

# Python 3.9+: the py launcher, a real python on PATH (not the Microsoft Store stub), the build's embedded Python, uv.
$py = $null; $pyArgs = @()
if (Have py) { $py = "py"; $pyArgs = @("-3") }
elseif ((Have python) -and -not ((Get-Command python).Source -like "*WindowsApps*")) { $py = "python" }
elseif (Test-Path "$Root\desktop\resources\python\python.exe") { $py = "$Root\desktop\resources\python\python.exe" }
elseif (Have uv) { $py = "uv"; $pyArgs = @("run", "--no-project", "python") }
else { Write-Host "ERROR: no Python found (install uv: winget install --id astral-sh.uv -e)" -ForegroundColor Red; exit 1 }

if (-not $Exe -and -not $App) {
  $cand = Get-ChildItem "$Root\desktop\dist" -Filter "*Setup*.exe" -ErrorAction SilentlyContinue | Sort-Object LastWriteTime | Select-Object -Last 1
  if (-not $cand) { $cand = Get-ChildItem "$Root\desktop\dist" -Filter "Outpost-Luna-win-x64.exe" -ErrorAction SilentlyContinue | Select-Object -Last 1 }
  if ($cand) { $Exe = $cand.FullName }
}

$a = @("$Root\desktop\scripts\release_check.py")
if ($Exe) { $a += @("--exe", (Resolve-Path $Exe).Path) }
if ($App) { $a += @("--app", (Resolve-Path $App).Path) }
if ($Gates) { $a += @("--gates", $Gates) }
if ($Skip) { $a += @("--skip", $Skip) }
if ($AssetsSeed) { $a += @("--assets-seed", $AssetsSeed) }
if ($Keep) { $a += "--keep" }
if ($UpdateBaseline) { $a += "--update-baseline" }

& $py @pyArgs @a
exit $LASTEXITCODE
