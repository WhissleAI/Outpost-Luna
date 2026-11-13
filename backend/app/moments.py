"""The crew-audio index (data/index/clips.json) and the Moon Moments cut from it (docs/REVAMP.md §3.3).

A Moment is 8-25 s of crew audio, cut on Arc utterance boundaries (never mid-utterance). Only an utterance that is
itself longer than 25 s is subdivided: at a sentence end (word ending in . ? !) if any, else at its longest pause.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .gazetteer import norm

MIN_S, MAX_S = 8.0, 25.0
SENT_END = re.compile(r"[.?!]['\"]?$")
NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


def load_glossary(path: Path) -> dict:
    """{form (normalized): (term, explain)} for matching words in transcripts."""
    if not path.exists():
        return {}
    terms = json.loads(path.read_text())["terms"]
    return {norm(f): (k, v["explain"]) for k, v in terms.items() for f in v.get("forms", [k])}


def load_facts(path: Path) -> dict:
    return json.loads(path.read_text())["places"] if path.exists() else {}


def fact_numbers(facts: dict, place_ids) -> list[float]:
    out: list[float] = []
    for pid in place_ids:
        f = facts.get(pid) or {}
        if f.get("diameter_km") and not f.get("estimated"):  # crew-proposed sizes are guesses, never said
            out.append(float(f["diameter_km"]))
        for x in f.get("facts", []):
            out += [float(n) for n in x.get("numbers", [])]
    return out


def number_ok(v: float, allowed: list[float], tol: float = 0.10) -> bool:
    return any(abs(v - a) <= tol * abs(a) + 1e-9 for a in allowed)


class MomentIndex:
    def __init__(self, path: Path, glossary: dict | None = None, facts: dict | None = None):
        self.path = path
        self.meta_path = path.parent / "audio_meta.json"
        self.glossary = glossary if glossary is not None else load_glossary(path.parent.parent / "glossary.json")
        self.facts = facts if facts is not None else load_facts(path.parent.parent / "facts.json")
        self.glossary_terms = sorted({v[0] for v in self.glossary.values()})
        self._mtime = None
        self.clips: list[dict] = []
        self.moments: list[dict] = []
        self.refresh()

    # ---- loading -------------------------------------------------------------------------------------------------
    def refresh(self) -> None:
        """Reload when `make index` rewrites the file, so a rebuild needs no restart."""
        m = self.path.stat().st_mtime if self.path.exists() else None
        mm = self.meta_path.stat().st_mtime if self.meta_path.exists() else None
        if (m, mm) != self._mtime:
            self.clips = json.loads(self.path.read_text())["clips"] if m else []
            meta = json.loads(self.meta_path.read_text()) if mm else {}
            self.moments = [mo for c in self.clips for mo in cut_clip(c, meta.get(c["id"]), self.glossary, self.facts)]
            self._mtime = (m, mm)

    # ---- moments -------------------------------------------------------------------------------------------------
    def get(self, moment_id: str) -> dict | None:
        return next((m for m in self.moments if m["id"] == moment_id), None)

    def for_place(self, place_id: str, limit: int = 5) -> list[dict]:
        scored = [(score(m, place_id), m) for m in self.moments if place_id in m["places"]]
        scored.sort(key=lambda x: -x[0])
        return [m for _, m in scored[:limit]]

    def best_moment(self, place_id: str) -> dict | None:
        r = self.for_place(place_id, 1)
        return r[0] if r else None

    def best_in_clip(self, clip_id: str) -> dict | None:
        ms = [m for m in self.moments if m["clip_id"] == clip_id]
        return max(ms, key=lambda m: (MIN_S <= m["t1"] - m["t0"] <= MAX_S, m["awe"], -m["t0"])) if ms else None

    # ---- legacy (v1 clip-level) ----------------------------------------------------------------------------------
    def best_for(self, place_id: str) -> dict | None:
        m = self.best_moment(place_id)
        return {"id": m["clip_id"], "t": m["t0"], "mentions": len(m["places"])} if m else None

    def places_mentioned(self) -> set[str]:
        return {t["f"] for c in self.clips for t in c["tags"] if t.get("f")}


def score(m: dict, place_id: str) -> float:
    """Ranking (§3.3): mentions the place, 8-25 s, awe, has a verified claim, speaker known."""
    d = m["t1"] - m["t0"]
    s = 1.0 if place_id in m["places"] else 0.0
    s += 1.0 if MIN_S <= d <= MAX_S else -min(1.0, abs(d - (MIN_S if d < MIN_S else MAX_S)) / 10)
    s += m.get("awe", 0.0)
    s += 0.5 if any(c["status"] == "verified" for c in m.get("claims", [])) else 0.0
    s += 0.2 if m.get("speaker") not in (None, "", "crew") else 0.0
    s += 0.1 * m.get("_mentions", 0)
    return round(s, 3)


def _segments(clip: dict) -> list[tuple[int, int]]:
    """Utterance word ranges; any single utterance longer than MAX_S is split at sentence ends only."""
    words, dur = clip["words"], float(clip.get("dur") or 0)
    utts = [tuple(u) for u in clip.get("utterances") or []] or [(0, len(words))]

    def t(i: int) -> float:
        return float(words[i][0]) if i < len(words) else max(dur, float(words[-1][0]) if words else 0)

    def split(a: int, b: int) -> list[tuple[int, int]]:
        if t(b) - t(a) <= MAX_S or b - a < 4:
            return [(a, b)]
        # Break after a sentence end if there is one, else at the longest pause; keep both sides >= MIN_S if we can.
        cands = [i for i in range(a + 1, b) if t(i) - t(a) >= MIN_S and t(b) - t(i) >= MIN_S] or list(range(a + 1, b))
        k = max(cands, key=lambda i: (bool(SENT_END.search(str(words[i - 1][1]))), t(i) - t(i - 1)))
        return split(a, k) + split(k, b)

    out: list[tuple[int, int]] = []
    for a, b in utts:
        if b > a:
            out += split(a, b)
    return out


def cut_clip(clip: dict, meta: dict | None, glossary: dict, facts: dict) -> list[dict]:
    words = clip.get("words") or []
    if not words:
        return []
    dur = float(clip.get("dur") or 0)

    def t(i: int) -> float:
        return float(words[i][0]) if i < len(words) else max(dur, float(words[-1][0]) + 0.6)

    # Greedy merge of consecutive segments into 8-25 s groups.
    groups: list[list[int]] = []
    cur: list[int] | None = None
    for a, b in _segments(clip):
        if cur is None:
            cur = [a, b]
        elif t(b) - t(cur[0]) <= MAX_S or t(cur[1]) - t(cur[0]) < MIN_S and t(b) - t(cur[0]) <= MAX_S * 1.6:
            cur[1] = b
        else:
            groups.append(cur)
            cur = [a, b]
    if cur:
        groups.append(cur)
    # A short tail joins the previous group when that stays near the limit.
    if len(groups) > 1 and t(groups[-1][1]) - t(groups[-1][0]) < MIN_S and t(groups[-1][1]) - t(groups[-2][0]) <= MAX_S * 1.2:
        groups[-2][1] = groups.pop()[1]

    utt_meta = (meta or {}).get("utterances") or []
    peaks = (meta or {}).get("awe_peaks") or []
    out = []
    for k, (a, b) in enumerate(groups):
        t0, t1 = round(t(a), 2), round(min(t(b), dur) if dur else t(b), 2)
        ws = words[a:b]
        tags = [x for x in clip.get("tags") or [] if a <= x.get("i", -1) < b]
        places: list[str] = []
        for x in tags:
            if x.get("f") and x["f"] not in places:
                places.append(x["f"])
        speaker = _speaker(ws, utt_meta, t0, t1)
        awe = max([float(u.get("awe") or 0) for u in utt_meta if u.get("t0", 0) < t1 and u.get("t1", 0) > t0]
                  + [float(p.get("score") or 0) for p in peaks if t0 <= p.get("t", -1) <= t1] + [0.0])
        jargon, seen = [], set()
        for i, w in enumerate(ws):
            for form in (norm(str(w[1])), norm(f"{w[1]} {ws[i + 1][1]}") if i + 1 < len(ws) else ""):
                if form and form in glossary and glossary[form][0] not in seen:
                    seen.add(glossary[form][0])
                    jargon.append({"t": float(w[0]), "word": glossary[form][0], "explain": glossary[form][1]})
        allowed = fact_numbers(facts, places)
        claims, seen_c = [], set()
        for x in tags:
            if (x.get("type"), norm(str(x.get("label", "")))) in seen_c:
                continue
            seen_c.add((x.get("type"), norm(str(x.get("label", "")))))
            if x.get("type") == "NUMBER" and NUM.search(str(x.get("label", ""))):
                v = float(NUM.search(x["label"]).group(0).replace(",", ""))
                ok = number_ok(v, allowed)
                claims.append({"kind": "number", "text": x["label"], "status": "verified" if ok else "impression",
                               "source": _src(facts, places) if ok else "crew"})
            elif x.get("type") == "COLOR":
                claims.append({"kind": "color", "text": x["label"], "status": "impression", "source": "crew"})
        out.append({
            "id": f"{clip['id']}-{k:02d}", "clip_id": clip["id"], "t0": t0, "t1": t1, "speaker": speaker,
            "places": places, "text": " ".join(str(w[1]) for w in ws), "jargon": jargon, "awe": round(awe, 3),
            "claims": claims, "_mentions": sum(1 for x in tags if x.get("f")), "words": [a, b],
        })
    return out


def _speaker(ws: list, utt_meta: list, t0: float, t1: float) -> str:
    spk = [str(w[2]) for w in ws if len(w) > 2 and w[2]]
    if spk:
        return max(set(spk), key=spk.count)
    over = [u for u in utt_meta if u.get("speaker") and u.get("t0", 0) < t1 and u.get("t1", 0) > t0]
    if over:
        best = max(over, key=lambda u: min(u["t1"], t1) - max(u["t0"], t0))
        return str(best["speaker"])
    return "crew"


def _src(facts: dict, places: list[str]) -> str:
    for p in places:
        for x in (facts.get(p) or {}).get("facts", []):
            return x["source"]
    return "fact sheet"


def public(m: dict | None) -> dict | None:
    """The moment as the API returns it (contract in docs/CONTRACT.md)."""
    if m is None:
        return None
    return {k: m[k] for k in ("id", "clip_id", "t0", "t1", "speaker", "places", "text", "jargon", "awe", "claims")}
