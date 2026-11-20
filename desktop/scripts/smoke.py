"""Offline smoke test of a running Outpost Luna backend: voice ask -> answer -> the OS voice, a Flight School lesson,
and a mission shift. Uses only the bundled backend deps (httpx, websockets).

It WRITES to the app it talks to (a mission, a check ride, the ask history), so it only ever runs against a TEST app:
one launched headless on its own temp data folder (OUTPOST_USER_DATA) and its own ports, never the owner's installed
app, its data folder or its ports (47310 / 47210). The usual way:

    make smoke-installed          # /Applications/Outpost Luna.app, headless, temp data + free ports, smoke, quit
    make release-check DMG=...    # the same smoke as one of the release gates (docs/RELEASING.md)

Run by hand only against such a test app:
    resources/python/bin/python3 desktop/scripts/smoke.py --engine <test data folder>/engine.json
(PYTHONPATH=desktop/resources/site/backend). With OUTPOST_USER_DATA set, --engine defaults to its engine.json.
Exit 1 on the first failure; exit 2 when pointed at the owner's own app (refused, nothing sent).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

import httpx
import websockets

FRAME = 2560  # 80 ms of PCM16 at 16 kHz
ROOT = Path(__file__).resolve().parents[2]


OWNER_PORTS = {47310, 47311, 47312, 47210, 47211, 47212}   # the installed app's defaults (release_check.py too)


def owner_data_dir() -> Path:
    """The owner's real data folder (Electron's userData for "Outpost Luna"): never smoke-tested."""
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming")) / "Outpost Luna"
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/Outpost Luna"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "Outpost Luna"


def default_engine() -> str | None:
    """A test app's engine.json: $OUTPOST_USER_DATA/engine.json, or None (then --engine or --base is required)."""
    ud = os.environ.get("OUTPOST_USER_DATA")
    return str(Path(ud) / "engine.json") if ud else None


def refuse_reason(engine: str | None, base: str | None, owner: Path | None = None) -> str:
    """Why this run would touch the owner's own app ("" = fine): its data folder, or one of its ports."""
    owner = owner or owner_data_dir()
    if engine:
        try:
            e = Path(engine).expanduser().resolve()
            if e == owner.resolve() or owner.resolve() in e.parents:
                return f"{engine} is in your own app's data folder ({owner}); smoke tests a temp-data test app only"
        except OSError:
            pass
    if base:
        from urllib.parse import urlparse
        try:
            port = urlparse(base).port
        except ValueError:
            port = None
        if port in OWNER_PORTS:
            return f"{base} is your own app's port; smoke tests a test app on its own ports only"
    if not engine and not base:
        return "no test app: pass --engine <test data>/engine.json (or set OUTPOST_USER_DATA), or run `make smoke-installed`"
    return ""


def ok(cond, what):
    print(("PASS " if cond else "FAIL ") + what, flush=True)
    if not cond:
        sys.exit(1)


