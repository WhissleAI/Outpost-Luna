#!/usr/bin/env python3
"""Outpost Luna -> Arc recording kit (macOS + Windows). See README.md in this folder.

    check          list audio devices, test the mic permission (one short silent read), estimate disk use
    render-lines   SILENT: render the app's spoken lines with every OS voice the app can use here -> files + manifest
    echo           ~25 min, unattended: play the app's lines through the speakers at 4 levels and record the mic,
                   saving the exact reference that was played, sample-aligned
    guided         ~15 min, a person present: on-screen prompts (to the app / to someone else / talk over the app)
                   while the app's lines play; consent first

Run with:  uv run --with sounddevice --with soundfile --with numpy python tools/arc_collect/arc_collect.py <command>
Everything stays on this computer. Nothing is uploaded.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import random
import signal
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import numpy as np  # noqa: E402

import align  # noqa: E402
import content  # noqa: E402
import devices as dv  # noqa: E402
import osvoices  # noqa: E402
from session import KIT_VERSION, Recorder, Timeline, measure_chirps, seg_entry, validate_manifest, write_json  # noqa: E402

LEVELS_DB = (0.0, -6.0, -12.0, -18.0)


# ================================================================================================= helpers
def say(msg: str = "") -> None:
    print(msg, flush=True)


def tilde(p: Path) -> str:
    """Show a path with ~ for the home folder (the terminal output gets pasted into chats)."""
    try:
        return "~/" + str(Path(p).resolve().relative_to(Path.home().resolve())).replace("\\", "/")
    except ValueError:
        return str(p)


def get_sd(dry_run: bool, **fake):
    if dry_run:
        from fakesd import FakeSoundDevice
        return FakeSoundDevice(**fake)
    try:
        import sounddevice as sd
    except Exception as e:  # noqa: BLE001 - OSError: PortAudio library not found
        raise SystemExit(f"Could not load sounddevice/PortAudio ({e}). Run through `uv run --with sounddevice ...` "
                         "as the README shows.")
    return sd


def session_dir(root: str | None, name: str, dry_run: bool) -> Path:
    if root:
        base = Path(root).expanduser()
    elif dry_run:
        base = Path(tempfile.mkdtemp(prefix="arc-collect-dry-"))
    else:
        base = dv.default_root()
    stem = f"{name}-{_dt.date.today().isoformat()}"
    d, k = base / stem, 2
    while d.exists():
        d, k = base / f"{stem}-{k}", k + 1
    d.mkdir(parents=True)
    return d


def ask(prompt: str, inp) -> str | None:
    try:
        return inp(prompt)
    except EOFError:
        return None


def _to_rate(x: np.ndarray, sr: int, rate: int) -> np.ndarray:
    return align.resample(x, sr, rate) if sr != rate else np.asarray(x, np.float32)


def open_devices(sd, a) -> tuple[dict, dict, int, int, list[str]]:
    din = dv.pick_device(sd, a.mic, "input")
    dout = dv.pick_device(sd, a.speakers, "output")
    out_ch = max(1, min(2, int(dout["max_output_channels"])))
    rate, notes = dv.choose_rate(sd, din, dout, out_ch, a.rate)
    return din, dout, out_ch, rate, notes


def speaker_gate(din: dict, dout: dict, a, inp, need_builtin: bool) -> bool:
    """Bluetooth / external speakers: the echo set must be the laptop's own speakers into its own mic."""
    warn = []
    if dv.is_bluetooth(dout["name"]):
        warn.append(f"The speakers are Bluetooth ('{dv.scrub_name(dout['name'])}').")
    elif need_builtin and not dv.looks_builtin_speaker(dout["name"]):
        warn.append(f"The speakers ('{dv.scrub_name(dout['name'])}') don't look like the laptop's built-in ones.")
    if dv.is_bluetooth(din["name"]):
        warn.append(f"The mic is Bluetooth ('{dv.scrub_name(din['name'])}'): use the laptop's built-in mic.")
    if not warn:
        return True
    say("\n!! " + "\n!! ".join(warn))
    if need_builtin:
        say("!! The echo session needs the laptop's BUILT-IN speakers and BUILT-IN mic. Disconnect headphones / AirPods "
            "and pick the built-in output in the sound settings, or pass --speakers / --mic.")
    if a.force_speakers:
        say("!! --force-speakers: continuing anyway.")
        return True
    r = ask("Type  yes  to continue anyway, or anything else to stop: ", inp)
    return (r or "").strip().lower() == "yes"


