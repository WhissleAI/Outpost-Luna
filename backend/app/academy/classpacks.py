"""Class lessons: teacher-written lesson packs (docs/CURRICULUM.md).

A pack is one JSON file a teacher writes in Settings → For grown-ups → Class lessons (or imports from another computer).
Packs live in the per-user data folder, next to the auto-save: `CLASS_DIR`, else `<cache_dir or data_dir>/class/`,
one `<pack id>.json` each. They are compiled into ordinary course lessons (`track: "class"`), so a Class lesson plays
with the same lesson card, voice, hints, patches and grading as a NASA lesson. NASA lessons and facts are never
replaced: a pack can only add lessons, its titles may not reuse a NASA title, and every fact it adds carries its own
source link (shown as "Class facts", never as "NASA facts").

The loader never raises: a file that is not JSON, too big, or fails the checks is skipped and listed in `problems()`
with a plain message, and the app keeps running with every other pack.
"""
from __future__ import annotations

import json
import math
import os
import re
import threading
import time
from pathlib import Path

FORMAT = "outpost-luna-class-pack"
VERSION = 1
KINDS = ("say", "place", "choice", "predict")
SLUG = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,22}[a-z0-9])?$")   # 1-24 chars: a-z, 0-9, inner hyphens
MAX_BYTES = 256_000
MAX_LESSONS = 20
MAX_STEPS = 8
MAX_FACTS = 5
# docs/COPY.md §3 budgets (words / characters)
TITLE_WORDS, TITLE_CHARS = 6, 24
BRIEF_WORDS, BRIEF_SENTENCES = 20, 2
PROMPT_WORDS, PROMPT_CHARS = 20, 90
SUCCESS_WORDS, FAIL_WORDS, HINT_WORDS, FAIL_HINT_WORDS = 8, 6, 10, 20
LABEL_WORDS, PATCH_WORDS, PACK_TITLE_CHARS, FACT_WORDS = 6, 2, 32, 30
REVEAL_WORDS = 20
DEFAULT = {"success": "Roger. That's it.", "fail": "Not quite."}
DEFAULT_HINT = {"say": "Listen to the question again.", "place": "Look for the glow.",
                "choice": "Read each answer again.", "predict": "Make your best guess."}
STOP = {"a", "an", "the", "of", "to", "in", "on", "at", "and", "or", "is", "it", "its", "for", "by", "with", "be",
        "are", "was", "this", "that", "from", "as", "about", "into", "than", "then", "so", "not", "no", "yes"}
EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿⬀-⯿⌀-⏿️‍⃣]")
LETTERS = "abcd"

_LOCK = threading.Lock()
_STATE: dict = {"packs": None, "problems": [], "preview": None}
DIR: Path | None = None   # tests point this elsewhere


def class_dir() -> Path:
    """Where packs are stored: CLASS_DIR, else the per-user data folder (the desktop app's cache_dir, like the
    auto-save), else data_dir in a dev checkout (gitignored)."""
    if DIR:
        return DIR
    env = os.environ.get("CLASS_DIR")
    if env:
        return Path(env)
    from ..config import settings
    return (settings.cache_dir or settings.data_dir) / "class"


# ---------------------------------------------------------------------------------------------------------------------
# checks

def _words(s) -> int:
    return len(str(s or "").split())


def _sentences(s: str) -> int:
    return len(re.findall(r"[.!?](?:\s|$)", s.strip() + " ")) or 1


def key_words(label: str) -> set[str]:
    """The words a spoken answer can match an option by (no small words)."""
    return {w for w in re.findall(r"[a-z0-9]+", str(label).lower()) if w not in STOP and len(w) > 1}


def _err(out: list, at: str, msg: str) -> None:
    out.append({"at": at, "msg": msg})


def _text(errs: list, at: str, v, *, name: str, words: int, chars: int | None = None, need: bool = True) -> None:
    s = v if isinstance(v, str) else ""
    if v is not None and not isinstance(v, str):
        _err(errs, at, f"{name} must be text.")
        return
    if not s.strip():
        if need:
            _err(errs, at, f"Add {name}.")
        return
    if EMOJI.search(s):
        _err(errs, at, f"No emoji in {name}.")
    if _words(s) > words:
        _err(errs, at, f"{name.capitalize()} is {_words(s)} words. Keep it to {words}.")
    if chars and len(s) > chars:
        _err(errs, at, f"{name.capitalize()} is {len(s)} characters. Keep it to {chars}.")


