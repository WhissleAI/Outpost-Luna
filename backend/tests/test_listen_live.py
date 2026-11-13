"""/ws/listen against the real Deepgram Flux, fed a recorded question at real-time pace.

Starts the backend on port 8111. Skipped when DEEPGRAM_API_KEY is not configured.
"""
import asyncio
import json
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
import websockets

from app.config import settings

PCM = Path(__file__).parent / "fixtures/bullseye_16k.s16le"  # `say "show me the giant bullseye"`, 16 kHz s16le
PORT = 8111
FRAME = 2560  # 80 ms of PCM16 at 16 kHz

pytestmark = pytest.mark.skipif(not settings.deepgram_api_key, reason="no DEEPGRAM_API_KEY")


@pytest.fixture(scope="module")
def server():
    p = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(PORT)],
                         cwd=Path(__file__).parent.parent, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(100):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", PORT)) == 0:
                break
        time.sleep(0.1)
    yield f"ws://127.0.0.1:{PORT}/ws/listen"
    p.terminate()
    p.wait(5)


async def run(url):
    got = []
    async with websockets.connect(url) as ws:
        assert json.loads(await ws.recv())["t"] == "ready"

        async def feed():
            pcm = PCM.read_bytes() + bytes(16000 * 2 * 2)  # + 2 s of silence so Flux can end the turn
            for i in range(0, len(pcm), FRAME):
                await ws.send(pcm[i:i + FRAME])
                await asyncio.sleep(0.08)
            await ws.send(json.dumps({"t": "stop"}))

        task = asyncio.create_task(feed())
        try:
            async for raw in ws:
                m = json.loads(raw)
                got.append(m)
                if m["t"] == "turn" and m["state"] == "end":
                    break
        finally:
            task.cancel()
    return got


def test_flux_turn_for_a_spoken_question(server):
    got = asyncio.run(asyncio.wait_for(run(server), 20))
    assert not [m for m in got if m["t"] == "error"], got
    states = [m["state"] for m in got if m["t"] == "turn"]
    assert "start" in states and states[-1] == "end"
    final = [m for m in got if m["t"] == "words" and m["final"]][-1]["text"].lower()
    assert "giant bull" in final, final  # "bullseye" / "bull's eye"