def finalize(outdir: Path, manifest: dict, tl: Timeline, res: dict, chirps: list[dict], chirp_pcm: np.ndarray) -> dict:
    """After the stream: 16 kHz copies, the chirp latencies, the final manifest. Ctrl-C is ignored while saving."""
    old = signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        sr, frames = manifest["sample_rate"], res["frames"]
        say(f"\nSaving ({frames / sr / 60:.1f} min recorded) ...")
        if frames > 0:
            align.resample_file(str(outdir / "mic.wav"), str(outdir / "mic_16k.wav"), 16000)
            align.resample_file(str(outdir / "ref.wav"), str(outdir / "ref_16k.wav"), 16000)
            manifest["files"].update({"mic_16k": "mic_16k.wav", "reference_16k": "ref_16k.wav"})
        lat = measure_chirps(outdir, chirps, chirp_pcm, sr)
        good = [c for c in lat if c["reliable"]]
        manifest["latency"] = {
            "measured_roundtrip_s": good[0]["delay_s"] if good else None,
            "how": "matched filter of the played chirp in mic.wav: mic sample n + round trip hears ref sample n",
            "chirps": lat,
            "portaudio_reported_s": {"stream_latency_in_out": res.get("portaudio_latency_s"),
                                     "first_callback": res.get("first_times")}}
        if not good and frames > 0:
            manifest["notes"].append("no chirp was heard clearly: check the mic and the volume (latency unknown)")
        manifest["frames"] = frames
        manifest["duration_s"] = round(frames / sr, 3)
        manifest["status"] = "stopped_early" if res["interrupted"] or frames < tl.total else "complete"
        manifest["stream_status"] = {**res["status"], "writer_error": res.get("writer_error")}
        manifest["segments"] = [e for e in (seg_entry(s, sr, frames, i) for i, s in enumerate(tl.segs)) if e]
        if "prompts" in manifest:
            manifest["prompts"] = [p for p in manifest["prompts"] if p["window_start_frame"] < frames]
            for p in manifest["prompts"]:
                if p["window_end_frame"] > frames:
                    p["window_end_frame"], p["truncated"] = frames, True
                p["window_start_s"] = round(p["window_start_frame"] / sr, 6)
                p["window_end_s"] = round(p["window_end_frame"] / sr, 6)
        write_json(outdir / "manifest.json", manifest)
        errs = validate_manifest(manifest, outdir)
        if errs:
            say("Manifest problems: " + "; ".join(errs))
        return manifest
    finally:
        signal.signal(signal.SIGINT, old)


def base_manifest(session: str, a, sd, din, dout, rate, out_ch, rate_notes) -> dict:
    return {
        "kit": "outpost-luna/tools/arc_collect", "kit_version": KIT_VERSION, "session": session, "status": "recording",
        "date": _dt.date.today().isoformat(), "dry_run": bool(a.dry_run),
        "machine": dv.machine_info(a.dry_run),
        "devices": {"input": dv.device_entry(din, "input"), "output": dv.device_entry(dout, "output")},
        "sample_rate": rate, "output_channels": out_ch, "rate_notes": rate_notes,
        "files": {"mic": "mic.wav", "reference": "ref.wav"},
        "format": "mic.wav / ref.wav: mono float32 at sample_rate; *_16k.wav: mono PCM16 16 kHz (same clock)",
        "clock": ("seconds from the first sample of mic.wav and ref.wav. Both come from ONE duplex stream: ref sample n "
                  "was handed to the speakers in the same callback that captured mic sample n, so the files are "
                  "sample-aligned; the speaker->mic sound arrives latency.measured_roundtrip_s later. For Arc: "
                  "feed_reference(ref[n:n+k], stream_time=n / sample_rate)."),
        "frames": 0, "segments": [], "notes": [], "uploaded": False,
    }


def write_readme(outdir: Path, session: str) -> None:
    (outdir / "README.txt").write_text(
        f"Outpost Luna recording for the Arc speech team ({session} session).\n"
        "mic.wav = what the microphone heard; ref.wav = exactly what was played (same clock); *_16k.wav = 16 kHz copies;\n"
        "manifest.json = what played when, devices, latency.\n"
        "Nothing was uploaded. Hand this folder over yourself (USB / a shared drive you choose), or delete it to delete "
        "the recording.\n", encoding="utf-8")


# ================================================================================================= content prep
def voice_meta(v: dict) -> dict:
    return {"id": v["id"], "name": v.get("voice_label") or v.get("name"), "engine": v.get("engine"),
            "quality": v.get("quality"), "locale": v.get("locale"), "roles": v.get("roles", [])}


def prepare_os_lines(a, rate: int, n_pack_texts: int = 16) -> tuple[list[dict], list[str]]:
    """Render the app's live lines (+ a few pack lines) with the role voices and a few more picker voices."""
    engines, notes = osvoices.load_engines(a.dry_run, a.engines)
    if not engines:
        return [], notes + ["no OS speech engine: OS-voice lines skipped"]
    voices, roles, n2 = osvoices.app_voices(engines)
    notes += n2
    role_ids = list(dict.fromkeys(roles.values()))
    pick = [v for v in voices if v["id"] in role_ids] + [v for v in voices if v["in_picker"] and v["id"] not in role_ids]
    pick = pick[: max(1, a.echo_voices)]
    texts = [("live", t) for t in content.LIVE_LINES] + [("pack_text", t) for t in content.pack_line_texts(n_pack_texts)]
    items = []
    for i, (kind, text) in enumerate(texts):
        v = pick[i % len(pick)] if pick else None
        if v is None:
            break
        try:
            pcm, sr = osvoices.engine_for(engines, v).render(text, v["id"])
        except Exception as e:  # noqa: BLE001
            notes.append(f"render failed for {v['id']}: {str(e)[:100]}")
            continue
        items.append({"pcm": align.master(_to_rate(pcm, sr, rate), rate), "kind": "os_voice", "text": text,
                      "voice": voice_meta(v), "line_kind": kind})
        if sys.stdout.isatty():
            print(f"\r  preparing OS-voice lines {len(items)}/{len(texts)}", end="", flush=True)
    say(f"  {len(items)} OS-voice lines ready")
    return items, notes


