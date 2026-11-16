# Build and test Outpost Luna on Windows

You build the Windows app (version 0.3.3) from `main` with one command. Then you run it and go through the checklist in
§8. You need no accounts, keys or tokens, and nothing from us.

> **Status.** The first tester build on a real Windows PC (2026-11-15) found three things, all fixed on `main`:
> CMake picked a Visual Studio without clang-cl when two are installed (the script now pins the one with clang-cl),
> the ear library needed `/arch:AVX2` with clang-cl (added; the app needs an AVX2 CPU, Intel 2013+ / AMD 2015+), and the
> guide voice alternated between the recorded Mac voice and the Windows voice (now one voice: the Windows voice live).
> If anything else breaks, send the items in §9.

**Already built an earlier version?** Update and rebuild in the same folder (steps 1 to 5 are cached):

```powershell
cd C:\src\atm
git checkout -- .
git checkout main
git pull
Remove-Item -Recurse -Force desktop\build\arctag, desktop\build\libarc -ErrorAction SilentlyContinue
powershell -ExecutionPolicy Bypass -File desktop\scripts\build-windows.ps1
```

**The short version**

1. Install the tools (§1). Then open a **new** PowerShell window.
2. Clone the repo to `C:\src\atm` (§2).
3. Run `powershell -ExecutionPolicy Bypass -File desktop\scripts\build-windows.ps1` (§3). It takes about 15 to 30 minutes.
4. Run `desktop\dist\win-unpacked\Outpost Luna.exe`, or install `desktop\dist\Outpost Luna Setup 0.3.3.exe` (§5).
5. On first launch the app downloads its models (510 MB, required), or you click **Import offline pack…** (§6).
6. Go through the tester checklist (§8) and send it back with the logs from `%APPDATA%\Outpost Luna\logs` (§9).
7. If it works, attach `desktop\dist\Outpost-Luna-win-x64.exe` to the release: `gh release upload <tag> desktop\dist\Outpost-Luna-win-x64.exe` (§9).

---

## 1. Prerequisites

You need:

- Windows 10 or Windows 11, 64-bit (x64). ARM PCs are not supported.
- 16 GB of RAM recommended.
- **8 GB free** on the drive you clone to. The build uses about 4 GB: the package cache (about 1 GB), the NASA media
  download (0.7 GB), the staged app (0.4 GB), the unpacked app (0.8 GB), the installer and node_modules. The app's first
  launch then downloads up to 0.9 GB into `%APPDATA%`.
- Internet access while you build, and for the first launch (or the offline pack, §6). After that the app needs none.
- A webcam and a microphone, to test gestures and voice.

In PowerShell (a normal window, not Administrator):

```powershell
winget install --id Git.Git -e                      # Git 2.40 or newer
winget install --id OpenJS.NodeJS.LTS -e            # Node 22 or newer (the LTS is fine)
winget install --id astral-sh.uv -e                 # uv 0.9 or newer; it fetches its own Python 3.11
winget install --id Kitware.CMake -e                # CMake 3.21 or newer (libarc's configure reads a JSON lock)
# C compilers (about 3 GB, 10 to 20 minutes): MSVC for the Arc Tagger library, and clang-cl for libarc (the ear)
winget install --id Microsoft.VisualStudio.2022.BuildTools -e --override "--wait --passive --add Microsoft.VisualStudio.Workload.VCTools --add Microsoft.VisualStudio.Component.VC.Llvm.Clang --add Microsoft.VisualStudio.Component.VC.Llvm.ClangToolset --includeRecommended"
```

**Close PowerShell and open a new window**, so the new tools are on `PATH`. Then check them:

```powershell
git --version; node -v; uv --version; cmake --version
```

Why two compilers: libarc, the speech recognizer ("the ear"), needs clang (C11 atomics and GCC built-ins). Plain
`cl.exe` can't compile it. The command above adds Visual Studio's own clang-cl, so you need nothing else. If you
already have Build Tools without clang, run the same command again: it adds the missing parts. LLVM works too:
`winget install --id LLVM.LLVM -e; winget install --id Ninja-build.Ninja -e`. The build script finds LLVM in
`C:\Program Files\LLVM\bin` even when it is not on `PATH`, and it checks for clang in step 1, before the long steps.