def _source(errs: list, at: str, src) -> None:
    if not isinstance(src, dict) or not str(src.get("title") or "").strip():
        _err(errs, at, "Every fact needs a source: a title and a link.")
        return
    if not re.match(r"^https://[^\s/]+\.[^\s]+$", str(src.get("url") or "")):
        _err(errs, at, "The source link must start with https://")


def _place_ok(pid) -> bool:
    if not isinstance(pid, str) or not pid:
        return False
    return pid in place_ids()


def places() -> list[dict]:
    """The places a Class lesson may use (the editor's list): named Moon features and the mission sites. Hardware is
    left out (its markers are off on Flight School screens)."""
    try:
        from .grade import gaz, _sites
        out = [{"id": p.id, "name": p.name.split(" (")[0]} for p in gaz().places.values() if p.kind != "artifact"]
        have = {p["id"] for p in out}
        out += [{"id": s["id"], "name": s["name"]} for s in _sites().values() if s["id"] not in have]
        return sorted(out, key=lambda p: p["name"].lower())
    except Exception:   # noqa: BLE001
        return []


def place_ids() -> set[str]:
    if "place_ids" not in _STATE:
        _STATE["place_ids"] = {p["id"] for p in places()}
    return _STATE["place_ids"]


def validate(pack, *, nasa_titles: set[str] | None = None) -> tuple[list[dict], list[dict]]:
    """Check one pack → (errors, warnings), each [{at, msg}]. `at` is a path into the pack ("lessons[0].steps[1].prompt")
    so the editor can mark the field. Errors block saving and loading; warnings are advice (docs/COPY.md style)."""
    errs: list[dict] = []
    warns: list[dict] = []
    if not isinstance(pack, dict):
        return [{"at": "", "msg": "This file is not a lesson pack."}], []
    if pack.get("format") != FORMAT:
        _err(errs, "format", f"This file is not an Outpost Luna lesson pack (format should be {FORMAT!r}).")
    if pack.get("version") != VERSION:
        _err(errs, "version", f"Unknown pack version {pack.get('version')!r}. This app reads version {VERSION}.")
    if not (isinstance(pack.get("id"), str) and SLUG.match(pack["id"])):
        _err(errs, "id", "The pack id must be 1 to 24 letters, numbers or hyphens, lower case.")
    _text(errs, "title", pack.get("title"), name="a pack title", words=6, chars=PACK_TITLE_CHARS)
    lessons = pack.get("lessons")
    if not isinstance(lessons, list) or not lessons:
        _err(errs, "lessons", "Add at least one lesson.")
        return errs, warns
    if len(lessons) > MAX_LESSONS:
        _err(errs, "lessons", f"A pack holds up to {MAX_LESSONS} lessons.")
    nasa = {t.lower() for t in (nasa_titles if nasa_titles is not None else _nasa_titles())}
    ids, titles = set(), set()
    for li, L in enumerate(lessons[:MAX_LESSONS]):
        at = f"lessons[{li}]"
        if not isinstance(L, dict):
            _err(errs, at, "This lesson is empty.")
            continue
        lid = L.get("id")
        if not (isinstance(lid, str) and SLUG.match(lid)):
            _err(errs, f"{at}.id", "The lesson id must be 1 to 24 letters, numbers or hyphens, lower case.")
        elif lid in ids:
            _err(errs, f"{at}.id", f"Two lessons share the id {lid!r}.")
        ids.add(lid)
        _text(errs, f"{at}.title", L.get("title"), name="a title", words=TITLE_WORDS, chars=TITLE_CHARS)
        t = str(L.get("title") or "").strip().lower()
        if t and t in nasa:
            _err(errs, f"{at}.title", "A NASA lesson already has this title. Pick another (voice opens lessons by title).")
        elif t and t in titles:
            _err(errs, f"{at}.title", "Two lessons share this title.")
        titles.add(t)
        _text(errs, f"{at}.brief", L.get("brief"), name="a brief", words=BRIEF_WORDS)
        if isinstance(L.get("brief"), str) and _sentences(L["brief"]) > BRIEF_SENTENCES:
            _err(errs, f"{at}.brief", "Keep the brief to 1 or 2 sentences.")
        if not _place_ok(L.get("place")):
            _err(errs, f"{at}.place", "Pick the lesson's place on the Moon from the list.")
        p = L.get("patch") if isinstance(L.get("patch"), dict) else {}
        _text(errs, f"{at}.patch.name", p.get("name"), name="a patch name", words=PATCH_WORDS, chars=20)
        g = p.get("glyph")
        if g is not None and not (isinstance(g, str) and re.fullmatch(r"[A-Za-z0-9]", g)):
            _err(errs, f"{at}.patch.glyph", "The patch letter is one letter or number.")
        facts = L.get("facts") or []
        if not isinstance(facts, list) or len(facts) > MAX_FACTS:
            _err(errs, f"{at}.facts", f"Up to {MAX_FACTS} facts per lesson.")
            facts = []
        for fi, f in enumerate(facts):
            fat = f"{at}.facts[{fi}]"
            if not isinstance(f, dict):
                _err(errs, fat, "This fact is empty.")
                continue
            _text(errs, f"{fat}.text", f.get("text"), name="the fact", words=FACT_WORDS)
            _source(errs, f"{fat}.source", f.get("source"))
        steps = L.get("steps")
        if not isinstance(steps, list) or not steps:
            _err(errs, f"{at}.steps", "Add at least one step.")
            continue
        if len(steps) > MAX_STEPS:
            _err(errs, f"{at}.steps", f"A lesson has up to {MAX_STEPS} steps.")
        prev = None
        for si, s in enumerate(steps[:MAX_STEPS]):
            _check_step(errs, warns, f"{at}.steps[{si}]", s)
            kind = s.get("kind") if isinstance(s, dict) else None
            if kind and kind == prev:
                _err(warns, f"{at}.steps[{si}]", "Two steps of the same kind in a row. Mixing them keeps it lively.")
            prev = kind
        if len(steps) > 5:
            _err(warns, f"{at}.steps", "Lessons of 5 steps or fewer hold attention best.")
    return errs, warns