def load_pack_item(c: dict, rate: int) -> dict | None:
    try:
        x, sr = content.load_audio(c["file"])
    except Exception:  # noqa: BLE001
        return None
    return {"pcm": align.master(_to_rate(x, sr, rate), rate, rms_db=-18.0), "kind": "voice_pack", "text": c["text"],
            "role": c.get("role"), "key": c["key"],
            "voice": {"id": c.get("voice"), "name": c.get("voice_name"), "engine": "voice_pack"},
            "source": "voice_pack/" + Path(c["file"]).parent.name + "/" + Path(c["file"]).name}


def prepare_media(a, rate: int, rng: random.Random, notes: list[str]) -> tuple[list[dict], list[dict]]:
    crew = []
    files = content.crew_files(a.media_dir)
    if files:
        for f in rng.sample(files, min(6, len(files))):
            try:
                x, sr = content.load_audio(f, start_s=3.0, dur_s=15.0)
            except Exception as e:  # noqa: BLE001
                notes.append(f"crew clip {f.name} unreadable: {str(e)[:80]}")
                continue
            if len(x) > sr:
                crew.append({"pcm": align.master(_to_rate(x, sr, rate), rate, rms_db=-20.0), "kind": "crew",
                             "source": f.name, "src_start_s": 3.0, "text": None})
    if not crew and content.CREW_FIXTURE.exists():
        x, sr = content.load_audio(content.CREW_FIXTURE)
        crew.append({"pcm": align.master(_to_rate(x, sr, rate), rate, rms_db=-20.0), "kind": "crew",
                     "source": content.CREW_FIXTURE.name, "src_start_s": 0.0, "text": None})
        notes.append("crew audio: only the 7 s fixture in git (run `make data` or install the app's crew asset for more)")
    video = []
    vids = content.video_files(a.media_dir)
    for f in vids[:3]:
        try:
            x, sr = content.load_audio(f, start_s=5.0, dur_s=10.0)
        except Exception as e:  # noqa: BLE001
            notes.append(f"video {f.name}: {str(e)[:80]}")
            break
        if len(x) > sr and align.active_rms(x, sr) > 1e-4:
            video.append({"pcm": align.master(_to_rate(x, sr, rate), rate, rms_db=-20.0), "kind": "video",
                          "source": f.name, "src_start_s": 5.0, "text": None})
    if not vids:
        notes.append("NASA video sound: no cached videos found (open a few videos in the app first, or --media-dir)")
    return crew, video


def add_item(tl: Timeline, it: dict, gain_db: float, block: int) -> dict:
    meta = {k: v for k, v in it.items() if k != "pcm"}
    return tl.add(it["pcm"], gain_db=gain_db, level_db=gain_db, level_block=block, **meta)


