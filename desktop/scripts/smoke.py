"""Offline smoke test of a running Outpost Luna backend (the desktop app's, or any): voice ask -> answer -> the OS voice,
a Flight School lesson, and a mission shift. Uses only the bundled backend deps (httpx, websockets).

    resources/python/bin/python3 desktop/scripts/smoke.py --base http://127.0.0.1:47310 [--pcm backend/tests/fixtures/bullseye_16k.s16le]
(PYTHONPATH=desktop/resources/site/backend). Exit 1 on the first failure.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

import httpx
import websockets

FRAME = 2560  # 80 ms of PCM16 at 16 kHz
ROOT = Path(__file__).resolve().parents[2]


def ok(cond, what):
    print(("PASS " if cond else "FAIL ") + what, flush=True)
    if not cond:
        sys.exit(1)


async def voice_turn(base: str, pcm: bytes) -> tuple[str, float, list]:
    url = base.replace("http", "ws", 1) + "/ws/listen"
    got = []
    async with websockets.connect(url, max_size=None) as ws:
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
    ap.add_argument("--base", default="http://127.0.0.1:47310")
    ap.add_argument("--pcm", default=str(ROOT / "backend/tests/fixtures/bullseye_16k.s16le"))
    a = ap.parse_args()
    async with httpx.AsyncClient(base_url=a.base, timeout=60) as c:
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
        text, lat, msgs = await voice_turn(a.base, Path(a.pcm).read_bytes())
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

        # 2. Flight School: the course, one lesson step graded (keyword or paraphrase via the local embedder)
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
