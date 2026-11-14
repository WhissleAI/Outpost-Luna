# Build Outpost Luna for Windows

> **Untested: the first build will validate these steps.** Everything here was written on a Mac, where the same steps
> (`desktop/scripts/build-mac.sh`) build a working app. Expect a snag or two; the last section says what to send back.

You will end up with `desktop\dist\Outpost Luna Setup 0.1.0.exe`: an installer for an app that runs with **no
internet**. The app bundles its own Python, the backend, the model server, every model and the NASA audio. You need no
accounts, API keys or tokens.

## 1. What you need

- Windows 10 or 11, 64-bit (x64), 16 GB RAM recommended
- About **6 GB free** on the drive you clone to
- Internet access *for the build* (the finished app needs none)
- These tools. In PowerShell:

```powershell
winget install --id Git.Git -e
winget install --id OpenJS.NodeJS.LTS -e          # Node 22 or newer
winget install --id astral-sh.uv -e               # Python toolchain; it fetches its own Python
winget install --id Kitware.CMake -e
# a C compiler for the Arc Tagger library (about 2 GB; takes a while):
winget install --id Microsoft.VisualStudio.2022.BuildTools -e --override "--wait --passive --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"
```

Close and reopen PowerShell afterwards so the new tools are on `PATH`. Check:

```powershell
git --version; node -v; uv --version; cmake --version
```

(Instead of Visual Studio Build Tools you can use LLVM: `winget install --id LLVM.LLVM -e` and
`winget install --id Ninja-build.Ninja -e`. The script picks whichever it finds.)

**Long paths.** Some files inside the bundled Python (torch) have very long paths. Either clone to a short folder such as
`C:\src\atm` (recommended), or enable long paths once, in an **Administrator** PowerShell:

```powershell
New-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" -Name LongPathsEnabled -Value 1 -PropertyType DWORD -Force
git config --global core.longpaths true
```

## 2. Get the code

The repo is private: you need read access to `WhissleAI/ask-the-moon` on GitHub (ask Karan).

```powershell
mkdir C:\src -Force; cd C:\src
git clone -b feat/desktop https://github.com/WhissleAI/ask-the-moon.git atm
cd atm
```

## 3. Build (one command)

```powershell
powershell -ExecutionPolicy Bypass -File desktop\scripts\build-windows.ps1
```

It prints `==> [time] step n/8` as it goes. The steps are:

| step | what | time (rough) |
|---|---|---|
| 1 | check the tools above, the C compiler, free disk, long paths | seconds |
| 2 | download the NASA crew audio (74 clips) and the Moon map, ~0.5 GB, from nasa.gov | 2–10 min |
| 3 | `npm ci` in `frontend\` | 1 min |
| 4 | embedded Python 3.11 + backend and model-server packages (torch CPU, onnxruntime, …) + app code; builds the frontend | 3–5 min |
| 5 | models: downloads the public model package (119 MB), checks its sha256 and every file | 1 min |
| 6 | builds `arctag.dll` with CMake | 1 min |
| 7 | Electron + electron-builder → NSIS installer | 5–10 min |
| 8 | prints the installer path | |

If the media download stops part-way (NASA's server can be slow), just run the command again: finished files are kept.
To skip that step when `backend\data\media` is already complete: add `-SkipMedia`.

## 4. Where the output goes

| | |
|---|---|
| installer | `desktop\dist\Outpost Luna Setup 0.1.0.exe` (about 1 GB) |
| unpacked app (run without installing) | `desktop\dist\win-unpacked\Outpost Luna.exe` |
| installed app | `%LOCALAPPDATA%\Programs\Outpost Luna\` (per-user install; you can choose the folder) |
| app data and logs | `%APPDATA%\Outpost Luna\` (`logs\main.log`, `logs\models.log`, `logs\backend.log`) |

The installer is **unsigned**, so SmartScreen will say "Windows protected your PC": click **More info → Run anyway**.

## 5. Smoke test, offline

1. Install and start **Outpost Luna**. You should see a splash, "Warming up the models…", then the Flight School screen
   within about 30 seconds. Note how long it takes.
2. **Block the network for the app.** Easiest: turn Wi-Fi off / unplug the cable. Or, more precisely, add Windows
   Firewall rules in an **Administrator** PowerShell (they block the app and its Python, not your other programs):

   ```powershell
   $app = "$env:LOCALAPPDATA\Programs\Outpost Luna"
   New-NetFirewallRule -DisplayName "Outpost Luna offline test (app)"    -Direction Outbound -Action Block -Program "$app\Outpost Luna.exe"
   New-NetFirewallRule -DisplayName "Outpost Luna offline test (python)" -Direction Outbound -Action Block -Program "$app\resources\python\python.exe"
   ```

   Loopback traffic (the app talking to its own servers on 127.0.0.1) is not affected by these rules. Remove them later:
   `Remove-NetFirewallRule -DisplayName "Outpost Luna offline test*"`.
3. Quit and restart the app with the network blocked. It must start the same way.
4. Run the automated smoke test from the clone (it talks to the running app on 127.0.0.1):

   ```powershell
   cd C:\src\atm
   $env:PYTHONPATH = "desktop\resources\site\backend"
   desktop\resources\python\python.exe desktop\scripts\smoke.py
   ```

   Expected: a list of `PASS` lines ending in `ALL PASS` (the local speech ear hears "show me the giant bull's eye",
   answers, speaks with Steer TTS, grades a Flight School step and runs a mission shift). If the app chose other ports
   (see `%APPDATA%\Outpost Luna\ports.json`), add `--base http://127.0.0.1:<backend port>`.
5. By hand: hold **Space** (or the talk button) and ask "where did Apollo 11 land?". Windows will ask for microphone
   access the first time. You should hear an answer. Open a Flight School lesson, then the **Mission** tab.
6. Quit the app (close the window). In Task Manager, no `python.exe` from Outpost Luna should remain.

## 6. Common errors

| you see | do this |
|---|---|
| `uv` / `node` / `cmake` "is not recognized" | open a new PowerShell after `winget install` |
| `No C compiler` | install VS 2022 Build Tools with the C++ workload (command in §1), or LLVM + Ninja |
| `running scripts is disabled on this system` | use the exact command in §3 (`-ExecutionPolicy Bypass`) |
| path / "file name too long" / `FileNotFoundError` deep inside `torch` | clone to `C:\src\atm` or enable long paths (§1) |
| media step fails with HTTP 403 / timeouts | re-run; NASA's CDN is rate-limited at times |
| `model package sha256 mismatch` | re-run (it re-downloads); if it persists the package link changed: report it |
| `models differ from models.lock.json` | delete `desktop\resources\models` and `desktop\build\outpost-luna-models-v1.tar`, re-run |
| CMake: `arctag.dll was not produced` | send the CMake output; try the LLVM route |
| splash says the backend or model server "keeps stopping" | send `%APPDATA%\Outpost Luna\logs\*.log` |
| antivirus quarantines `python.exe` or a `.pyd` | allow the `desktop\` folder (or the install folder) and re-run |

## 7. What to report back

Please send (Slack or the PR):

1. Pass / fail of `build-windows.ps1`, and the last 40 lines of output if it failed.
2. Windows version (`winver`), CPU, RAM, and which compiler was used (MSVC or clang).
3. Total build time (printed at the end) and the installer size.
4. Cold start time (launch to Flight School screen), the first time and the second time.
5. RAM in Task Manager after one voice question (Outpost Luna + its `python.exe` processes).
6. The `smoke.py` output.
7. Anything in `%APPDATA%\Outpost Luna\logs\main.log` that says `blocked`, `FAIL` or `exited`.
8. Whether the microphone prompt appeared and voice worked, and whether quitting left any `python.exe` behind.