# ================================================================================================= echo
def build_echo(a, rate: int, rng: random.Random, notes: list[str]) -> tuple[Timeline, list[dict], np.ndarray]:
    tl = Timeline(rate)
    ch = align.chirp(rate)
    chirps = []
    levels = [float(x) for x in a.levels.split(",")] if a.levels else list(LEVELS_DB)
    say("Preparing the app's lines (silent) ...")
    os_items, n1 = prepare_os_lines(a, rate)
    notes += n1
    pack = content.pack_clips()
    if not pack:
        notes.append("voice pack not found: no Nora clips")
    crew, video = prepare_media(a, rate, rng, notes)
    total = a.minutes * 60.0
    tl.silence(2.0, "noise_floor", label="start")
    chirps.append(tl.add(ch, kind="chirp", label="start", gain_db=0.0, level_db=0.0))
    tl.silence(1.5)
    per_block = (total - tl.cursor / rate - 6.0) / len(levels)
    # crew: 10% when there are real crew clips; just a touch when only the 7 s fixture is there (no endless repeats)
    weights = {"voice_pack": 0.5, "os_voice": 0.35, "crew": 0.1 if len(crew) >= 3 else 0.015, "video": 0.05}
    pools = {"voice_pack": None, "os_voice": os_items, "crew": crew, "video": video}
    if not pack:
        weights.pop("voice_pack")
    for k in ("os_voice", "crew", "video"):
        if not pools[k]:
            weights.pop(k, None)
    for b, g in enumerate(levels):
        end = tl.cursor + int(per_block * rate)
        chirps.append(tl.add(ch, kind="chirp", label=f"level {b}", gain_db=g, level_db=g, level_block=b))
        tl.silence(1.0)
        tl.silence(6.0, "noise_floor", level_block=b)
        last_floor = tl.cursor
        pack_order = rng.sample(pack, len(pack)) if pack else []
        cyc = {k: rng.sample(v, len(v)) for k, v in pools.items() if v}
        idx = {k: 0 for k in pools}
        misses = 0
        while tl.cursor < end - int(2.0 * rate) and weights and misses < 20:
            if tl.cursor - last_floor > 60 * rate:
                tl.silence(3.0, "noise_floor", level_block=b)
                last_floor = tl.cursor
            kind = rng.choices(list(weights), list(weights.values()))[0]
            if kind == "voice_pack":
                it = None
                while it is None and pack_order:
                    it = load_pack_item(pack_order[idx[kind] % len(pack_order)], rate)
                    idx[kind] += 1
                if it is None:
                    weights.pop(kind)
                    continue
            else:
                lst = cyc[kind]
                it = lst[idx[kind] % len(lst)]
                idx[kind] += 1
            if tl.cursor + len(it["pcm"]) > end:
                misses += 1
                continue
            add_item(tl, it, g, b)
            tl.silence(rng.uniform(0.3, 1.2))
        if tl.cursor < end:
            tl.silence((end - tl.cursor) / rate, "noise_floor", level_block=b)
    chirps.append(tl.add(ch, kind="chirp", label="end", gain_db=0.0, level_db=0.0))
    tl.silence(2.0, "noise_floor", label="end tail")
    return tl, chirps, ch


def cmd_echo(a, inp=input) -> int:
    sd = get_sd(a.dry_run)
    din, dout, out_ch, rate, rate_notes = open_devices(sd, a)
    if not speaker_gate(din, dout, a, inp, need_builtin=True):
        say("Stopped. Nothing was played or recorded.")
        return 2
    rng = random.Random(a.seed)
    notes: list[str] = []
    tl, chirps, ch = build_echo(a, rate, rng, notes)
    vol = dv.output_volume() if not a.dry_run else None
    mins = tl.total / rate / 60
    say("\n" + "=" * 72)
    say(f"  ECHO SESSION: this will PLAY SOUND through the speakers for about {mins:.0f} minutes")
    say("  (the app's voice lines at 4 loudness levels, crew audio, short sweeps, and silent gaps).")
    say("  Keep the room quiet. Don't talk, type or move the laptop. Lid open, nothing over the speakers.")
    say(f"  Speakers: {dv.scrub_name(dout['name'])}    Mic: {dv.scrub_name(din['name'])}    {rate} Hz")
    if vol is not None:
        say(f"  System volume: {vol}% (leave it there for the whole session; 60-80% is right)")
    say("=" * 72)
    if a.yes and a.dry_run:
        say("(dry run: starting without waiting for Enter)")
    elif ask("Press Enter to start, or Ctrl-C to stop. ", inp) is None:
        say("Stopped. Nothing was played or recorded.")
        return 2
    if vol is None and not a.dry_run and sys.platform != "darwin":
        r = ask("What is the Windows volume, 0-100? (Enter to skip) ", inp)
        vol = int(r) if r and r.strip().isdigit() else None
    outdir = session_dir(a.out, "echo", a.dry_run)
    write_readme(outdir, "echo")
    m = base_manifest("echo", a, sd, din, dout, rate, out_ch, rate_notes)
    m.update({"system_output_volume_pct": vol, "levels_db": sorted({s.get("level_db") for s in tl.segs
                                                                    if s.get("level_db") is not None}, reverse=True),
              "planned_frames": tl.total, "notes": notes,
              "level_note": ("each line is mastered to about -18 dBFS speech RMS (peaks under -1 dBFS), then played at "
                             "the block's level_db below that, at the system volume above")})
    write_json(outdir / "manifest.json", m)
    say(f"Recording to {tilde(outdir)}  (Ctrl-C stops and keeps what was recorded)")
    last = {"t": 0}

    def tick(pos):
        if pos - last["t"] >= rate * (30 if not a.dry_run else 600):
            last["t"] = pos
            seg = tl.at(pos) or {}
            print(f"\r  {pos / rate / 60:5.1f} / {mins:.1f} min   level {seg.get('level_db', '')} dB   ", end="",
                  flush=True)
            chk = dict(m, frames=pos, segments=[e for e in (seg_entry(s, rate, pos, i) for i, s in enumerate(tl.segs))
                                               if e])
            write_json(outdir / "manifest.json", chk)

    res = Recorder(sd, tl, rate, din, dout, out_ch, outdir, blocksize=a.blocksize).run(on_tick=tick)
    m = finalize(outdir, m, tl, res, chirps, ch)
    return report(outdir, m)


