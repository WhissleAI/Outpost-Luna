"""Load and check the course (backend/data/academy/course.json)."""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).resolve().parents[2] / "data"
COURSE = DATA / "academy" / "course.json"
ACCEPT_TYPES = ("intent", "command", "tap", "keywords", "choice",
                "vocab_match", "vocab_say", "vocab_fill", "vocab_listen")   # vocab: app/academy/vocab.py
NUM = re.compile(r"-?\d[\d,]*(?:\.\d+)?")


@lru_cache(maxsize=1)
def course() -> dict:
    return json.loads(COURSE.read_text())


def lesson(lesson_id: str) -> dict | None:
    return next((l for l in course()["lessons"] if l["id"] == lesson_id), None)


def public() -> dict:
    """The course for the client: everything except the answer keys (choices keep their labels)."""
    def step(s: dict) -> dict:
        a = s["accept"]
        acc = {"type": a["type"]}
        if a["type"] == "choice":
            acc["options"] = [{"id": o["id"], "label": o["label"], **({"place": o["place"]} if o.get("place") else {})}
                              for o in a["options"]]
        if a["type"] in ("tap", "intent"):
            acc["place"] = a["place"]
        if a["type"].startswith("vocab_"):           # Space words: options without the answer key
            from .vocab import public_accept
            acc = public_accept(a)
        return {k: v for k, v in s.items() if k not in ("accept",)} | {"accept": acc}
    c = course()
    return {"title": c["title"], "pass_badge": c["pass_badge"],
            "lessons": [{k: v for k, v in l.items() if k != "steps"} | {"steps": [step(s) for s in l["steps"]]}
                        for l in c["lessons"]]}


def longest_dark_h(site_id: str) -> int:
    """Longest run of hours with the Sun below the site's effective horizon (JPL Horizons ephemeris)."""
    e = json.loads((DATA / "mission" / f"ephemeris_{site_id}.json").read_text())
    best = cur = 0
    for elev in e["sun_elev_deg"]:
        cur = 0 if elev > e["horizon_deg"] else cur + 1
        best = max(best, cur)
    return best


def check() -> list[str]:
    """Problems with the course: missing fields, unsourced facts, numbers not found in the cited data."""
    probs: list[str] = []
    c = course()
    data_text = {p: p.read_text() for p in DATA.rglob("*.json") if "academy" not in p.parts}
    every = "\n".join(data_text.values())
    for l in c["lessons"]:
        lid = l.get("id", "?")
        for k in ("id", "title", "brief", "steps", "badge", "facts"):
            if not l.get(k):
                probs.append(f"{lid}: missing {k}")
        if len(re.findall(r"[.!?](?:\s|$)", l.get("brief", ""))) > 3:
            probs.append(f"{lid}: brief longer than 3 sentences")
        for f in l.get("facts", []):
            src = f.get("source") or {}
            if not (src.get("title") and str(src.get("url", "")).startswith("http")):
                probs.append(f"{lid}: fact without a {{title,url}} source: {f.get('text')!r}")
            url = str(src.get("url") or "")
            host = re.sub(r"^https?://([^/]+).*$", r"\1", url)
            if url and url not in every and host not in every:
                probs.append(f"{lid}: source url not in repo data: {src.get('url')}")
            files = [DATA / p for p in f.get("from", [])]
            if not files or not all(p.exists() for p in files):
                probs.append(f"{lid}: fact has no data file: {f.get('text')!r}")
                continue
            text = "\n".join(p.read_text() for p in files)
            calc = f.get("calc")
            calc_vals = {str(longest_dark_h(calc["site"]))} if calc and calc.get("kind") == "longest_dark_h" else set()
            for n in NUM.findall(f["text"]):
                plain = n.replace(",", "")
                if n in text or plain in text or plain in calc_vals:
                    continue
                if calc_vals and any(float(plain) < float(v) / 24 for v in calc_vals):  # "more than 6 days"
                    continue
                probs.append(f"{lid}: number {n} not in {f.get('from')}: {f['text']!r}")
        for i, s in enumerate(l.get("steps", [])):
            for k in ("prompt", "accept", "hint", "success", "fail"):
                if not s.get(k):
                    probs.append(f"{lid}[{i}]: missing {k}")
            a = s.get("accept") or {}
            if a.get("type") not in ACCEPT_TYPES:
                probs.append(f"{lid}[{i}]: bad accept type {a.get('type')!r}")
            if a.get("type") == "choice" and a.get("answer") not in {o["id"] for o in a.get("options", [])}:
                probs.append(f"{lid}[{i}]: answer not among options")
            if str(a.get("type", "")).startswith("vocab_"):
                from .vocab import check_step
                probs += [f"{lid}[{i}]: {p}" for p in check_step(a)]
    return probs