def _check_step(errs: list, warns: list, at: str, s) -> None:
    if not isinstance(s, dict):
        _err(errs, at, "This step is empty.")
        return
    kind = s.get("kind")
    if kind not in KINDS:
        _err(errs, f"{at}.kind", "Pick a step kind: say, find a place, multiple choice or predict.")
        return
    _text(errs, f"{at}.prompt", s.get("prompt"), name="the question", words=PROMPT_WORDS, chars=PROMPT_CHARS)
    if '"' in str(s.get("prompt") or "") or "“" in str(s.get("prompt") or ""):
        _err(errs, f"{at}.prompt", "No quote marks in the question (the app would read them as an order to repeat).")
    _text(errs, f"{at}.success", s.get("success"), name="the success line", words=SUCCESS_WORDS, need=False)
    _text(errs, f"{at}.fail", s.get("fail"), name="the try-again line", words=FAIL_WORDS, need=False)
    _text(errs, f"{at}.hint", s.get("hint"), name="the hint", words=HINT_WORDS, need=False)
    fail = s.get("fail") or DEFAULT["fail"]
    hint = s.get("hint") or DEFAULT_HINT[kind]
    if isinstance(fail, str) and isinstance(hint, str) and _words(fail) + 1 + _words(hint) > FAIL_HINT_WORDS:
        _err(errs, f"{at}.hint", f"The try-again line and the hint together go over {FAIL_HINT_WORDS} words.")
    if kind == "place" and not _place_ok(s.get("place")):
        _err(errs, f"{at}.place", "Pick the place to find from the list.")
    if kind == "say":
        ws = s.get("words")
        if not isinstance(ws, list) or not [w for w in ws if isinstance(w, str) and w.strip()]:
            _err(errs, f"{at}.words", "Add at least one word that counts as a right answer.")
        elif len(ws) > 12 or any(not isinstance(w, str) or _words(w) > 3 for w in ws):
            _err(errs, f"{at}.words", "Up to 12 answer words, each 1 to 3 words long.")
    if kind in ("choice", "predict"):
        opts = s.get("options")
        if not isinstance(opts, list) or not 2 <= len(opts) <= 4:
            _err(errs, f"{at}.options", "Give 2 to 4 answers.")
            return
        seen: dict[str, int] = {}
        for oi, o in enumerate(opts):
            _text(errs, f"{at}.options[{oi}]", o, name="the answer", words=LABEL_WORDS, chars=40)
            for w in key_words(o if isinstance(o, str) else ""):
                if w in seen and seen[w] != oi:
                    _err(errs, f"{at}.options[{oi}]", f"Answers {seen[w] + 1} and {oi + 1} share the word {w!r}. "
                                                      "Spoken answers match by their words.")
                seen.setdefault(w, oi)
            if isinstance(o, str) and o.strip() and not key_words(o):
                _err(errs, f"{at}.options[{oi}]", "This answer needs a word that can be said (not only small words).")
        a = s.get("answer")
        if not (isinstance(a, int) and not isinstance(a, bool) and 0 <= a < len(opts)):
            _err(errs, f"{at}.answer", "Mark which answer is right.")
        if kind == "predict":
            _text(errs, f"{at}.reveal", s.get("reveal"), name="the reveal line", words=REVEAL_WORDS)


