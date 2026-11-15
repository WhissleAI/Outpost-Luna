# Outpost Luna desktop: one command from a fresh clone to desktop\dist\Outpost Luna Setup <version>.exe (Windows x64).
# Mirrors desktop/scripts/build-mac.sh step for step. Step-by-step guide: docs/BUILD_WINDOWS.md.
#
# UNTESTED: written on a Mac; the first Windows build will validate it. Please report what breaks (docs/BUILD_WINDOWS.md).
#
#   powershell -ExecutionPolicy Bypass -File desktop\scripts\build-windows.ps1
#   powershell -ExecutionPolicy Bypass -File desktop\scripts\build-windows.ps1 -SkipMedia   # media already in place
#
# Needs: Node 22+, uv, CMake, Git, and a C compiler (Visual Studio 2022 Build Tools with "Desktop development with C++",
# or LLVM clang + Ninja). About 6 GB free disk. No accounts, keys or tokens.
param([switch]$SkipMedia)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $Root
$T0 = Get-Date

function Step($msg) { Write-Host ""; Write-Host ("==> [{0:N0}s] {1}" -f ((Get-Date) - $T0).TotalSeconds, $msg) -ForegroundColor Cyan }
function Die($msg) { Write-Host ""; Write-Host "ERROR: $msg" -ForegroundColor Red; exit 1 }
function Have($cmd) { [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }
# Run a native command; stop on a non-zero exit code (PowerShell does not, by itself).
function Run { param([Parameter(ValueFromRemainingArguments = $true)] $cmd)
  & $cmd[0] @($cmd | Select-Object -Skip 1)
  if ($LASTEXITCODE -ne 0) { Die "failed (exit $LASTEXITCODE): $($cmd -join ' ')" } }

# Caches stay inside the clone.
$env:UV_CACHE_DIR = "$Root\desktop\build\uv-cache"
$env:ELECTRON_CACHE = "$Root\desktop\build\cache\electron"
$env:ELECTRON_BUILDER_CACHE = "$Root\desktop\build\cache\electron-builder"
$env:npm_config_cache = "$Root\desktop\build\cache\npm"
$env:CSC_IDENTITY_AUTO_DISCOVERY = "false"   # unsigned until an Authenticode certificate exists (docs/DESKTOP.md)
$env:PYTHONUTF8 = "1"

Step "1/8 prerequisites"
if (-not [Environment]::Is64BitOperatingSystem) { Die "64-bit Windows is required" }
if (-not (Have git))   { Die "Git missing:   winget install --id Git.Git -e" }
if (-not (Have node))  { Die "Node missing:  winget install --id OpenJS.NodeJS.LTS -e   (then open a new terminal)" }
$nodeMajor = [int]((node -p "process.versions.node.split('.')[0]").Trim())
if ($nodeMajor -lt 22) { Die "Node $nodeMajor found, need 22+:  winget upgrade --id OpenJS.NodeJS.LTS -e" }
if (-not (Have uv))    { Die "uv missing:    winget install --id astral-sh.uv -e   (then open a new terminal)" }
if (-not (Have cmake)) { Die "CMake missing: winget install --id Kitware.CMake -e   (then open a new terminal)" }
# C compiler: Visual Studio (Build Tools) with the C++ workload, found by vswhere; else LLVM clang + Ninja.
$vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
$vs = $null
if (Test-Path $vswhere) { $vs = & $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath }
$useClang = $false
if (-not $vs) {
  if ((Have clang) -and (Have ninja)) { $useClang = $true }
  else { Die ("No C compiler. Install one of:`n  winget install --id Microsoft.VisualStudio.2022.BuildTools -e --override " +
              "`"--wait --passive --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended`"`n" +
              "  or: winget install --id LLVM.LLVM -e; winget install --id Ninja-build.Ninja -e") }
}
# Deep paths (torch) can pass 260 characters: keep the clone short (e.g. C:\src\atm) or enable long paths.
$longPaths = (Get-ItemProperty "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" -Name LongPathsEnabled -ErrorAction SilentlyContinue).LongPathsEnabled
if ($longPaths -ne 1 -and $Root.Length -gt 20) {
  Write-Host "warning: long paths are off and the clone path is $($Root.Length) characters. If the build fails with a path error," -ForegroundColor Yellow
  Write-Host "         clone to C:\src\atm, or enable long paths (docs/BUILD_WINDOWS.md)." -ForegroundColor Yellow
}
$drive = (Get-Item $Root).PSDrive
$freeGB = [math]::Floor($drive.Free / 1GB)
if ($freeGB -lt 6) { Die "only $freeGB GB free on ${drive}:; the build needs about 6 GB" }
Write-Host ("node {0}, {1}, {2}, compiler {3}, {4} GB free" -f (node -v), (uv --version), ((cmake --version) | Select-Object -First 1),
  $(if ($vs) { "MSVC ($vs)" } else { "clang + ninja" }), $freeGB)

Step "2/8 NASA media (backend\data\media: the Moon map ships; the crew clips are a first-run asset, see make asset-pack)"
if ($SkipMedia) { Write-Host "skipped (-SkipMedia)" }
else { Run uv run --no-project --with pillow==11.3.0 python backend\pipeline\fetch_media.py }
if (-not (Test-Path backend\data\media\img\moon4k.jpg)) { Die "backend\data\media is incomplete (re-run; fetch_media.py resumes)" }

Step "3/8 frontend dependencies"
Push-Location frontend; Run npm ci --no-audit --no-fund; Run node tools/fetch_vision.mjs; Pop-Location   # + camera-gesture runtime/models (sha256-pinned)

Step "4/8 embedded Python + backend/model-server deps + app code (frontend build included)"
# the recorded voice pack (backend\data\voice_pack, docs/VOICE_PACK.md) ships inside the app code: Windows kids hear it too
Run uv run --no-project python backend\tools\voice_pack_check.py --allow-empty
Run uv run --no-project python desktop\scripts\build_python.py

Step "5/8 first-run assets: nothing bundled (desktop\assets.manifest.json lists them; the app downloads them)"
$m = Get-Content desktop\assets.manifest.json -Raw | ConvertFrom-Json
$miss = @($m.assets | Where-Object { $_.required -and -not $_.url -and -not $_.fallback } | ForEach-Object { $_.id })
if ($miss.Count) { Die "assets without a download link: $($miss -join ', ') (make asset-pack asset-upload)" }
Remove-Item -Recurse -Force desktop\resources\models -ErrorAction SilentlyContinue   # an older build's bundled models

Step "6/8 native libraries (arctag.dll: Arc Tagger; arc.dll: the ear)"
Remove-Item -Recurse -Force desktop\build\arctag, desktop\build\libarc -ErrorAction SilentlyContinue
if ($useClang) {
  Run cmake -S desktop\vendor\arctag -B desktop\build\arctag -G Ninja -DCMAKE_C_COMPILER=clang -DCMAKE_BUILD_TYPE=Release
} else {
  Run cmake -S desktop\vendor\arctag -B desktop\build\arctag -A x64
}
Run cmake --build desktop\build\arctag --config Release
$dll = @("desktop\build\arctag\Release\arctag.dll", "desktop\build\arctag\arctag.dll", "desktop\build\arctag\libarctag.dll") |
  Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $dll) { Die "arctag.dll was not produced (see the CMake output above)" }