You do **not** need to install Python, ffmpeg, 7-Zip, ONNX Runtime or the Visual C++ Redistributable. The build
fetches pinned copies, and the app ships its own.

**Long paths.** Some files deep inside the Python packages have long paths. Clone to a short folder such as `C:\src\atm`
(see §2). Or turn on long paths once, in an **Administrator** PowerShell:

```powershell
New-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" -Name LongPathsEnabled -Value 1 -PropertyType DWORD -Force
git config --global core.longpaths true
```

## 2. Get the code

The repo is public, so no GitHub account is needed. (It was renamed from `ask-the-moon`; old URLs redirect.)

```powershell
mkdir C:\src -Force; cd C:\src
git clone https://github.com/WhissleAI/Outpost-Luna.git atm
cd atm
```

To update a clone you already have:

```powershell
cd C:\src\atm; git checkout main; git pull
```

## 3. Build (one command)

```powershell
powershell -ExecutionPolicy Bypass -File desktop\scripts\build-windows.ps1
```

While it works, it prints `==> [time] step n/8`. The steps match the Mac build (`build-mac.sh`):

| step | what it does | time |
|---|---|---|
| 1 | Checks the tools, both compilers (MSVC for arctag, clang for libarc), free disk and long paths | seconds |
| 2 | Downloads the NASA media from nasa.gov (about 0.5 GB). Only the Moon map goes into the installer | 3 to 10 min |
| 3 | Runs `npm ci` for the frontend, then fetches the camera-gesture runtime and models (sha256-pinned) | 1 to 2 min |
| 4 | Sets up the embedded Python 3.11 and installs the backend and model-server packages: ONNX Runtime, the WinRT and SAPI speech packages, the Steer TTS runtime, and the Visual C++ runtime DLLs. It then builds the frontend and stages the app code, and checks that every DLL import resolves | 3 to 6 min |
| 5 | Checks `desktop\assets.manifest.json`. No models are bundled: the app downloads them on first launch (§6) | seconds |
| 6 | Builds `arctag.dll` (MSVC) and `arc.dll` (libarc, the ear: clang-cl or clang) with CMake. Configuring libarc downloads the pinned ONNX Runtime (`onnxruntime-win-x64-1.32.0.zip`, 97 MB, once; cached in `desktop\build\cache\onnxruntime`), checks its sha256, and the script copies `onnxruntime.dll` to `resources\native\onnxruntime\`. Then it checks the Python bindings match `arc.h` / `arctag.h` and that `arc.dll` reports the header's ABI | 1 to 3 min |
| 7 | Runs Electron and electron-builder. This makes `dist\win-unpacked`, then compresses it into the NSIS installer | 3 to 10 min |
| 8 | Checks the unpacked app: `win_bundle_check.py dlls`, `speech` and `runtime` (§12). Then it prints the installer path | under 1 min |

The total is about **15 to 30 minutes** on a recent PC. A re-run is faster, because downloads and caches are kept.

If the NASA download stops part-way, run the same command again. It keeps the files it already has. When
`backend\data\media` is complete, `-SkipMedia` skips that download.

## 4. Where the output goes

| what | where |
|---|---|
| Installer | `desktop\dist\Outpost Luna Setup 0.3.3.exe` (about 190 MB) |
| Installer, release name (a copy) | `desktop\dist\Outpost-Luna-win-x64.exe`: the file to attach to a GitHub release (§9) |
| Unpacked app (runs without installing) | `desktop\dist\win-unpacked\Outpost Luna.exe` (783 MB, about 7,900 files) |
| Installed app | `%LOCALAPPDATA%\Programs\Outpost Luna\` (a per-user install; you can choose another folder) |
| Downloaded models and media | `%APPDATA%\Outpost Luna\assets\` (`ear`, `tagger`, `embedder`, `voice`, and later `crew`, `videos`, `steer`) |
| App data, settings and caches | `%APPDATA%\Outpost Luna\` |
| **Logs** | `%APPDATA%\Outpost Luna\logs\` (`main.log`, `backend.log`, `models.log`) |
| Ports the app chose | `%APPDATA%\Outpost Luna\ports.json` (backend on 47310, models on 47210 unless taken) |

To open the logs folder, run `explorer "$env:APPDATA\Outpost Luna\logs"`.

## 5. Run it

**Without installing** (the quickest way to test):

```powershell
& "desktop\dist\win-unpacked\Outpost Luna.exe"
```

**With the installer.** Double-click `desktop\dist\Outpost Luna Setup 0.3.3.exe`. It is a per-user install, so it does
not ask for Administrator rights. Start the app from the Start menu: **Outpost Luna**. To uninstall, use Settings →
Apps → Outpost Luna → Uninstall. (Uninstalling leaves `%APPDATA%\Outpost Luna`; delete it by hand for a clean slate.)

### SmartScreen (the app is unsigned)

There is no code-signing certificate yet. So the first time you run the installer or the app, Windows shows **"Windows
protected your PC"**. Click **More info → Run anyway**. Nothing else should prompt:

- **No firewall prompt.** Both servers listen on `127.0.0.1` only. A "Windows Defender Firewall has blocked some
  features" dialog for `python.exe` is a bug: report it. Clicking Cancel is safe.
- **No console windows.** The two `python.exe` children start hidden. A black console window is a bug.
- **Antivirus** may scan the new files on the first start and right after each download, which makes those slower.
  The app retries renames that a scan blocks for a moment. If it quarantines `python.exe` or a `.pyd` file, allow
  the install folder and reinstall.

### Camera and microphone

Windows doesn't ask each app for the camera or microphone. Two system switches decide for every desktop app:

- **Settings → Privacy & security → Camera**: turn on "Camera access" and "Let desktop apps access your camera".
- **Settings → Privacy & security → Microphone**: turn on "Microphone access" and "Let desktop apps access your
  microphone".

If a switch is off, the app says "Camera blocked" or "Mic is blocked. Type instead.", and `main.log` records
`windows privacy camera: denied`. Turn the switch on, then turn gestures (or the mic) off and on again. You don't
need to restart the app.

## 6. First launch: the downloads (or the offline pack)

The installer carries the code only. On the very first launch the app shows **"Getting Outpost Luna ready"** and
downloads its models from Dropbox into `%APPDATA%\Outpost Luna\assets\`:

| asset | what | size | when |
|---|---|---|---|
| `ear` | Arc Transcriber Space (the speech recognizer) | 461 MB | first launch, required |
| `tagger` | Arc Tagger v0.3 | 12 MB | first launch, required |
| `embedder` | MiniLM (the local brain's embedder) | 23 MB | first launch, required |
| `voice` | the recorded Nora voice pack (889 lines) | 14 MB | first launch, required |
| `crew` | the Artemis II crew audio | 175 MB | in the background, after the window opens |
| `videos` | the 8 saved NASA videos | 199 MB | in the background, after the window opens |
| `steer` | the Steer TTS voice | 13 MB | only when you pick Steer in Settings → Voice |

So the first launch needs **510 MB** before the app opens, then about **375 MB more** in the background. Each file is
checked against its sha256 before it is installed. You can:

- Watch the progress. The app opens by itself when the four required assets are in.
- Click **Continue later**. The app quits, and the next launch resumes where it stopped (it doesn't start from 0).
- Click **Try again** after a network error.
- Click **Import offline pack…** and pick `outpost-luna-assets-v2.zip` (885 MB: all six assets except Steer). This
  works with no network at all. Get the zip on another computer (or from a USB stick):
  [outpost-luna-assets-v2.zip](https://www.dropbox.com/scl/fi/h88nx83klw5i6s6a70ku1/outpost-luna-assets-v2.zip?rlkey=v4446k5cn0csua1a046jl1rn5&dl=1)
  (sha256 `aa0961fbcd6caf7efffe78ff443710a560a885b1afc9f53c74249f0b436d5e8d`).

Then you see a splash screen, "Warming up the models…", and the call-sign screen or Flight School within about 30
seconds. Later launches skip the download and only check the files' sizes. Settings → **Storage & updates** shows what
is installed, and whether an update is ready.

### Automated smoke test (optional, 1 minute)

With the app running:

```powershell
cd C:\src\atm
$res = "desktop\dist\win-unpacked\resources"     # installed app: "$env:LOCALAPPDATA\Programs\Outpost Luna\resources"
$env:PYTHONPATH = "$res\site\backend"; $env:PYTHONUTF8 = "1"
& "$res\python\python.exe" desktop\scripts\smoke.py
```

It should print `PASS` lines that end in `ALL PASS`. If the app chose other ports (see `ports.json`), add
`--base http://127.0.0.1:<backend port>`.