def report(outdir: Path, m: dict) -> int:
    lat = (m.get("latency") or {}).get("measured_roundtrip_s")
    say(f"\nDone: {m['status']}, {m['duration_s'] / 60:.1f} min, {len(m['segments'])} segments.")
    say(f"Round-trip latency from the chirp: {lat * 1000:.1f} ms" if lat is not None else "Latency: not measured")
    for n in m.get("notes", []):
        say(f"  note: {n}")
    say(f"Saved in {tilde(outdir)} (nothing uploaded).")
    return 0 if m["status"] == "complete" else 130


# ================================================================================================= guided
CONSENT = """\
OUTPOST LUNA x ARC: GUIDED VOICE RECORDING (about 15 minutes)

  * This records the microphone while the app's voice plays. It stays on THIS computer, in the folder shown at the end.
    Nothing is uploaded.
  * Please don't say names, addresses, school names or phone numbers.
  * A child takes part only with a parent or guardian next to them for the whole session.
  * You can stop at any time with Ctrl-C; what was recorded so far is kept and can be deleted (delete the folder).
  * The folder is shared with the Whissle Arc speech team only if you hand it over yourself. They use it only to train
    and test speech understanding (who is talking to the app, echo, barge-in), and delete it on request.
"""


def consent_gate(inp=input) -> dict | None:
    """Whose voice, adult or child (with a parent's consent), and agreement to share with the Arc team. Anything but
    the exact answers refuses: returns None and nothing is recorded."""
    say(CONSENT)
    who = (ask("Whose voice will be recorded? Type  adult  or  child : ", inp) or "").strip().lower()
    if who not in ("adult", "child"):
        say("No consent: nothing recorded.")
        return None
    parent = None
    if who == "child":
        r = (ask("A parent or guardian must be here and agree. Parent: type  I AGREE : ", inp) or "").strip().upper()
        if r != "I AGREE":
            say("No parent consent: nothing recorded.")
            return None
        parent = True
    r = (ask("Do you agree to record and to share this recording with the Arc speech team? Type  I AGREE : ", inp)
         or "").strip().upper()
    if r != "I AGREE":
        say("No consent: nothing recorded.")
        return None
    return {"agreed": True, "speaker": who, "parent_present_and_agreed": parent, "share_with_arc_team": True,
            "uploaded": False, "date": _dt.date.today().isoformat(), "text": CONSENT}


def build_guided(a, rate: int, rng: random.Random, notes: list[str]) -> tuple[Timeline, list[dict], list[dict], np.ndarray, list[dict]]:
    tl = Timeline(rate)
    ch = align.chirp(rate)
    say("Preparing the app's lines (silent) ...")
    os_items, n1 = prepare_os_lines(a, rate, n_pack_texts=8)
    notes += n1
    pack = content.pack_clips()
    pack_order = rng.sample(pack, len(pack)) if pack else []
    pi = {"k": 0}

    def app_line(long: bool = False) -> dict | None:
        """A line the app would say: Nora's pack clip or an OS-voice line; `long` = at least 3.5 s (for barge-ins)."""
        cands = []
        if os_items and (not pack_order or rng.random() < 0.5):
            cands = [x for x in os_items if not long or len(x["pcm"]) >= 3.5 * rate] or os_items
            return rng.choice(cands)
        while pack_order:
            c = pack_order[pi["k"] % len(pack_order)]
            pi["k"] += 1
            it = load_pack_item(c, rate)
            if it and (not long or len(it["pcm"]) >= 3.0 * rate or pi["k"] > len(pack_order)):
                return it
        return rng.choice(os_items) if os_items else None

    chirps = []
    tl.silence(1.0, "noise_floor", label="start")
    chirps.append(tl.add(ch, kind="chirp", label="start", gain_db=0.0))
    tl.silence(1.5)
    tl.silence(5.0, "noise_floor", label="quiet please")
    events, prompts = [], []
    events.append({"frame": 0, "text": "Starting. Stay quiet for a few seconds..."})
    budget = int(a.minutes * 60 * rate)
    for p in content.guided_plan(a.minutes * 1.5, seed=a.seed):
        if tl.cursor >= budget:
            break
        rec = {"i": len(prompts), "kind": p["kind"], "label": p["label"], "say": p["say"], "head": p["head"]}
        if p["kind"] in ("addressed", "not_addressed"):
            if p["kind"] == "addressed" and rng.random() < 0.5:
                it = app_line()
                if it:
                    s = add_item(tl, it, 0.0, 0)
                    rec["app_line"] = {"text": it.get("text"), "start_s": round(s["start"] / rate, 3)}
                    tl.silence(0.6)
            ready = tl.cursor
            tl.silence(2.5)
            now = tl.cursor
            tl.silence(5.5)
            w0, w1 = now, tl.cursor
            tl.silence(1.0)
        else:
            ready = tl.cursor
            tl.silence(2.5)
            it = app_line(long=True)
            if not it:
                continue
            s = add_item(tl, it, 0.0, 0)
            rec["app_line"] = {"text": it.get("text"), "start_s": round(s["start"] / rate, 3)}
            now = s["start"] + int(min(1.0, (s["end"] - s["start"]) / rate / 3) * rate)
            tl.silence(1.0)
            w0, w1 = now, tl.cursor
            tl.silence(1.5)
        events.append({"frame": ready, "text": f"Get ready ({p['head']}):\n\n      \"{p['say']}\"", "prompt": rec["i"],
                       "phase": "ready"})
        events.append({"frame": now, "text": f">>> NOW: {p['head']}:   \"{p['say']}\"", "prompt": rec["i"],
                       "phase": "now"})
        rec.update({"ready_frame": ready, "now_frame": now, "window_start_frame": w0, "window_end_frame": w1,
                    "ready_s": round(ready / rate, 6), "now_s": round(now / rate, 6)})
        prompts.append(rec)
        if len(prompts) % 8 == 0:
            tl.silence(4.0, "noise_floor", label="rest")
            events.append({"frame": tl.cursor - int(4.0 * rate), "text": "(short rest: stay quiet)"})
    chirps.append(tl.add(ch, kind="chirp", label="end", gain_db=0.0))
    tl.silence(1.5, "noise_floor", label="end tail")
    events.append({"frame": tl.cursor - int(1.5 * rate), "text": "Finishing ..."})
    events.sort(key=lambda e: e["frame"])
    return tl, prompts, events, ch, chirps


