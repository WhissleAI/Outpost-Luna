"""Summary feedback: can a small local model rewrite the template? (docs/SPEECH_LEARNING.md §4, the LLM spike)

Runs synthetic kid summaries through the product's own pieces: speech.grade_summary (lexical coverage, as shipped),
feedback.template (v1), feedback.prompt (the rewrite request) and feedback.guard (what a rewrite must pass before it is
shown). The rewrite comes from a llama.cpp server (OpenAI chat endpoint) on loopback.

  backend/.venv/bin/python backend/tools/summary_llm_eval.py --url http://127.0.0.1:8486 --model NAME --out file.json
  backend/.venv/bin/python backend/tools/summary_llm_eval.py --dry      # coverage + template only, no server

Nothing is stored but the JSON you ask for. The summaries are synthetic (no kid's speech).
"""
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.academy import feedback, speech  # noqa: E402

RUBRICS = {
    "moon:hammer": {"lesson": "summary_hammer", "acc": {
        "type": "summary", "need": 2,
        "example": "On the Moon, David Scott dropped a hammer and a feather. They landed together, because there is no air.",
        "points": [
            {"id": "drop", "label": "David Scott dropped a hammer and a feather",
             "ask": "What did the astronaut drop?",
             "say": ["dropped a hammer and a feather", "hammer and feather", "drop hammer feather", "let go of a hammer and a feather"],
             "terms": ["David Scott"]},
            {"id": "same", "label": "they landed at the same time",
             "ask": "What happened when they hit the ground?",
             "say": ["landed at the same time", "same time", "hit the ground together", "fell together", "landed together", "both at once"]},
            {"id": "air", "label": "there is no air on the Moon to slow the feather",
             "ask": "Why didn't the feather float down slowly?",
             "say": ["no air", "there is no air", "nothing slows it down", "no air to slow the feather", "no atmosphere"]},
            {"id": "apollo", "label": "it was on Apollo 15",
             "ask": "Which mission was it?",
             "say": ["apollo 15", "apollo fifteen"], "terms": ["Apollo 15"]},
        ]}},
    "moon:ice": {"lesson": "read_ice", "acc": {
        "type": "summary", "need": 2,
        "example": "Some craters at the poles never get sunlight. They are so cold that ice stays frozen. LCROSS found water there.",
        "points": [
            {"id": "dark", "label": "the Sun never reaches some crater floors",
             "ask": "What is special about those crater floors?",
             "say": ["sun never reaches", "never get sunlight", "always dark", "always in shadow", "no sunlight", "never see the sun"]},
            {"id": "cold", "label": "they are so cold that ice stays frozen",
             "ask": "Why does the ice stay there?",
             "say": ["very cold", "so cold", "super cold", "ice stays frozen", "coldest", "freezing"]},
            {"id": "lcross", "label": "LCROSS hit Cabeus crater in 2009 and found water",
             "ask": "How do we know there is water there?",
             "say": ["lcross", "cabeus", "found water", "crashed into the crater", "rocket hit the crater"],
             "terms": ["LCROSS", "Cabeus"]},
            {"id": "use", "label": "ice could give astronauts water, air and rocket fuel",
             "ask": "How could astronauts use the ice?",
             "say": ["rocket fuel", "water to drink", "air to breathe", "drinking water", "make fuel", "water and air"]},
        ]}},
    "arch:rings": {"lesson": "archaeology:dating", "acc": {
        "type": "summary", "need": 2,
        "example": "Each year a tree adds a ring, wide in wet years and narrow in dry ones. Matching the pattern to the master chronology gives the year the beam was cut.",
        "points": [
            {"id": "rings", "label": "trees grow wide rings in wet years and narrow rings in dry years",
             "ask": "What do the rings look like from year to year?",
             "say": ["wide and narrow rings", "wide rings", "narrow rings", "ring every year", "one ring a year", "wet years", "dry years"]},
            {"id": "match", "label": "the ring pattern is matched to a master chronology",
             "ask": "What do archaeologists compare the beam's rings to?",
             "say": ["master chronology", "match the pattern", "compare the rings", "line up the rings", "matching the pattern"]},
            {"id": "year", "label": "the match gives the year the beam was cut",
             "ask": "What does the match tell you?",
             "say": ["cutting year", "year the tree was cut", "when it was cut", "year it was cut down", "cut down in"]},
        ]}},
}