def _nasa_titles() -> set[str]:
    try:
        from . import content
        return {l["title"] for l in content.nasa_course()["lessons"]}
    except Exception:   # noqa: BLE001
        return set()


# ---------------------------------------------------------------------------------------------------------------------
# compile: pack → course lessons

def lesson_id(pack_id: str, lid: str) -> str:
    return f"c-{pack_id}-{lid}"


def _option_rows(labels: list[str]) -> list[dict]:
    rows = []
    for i, lab in enumerate(labels):
        mine = key_words(lab)
        rows.append({"id": LETTERS[i], "label": lab.strip(), "say": sorted(mine)})
    return rows


def compile_step(s: dict) -> dict:
    kind = s["kind"]
    out = {"prompt": s["prompt"].strip(), "success": (s.get("success") or DEFAULT["success"]).strip(),
           "fail": (s.get("fail") or DEFAULT["fail"]).strip(), "hint": (s.get("hint") or DEFAULT_HINT[kind]).strip(),
           "kind": kind}
    if kind == "place":
        out["accept"] = {"type": "intent", "place": s["place"]}
    elif kind == "say":
        ws = [w.strip() for w in s["words"] if isinstance(w, str) and w.strip()]
        out["accept"] = {"type": "keywords", "all": [ws]}
        out["do"] = "Say it out loud, or type it"
    elif kind == "choice":
        rows = _option_rows(s["options"])
        out["accept"] = {"type": "choice", "answer": rows[s["answer"]]["id"], "options": rows}
        out["do"] = "Tap an answer, or say it"
    elif kind == "predict":
        rows = _option_rows(s["options"])
        out["accept"] = {"type": "predict", "answer": rows[s["answer"]]["id"], "options": rows}
        out["reveal"] = s["reveal"].strip()
    return out


def _glyph(L: dict) -> str:
    g = (L.get("patch") or {}).get("glyph")
    if isinstance(g, str) and g:
        return g.upper()
    m = re.search(r"[A-Za-z0-9]", (L.get("patch") or {}).get("name") or L.get("title") or "C")
    return m.group(0).upper() if m else "C"


def compile_pack(pack: dict, *, preview: bool = False) -> list[dict]:
    """A valid pack → course lessons (content.py's shape), in the pack's order."""
    out = []
    for L in pack["lessons"]:
        lid = lesson_id(pack["id"], L["id"])
        steps = [compile_step(s) for s in L["steps"]]
        out.append({
            "id": lid, "title": L["title"].strip(), "brief": L["brief"].strip(), "place": L["place"],
            "track": "class", "pack": {"id": pack["id"], "title": pack["title"].strip()},
            "minutes": max(1, math.ceil(len(steps) * 0.8)),
            "badge": {"id": lid, "name": L["patch"]["name"].strip(), "glyph": _glyph(L)},
            "facts": [{"text": f["text"].strip(), "source": {"title": f["source"]["title"].strip(),
                                                              "url": f["source"]["url"].strip()}}
                      for f in (L.get("facts") or [])],
            "steps": steps,
            **({"preview": True} if preview else {}),
        })
    return out


# ---------------------------------------------------------------------------------------------------------------------
# store + loader

def _read(path: Path) -> tuple[dict | None, str | None]:
    try:
        if path.stat().st_size > MAX_BYTES:
            return None, f"{path.name}: the file is bigger than {MAX_BYTES // 1000} KB."
        return json.loads(path.read_text(encoding="utf-8")), None
    except ValueError as e:
        return None, f"{path.name}: not a JSON file ({e.__class__.__name__})."
    except OSError as e:
        return None, f"{path.name}: can't read it ({e.strerror or e})."


def _summary(errs: list[dict], n: int = 3) -> str:
    head = "; ".join(f"{e['at'] + ': ' if e['at'] else ''}{e['msg']}" for e in errs[:n])
    return head + (f" (and {len(errs) - n} more)" if len(errs) > n else "")