def cmd_guided(a, inp=input) -> int:
    consent = consent_gate(inp)
    if consent is None:
        return 2
    sd = get_sd(a.dry_run)
    din, dout, out_ch, rate, rate_notes = open_devices(sd, a)
    if not speaker_gate(din, dout, a, inp, need_builtin=False):
        say("Stopped. Nothing was recorded.")
        return 2
    rng = random.Random(a.seed)
    notes: list[str] = []
    tl, prompts, events, ch, chirps = build_guided(a, rate, rng, notes)
    mins = tl.total / rate / 60
    say("\n" + "=" * 72)
    say(f"  GUIDED SESSION, about {mins:.0f} minutes. The app's voice will play at times.")
    say("  Watch this window. Each prompt says 'Get ready', then '>>> NOW'. Three kinds:")
    say("    Say this TO THE APP               - talk to the laptop, like playing the game")
    say("    Say this to SOMEONE ELSE           - turn to a person in the room (or pretend to)")
    say("    TALK OVER THE APP NOW             - interrupt the app while it is talking")
    say("  Keep the volume where you normally play. Ctrl-C stops and keeps what was recorded.")
    say("=" * 72)
    if a.yes and a.dry_run:
        say("(dry run: starting without waiting for Enter)")
    elif ask("Press Enter to start, or Ctrl-C to stop. ", inp) is None:
        say("Stopped. Nothing was recorded.")
        return 2
    outdir = session_dir(a.out, "guided", a.dry_run)
    write_readme(outdir, "guided")
    write_json(outdir / "consent.json", consent)
    m = base_manifest("guided", a, sd, din, dout, rate, out_ch, rate_notes)
    m.update({"consent": {k: v for k, v in consent.items() if k != "text"}, "prompts": prompts, "notes": notes,
              "labels": {"addressed": "said to the app", "not_addressed": "said to someone else in the room",
                         "barge_in": "said over the app's playback"},
              "planned_frames": tl.total,
              "prompt_timing": ("ready_s: the prompt appears; now_s: '>>> NOW' appears; window_*: when the speech is "
                                "expected (barge_in: from NOW to 1 s after the app line ends); shown_*_s: when the "
                                "screen actually showed it (stream clock)")})
    write_json(outdir / "manifest.json", m)
    ev = {"i": 0}
    clear = sys.stdout.isatty() and not a.dry_run

    def tick(pos):
        while ev["i"] < len(events) and pos >= events[ev["i"]]["frame"]:
            e = events[ev["i"]]
            ev["i"] += 1
            if "prompt" in e:
                prompts[e["prompt"]][f"shown_{e['phase']}_s"] = round(pos / rate, 3)
            if clear and e.get("phase") == "ready":
                print("\033[2J\033[H", end="")
            if not a.dry_run or ev["i"] < 6:
                say(("\n" if e.get("phase") == "ready" else "") + e["text"])

    res = Recorder(sd, tl, rate, din, dout, out_ch, outdir, blocksize=a.blocksize).run(on_tick=tick)
    m = finalize(outdir, m, tl, res, chirps, ch)
    say(f"{len(m['prompts'])} prompts recorded.")
    return report(outdir, m)


