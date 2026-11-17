# Arc recording kit (macOS + Windows)

Data the Arc speech team asked for in their 16 November 2026 update (section 4): the app's real playback through
laptop speakers into the laptop mic, with the exact reference that was played, plus the app's lines rendered with the
OS voices, plus consented "talking to the app / to someone else / over the app" recordings. It feeds Arc's echo
canceller (`arc_nft2_stream_feed_ref`, Python `feed_reference`), its `playback` flag, barge-in, and the coming
addressee head.

| command | time | sound? | what you get |
|---|---|---|---|
| `check` | seconds | no (one 0.25 s mic read, discarded) | devices, mic permission, disk estimate, which content and voices were found |
| `render-lines` | 20-60 min, unattended | **silent** (renders to files) | every app line x every OS voice the app can use here, WAV + 16 kHz + `manifest.json` |
| `echo` | ~25 min, unattended | **plays through the speakers** | `mic.wav` + `ref.wav` (sample-aligned) + 16 kHz copies + `manifest.json` |
| `guided` | ~15 min, a person present | plays the app's lines at times | the same, plus a label and timing per prompt, and `consent.json` |

Nothing is ever uploaded. Output goes to `~/Outpost Luna recordings/<session>-<date>/` (or `--out <folder>`).

## Setup (once)

Install [uv](https://docs.astral.sh/uv/) and get this repo (or just this folder plus `backend/data/voice_pack` and
`model_server/app/os_voices.py`). `uv run --with ...` puts the three packages in a throwaway environment; nothing is
installed globally.

### macOS (Terminal, from the repo folder)

```
uv run --with sounddevice --with soundfile --with numpy python tools/arc_collect/arc_collect.py check
uv run --with sounddevice --with soundfile --with numpy python tools/arc_collect/arc_collect.py render-lines
uv run --with sounddevice --with soundfile --with numpy python tools/arc_collect/arc_collect.py echo
uv run --with sounddevice --with soundfile --with numpy python tools/arc_collect/arc_collect.py guided
```

**Mic permission (macOS).** The first `check` does one short silent read of the mic. That read is what makes macOS
show *"Terminal would like to access the microphone"* (or iTerm / VS Code, whichever app runs the command): click
**OK / Allow**. If you clicked Don't Allow before, macOS does not ask again and the mic delivers pure digital silence;
`check` detects that and says so. Fix: System Settings > Privacy & Security > Microphone > switch on your terminal app,
quit and reopen it, run `check` again.

### Windows (PowerShell, from the repo folder)

```
$W = "--with","sounddevice","--with","soundfile","--with","numpy","--with","comtypes==1.4.17","--with","winrt-runtime==3.2.1","--with","winrt-Windows.Media.SpeechSynthesis==3.2.1","--with","winrt-Windows.Media.Core==3.2.1","--with","winrt-Windows.Storage.Streams==3.2.1","--with","winrt-Windows.Foundation==3.2.1","--with","winrt-Windows.Foundation.Collections==3.2.1"
uv run @W python tools/arc_collect/arc_collect.py check
uv run @W python tools/arc_collect/arc_collect.py render-lines
uv run @W python tools/arc_collect/arc_collect.py echo
uv run @W python tools/arc_collect/arc_collect.py guided
```

The extra packages are the Windows speech engines the app uses (the same pins as `model_server/pyproject.toml`):
WinRT for the OneCore / Natural voices, SAPI 5 (comtypes) for the classic desktop voices. `render-lines` uses both, so
one run gives the whole Windows voice set the app can speak with.

**Mic permission (Windows).** Settings > Privacy & security > Microphone: turn on *Microphone access* and *Let desktop
apps access your microphone*. `check` reports pure digital silence when it is off.

## Before the `echo` session

- Use the laptop's **built-in speakers and built-in mic**. Unplug headphones, turn off AirPods / Bluetooth audio. The
  kit warns and asks before it plays through Bluetooth or anything that doesn't look built in (`--speakers` / `--mic`
  pick devices by index or name; `check` lists them).
- Set the system volume where a kid would play (60-80%) and leave it. On macOS the kit reads it into the manifest; on
  Windows it asks you to type it.
- Quiet room, lid open, nothing on the keyboard. It runs ~25 minutes on its own. At the start it shows *"this will
  play sound for about 25 minutes; press Enter to start / Ctrl-C to stop"*.
- **Ctrl-C at any time stops it and keeps what was recorded.** The manifest is rewritten for the shorter recording
  (`status: stopped_early`) and is still valid.

What it plays, at four levels (0, -6, -12, -18 dB below the app's mastered level; `--levels`):

- Nora's recorded voice-pack clips (`backend/data/voice_pack/clips`, or the installed app's copy);
- the lines the app speaks live (readbacks with numbers, Houston, place answers, coordinates), rendered with the app's
  OS voices (the persona voices first, then other Settings voices);