def _load() -> None:
    packs, problems = [], []
    d = class_dir()
    try:
        files = sorted(d.glob("*.json")) if d.is_dir() else []
    except OSError:
        files = []
    nasa = _nasa_titles()
    taken_ids, taken_titles = set(), set()
    for f in files:
        try:
            pack, why = _read(f)
            if why:
                problems.append({"file": f.name, "msg": why})
                continue
            errs, _ = validate(pack, nasa_titles=nasa)
            if errs:
                problems.append({"file": f.name, "msg": f"{f.name}: skipped. {_summary(errs)}"})
                continue
            if pack["id"] in taken_ids:
                problems.append({"file": f.name, "msg": f"{f.name}: skipped. Another pack already uses the id {pack['id']!r}."})
                continue
            titles = {L["title"].strip().lower() for L in pack["lessons"]}
            if titles & taken_titles:
                problems.append({"file": f.name, "msg": f"{f.name}: skipped. A lesson title is already used by another pack."})
                continue
            taken_ids.add(pack["id"])
            taken_titles |= titles
            packs.append({"id": pack["id"], "title": pack["title"], "file": f.name, "source": pack,
                          "lessons": compile_pack(pack), "mtime": f.stat().st_mtime})
        except Exception as e:   # noqa: BLE001  (never crash the app over a pack)
            problems.append({"file": f.name, "msg": f"{f.name}: skipped ({e.__class__.__name__})."})
    _STATE["packs"], _STATE["problems"] = packs, problems


def packs() -> list[dict]:
    with _LOCK:
        if _STATE["packs"] is None:
            _load()
        return list(_STATE["packs"])


def problems() -> list[dict]:
    packs()
    return list(_STATE["problems"])


def lessons() -> list[dict]:
    """Every Class lesson, pack by pack (pack files in name order), then the preview lesson (hidden from the map)."""
    out = [l for p in packs() for l in p["lessons"]]
    if _STATE["preview"]:
        out += _STATE["preview"]
    return out


def _changed() -> None:
    """Drop every cache that holds lesson lists (the course, the voice titles, the session's lesson table)."""
    with _LOCK:
        _STATE["packs"] = None
    try:
        from . import content
        content.reload()
    except Exception:   # noqa: BLE001
        pass


def reload() -> None:
    _changed()


def get(pack_id: str) -> dict | None:
    return next((p["source"] for p in packs() if p["id"] == pack_id), None)


def save(pack: dict) -> tuple[list[dict], list[dict]]:
    """Validate and store one pack (atomic: temp file + rename). Returns (errors, warnings); nothing is written when
    there are errors. A pack with the same id is replaced."""
    errs, warns = validate(pack)
    if not errs:
        others = {L["title"].strip().lower() for p in packs() if p["id"] != pack["id"] for L in p["source"]["lessons"]}
        for li, L in enumerate(pack["lessons"]):
            if L["title"].strip().lower() in others:
                _err(errs, f"lessons[{li}].title", "Another pack on this computer already has a lesson with this title.")
    if errs:
        return errs, warns
    d = class_dir()
    d.mkdir(parents=True, exist_ok=True)
    body = {**pack, "saved_at": int(time.time())}
    tmp = d / f".{pack['id']}.json.tmp"
    tmp.write_text(json.dumps(body, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(d / f"{pack['id']}.json")
    _changed()
    return [], warns


def delete(pack_id: str) -> bool:
    if not (isinstance(pack_id, str) and SLUG.match(pack_id)):
        return False
    hit = next((p for p in packs() if p["id"] == pack_id), None)
    path = class_dir() / (hit["file"] if hit else f"{pack_id}.json")
    try:
        path.unlink()
    except OSError:
        return False
    _changed()
    return True


def set_preview(pack: dict | None, lesson_index: int = 0) -> tuple[list[dict], str | None]:
    """Preview one lesson as it will play, without saving: it joins the course in memory only, hidden from the map,
    and earns no patch (the client checks `preview`). Returns (errors, lesson id)."""
    if pack is None:
        _STATE["preview"] = None
        _changed()
        return [], None
    errs, _ = validate(pack)
    errs = [e for e in errs if "already has this title" not in e["msg"]]
    if errs:
        return errs, None
    p = {**pack, "id": "preview"}
    i = max(0, min(lesson_index, len(p["lessons"]) - 1))
    les = compile_pack({**p, "lessons": [p["lessons"][i]]}, preview=True)
    _STATE["preview"] = les
    _changed()
    return [], les[0]["id"]


def blank_pack(pack_id: str = "my-class", title: str = "My class") -> dict:
    return {"format": FORMAT, "version": VERSION, "id": pack_id, "title": title, "lessons": []}