## 7. Keys you'll need for testing

| key | what it does |
|---|---|
| Hold **Space** (or the talk button) | Talk to the guide |
| **M** | Mic on or off |
| **Shift+M** | Mute: every sound off, or back on (the same as the Mute button in the top bar) |
| **R** | Cabin: re-centre the view (the same as the Center view button). **Ctrl+R** must do nothing |
| **Esc** | Back, or close a video |
| **?** | Key help |
| **F5**, **Ctrl+R**, **Ctrl+Shift+I** | Must do nothing (no reload, no dev tools) |
| **Ctrl+= / Ctrl+- / Ctrl+0**, **F11** | Zoom in, out or reset; full screen |
| **Alt+F4** | Quit |

## 8. Tester checklist

Do it once with Wi-Fi **on**, then start the app again with Wi-Fi **off**. Note anything odd, even if it worked.

1. **First launch.** On a fresh Windows account (or after deleting `%APPDATA%\Outpost Luna`): the "Getting Outpost
   Luna ready" screen shows about 510 MB and its progress. Note how long it takes: ___ min. Then check:
   - Click **Continue later** halfway, and start the app again: it resumes, it doesn't start from 0.
   - With Wi-Fi off from the start: the screen says you're offline and offers the pack. **Import offline pack…** with
     the zip (§6) installs everything with no network.
   - After the window opens, the crew audio and the videos keep downloading (Settings → Storage & updates).
