"""Regression for the packaged-app loop, with real audio: the app's own TTS (GET /api/tts, Steer) streamed back into
/ws/listen (the Arc ear) while the session knows it is speaking -> no reply. Needs a running stack:

    HANDSFREE_LIVE=http://127.0.0.1:8330 uv run pytest tests/test_handsfree_live.py -s
"""
import asyncio
import io
import json
import os
import time
import urllib.parse
import wave

import pytest

BASE = os.environ.get("HANDSFREE_LIVE")
pytestmark = pytest.mark.skipif(not BASE, reason="set HANDSFREE_LIVE=http://host:port (a running backend + model server)")

OUR_LINES = [   # (voice, text): what the app says in the cabin during a storm, incl. the old fallback line
    ("capcom", "Storm is here! Into the shelter, and shields up."),
    ("capcom", "Houston can hear us. Comm window open."),
    ("guide", "I don't know that one yet. Try: show me the giant bullseye, or where did Apollo 11 land?"),
    ("guide", "I don't know that one yet."),
    ("capcom", "Copy, commander. Setting the radiation shields to 40 percent of our power."),
    ("story", "Mm-mm."),
]


def pcm16k(wav_bytes: bytes):
    import numpy as np
    w = wave.open(io.BytesIO(wav_bytes))
    sr, x = w.getframerate(), np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32)
    n = int(len(x) * 16000 / sr)
    y = np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.int16)
    return np.concatenate([np.zeros(3200, np.int16), y, np.zeros(16000, np.int16)]), n / 16000


async def run_live():
    import httpx
    import websockets
    sid = f"live-{int(time.time())}"
    ws_base = BASE.replace("http", "ws")
    out = {"echo": [], "control": None}
    async with httpx.AsyncClient(base_url=BASE, timeout=60) as h, websockets.connect(ws_base + "/ws/session") as ss:
        await ss.send(json.dumps({"t": "hello", "session": sid, "mode": "mission"}))
        st = (await h.post("/api/mission/start", json={"site": "shackleton_rim", "seed": 7, "roles": []})).json()
        await ss.send(json.dumps({"t": "hello", "session": sid, "mode": "mission", "mission_id": st["id"]}))
        await ss.send(json.dumps({"t": "ui", "event": "screen", "screen": "cabin"}))

        async def drain(sec):
            got, end = [], time.monotonic() + sec
            while time.monotonic() < end:
                try:
                    m = json.loads(await asyncio.wait_for(ss.recv(), max(0.05, end - time.monotonic())))
                except asyncio.TimeoutError:
                    break
                if m.get("t") not in ("ready", "floor", "hud", "alert"):
                    got.append(m)
            return got

        async def feed(voice, text, report=True):
            q = urllib.parse.urlencode({"text": text, "voice": voice})
            pcm, dur = pcm16k((await h.get(f"/api/tts?{q}")).content)
            async with websockets.connect(ws_base + f"/ws/listen?session={sid}") as ls:
                if report:
                    await ss.send(json.dumps({"t": "playback", "kind": "guide", "state": "start", "id": f"p{time.time()}",
                                              "text": text}))
                t0 = time.monotonic()
                for i in range(0, len(pcm), 1280):
                    await ls.send(pcm[i:i + 1280].tobytes())
                    await asyncio.sleep(0.08)
                    if report and time.monotonic() - t0 > dur + 0.2:
                        await ss.send(json.dumps({"t": "playback", "kind": "guide", "state": "end"}))
                        report = False
                if report:
                    await ss.send(json.dumps({"t": "playback", "kind": "guide", "state": "end"}))
                await asyncio.sleep(1.0)
                await ls.send(json.dumps({"t": "stop"}))
            return await drain(4.0)

        await drain(1.0)
        for voice, text in OUR_LINES:
            ds = await feed(voice, text)
            heard = [d.get("text") for d in ds if d["t"] == "heard"]
            replies = [d for d in ds if d["t"] in ("say", "nav", "answer", "ask_confirm")]
            out["echo"].append({"line": text, "heard": heard, "routes": [(d.get("outcome"), d.get("reason"))
                                                                            for d in ds if d["t"] == "heard"],
                                "replies": [d.get("text") or d.get("intent") for d in replies]})
        await asyncio.sleep(2.0)
        # positive control: a kid's order (another voice, not something we said) is heard and answered
        ds = await feed("story", "Send the rover for ice.", report=False)
        out["control"] = {"heard": [d.get("text") for d in ds if d["t"] == "heard"],
                          "replies": [d.get("text") for d in ds if d["t"] == "say"]}
    return out


def test_own_tts_fed_into_the_ear_gets_no_reply():
    out = asyncio.run(run_live())
    print(json.dumps(out, indent=1))
    for e in out["echo"]:
        assert e["replies"] == [], e
    assert out["control"]["replies"], out["control"]
