# Build Outpost Luna for Windows

> **No Windows machine has run this yet.** The script has been parsed and dry-run in PowerShell 7 (on a Mac, with
> stand-in tools), and the same app has been cross-built on a Mac as an unpacked Windows app and checked file by file
> against the Mac app (§8). Only a real PC can show that it starts. Expect a snag or two; §7 says what to send back.

You will end up with `desktop\dist\Outpost Luna Setup 0.1.0.exe`: an installer for an app that runs with **no
internet**. The app bundles its own Python, the backend, the model server, every model, the NASA audio, the camera
gesture models and the Visual C++ runtime. You need no accounts, API keys or tokens.

## 1. What you need

- Windows 10 or 11, 64-bit (x64), 16 GB RAM recommended, a CPU from about 2015 or later
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
`winget install --id Ninja-build.Ninja -e`. The script picks whichever it finds. The LLVM route is the less certain one:
see §6 if it fails to link.)

**Long paths.** Some files inside the bundled Python (torch) have very long paths. Either clone to a short folder such as
`C:\src\atm` (recommended), or enable long paths once, in an **Administrator** PowerShell:

```powershell
New-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" -Name LongPathsEnabled -Value 1 -PropertyType DWORD -Force
git config --global core.longpaths true
```

The *installed* app is fine without long paths: its deepest file is 138 characters below `resources\`, so the default
install folder (`C:\Users\<you>\AppData\Local\Programs\Outpost Luna\resources\`, ~75 characters) stays well under 260.
Only an install folder longer than about 120 characters would need long paths.

## 2. Get the code

The repo is private: you need read access to `WhissleAI/ask-the-moon` on GitHub (ask Karan).

```powershell
mkdir C:\src -Force; cd C:\src
git clone https://github.com/WhissleAI/ask-the-moon.git atm
cd atm
```

(`main` is the release line. To build a branch under test, add `-b <branch>`, e.g. `-b fix/windows-parity`.)

## 3. Build (one command)

```powershell
powershell -ExecutionPolicy Bypass -File desktop\scripts\build-windows.ps1
```

It prints `==> [time] step n/8` as it goes. The steps are the same as the Mac build's (`build-mac.sh`):

| step | what | time (rough) |
|---|---|---|
| 1 | check the tools above, the C compiler, free disk, long paths | seconds |
| 2 | download the NASA crew audio (74 clips) and the Moon map, ~0.5 GB, from nasa.gov | 2–10 min |
| 3 | `npm ci` in `frontend\`, then the camera-gesture runtime and models (sha256-pinned) | 1 min |
| 4 | embedded Python 3.11 + backend and model-server packages (torch CPU, onnxruntime, …) + the Visual C++ runtime + app code; builds the frontend; checks every DLL import resolves | 3–5 min |
| 5 | models: downloads the public model package (119 MB), checks its sha256 and every file | 1 min |
| 6 | builds `arctag.dll` with CMake | 1 min |
| 7 | Electron + electron-builder → NSIS installer | 5–10 min |
| 8 | checks the unpacked app's DLL imports again, prints the installer path | seconds |

If the media download stops part-way (NASA's server can be slow), just run the command again: finished files are kept.
To skip that step when `backend\data\media` is already complete: add `-SkipMedia`.

## 4. Where the output goes

| | |
|---|---|
| installer | `desktop\dist\Outpost Luna Setup 0.1.0.exe` (about 1 GB) |
| unpacked app (run without installing) | `desktop\dist\win-unpacked\Outpost Luna.exe` |
| installed app | `%LOCALAPPDATA%\Programs\Outpost Luna\` (per-user install; you can choose the folder) |
| app data and logs | `%APPDATA%\Outpost Luna\` (`logs\main.log`, `logs\models.log`, `logs\backend.log`) |
| voice-guide turn log (only if Settings → "Help improve the voice guide" is on) | `%APPDATA%\Outpost Luna\cache\turnlog\turns.jsonl` |

## 5. First run and what to test

### 5.1 SmartScreen (first run only)

The installer is **unsigned** (no Authenticode certificate yet; docs/DESKTOP.md). The first time, Windows Defender
SmartScreen shows **"Windows protected your PC"**: click **More info → Run anyway**. The same can happen once more when
the installed app first starts. Nothing else should prompt:

- **No firewall prompt.** Both servers listen on `127.0.0.1` only, and Windows Defender Firewall only asks about programs
  that listen on a network interface. If a "Windows Defender Firewall has blocked some features" dialog appears for
  `python.exe` or Outpost Luna, that is a bug: report it (and it is safe to click Cancel).
- **No console windows.** The two `python.exe` children start hidden. A black console window is a bug.
- **Antivirus** may scan the ~20,000 files on first start (slow first launch). If it quarantines `python.exe` or a
  `.pyd`, allow the install folder and reinstall.

### 5.2 Camera and microphone privacy switches

Windows does not ask per app, the way macOS does. Two system switches decide, for every desktop app:

- **Settings → Privacy & security → Camera**: **"Camera access" on** and **"Let desktop apps access your camera" on**.
- **Settings → Privacy & security → Microphone**: **"Microphone access" on** and **"Let desktop apps access your
  microphone" on**.

If the camera switch is off, turning on gestures shows "Camera blocked. Allow it in your computer's privacy settings."
(or, with some drivers, "The camera didn't start. Close other apps using it, or check your privacy settings."). If the
microphone switch is off, the voice bar says "Mic is blocked. Type instead." Either way `main.log` records what Windows
reported, e.g. `windows privacy camera: denied`. Turn the switch on, then turn gestures (or the mic) off and on again;
no restart needed. A camera already in use by another app (Teams, Zoom) gives the second message too.

### 5.3 Smoke test, offline

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
4. Run the automated smoke test (it talks to the running app on 127.0.0.1). From your clone, with the installed app's
   own Python:

   ```powershell
   cd C:\src\atm
   $app = "$env:LOCALAPPDATA\Programs\Outpost Luna\resources"
   $env:PYTHONPATH = "$app\site\backend"; $env:PYTHONUTF8 = "1"
   & "$app\python\python.exe" desktop\scripts\smoke.py
   ```

   (If you built it yourself, `desktop\resources\python\python.exe` with `PYTHONPATH=desktop\resources\site\backend`
   works too.) Expected: a list of `PASS` lines ending in `ALL PASS`: the local speech ear hears "show me the giant
   bull's eye", answers, speaks with Steer TTS, grades a Flight School step, runs a mission shift, and finds every
   gesture model both served and on disk. If the app chose other ports (see `%APPDATA%\Outpost Luna\ports.json`), add
   `--base http://127.0.0.1:<backend port>`.