# ================================================================================================= render-lines
def cmd_render_lines(a, inp=input) -> int:
    engines, notes = osvoices.load_engines(a.dry_run, a.engines)
    if not engines:
        say("No OS speech engine here. " + "; ".join(notes))
        return 1
    voices, roles, n2 = osvoices.app_voices(engines)
    notes += n2
    if a.voice:
        voices = [v for v in voices if a.voice.lower() in (v["id"] + " " + v.get("name", "")).lower()]
    if a.max_voices:
        voices = voices[: a.max_voices]
    strip = osvoices.ov.strip_markup if osvoices.ov else (lambda s: s)
    lines = [{"i": i, "kind": "live", "text": t} for i, t in enumerate(content.LIVE_LINES)]
    pt = content.pack_line_texts(None if a.all_lines else a.pack_lines)
    lines += [{"i": len(content.LIVE_LINES) + j, "kind": "pack_text", "text": strip(t)} for j, t in enumerate(pt)]
    if a.max_lines:
        lines = lines[: a.max_lines]
    outdir = session_dir(a.out, "render-lines", a.dry_run)
    say(f"Rendering {len(lines)} lines x {len(voices)} voices (silent, to files) -> {tilde(outdir)}")
    m = {"kit": "outpost-luna/tools/arc_collect", "kit_version": KIT_VERSION, "session": "render-lines",
         "date": _dt.date.today().isoformat(), "dry_run": bool(a.dry_run), "machine": dv.machine_info(a.dry_run),
         "engines": [e.name for e in engines], "roles": roles,
         "voices": [{**voice_meta(v), "gender": v.get("gender"), "in_picker": v.get("in_picker"),
                     "dir": osvoices.safe_name(v["id"])} for v in voices],
         "lines": lines, "renders": [], "failures": [], "notes": notes, "status": "rendering",
         "format": "<voice dir>/<line i>.wav: mono PCM16 at the engine's rate; <voice dir>/16k/<line i>.wav: 16 kHz",
         "uploaded": False}
    import soundfile as sf
    try:
        for vi, v in enumerate(voices):
            d = outdir / osvoices.safe_name(v["id"])
            (d / "16k").mkdir(parents=True, exist_ok=True)
            eng = osvoices.engine_for(engines, v)
            for ln in lines:
                try:
                    pcm, sr = eng.render(ln["text"], v["id"])
                except Exception as e:  # noqa: BLE001
                    m["failures"].append({"voice": v["id"], "line": ln["i"], "error": str(e)[:160]})
                    continue
                f = f"{ln['i']:04d}.wav"
                sf.write(str(d / f), np.clip(pcm, -1, 1), sr, subtype="PCM_16")
                sf.write(str(d / "16k" / f), np.clip(align.resample(pcm, sr, 16000), -1, 1), 16000, subtype="PCM_16")
                m["renders"].append({"voice": v["id"], "line": ln["i"], "file": f"{d.name}/{f}",
                                     "file_16k": f"{d.name}/16k/{f}", "sr": sr, "dur_s": round(len(pcm) / sr, 3)})
            say(f"  [{vi + 1}/{len(voices)}] {v.get('voice_label') or v.get('name')} ({v.get('engine')}, "
                f"{v.get('quality')}) done")
            write_json(outdir / "manifest.json", m)
        m["status"] = "complete"
    except KeyboardInterrupt:
        m["status"] = "stopped_early"
        say("\nStopped: keeping what was rendered.")
    finally:
        write_json(outdir / "manifest.json", m)
    say(f"{len(m['renders'])} files, {len(m['failures'])} failures. Saved in {tilde(outdir)}")
    return 0 if m["status"] == "complete" else 130


