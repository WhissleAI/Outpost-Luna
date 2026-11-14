"""Reference only: Deepgram Flux (cloud) on the same audio, through the backend's own Flux URL (keyterms included).
Streams each clip at real-time pace, 8 at a time. Skips without DEEPGRAM_API_KEY.

cd backend && uv run python tests/fixtures/ear_eval/eval_flux.py
"""
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

import soundfile as sf
import websockets

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, ".")
from score import score, summarize  # noqa: E402

from app.config import settings  # noqa: E402
from app.listen import flux_url  # noqa: E402


async def run_clip(path, speech_end_s):
    x = sf.read(path, dtype="int16")[0].tobytes()
    async with websockets.connect(flux_url(), additional_headers={"Authorization": f"Token {settings.deepgram_api_key}"}) as ws:
        t0 = time.perf_counter()
        res = {"hyp": "", "end_ms": None}

        async def rx():
            async for raw in ws:
                d = json.loads(raw)
                if d.get("type") == "TurnInfo" and d.get("event") == "EndOfTurn":
                    if res["end_ms"] is None:
                        res["end_ms"] = round((time.perf_counter() - t0 - speech_end_s) * 1000)
                    res["hyp"] = (res["hyp"] + " " + (d.get("transcript") or "")).strip()

        task = asyncio.create_task(rx())
        for i in range(0, len(x), 2560):
            await ws.send(x[i:i + 2560])
            await asyncio.sleep(0.08)
        await asyncio.sleep(1.0)
        await ws.send(json.dumps({"type": "CloseStream"}))
        try:
            await asyncio.wait_for(task, 3)
        except Exception:  # noqa: BLE001
            task.cancel()
        return res


async def main():
    if not settings.deepgram_api_key:
        sys.exit("no DEEPGRAM_API_KEY")
    items = {it["id"]: it for it in json.load(open(HERE / "set.json"))["items"]}
    man = json.load(open(HERE / "manifest.json"))["clips"]
    sem = asyncio.Semaphore(8)

    async def one(m):
        async with sem:
            r = await run_clip(HERE / "audio" / f"{m['clip']}.wav", m["speech_end_s"])
            return {**m, **score(items[m["id"]], r["hyp"]), "hyp": r["hyp"], "ref": items[m["id"]]["text"], "end_ms": r["end_ms"]}

    rows = await asyncio.gather(*[one(m) for m in man])
    lats = [r["end_ms"] for r in rows if r["end_ms"] is not None]
    summ = {"all": summarize(rows), "clean": summarize([r for r in rows if not r["noisy"]]),
            "noisy": summarize([r for r in rows if r["noisy"]]),
            "endpoint_ms_p50": statistics.median(lats) if lats else None,
            "endpoint_ms_p90": sorted(lats)[int(0.9 * (len(lats) - 1))] if lats else None,
            "turn_end_missing": sum(r["end_ms"] is None for r in rows)}
    print(json.dumps(summ))
    json.dump({"model": "flux-general-en + keyterms", "summary": summ, "rows": rows}, open(HERE / "results_flux.json", "w"), indent=1)


asyncio.run(main())