CASES = [
    # hammer / feather video (kids 7-12, ear-style lowercase)
    ("moon:hammer", "the astronaut dropped a hammer and a feather and they landed at the same time"),
    ("moon:hammer", "so um david scott on apollo 15 dropped a hammer and a feather and they hit the ground together because there is no air"),
    ("moon:hammer", "he let go of a hammer and a feather and they fell together"),
    ("moon:hammer", "there was a hammer and a feather and the feather didnt float because there is no air on the moon"),
    ("moon:hammer", "they landed at the same time cause theres no air"),
    ("moon:hammer", "i liked the video it was cool"),
    ("moon:hammer", "the hammer and feather hit the ground together because the moon has no air and also the feather was made of gold"),
    ("moon:hammer", "apollo 15 dropped a hammer and a feather and they landed together this is so damn cool"),
    ("moon:hammer", "dropped hammer feather same time"),
    ("moon:hammer", "the guy on the moon dropped a hammer and a feather and they both landed at once i think it was apollo fifteen"),
    ("moon:hammer", "my dog ate my homework and then we went to the park"),
    # ice article
    ("moon:ice", "some craters never get sunlight so they are super cold and the ice stays frozen"),
    ("moon:ice", "lcross crashed into cabeus crater and found water"),
    ("moon:ice", "the ice could give astronauts water to drink and air to breathe and rocket fuel because the craters are so cold"),
    ("moon:ice", "theres ice in the dark craters at the poles where the sun never reaches and lcross found water in 2009"),
    ("moon:ice", "its really cold"),
    ("moon:ice", "the craters are always dark and very cold and astronauts can make fuel from the ice and there are aliens living there"),
    ("moon:ice", "ice ice baby"),
    ("moon:ice", "the sun never reaches the bottom so it is freezing and the ice could be drinking water"),
    ("moon:ice", "a rocket hit the crater and they found water and it was super cold"),
    # archaeology (grades 9-12)
    ("arch:rings", "every year a tree grows a ring and wide rings mean wet years and narrow rings mean dry years"),
    ("arch:rings", "they match the pattern of the beam to the master chronology and that gives the cutting year"),
    ("arch:rings", "you compare the rings to a master chronology"),
    ("arch:rings", "trees grow one ring a year wide in wet years narrow in dry years and if you line up the rings with the master chronology you get the year it was cut down"),
    ("arch:rings", "dendrochronology is dating with tree rings"),
    ("arch:rings", "the rings tell you when it was cut which was like 1275 i think"),
    ("arch:rings", "wide rings and narrow rings and the year the tree was cut"),
    ("arch:rings", "honestly this lesson is kind of boring but the rings are wide and narrow"),
    ("arch:rings", "the beam was from a dinosaur tree and they match the pattern to find the cutting year"),
    ("arch:rings", "matching the pattern tells archaeologists the year it was cut down"),
]


SYSTEM_V2 = ("You give feedback to a child about their spoken summary. Talk to the child as \"you\". Use ONLY the "
             "facts given. Write exactly 2 short, warm sentences: first say what they covered, then name the one "
             "missing point. Never grade, never say wrong, no new facts, no numbers that are not given, no questions.")
SHOT_USER = ('Student said: "the feather and hammer fell together"\nCovered: they landed at the same time\n'
             'Missing: there is no air on the Moon to slow the feather\nAt most 14 words per sentence, 36 words in all.\n'
             'Feedback:')
SHOT_REPLY = "Nice work: you said they landed at the same time. One more key point: there is no air on the Moon to slow the feather."


def build_prompt(variant: str, acc, cov, miss, text, lv) -> list[dict]:
    msgs = feedback.prompt(acc, cov, miss, text, lv)
    if variant == "v2":   # the suggested fix: second person, 2 sentences, one worked example
        msgs = [{"role": "system", "content": SYSTEM_V2}, {"role": "user", "content": SHOT_USER},
                {"role": "assistant", "content": SHOT_REPLY}, msgs[1]]
    return msgs