# ================================================================================================= check
def cmd_check(a, inp=input) -> int:
    sd = get_sd(a.dry_run, silent_mic=getattr(a, "fake_denied", False))
    mi = dv.machine_info(a.dry_run)
    say(f"Machine: {mi.get('model')}  {mi['os']} {mi['os_version']} ({mi['arch']})")
    say("\nAudio devices:")
    for d in dv.list_devices(sd):
        flags = ("  [default mic]" if d["default_in"] else "") + ("  [default speakers]" if d["default_out"] else "") + \
                ("  [Bluetooth?]" if d["bluetooth_guess"] else "")
        say(f"  {d['index']:>3}  in {d['in']}  out {d['out']}  {d['rate']:>6} Hz  {dv.scrub_name(d['name'])}{flags}")
    ok = True
    try:
        din, dout, out_ch, rate, notes = open_devices(sd, a)
        say(f"\nWill use: mic '{dv.scrub_name(din['name'])}', speakers '{dv.scrub_name(dout['name'])}', {rate} Hz")
        for n in notes:
            say(f"  note: {n}")
        if dv.is_bluetooth(dout["name"]) or not dv.looks_builtin_speaker(dout["name"]):
            say("  !! For the echo session the speakers must be the laptop's BUILT-IN speakers (not Bluetooth / "
                "headphones / a monitor).")
        if dv.is_bluetooth(din["name"]):
            say("  !! The mic is Bluetooth: use the built-in mic.")
    except SystemExit as e:
        say(f"\n!! {e}")
        ok, rate = False, 48000
    if a.no_mic:
        say("\nMic permission: not tested (--no-mic).")
    else:
        say("\nMic permission: one short read (0.25 s, discarded, nothing played) ...")
        if sys.platform == "darwin" and not a.dry_run:
            say("  (the first time, macOS asks '<your terminal> would like to access the microphone': click Allow / OK)")
        r = dv.mic_probe(sd, a.mic)
        if r["ok"]:
            say(f"  OK: the mic is delivering sound ({r.get('rms_dbfs')} dBFS room noise).")
        else:
            ok = False
            say(f"  !! The mic gave {'pure digital silence' if r.get('all_zero') else 'an error: ' + r.get('error', '')}"
                " -> permission is probably missing.")
            say("  " + dv.permission_help())
    root = Path(a.out).expanduser() if a.out else dv.default_root()
    bps = dv.bytes_per_second(rate)
    free = dv.free_bytes(root)
    say(f"\nDisk ({tilde(root)}): echo {a.minutes:.0f} min ~ {dv.human(bps * a.minutes * 60)}, guided 15 min ~ "
        f"{dv.human(bps * 15 * 60)}; render-lines ~ 0.1-0.3 MB per line per voice. Free: {dv.human(free)}")
    if free is not None and free < bps * (a.minutes + 15) * 60 * 1.2:
        ok = False
        say("  !! Not enough free space for both sessions.")
    pack = content.pack_clips()
    say(f"\nContent: {len(pack)} voice-pack clips; {len(content.crew_files(a.media_dir))} crew audio files; "
        f"{len(content.video_files(a.media_dir))} NASA videos (sound needs ffmpeg: "
        f"{'found' if __import__('shutil').which('ffmpeg') else 'not installed'})")
    if not a.no_voices:
        engines, notes = osvoices.load_engines(a.dry_run, a.engines)
        voices, roles, n2 = osvoices.app_voices(engines) if engines else ([], {}, [])
        by = {}
        for v in voices:
            by[v["engine"]] = by.get(v["engine"], 0) + 1
        say(f"OS voices the app can use: {len(voices)} ({', '.join(f'{k} {n}' for k, n in by.items()) or 'none'}); "
            f"roles: {', '.join(f'{r}={vid}' for r, vid in roles.items()) or '-'}")
        for n in notes + n2:
            say(f"  note: {n}")
    say("\n" + ("All good." if ok else "Fix the items marked !! before recording."))
    return 0 if ok else 1


# ================================================================================================= main
def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="arc_collect", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(s, minutes):
        s.add_argument("--dry-run", action="store_true", help="no real audio at all: an in-memory loopback + fake voices")
        s.add_argument("--out", help="the folder to save into (default: ~/Outpost Luna recordings)")
        s.add_argument("--mic", help="input device: index or part of its name (default: the system default)")
        s.add_argument("--speakers", help="output device: index or part of its name (default: the system default)")
        s.add_argument("--rate", type=int, default=48000, help="preferred sample rate (default 48000; falls back)")
        s.add_argument("--minutes", type=float, default=minutes)
        s.add_argument("--engines", default="auto", help="say | winrt | sapi | winrt,sapi (default: auto)")
        s.add_argument("--media-dir", help="a folder with crew clips (mp3/wav) and/or NASA videos (mp4)")
        s.add_argument("--seed", type=int, default=1)
        s.add_argument("--blocksize", type=int, default=0)
        s.add_argument("--force-speakers", action="store_true", help="skip the built-in-speakers question")
        s.add_argument("--yes", action="store_true", help="dry run only: start without waiting for Enter")
        s.add_argument("--echo-voices", type=int, default=6, help="how many OS voices speak the live lines")
        return s

    e = common(sub.add_parser("echo", help="~25 min unattended speaker->mic echo set"), 25.0)
    e.add_argument("--levels", help="comma-separated playback levels in dB (default 0,-6,-12,-18)")
    common(sub.add_parser("guided", help="~15 min guided set with a person (consent first)"), 15.0)
    r = common(sub.add_parser("render-lines", help="silent: the app's lines in every OS voice the app can use"), 0)
    r.add_argument("--pack-lines", type=int, default=60, help="how many voice-pack lines to add (default 60)")
    r.add_argument("--all-lines", action="store_true", help="every voice-pack line (889) instead of a sample")
    r.add_argument("--voice", help="only voices whose id or name contains this")
    r.add_argument("--max-voices", type=int)
    r.add_argument("--max-lines", type=int)
    c = common(sub.add_parser("check", help="devices, mic permission, disk"), 25.0)
    c.add_argument("--no-mic", action="store_true", help="skip the mic permission read")
    c.add_argument("--no-voices", action="store_true", help="skip listing the OS voices")
    c.add_argument("--fake-denied", action="store_true", help=argparse.SUPPRESS)
    return p


def main(argv=None, inp=input) -> int:
    a = parser().parse_args(argv)
    if a.yes and not a.dry_run:
        raise SystemExit("--yes only works with --dry-run: a real session always asks before it plays or records.")
    fn = {"echo": cmd_echo, "guided": cmd_guided, "render-lines": cmd_render_lines, "check": cmd_check}[a.cmd]
    try:
        return fn(a, inp)
    except KeyboardInterrupt:
        say("\nStopped before recording started. Nothing was saved.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