2. **Start.** After the downloads: splash, then Flight School in about 30 s or less (second start: ___ s, offline:
   ___ s). There should be no console window and no firewall dialog.
3. **The ear, with your real voice** (don't play TTS into the mic). Hold Space and say "show me Tycho", then "take me
   to the Sea of Tranquility": the right place opens. Open `http://127.0.0.1:47210/health`: `models.arc_ear` should
   say it is available, on ONNX Runtime. Note how long it feels from the end of your sentence to the response.
4. **Voice: which engine and voice.** In the same `/health`, under `models.tts`, note `engine` (expect `winrt`; `sapi`
   means WinRT failed, so send `models.log`), `voice_name`, `voices` and `warm_ms`. In Settings → Voice, the
   computer's voice lists this PC's English voices. Preview two, pick one, and ask a question: the answer should use
   the new voice.
5. **Steer.** Settings → Voice → **Steer TTS (Whissle)**. It says it is downloading the Steer voice (13 MB),
   then answers in Steer with captions in step. Switch back to the computer's voice mid-session: that works too.
6. **Nora lines.** The scripted lines (lesson prompts and CAPCOM calls) play the recorded Nora voice. Live answers use
   the chosen engine. Both should be clear, with no clipped starts.
7. **First-word latency.** Ask "where did Apollo 11 land?". Time from the end of your question to the first word you
   hear: ___ s. Note any gaps between sentences.
8. **Captions.** Settings → Read → Captions on. While the guide speaks, the highlighted word should keep pace with the
   voice. Is it ahead, behind or fine?
9. **Mic and turn-taking.** Ask three questions in a row. Interrupt the guide mid-sentence by talking. Does it stop
   and listen? Does it ever answer itself, or miss a question?
10. **Camera gestures.** Settings → Camera & gestures → turn on **Use the camera for gestures**. A red "Camera on" chip
    and your hand's skeleton should appear. Check each of these:
    - Open hand held still: Stop.
    - Thumbs up: Yes. Thumbs down: No.
    - 1, 2 or 3 fingers held still: picks that answer (the badges show 1 2 3).
    - Fist leaned to one side: the Moon spins that way.
    - Swipe an open hand: next or back.
    - **Turn off** in the chip: the webcam light goes off.
    Note the "N frames a second" figure: ___.
11. **Videos.** Open a lesson with a NASA video. A saved NASA video plays in the app's own player, even with Wi-Fi off.
    A NASA YouTube clip plays as an embed when online, and says "Needs internet" when offline. Click the YouTube logo
    or "Watch on YouTube": a grown-up gate must appear (hold for 3 s), and only then does the browser open. Esc closes
    a video.
12. **Reset.** Fly a lesson first. Then go to Settings → Reset (the last item):
    - **Start over**: a plain click does nothing. Holding **Hold to start over** for 3 s closes the app, and it
      restarts by itself at the call-sign screen. Nothing downloads again.
    - **Reset everything**: the app restarts at the **"Getting Outpost Luna ready"** screen and downloads the 510 MB
      again (or takes the offline pack). `%APPDATA%\Outpost Luna\assets`, `cache` and `hf` were emptied; `logs` stays.
    - `main.log` must not say `could not delete`. If it does, send the line: that is a Windows file lock.
13. **Mute.** Press Shift+M (or click Mute in the top bar). Every sound stops: the voice, crew audio, videos and the
    beeps. Captions stay. Press Shift+M again: sound is back.
14. **Cabin re-centre.** Mission tab → the 3D cabin. Turn your head (camera on) or drag to look away. Press **R**: the
    view comes back to the centre. The Center view button does the same. Ctrl+R does nothing.
15. **Quit.** Close the window. In Task Manager, no `python.exe` from Outpost Luna is left.

## 9. What to send back

Copy this, fill it in, and attach the three logs (`%APPDATA%\Outpost Luna\logs\*.log`).

```
build-windows.ps1: pass / fail (if fail: the last 40 lines)    build time: ___ min    installer: ___ MB
compilers printed in step 1 (arctag / libarc):
Windows version (winver) / CPU / RAM / GPU / is your Windows user name plain ASCII?
SmartScreen "Run anyway" worked? firewall dialog? console window?
first launch: 510 MB took ___ min; Continue later resumed? offline pack import worked? background crew+videos done?
start to Flight School: 2nd ___ s, offline ___ s
smoke.py: ALL PASS? (paste the output if not)
ear with my voice: "show me Tycho" opened Tycho? Sea of Tranquility? feel of the delay: ___
voice: engine ___  voice ___  voices ___  warm_ms ___   Steer: downloaded? speaks? captions in step?
Nora lines clear? ___   first word after a question: ___ s   gaps between sentences? ___
captions in step with the voice? (ahead / behind / fine)
mic and turn-taking: interrupting works? missed questions?
gestures: stop / yes / no / 1-2-3 / fist spin / swipe / camera off: each ok? frames a second: ___
videos: saved NASA video plays offline? YouTube embed plays online? gate shown?
reset: Start over relaunches, no re-download? Reset everything re-downloads (or takes the pack)? "could not delete"?
mute: Shift+M silences everything and brings it back?
cabin: R and Center view re-centre? Ctrl+R does nothing?
quit: no python.exe left?
RAM after one question (Outpost Luna + its python.exe processes): ___ MB
main.log lines with "assets:", "blocked", "FAIL", "exited", "ROLLBACK", "windows privacy":
```

### Attach the installer to the release

If the build passes and the app runs, attach the installer to the GitHub release under its stable name. The website's
"Download for Windows" button links `releases/latest/download/Outpost-Luna-win-x64.exe`, so this is what makes it work.
You need the [GitHub CLI](https://cli.github.com/) (`winget install --id GitHub.cli -e`, then `gh auth login`) and write
access to the repo. Use the tag of the release you built (for example `v0.3.3`):

```powershell
gh release upload <tag> desktop\dist\Outpost-Luna-win-x64.exe
```

Add `--clobber` to replace a file that is already attached. Keep the name as it is: the site looks for exactly
`Outpost-Luna-win-x64.exe`.

## 10. Known limitations

- **Unsigned.** There is no Authenticode certificate yet, so SmartScreen warns once (§5).
- **First launch needs the internet, or the offline pack.** 510 MB before the app opens; 375 MB more in the
  background; Steer another 13 MB when picked.
- **NSIS 2 GB limit.** An NSIS installer can't hold more than 2 GB. The 0.3 app is **783 MB uncompressed**
  (`dist\win-unpacked`, 7,896 files, measured 2026-11-15), well under it, because the models are no longer bundled.
  (0.1.x bundled them: 1,620 MB.) Compressed, the installer is 192 MB.
- **x64 only.** There is no ARM64 build.
- **No app icon yet.** The app shows Electron's default icon, on the Mac too (`desktop/build-resources` has none).
  A cross-built installer (§12) also lacks the version details, because it is built without Wine.
- **Downloads ignore system proxies.** On a network that only allows a proxy, use the offline pack.
- **Voices.** The computer's voices come from Windows itself. You can add better ones in Settings → Time & language →
  Speech → Manage voices; they appear in the app within 30 s.
- **The clang-cl build of libarc is untested.** The Mac cross-build uses mingw-w64 gcc. Report step 6's output if it
  fails.
- **The pinned ONNX Runtime and the generated bindings (#85, #86) are untested on a Windows machine.** The Mac
  cross-build fetches and checks the same `onnxruntime.dll`; what only a Windows build can confirm is listed just
  below ("Engine boundary").

### Engine boundary (pinned ONNX Runtime, ABI check, model checksums)

After a native Windows build, please confirm and send the output:

1. Step 6 prints `onnxruntime 1.32.0 (windows-x64): ...\onnxruntime\onnxruntime.dll (sha256 ok)` during libarc's
   configure (both generators: LLVM clang + Ninja, and Visual Studio `-T ClangCL`), then
   `C bindings match arc.h and arctag.h` and `desktop\resources\native\arc.dll: ABI 1 (matches arc.h)`.
2. `desktop\dist\win-unpacked\resources\native\onnxruntime\` holds `onnxruntime.dll`, `onnxruntime.json`,
   `LICENSE`, `ThirdPartyNotices.txt`, and step 8's `runtime` check says `onnxruntime.dll 1.32.0 sha256 ok`.
3. Step 8's `dlls` check passes (the pinned `onnxruntime.dll` imports `MSVCP140.dll` / `VCRUNTIME140*.dll`; they must
   resolve from `resources\python\`).
4. Start the unpacked app, then `curl http://127.0.0.1:47210/health` (the models port from `ports.json`):
   `models.arc_ear.available` is true and `models.arc_ear.engine` shows `"abi": 1`, `"ort_source": "pinned"`,
   `"backend": "onnxruntime 1.32.0"`, `"verify": {"verified": true, ...}`; `ort_wheel` is `1.32.0`.
5. Say something with a lunar name ("take me to Tycho"): the transcript and the link work as before.
6. Optional, the repair path: quit the app, append one byte to `%APPDATA%\Outpost Luna\assets\tagger\NOTICE`
   (a size change) or overwrite a byte of `assets\ear\nft2\tags.json` keeping its size; start the app. `/health`
   shows the ear (or tagger) refused with `is damaged ... sha256`, the file is renamed `*.damaged`, and the asset
   downloads again (a size change is caught by the app before the servers start; a same-size change by the model
   server, which asks for the download through `assets\.want\`).

## 11. Troubleshooting

| you see | do this |
|---|---|
| `uv` / `node` / `cmake` "is not recognized" | Open a new PowerShell after `winget install` |
| `running scripts is disabled on this system` | Use the exact command in §3 (it has `-ExecutionPolicy Bypass`) |
| `No C compiler` | Install the Build Tools with the command in §1 |
| `libarc (the ear) needs clang` (step 1) | Run the Build Tools command in §1 again: it adds the clang-cl components. Or install LLVM and Ninja (§1) |
| CMake: `arc.dll was not produced` / `The build tools for ClangCL cannot be found` | Same as above. Send the CMake output if it persists |
| CMake: `arctag.dll was not produced` | Send the CMake output. Try the other compiler (MSVC or LLVM) |
| `No CMAKE_C_COMPILER could be found` at `cmake ... -T ClangCL` | Two Visual Studios are installed and CMake picked the newer one, which has no clang-cl (e.g. VS 2026 next to VS 2022 with clang). Pull the latest main (the script now pins the Visual Studio that has clang-cl), or set `$env:CMAKE_GENERATOR = "Visual Studio 17 2022"`, delete `desktop\build\arctag` and `desktop\build\libarc`, and re-run |
| clang-cl build of `arc.dll` fails on AVX2 / FMA intrinsics | Fixed on main: libarc's CMakeLists passes `/arch:AVX2` to clang-cl. Pull main. The Windows app needs a CPU with AVX2 (Intel 2013+, AMD 2015+) |
| `git clone` says `invalid path` | You have an old copy: four screenshot names had a `?` until 2026-11-15. Clone again |
| Path / "file name too long" deep inside a package | Clone to `C:\src\atm`, or turn on long paths (§1) |
| `only N GB free` | Free up space: the build uses about 4 GB, and 8 GB free is safe |
| Media step fails with HTTP 403 or timeouts | Run it again. NASA's server limits the rate at times |
| `assets without a download link` (step 5) | Report it: the asset manifest on `main` is incomplete |
| `DLL imports that resolve nowhere` (step 4 or 8) | Send the list: a package needs a DLL the app doesn't ship |
| `runtime check(s) failed` (step 8) | Send the `MISS` lines: a file the app needs is not in the bundle |
| "Windows protected your PC" | Click More info → Run anyway (§5) |
| First launch: "You're offline" / the download fails | Check the network and click Try again, or use **Import offline pack…** (§6) |
| First launch stuck at the same percentage | Wait a minute (antivirus scans each finished file), then Continue later and start again: it resumes |
| `main.log`: `assets: ... sha256 mismatch` | Click Try again (the file downloads again). If it repeats, send `main.log` |
| "not enough disk space for …" | Free the space it names on the system drive (`%APPDATA%` lives there), then Try again |
| Splash says the backend or model server "keeps stopping" | Send `%APPDATA%\Outpost Luna\logs\*.log` |
| `models.log`: `libarc not found` or `cannot load ... arc.dll` | Send `models.log`. The app should have `resources\native\arc.dll` |
| `models.log`: `ONNX Runtime: cannot load ...onnxruntime.dll` | Send `models.log`. libarc loads the pinned `resources\native\onnxruntime\onnxruntime.dll` by path (it needs the VC++ DLLs next to `python.exe`) |
| `models.log` / `/health`: `ONNX Runtime ... not found next to libarc` or `... damaged or not the pinned build` | `resources\native\onnxruntime\` is missing or altered: rebuild (step 6) or reinstall. Send step 6's output |
| `models.log` / `/health`: `AbiMismatch: ... libarc ABI` or `C bindings out of date with the headers` (step 6) | `arc.dll` and the Python code come from different commits: pull, delete `desktop\build\libarc`, re-run |
| `/health`: `The speech model ... is damaged: nft2/... sha256 ...` | A model file changed on disk after its download. The app moves it aside and downloads the asset again; restart when it finishes. Send `models.log` if it repeats |
| `models.log`: `cannot open ...` for a file under `assets\ear` | Send `models.log`, and say whether your Windows user name has accents or non-Latin letters |
| `models.log`: `DLL load failed` / `WinError 126` | Send `models.log`. As a test only, installing the "Microsoft Visual C++ Redistributable (x64)" should fix it; report it either way |
| `models.log`: `does not report AVX2 + FMA` | Report the CPU (only a cross-built DLL needs AVX2) |
| No voice, and `/health` shows `engine: sapi` or none | Send `models.log`. Check Settings → Time & language → Speech that an English voice is installed |
| Steer stays at "Downloading…" | Check the network; send `main.log` lines with `assets: steer` |
| "Camera blocked" / "Mic is blocked" | Turn on the privacy switches (§5) |
| Camera "didn't start" | Close Teams, Zoom or other apps that use the camera |
| YouTube clip shows an error (101, 150, 153) | Note the video and the error. Saved NASA videos should still play |
| Reset: `could not delete` in `main.log` | Send the line (a file lock). Quit, then delete `%APPDATA%\Outpost Luna\assets` and `cache` by hand |
| Antivirus quarantines `python.exe` or a `.pyd` | Allow the `desktop\` folder (or the install folder) and run it again |
| A `python.exe` stays after quitting | Send `main.log`. To end it: `taskkill /IM python.exe /F` (this also stops other Python programs) |

## 12. Cross-building on a Mac (for us, not the tester)

A Mac can build the same Windows tree. This is how it was checked without a PC:

```bash
brew install mingw-w64 sevenzip cmake node@22 uv
bash desktop/scripts/cross-build-windows.sh                       # -> desktop/dist/Outpost Luna Setup 0.3.3.exe
SKIP_MEDIA=1 DIR_ONLY=1 KEEP_INTERMEDIATES=1 bash desktop/scripts/cross-build-windows.sh   # win-unpacked only, kept
MAC_APP="/Applications/Outpost Luna.app" bash desktop/scripts/cross-build-windows.sh       # + a parity report vs the Mac app
```

These are the differences from the native build:

- **Python and wheels.** The interpreter is python-build-standalone's `x86_64-pc-windows-msvc` build, checked against
  its `SHA256SUMS`. The packages are win_amd64 wheels, from `uv pip install --python-platform x86_64-pc-windows-msvc`.
- **`arctag.dll` and `arc.dll`** come from mingw-w64 gcc, statically linked (they import only Windows' own DLLs).
  The pinned `onnxruntime.dll` is Microsoft's release build either way (`windows-x64` in
  `desktop/vendor/libarc/onnxruntime.lock.json`); it imports the VC++ runtime, which ships next to `python.exe`.
- **The `.exe` icon and version info are not edited**, because there is no Wine.

`desktop/resources/` holds one platform's build at a time. After a cross-build, `build-mac.sh` rebuilds it for the Mac.

Step 8 checks the result with `desktop/scripts/win_bundle_check.py`, which is stdlib-only and also runs on Windows:

| command | checks |
|---|---|
| `dlls <resources>` | Every `.dll` / `.pyd` import (the import and delay-load tables) resolves in the bundle or in Windows itself |
| `speech <resources>` | The WinRT SpeechSynthesis, Media.Core, Storage.Streams and Foundation `.pyd` files, comtypes (SAPI) and `steertts_edge` (the Steer runtime) |
| `runtime <resources>` | Every file the app needs at run time: python.exe and the VC++ DLLs; `arctag.dll` and `arc.dll`; the pinned `native\onnxruntime\onnxruntime.dll` libarc loads, at its sha256; no bundled models; a usable `assets.manifest.json` (an https download, sha256 and file list for every asset); the NASA video catalog and downloader; the ear and Steer bindings; Reset; the assets API; the Director weights; the vision assets; and the Electron shell inside `app.asar` (main, supervisor, permissions, keys, reset, the grown-up gate, the splash, the first-run screen, assets and updates) |
| `compare <mac Resources> <win resources>` | Parity with a Mac build, area by area |

The platform-mocked tests run on any OS:

```bash
cd desktop && node --test main/       # shell: win32 paths, taskkill, reset, keys, assets, updates, sign-resources no-op, repo paths
cd model_server && uv run pytest tests/test_platform_win.py tests/test_tts_os.py tests/test_os_voices.py tests/test_tts_steer.py
cd backend && uv run pytest tests/test_windows_paths.py tests/test_reset.py tests/test_video.py tests/test_assets_api.py
```

**Last cross-build (2026-11-15, `main` at 0.3.0 + this guide's PR):** steps 1 to 8 passed, including the NSIS
installer (`Outpost Luna Setup 0.3.3.exe`, 192 MB; 9.4 min on a Mac at load average ~30). `dlls`: 231 DLL/PYD files,
every import resolves. `speech`: all 8 present. `runtime`: RUNTIME OK. The installer's payload, unpacked with 7-Zip, is
identical to `win-unpacked` (783 MB, 7,896 files). Every asset link in the manifest answered a 1-byte range request.