def coverage(key: str, text: str) -> tuple[list[str], list[str], bool]:
    acc = RUBRICS[key]["acc"]
    ok, ex = speech.grade_summary(acc, {}, text)
    return ex["got"], ex["missing"], ok


def chat(url: str, messages: list[dict]) -> tuple[str | None, float, dict]:
    import httpx
    t0 = time.perf_counter()
    try:
        r = httpx.post(url.rstrip("/") + "/v1/chat/completions",
                       json={"messages": messages, "temperature": 0.2, "max_tokens": 90, "stream": False}, timeout=60)
        r.raise_for_status()
        d = r.json()
        dt = time.perf_counter() - t0
        return (d["choices"][0]["message"]["content"] or "").strip(), dt, d.get("timings") or {}
    except Exception as e:   # noqa: BLE001
        return None, time.perf_counter() - t0, {"error": str(e)}


def server_rss_mb(port: int) -> float | None:
    try:
        pid = subprocess.run(["lsof", "-ti", f"tcp:{port}", "-sTCP:LISTEN"], capture_output=True, text=True).stdout.split()[0]
        kb = int(subprocess.run(["ps", "-o", "rss=", "-p", pid], capture_output=True, text=True).stdout.strip())
        return round(kb / 1024, 1)
    except Exception:   # noqa: BLE001
        return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8486")
    ap.add_argument("--model", default="model")
    ap.add_argument("--out", default="")
    ap.add_argument("--prompt", default="v1", choices=["v1", "v2"], help="v1 = feedback.prompt as it is now (since the evaluation it is the v2 wording); v2 = the v2 wording built here")
    ap.add_argument("--dry", action="store_true", help="coverage + template only")
    a = ap.parse_args()
    rows = []
    if not a.dry:   # warmup
        acc = RUBRICS["moon:hammer"]["acc"]
        chat(a.url, build_prompt(a.prompt, acc, ["drop"], ["same"], "a hammer and a feather", feedback.level_for(None)))
    rss = None if a.dry else server_rss_mb(int(a.url.rsplit(":", 1)[-1].split("/")[0]))
    for n, (key, text) in enumerate(CASES):
        rb = RUBRICS[key]
        acc, lid = rb["acc"], rb["lesson"]
        lv = feedback.level_for(lid)
        cov, miss, passed = coverage(key, text)
        tmpl = feedback.template(acc, cov, miss, lv, key=lid)
        row = {"n": n, "rubric": key, "lesson": lid, "text": text, "covered": cov, "missing": miss, "passed": passed,
               "template": " ".join(tmpl)}
        if not a.dry:
            out, dt, tim = chat(a.url, build_prompt(a.prompt, acc, cov, miss, text, lv))
            ok, why = feedback.guard(out or "", acc, cov, miss, text, lv, None)
            row |= {"rewrite": out, "latency_s": round(dt, 3), "tok_s": tim.get("predicted_per_second"),
                    "tokens": tim.get("predicted_n"), "guard_ok": ok, "guard_why": why}
        rows.append(row)
        print(json.dumps(row)[:400], flush=True)
    summ = {"model": a.model, "prompt": a.prompt, "cases": len(rows), "rss_mb": rss}
    if not a.dry:
        lat = sorted(r["latency_s"] for r in rows)
        summ |= {"p50_s": statistics.median(lat), "p95_s": lat[min(len(lat) - 1, int(round(0.95 * (len(lat) - 1))))],
                 "tok_s_mean": round(statistics.mean([r["tok_s"] for r in rows if r.get("tok_s")] or [0]), 1),
                 "guard_pass": sum(r["guard_ok"] for r in rows) / len(rows),
                 "guard_fail_reasons": {w: sum(1 for r in rows if not r["guard_ok"] and r["guard_why"].split(":")[0] == w)
                                        for w in sorted({r["guard_why"].split(":")[0] for r in rows if not r["guard_ok"]})}}
    print(json.dumps(summ))
    if a.out:
        Path(a.out).write_text(json.dumps({"summary": summ, "rows": rows}, indent=1))


if __name__ == "__main__":
    main()
