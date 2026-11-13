"""Evaluate the local brain against the running model server (MODEL_SERVER_URL; needs EMBED=on there).

  uv run python tools/eval_brain.py [--verbose]

1. tests/eval/kid_questions.json (80): top-1 card+attribute accuracy, ask rate, "I don't know" rate (brain.answer, with
   the gazetteer link as the place hint, as the Director does).
2. tests/eval/commands_heldout.json (40 the rules miss): rules vs rules+embedder.
3. Latency per query (embed + search).
"""
from __future__ import annotations

import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import knowledge  # noqa: E402
from app.config import settings  # noqa: E402
from app.gazetteer import Gazetteer, norm  # noqa: E402
from app.mission import nlu  # noqa: E402
from app.moments import load_facts  # noqa: E402

EVAL = Path(__file__).resolve().parent.parent / "tests/eval"
V = "--verbose" in sys.argv


def _ok_cmd(cmd: dict, exp: dict) -> bool:
    if cmd["type"] != exp["type"]:
        return False
    if exp["type"] == "allocate":
        a = cmd["amount"]
        sign = 1 if a["kind"] in ("all", "half") or (a.get("value") or 0) > 0 else -1
        return cmd["to"] == exp["to"] and sign == exp["sign"]
    return all(cmd.get(k) == v for k, v in exp.items() if k != "type")


async def main() -> None:
    gaz = Gazetteer(settings.data_dir / "places.json")
    brain = knowledge.get(gaz, load_facts(settings.data_dir / "facts.json"))
    t = time.perf_counter()
    assert await brain.warm(), "embedder unreachable"
    print(f"bank: {len(brain.bank)} card questions over {len(brain.cards)} cards, warm {time.perf_counter() - t:.2f}s")

    qs = json.loads((EVAL / "kid_questions.json").read_text())["questions"]
    n = {"correct": 0, "wrong": 0, "ask": 0, "ask_has_right": 0, "unknown": 0, "unknown_right": 0, "offtopic": 0,
         "offtopic_answered": 0}
    lat = []
    for item in qs:
        q, ok = item["q"], set(item["ok"])
        p = gaz.match_text(norm(q))
        t = time.perf_counter()
        r = await brain.answer(q, session="eval", place_hint=p.id if p else None)
        lat.append((time.perf_counter() - t) * 1000)
        label = f"{r['card']}|{r['attr']}"
        if "unknown" in ok:
            n["offtopic"] += 1
            n["offtopic_answered"] += r["status"] == "answer"
        if r["status"] == "answer":
            hit = label in ok
            n["correct" if hit else "wrong"] += 1
        elif r["status"] == "ask":
            n["ask"] += 1
            n["ask_has_right"] += any(f"{o['card']}|{o['attr']}" in ok for o in r["options"])
        else:
            n["unknown"] += 1
            n["unknown_right"] += "unknown" in ok
        if V or (r["status"] == "answer" and label not in ok):
            print(f"  [{r['status']:7}] {q!r} -> {label} ({r['score']}) {'' if label in ok else 'EXPECTED ' + str(sorted(ok))[:90]}")
    N = len(qs)
    print(f"\nKid questions (n={N}): top-1 correct {n['correct']}/{N} = {n['correct'] / N:.0%}; wrong answers {n['wrong']}; "
          f"ask {n['ask']} ({n['ask'] / N:.0%}, right option offered in {n['ask_has_right']}); "
          f"I-don't-know {n['unknown']} ({n['unknown'] / N:.0%}, of which off-topic {n['unknown_right']}/{n['offtopic']}); "
          f"off-topic answered anyway {n['offtopic_answered']}")
    in_scope = N - n["offtopic"]
    print(f"In-scope (n={in_scope}): answered correctly {n['correct'] - 0}/{in_scope} = {n['correct'] / in_scope:.0%}; "
          f"correct incl. ask-with-right-option {(n['correct'] + n['ask_has_right']) / in_scope:.0%}")
    em = sorted(brain.embed_ms)
    print(f"Latency per question, all (rules answer most without embedding): median {statistics.median(lat):.1f} ms; "
          f"embedder path only (n={len(em)}, embed HTTP + search): median {statistics.median(em):.1f} ms, "
          f"p95 {em[int(0.95 * len(em)) - 1]:.1f} ms")

    cs = json.loads((EVAL / "commands_heldout.json").read_text())["commands"]
    rules_ok = emb_ok = emb_wrong = 0
    clat = []
    for c in cs:
        pr = nlu.parse(c["text"])
        rules_ok += any(_ok_cmd(x, c["expect"]) for x in pr["commands"])
        t = time.perf_counter()
        out = await nlu.understand(c["text"])
        clat.append((time.perf_counter() - t) * 1000)
        good = any(_ok_cmd(x, c["expect"]) for x in out["commands"])
        emb_ok += good
        emb_wrong += bool(out["commands"]) and not good
        if V or (out["commands"] and not good):
            print(f"  {c['text']!r} -> {out['commands']} ({out.get('confidence')}, near {out.get('nearest')!r})"
                  f"{'' if good else '  EXPECTED ' + json.dumps(c['expect'])}")
    print(f"\nHeld-out commands the rules miss (n={len(cs)}): rules {rules_ok}/{len(cs)}; rules+embedder {emb_ok}/{len(cs)} = "
          f"{emb_ok / len(cs):.0%}; wrong commands fired {emb_wrong}; nothing fired {len(cs) - emb_ok - emb_wrong}")
    print(f"Latency per command fallback: median {statistics.median(clat):.1f} ms")


if __name__ == "__main__":
    asyncio.run(main())