async def voice_turn(base: str, pcm: bytes, headers: dict) -> tuple[str, float, list]:
    url = base.replace("http", "ws", 1) + "/ws/listen"
    got = []
    async with websockets.connect(url, max_size=None, additional_headers=headers) as ws:
        audio = pcm + bytes(16000 * 2 * 2)       # + 2 s of silence: the ear ends the turn
        t_end_speech = None

        async def feed():
            nonlocal t_end_speech
            for i in range(0, len(audio), FRAME):
                await ws.send(audio[i:i + FRAME])
                if i + FRAME >= len(pcm) and t_end_speech is None:
                    t_end_speech = time.perf_counter()
                await asyncio.sleep(0.08)        # real-time pace
            await ws.send(json.dumps({"t": "stop"}))

        task = asyncio.create_task(feed())
        try:
            async for raw in ws:
                if isinstance(raw, bytes):
                    continue
                m = json.loads(raw)
                got.append(m)
                if m.get("t") == "error":
                    break
                if m.get("t") == "turn" and m.get("state") == "end":
                    break
        finally:
            task.cancel()
    finals = [m for m in got if m.get("t") == "words" and m.get("final")]
    lat = time.perf_counter() - t_end_speech if t_end_speech else -1
    return (finals[-1]["text"] if finals else ""), lat, got


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=None, help="default: the backend in engine.json")
    ap.add_argument("--token", default=os.environ.get("LUNA_TOKEN"), help="default: the token in engine.json")
    ap.add_argument("--engine", default=default_engine(), help="the TEST app's discovery file (default: $OUTPOST_USER_DATA/engine.json)")
    ap.add_argument("--pcm", default=str(ROOT / "backend/tests/fixtures/bullseye_16k.s16le"))
    a = ap.parse_args()
    why = refuse_reason(a.engine, a.base)
    if why:
        print(f"REFUSED {why}", flush=True)
        sys.exit(2)
    eng = {}
    try:
        eng = json.loads(Path(a.engine).read_text(encoding="utf-8")) if a.engine else {}
    except (OSError, ValueError):
        print(f"  -    no engine.json at {a.engine}: using --base / --token")
    a.base = a.base or eng.get("backend")
    why = refuse_reason(None, a.base) if a.base else "engine.json names no backend; pass --base"
    if why:
        print(f"REFUSED {why}", flush=True)
        sys.exit(2)
    headers = {"X-Luna-Token": a.token or eng.get("token") or ""}
    print(f"  -    backend {a.base}, token {'set' if headers['X-Luna-Token'] else 'none'}")
    async with httpx.AsyncClient(base_url=a.base, timeout=60, headers=headers) as c:
        h = (await c.get("/api/health")).json()
        ms = h.get("model_server", {}).get("models", {})
        ok(h.get("ok") and all(ms.get(k, {}).get("loaded") for k in ("arc_tagger", "arc_meta", "tts", "embedder")),
           f"health: models {sorted(k for k, v in ms.items() if v.get('loaded') or v.get('available'))}")

        tts = ms.get("tts", {})
        ok(tts.get("engine") in ("say", "winrt", "sapi") and tts.get("voices", 0) > 0,
           f"OS voice: engine {tts.get('engine')}, default {tts.get('voice')} ({tts.get('voice_name')}), "
           f"{tts.get('voices')} voices, timing {tts.get('timing')}, warm-up {tts.get('warm_ms')} ms, roles {tts.get('roles')}")
        vs = (await c.get("/api/voices")).json()
        ok(isinstance(vs, list) and vs and vs[0]["id"] == tts.get("voice"),
           f"Settings voices: {[(v['name'], v['desc']) for v in vs][:6]}")

        # 1. voice ask -> answer -> the OS voice
        text, lat, msgs = await voice_turn(a.base, Path(a.pcm).read_bytes(), headers)
        ear = next((m for m in msgs if m.get("t") == "ear"), {})
        ok(ear.get("ear") == "arc", f"ear is the local Arc ear ({ear})")
        ok("bull" in text.lower(), f"heard {text!r}; turn end {lat * 1000:.0f} ms after speech end")
        t = time.perf_counter()
        ans = (await c.post("/api/ask", json={"text": text})).json()
        ask_ms = (time.perf_counter() - t) * 1000
        say = ans.get("say") or ans.get("text") or ans.get("answer") or json.dumps(ans)[:200]
        ok(bool(say), f"answer in {ask_ms:.0f} ms ({ans.get('type') or ans.get('kind') or ''}): {str(say)[:120]!r}")
        t = time.perf_counter()
        r = await c.post("/api/tts", json={"text": str(say)[:300], "voice": "guide"})
        tts_ms = (time.perf_counter() - t) * 1000
        ok(r.status_code == 200 and r.headers.get("content-type", "").startswith("audio/wav")
           and r.headers.get("x-tts-engine") == "os",
           f"OS voice TTS: {r.status_code} {r.headers.get('content-type')} {len(r.content)} B in {tts_ms:.0f} ms "
           f"(engine {r.headers.get('x-tts-engine')}, voice {r.headers.get('x-tts-voice')})")
        # word timings that fit the audio: one per display word, in order, ending inside the clip
        import io
        import wave
        with wave.open(io.BytesIO(r.content)) as w:
            dur_ms = w.getnframes() / w.getframerate() * 1000
        times = [tuple(int(x) for x in p.split("-")) for p in (r.headers.get("x-tts-words") or "").split(",") if p]
        n_words = len(str(say)[:300].split())
        ok(len(times) == n_words and all(a <= b for a, b in times) and all(times[i][1] <= times[i + 1][0] + 1
           for i in range(len(times) - 1)) and times and times[-1][1] <= dur_ms + 1,
           f"word timings: {len(times)}/{n_words} words, last ends {times[-1][1] if times else '-'} ms of {dur_ms:.0f} ms")

        # 1b. the recorded voice pack (docs/VOICE_PACK.md): a scripted line plays the clip, word timings included
        vp = ms.get("voice_pack", {})
        if vp.get("clips"):
            line = "Each pin on the Moon is a lesson."
            r = await c.post("/api/tts", json={"text": line, "voice": "capcom"})
            times = [tuple(int(x) for x in p.split("-")) for p in (r.headers.get("x-tts-words") or "").split(",") if p]
            ok(r.status_code == 200 and r.headers.get("x-tts-engine") == "pack" and len(times) == len(line.split()),
               f"voice pack: {vp.get('clips')} clips ({vp.get('voice')}); scripted line -> engine "
               f"{r.headers.get('x-tts-engine')}, {len(times)} word timings")
        else:
            print(f"  -    voice pack: none in this build ({vp})")

        # 2. Flight School: the course, one lesson step graded (keyword or paraphrase via the local embedder)
        # [courses] the packaged app must see the Moon as a course and list the downloadable packs (a 0.4.x build
        # looked for the asset catalog in a dev-only path: no packs, and the Moon skipped as "voice_pack: no such file")
        cs = (await c.get("/api/courses")).json()
        ok(any(x.get("id") == "moon" for x in cs.get("courses", [])) and not cs.get("problems"),
           f"courses: the Moon is registered, no problems ({cs.get('problems') or 'none'})")
        pk = (await c.get("/api/courses/packs")).json()
        ok(len(pk.get("packs", [])) >= 1, f"courses: the catalog lists course packs ({[p.get('id') for p in pk.get('packs', [])]})")
        course = (await c.get("/api/academy/course")).json()
        lessons = course.get("lessons") or [le for tr in course.get("tracks", []) for le in tr.get("lessons", [])]
        ok(len(lessons) > 0, f"Flight School course: {len(lessons)} lessons")
        les = next(le for le in lessons if not le.get("ride"))
        step0 = (les.get("steps") or [{}])[0]
        guess = step0.get("say") or step0.get("expect") or step0.get("answer") or "shields"
        r = await c.post("/api/academy/attempt", json={"lesson_id": les["id"], "step": 0,
                                                       "input": {"text": str(guess)[:300]}})
        ok(r.status_code == 200, f"lesson {les['id']!r} step 0 graded: {r.text[:160]}")
        r = await c.post("/api/academy/ride")
        ok(r.status_code == 200, f"check ride started: {r.text[:120]}")

        # 3. Mission cabin: start a shift at a site, give an order, advance, debrief
        sites = (await c.get("/api/mission/sites")).json()
        sid = (sites[0] if isinstance(sites, list) else (sites.get("sites") or [{}])[0]).get("id")
        m = (await c.post("/api/mission/start", json={"site": sid, "seed": 7})).json()
        mid = m.get("id") or m.get("mission_id") or (m.get("state") or {}).get("id")
        ok(bool(mid), f"mission started at {sid}: {mid}")
        r = await c.post(f"/api/mission/{mid}/command",
                         json={"command": {"type": "allocate", "to": "shields", "amount": {"kind": "delta", "value": 5}}})
        ok(r.status_code == 200, f"order 'shields +5': {r.text[:120]}")
        r = await c.post(f"/api/mission/{mid}/advance", json={"shifts": 1})
        ok(r.status_code == 200, "shift advanced")
        r = await c.get(f"/api/mission/{mid}/debrief")
        ok(r.status_code == 200, f"debrief: {r.text[:120]}")

        # 4. Camera gestures: the vision runtime and models are in the bundle and served from the app's own origin
        #    (never a CDN). The camera itself stays off until Settings turns it on, so nothing here opens it.
        man = await c.get("/vision/manifest.json")
        ok(man.status_code == 200, f"gesture bundle manifest: {man.text[:100]}")
        for f in man.json().get("files", []):
            r = await c.head(f"/vision/{f['file']}")
            size = int(r.headers.get("content-length") or 0)
            ok(r.status_code == 200 and size == f["bytes"] and size > 0, f"gesture asset {f['file']}: {size} B ({r.headers.get('content-type')})")
        # resources/python/bin/python3 (macOS) or resources\python\python.exe (Windows) → resources/app
        res = Path(sys.executable).resolve().parents[1 if sys.platform == "win32" else 2]
        app_dir = res / "app" / "frontend" / "vision"
        if app_dir.exists():
            ok(all((app_dir / f["file"]).is_file() for f in man.json()["files"]), f"gesture models on disk in the bundle: {app_dir}")
    print("ALL PASS")


if __name__ == "__main__":
    asyncio.run(main())