5. **Voice.** Hold **Space** (or the talk button) and ask "where did Apollo 11 land?". You should hear an answer in the
   default voice. Then **Settings → Voice**: play two or three voice previews (each is a short offline clip), pick one,
   and ask again: the answer uses the new voice. Volume and speed changes apply to the next line.
6. **Keyboard** (docs/KEYBOARD.md). With the mouse untouched: arrows move the focus ring, Enter selects, Esc goes back,
   `?` opens the key help, **Alt+→ / Alt+←** next / previous, **Alt+Y / Alt+N** yes / no, **Alt+.** stops speech.
   Pressing **Alt** alone must do nothing (there is no menu bar to open). The shell keys: **F5**, **Ctrl+R** and
   **Ctrl+Shift+I** must do nothing (no reload, no dev tools); **Ctrl+= / Ctrl+- / Ctrl+0** zoom in / out / reset;
   **F11** full screen; **Alt+F4** quits.
7. **Cockpit.** Open a Flight School lesson, then the **Mission** tab: the 3D cabin must build within a few seconds and
   turn smoothly (note roughly how smooth: the GPU is used through Direct3D here, Metal on the Mac). Open a panel
   (power, comm, …), give an order ("give shields more"), and go back to the seat.
8. **Controller** (optional; docs/KEYBOARD.md §Controller). Plug in or pair an Xbox or PlayStation controller and press
   any button: a "Controller connected" toast appears. D-pad / left stick move, A / Cross selects, B / Circle goes back,
   X / Square is the mic, Y / Triangle help, LB / RB previous / next, the right stick turns the Moon (or looks around
   in the cabin). Xbox pads work over USB or Bluetooth; a PlayStation pad works over USB, and over Bluetooth on most PCs.