- a few crew audio excerpts (the app's crew asset or `make data` media; else the 7 s crew fixture in git) and a little
  NASA video sound (cached videos, decoded with ffmpeg when installed; `--media-dir` points at more);
- a log sweep (chirp) at the start, at each level and at the end, to measure the round trip;
- silent gaps (6 s per level, 3 s every minute, plus the start / end) for the noise floor.

## The `guided` session

A consent screen comes first: whose voice (adult, or a child with a parent or guardian present who types `I AGREE`),
and agreement to share with the Arc team (`I AGREE`). Anything else stops it before a device is opened, with nothing
recorded. Then ~15 minutes of prompts, each shown as *Get ready* and then *>>> NOW*:

| label | the screen says | |
|---|---|---|
| `addressed` | Say this TO THE APP | sometimes right after the app said a line |
| `not_addressed` | Say this to SOMEONE ELSE in the room | |
| `barge_in` | TALK OVER THE APP NOW | the app is mid-line |

## What a session folder holds

```
echo-2026-11-16/
  mic.wav          the microphone, mono float32 at the device rate (48 kHz when the devices allow)
  ref.wav          exactly what was sent to the speakers, same rate, SAME CLOCK as mic.wav
  mic_16k.wav      16 kHz mono PCM16 copies for Arc (same clock)
  ref_16k.wav
  manifest.json    see below
  consent.json     (guided only)
  README.txt
```

`mic.wav` and `ref.wav` come from **one** full-duplex stream: reference sample *n* went to the speakers in the same
audio callback that captured mic sample *n*. The sound reaches the mic `latency.measured_roundtrip_s` later (matched
filter on the chirps; every chirp is listed). For Arc: `feed_reference(ref[n:n+k], stream_time=n / sample_rate)` while
feeding the mic at the same `n`.

`manifest.json`: `segments` (start/end in seconds and frames on that clock, kind = `voice_pack` / `os_voice` / `crew` /
`video` / `chirp` / `noise_floor`, text, voice id + name + engine, `level_db`), the device names, sample rate (and any
rate fallback), the measured and PortAudio-reported latency, OS version and machine model, `status`
(`complete` / `stopped_early`), and for `guided` the `prompts` with `label`, the text, `ready_s`, `now_s`, the
expected speech `window_start_s` / `window_end_s`, and when the screen actually showed them.

## What gets shared

Only what you hand over yourself: copy the session folders (and the `render-lines-*` folder) to a USB stick or a shared
drive you choose, and send that to the Arc team. The kit never uploads, never phones home and needs no network.

What the folders contain:

- **echo / render-lines:** the app's own voice lines and the sound of the room they played in. No person speaks.
- **guided:** the voice of whoever took part, the prompt texts, and the consent answers (adult / child, agreed).
- **machine facts:** OS and version, the hardware model id (e.g. `Mac15,6`, or the Windows manufacturer + model),
  the chip, the audio device names. Never a serial number, host name, user name or file path. Device names with an
  owner's name are scrubbed ("Sam's AirPods" becomes "Owner's AirPods").
- **no clock time** beyond the date.

Delete a folder to delete that recording.

## Dry run and tests (no sound, no mic)

`--dry-run` swaps `sounddevice` for an in-memory loopback (`fakesd.py`) that "plays" into a fake mic with a delay, a
low-pass and attenuation, and swaps the OS voices for synthetic tones. It exercises everything else, including the
chirp alignment, the 16 kHz copies, the manifest and Ctrl-C.

```
uv run --with sounddevice --with soundfile --with numpy python tools/arc_collect/arc_collect.py echo --dry-run --yes --minutes 2
uv run --with pytest --with numpy --with soundfile python -m pytest tools/arc_collect/tests -q
```

The tests check that the chirp recovers the loopback delay within 1 ms (12 ms to 250 ms, 44.1 and 48 kHz, quiet and
noisy), that `ref.wav` is bit-exact what was played, that the 16 kHz copies keep the alignment, that the manifest
validates (also after a Ctrl-C midway), that the consent gate blocks every non-consent answer without opening a device,
that Bluetooth speakers are refused, and that device names are scrubbed.

## Files

| file | |
|---|---|
| `arc_collect.py` | the CLI and the four sessions |
| `session.py` | the playback timeline, the duplex recorder, the manifest + its validator |
| `align.py` | chirp, matched-filter delay, mastering, resampling (numpy only) |
| `devices.py` | device choice, sample-rate fallback, Bluetooth guess, mic probe, machine facts, disk |
| `osvoices.py` | the OS voices with the app's own ranking (`model_server/app/os_voices.py`): `say`, WinRT, SAPI |
| `content.py` | the voice pack, the live lines, crew and video sound, the guided prompts |
| `fakesd.py` | the in-memory loopback for `--dry-run` and the tests |