New-Item -ItemType Directory -Force desktop\resources\native | Out-Null
Copy-Item $dll desktop\resources\native\arctag.dll -Force
# libarc (the ear): same compiler; ONNX Runtime is the Python wheel's onnxruntime.dll, loaded by path at run time
if ($useClang) {
  Run cmake -S desktop\vendor\libarc -B desktop\build\libarc -G Ninja -DCMAKE_C_COMPILER=clang -DCMAKE_BUILD_TYPE=Release
} else {
  Run cmake -S desktop\vendor\libarc -B desktop\build\libarc -A x64
}
Run cmake --build desktop\build\libarc --config Release
$dll = @("desktop\build\libarc\Release\arc.dll", "desktop\build\libarc\arc.dll", "desktop\build\libarc\libarc.dll") |
  Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $dll) { Die "arc.dll was not produced (see the CMake output above)" }
Copy-Item $dll desktop\resources\native\arc.dll -Force

Step "7/8 Electron + electron-builder (NSIS installer)"
Push-Location desktop
Run npm ci --no-audit --no-fund
Remove-Item -Recurse -Force dist\win-unpacked -ErrorAction SilentlyContinue
Run npx electron-builder --win nsis --x64 --publish never
Pop-Location

Step "8/8 checks + done"
$exe = Get-ChildItem desktop\dist\*.exe | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $exe) { Die "no installer in desktop\dist" }
# Every .dll / .pyd import resolves inside the app or in Windows itself, so a PC without the VC++ Redistributable
# (or without Visual Studio, unlike this one) still starts the model server.
Run uv run --no-project python desktop\scripts\win_bundle_check.py dlls desktop\dist\win-unpacked\resources
Run uv run --no-project python desktop\scripts\win_bundle_check.py speech desktop\dist\win-unpacked\resources
Write-Host ("Installer: {0}  ({1:N0} MB, {2:N0} s)" -f $exe.FullName, ($exe.Length / 1MB), ((Get-Date) - $T0).TotalSeconds) -ForegroundColor Green
Write-Host "Unpacked app (run it without installing): $Root\desktop\dist\win-unpacked\Outpost Luna.exe"
Write-Host "Smoke test: start the app, then:  `$env:PYTHONPATH='desktop\resources\site\backend'; desktop\resources\python\python.exe desktop\scripts\smoke.py"