9. **Camera gestures** (docs/GESTURES.md). Check the privacy switches in §5.2 first. Open **Access** (settings) →
   **Camera & gestures** → turn on **Use the camera for gestures**. The camera stays off until you do this. With it on:
   a red "Camera on" chip appears (its **Turn off** button stops the camera at once; the webcam light must go off), and
   the self-view shows your hand's skeleton. Hold an open hand still for half a second: "Stop". Thumbs up: "Yes".
   Swipe an open hand sideways: next / back. In the cabin, lean in towards the screen: the aimed panel opens. The models
   are inside the app (`resources\app\frontend\vision\`), so this works with Wi-Fi off.
10. Quit the app (close the window). In Task Manager, no `python.exe` from Outpost Luna should remain. Start it again:
    it must reach Flight School the same way (and `main.log` may say `reaped stale children` only after a crash).

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
| CMake: `arctag.dll was not produced` | send the CMake output; try the other compiler route |
| LLVM route: `unresolved external symbol __cpu_model` / `__cpu_indicator_init` | use the Visual Studio route (it builds the portable kernels), or the cross-built `arctag.dll` (§8) |
| `DLL imports that resolve nowhere on a clean Windows` (step 4 or 8) | send the list: a package started needing a DLL the app does not ship |
| splash says the backend or model server "keeps stopping" | send `%APPDATA%\Outpost Luna\logs\*.log` |
| `models.log`: `DLL load failed` / `WinError 126` on `import torch` | send `models.log`; as a check, installing the "Microsoft Visual C++ Redistributable (x64)" should make it go away (it must not be needed: the app ships those DLLs) |
| `models.log`: `this x86_64 CPU does not report AVX2 + FMA` | a CPU older than ~2013 with a mingw / clang `arctag.dll`; the MSVC build does not need AVX2. Report the CPU |
| antivirus quarantines `python.exe` or a `.pyd` | allow the `desktop\` folder (or the install folder) and re-run |

## 7. What to report back

Short checklist (Slack or the PR). Copy it, fill in each line:

```
[ ] build-windows.ps1: pass / fail (if fail: last 40 lines)          build time: ___ min   installer: ___ MB
[ ] Windows version (winver) / CPU / RAM / compiler (MSVC or clang):
[ ] SmartScreen: "Run anyway" worked?  Any firewall dialog? (should be none)  Any console window? (should be none)
[ ] cold start to Flight School: 1st ___ s, 2nd ___ s, with network blocked ___ s
[ ] smoke.py: ALL PASS?  (paste the output if not)
[ ] voice: answer heard?  voice previews play?  changing the voice changes the answer?
[ ] keyboard: arrows/Enter/Esc, Alt shortcuts, F5 and Ctrl+R do nothing, Ctrl+= zooms, F11 full screen?
[ ] cockpit: cabin builds and turns smoothly?  panel opens, order works?
[ ] controller (if you have one): toast shown, A/B/D-pad work?
[ ] camera: privacy switches on?  "Camera on" + skeleton seen?  open hand = Stop, thumbs up = Yes?  "On. N frames a second": N = ___
            CPU % with camera on ___ / off ___   "Turn off" turns the webcam light off?
[ ] quit: no python.exe left in Task Manager?
[ ] RAM after one voice question (Outpost Luna + its python.exe processes): ___ MB
[ ] main.log lines with "blocked", "FAIL", "exited", "windows privacy":
```

## 8. Alternative: cross-build the installer on a Mac

The native build above stays the primary path: it is the one that runs on the machine it targets. A Mac can produce
the same installer, which is how the Windows bundle was first checked without a PC:

```bash
brew install mingw-w64 sevenzip cmake node@22 uv     # mingw-w64 (or zig) compiles arctag.dll; 7-Zip unpacks the installer
bash desktop/scripts/cross-build-windows.sh                  # -> desktop/dist/Outpost Luna Setup 0.1.0.exe
SKIP_MEDIA=1 bash desktop/scripts/cross-build-windows.sh     # media already in backend/data/media
MAC_APP="/Applications/Outpost Luna.app" bash desktop/scripts/cross-build-windows.sh   # + a parity report vs the Mac app
```

Same 8 steps, same inputs. What differs:

| | native (build-windows.ps1) | cross (cross-build-windows.sh) |
|---|---|---|
| Python | `uv python install 3.11` (python-build-standalone) | the same release's `x86_64-pc-windows-msvc` build, downloaded and checked against its `SHA256SUMS` (`build_python.py --target win-x64`) |
| packages | `uv pip install` for this PC | `uv pip install --python-platform x86_64-pc-windows-msvc`: the same locked versions, win_amd64 wheels; the build fails if any macOS binary slips in |
| bytecode | compiled by the bundled `python.exe` | compiled by the Mac's CPython 3.11 (a `.pyc` depends on the Python version, not the OS) |
| `arctag.dll` | MSVC (portable scalar kernels) or clang | mingw-w64 gcc: AVX2 + FMA kernels (the CPU is checked at load); needs only Windows' own DLLs |
| `.exe` resources | electron-builder edits the icon / version info | without Wine, not edited (`signAndEditExecutable: false`): the default Electron icon and file details. Nothing else changes |

Step 8 then checks the result without running it (`desktop/scripts/win_bundle_check.py`):

- `dlls`: every `.dll` / `.pyd` import (the import and delay-load tables, read from the PE files) resolves in the
  bundle or in Windows itself; this is the check that found the missing `MSVCP140.dll` (now shipped).
- the installer is unpacked with 7-Zip and its payload compared file by file with `dist/win-unpacked`;
- `compare` (with `MAC_APP`): the Mac `.app`'s `Contents/Resources` against the Windows `resources`: app code, models
  (sha256 vs `models.lock.json`), media, vision assets, voices and previews, Director weights, the native library,
  and both site folders' packages.

`desktop/resources/` holds one platform's build at a time: after a cross-build, `build-mac.sh` rebuilds it for the Mac
(and the other way round). The script deletes its intermediates (the unpacked app, the Python tree's caches) and keeps
only the installer. A cross-built installer must still go through §5 on a real PC before it ships.

**Status (2026-11-14).** Steps 1–6 and the unpacked app (`dist/win-unpacked`, 2.1 GB, 24,273 files) were built and
checked on a Mac: every DLL import resolves, and `compare` against the Mac app reports parity. The NSIS step did
not finish there: electron-builder's 7-Zip pass (`-mx=9` over 2 GB) ran for 90 minutes without finishing on a
machine at load average ~50. With `compression: store` the payload was 2.08 GB, which is past NSIS's 2 GB installer
limit, so makensis timed out after 4 minutes. On an idle Mac the default compression should finish in about 20
minutes; that has not been measured yet.
