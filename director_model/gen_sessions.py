"""Generate Director training/eval sessions by DRIVING THE REAL SESSION (backend/app/session.py) through the same
shadow hook the runtime uses (app.director_model.runtime.Shadow with a sink): the features are computed by the exact
serving code, and the rule Director + session policy produce the teacher labels.

Run in the backend env, with a private model server (real Arc Tagger + MiniLM embedder) on :8290:
  cd model_server && EMBED_MODEL_DIR=... STEER_TTS=off ARC_EAR=off ARC_META=off uv run uvicorn app.main:app --port 8290
  uv run --project backend python director_model/gen_sessions.py --out director_model/data/ds --train 1500 ...

Sources (one session = one browser session; one step per event):
  mission   real sim (5 sites, many seeds), templated + command-bank + compound/negation/conditional/risky->yes/no
            turns, End shift, polls (storms, comm windows, low power at night), CAPCOM playback
  cadet     the Moon library: knowledge-card questions with kid wrappers, misconceptions, tours, sounds, places,
            glossary, off-topic, PII
  academy   every lesson step: correct / wrong / hint answers (gold from academy.grade)
  barge/echo/chatter mixed into all: the kid starts during guide/crew audio; echo words of what's playing; kid-to-kid
  ASR       half the train sessions replay the kid's words through the Arc Mini error model (ear_errors.py), as partials
            with revisions; labels stay the kid's INTENT (the clean run's teacher), except when the noise destroyed a
            slot word -> ask_clarify
Held-out sets: test_clean / test_asr (unseen seeds, held-out templates and card questions), test_ear (REAL Arc Mini
decodes, even ear-eval ids), test_h40 (brain's 40 held-out commands), test_q80 (80 kid questions), test_gold.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent / "backend"
os.environ.setdefault("MODEL_SERVER_URL", "http://127.0.0.1:8290")
os.environ["DIRECTOR_MODEL"] = "off"
assert ":8200" not in os.environ["MODEL_SERVER_URL"], "never use the live demo model server"
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(HERE))

import numpy as np  # noqa: E402

from app import director, models_client, session as S  # noqa: E402
from app.academy import content as AC, grade as AG  # noqa: E402
from app.config import settings  # noqa: E402
from app.director_model import features as FX, runtime as RT  # noqa: E402
from app.gazetteer import Gazetteer  # noqa: E402
from app.knowledge.answer import detect_attr  # noqa: E402
from app.mission import capcom, registry, sim  # noqa: E402
from app.moments import MomentIndex  # noqa: E402

import pools as P  # noqa: E402
from ear_errors import ErrorModel, ear_rows, partials, EAR  # noqa: E402

SITES = [s["id"] for s in sim.sites()]
TAG = {"on": True}
_real_tag = models_client.tag


async def _tag(text, domain="assistant"):
    return await _real_tag(text, domain) if TAG["on"] else None
models_client.tag = _tag


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


# ------------------------------------------------------------------------------------------------- scripts
def mission_script(rng: random.Random, split: str, seed: int) -> dict:
    items = []
    n = rng.randint(8, 16)
    golds = [g for g in P.gold_items() if g["split"] == ("test" if split == "test" else "train") and g["mode"] == "mission"]
    bank = [b for b in P.bank() if P.split_of(b["root"]) == split]
    while len(items) < n:
        r = rng.random()
        if r < 0.32:
            items.append(P.mission_cmd(rng, split))
        elif r < 0.44:
            items.append(dict(rng.choice(bank)))
        elif r < 0.50:
            items.append(P.compound(rng, split))
        elif r < 0.57:
            items.append(P.risky(rng))
            items.append(P.yes_no(rng, rng.random() < 0.6))
        elif r < 0.66:
            ex = P.explorer(rng, split)
            sub = random.Random(seed * 1000 + len(items))     # own stream: the session's rng stream stays as before
            items.append(ex if sub.random() < 0.5 else P.mission_question(sub, split))
        elif r < 0.69:
            items.append(P.chatter(rng))
        elif r < 0.73:
            items.append({"op": "echo", "cat": "echo", "gold": {"act": "ignore"}})
        elif r < 0.79:
            it = P.mission_cmd(rng, split) if rng.random() < 0.5 else P.explorer(rng, split)
            items.append({**it, "during_play": True, "cat": "barge_" + it["cat"]})
        elif r < 0.81:
            items.append(P.pii(rng))
        elif r < 0.86:
            items.append({"op": "end_shift"})
        elif r < 0.89:
            items.append({"op": "emotion", "label": rng.choice(["frustrated", "confused", "excited", "happy", "bored",
                                                                 "scared"])})
        elif r < 0.95 and golds:
            items.append(dict(rng.choice(golds)))
        elif r < 0.95:
            items.append({"text": rng.choice(["give it more", "turn it down", "how much is left of it"]),
                          "cat": "cmd_pronoun", "root": "pron"})
        else:
            items.append({"op": "end_shift"})
    return {"mode": "mission", "site": rng.choice(SITES), "seed": seed, "role": None, "items": items}


def cadet_script(rng, split, seed) -> dict:
    items = []
    golds = [g for g in P.gold_items() if g["split"] == ("test" if split == "test" else "train") and g["mode"] == "cadet"]
    for _ in range(rng.randint(6, 14)):
        r = rng.random()
        if r < 0.6:
            items.append(P.explorer(rng, split))
        elif r < 0.7:
            items.append(P.chatter(rng))
        elif r < 0.77:
            items.append({"op": "echo", "cat": "echo", "gold": {"act": "ignore"}})
        elif r < 0.86:
            it = P.explorer(rng, split)
            items.append({**it, "during_play": True, "cat": "barge_" + it["cat"]})
        elif r < 0.9:
            items.append(P.pii(rng))
        elif r < 0.96 and golds:
            items.append(dict(rng.choice(golds)))
        else:
            items.append({"op": "tap", "id": rng.choice(list(GAZ.places))})
    return {"mode": "cadet", "seed": seed, "items": items}


def academy_script(rng, split, seed) -> dict:
    lessons = AC.course()["lessons"]
    L = rng.choice(lessons)
    items = []
    for si, st in enumerate(L["steps"]):
        items.append({"op": "lesson", "lesson_id": L["id"], "step": si, "status": "task"})
        for _ in range(rng.randint(1, 3)):
            if st["accept"]["type"] == "tap":
                items.append({"op": "tap", "id": st["accept"]["place"]})
                break
            items.append(P.academy_items(rng, L, si))
        if rng.random() < 0.1:
            items.append(P.chatter(rng))
    return {"mode": "academy", "lesson": L["id"], "seed": seed, "items": items}


def kind_script(rng, split, seed, hf_p: float = 0.0):
    if hf_p and random.Random(seed * 7 + 1).random() < hf_p:     # own stream: older sessions keep their seeds
        return handsfree_script(random.Random(seed * 7 + 2), split, seed)
    r = rng.random()
    return mission_script(rng, split, seed) if r < 0.5 else cadet_script(rng, split, seed) if r < 0.8 else \
        academy_script(rng, split, seed)


CLASS_W = {"chatter": 3, "echo": 3, "offer": 2, "panel": 2, "help": 2, "mode": 1, "globe": 3, "mishear": 2}


def logged_items(split: str) -> list[dict]:
    """Turns imported from the opt-in turn logs (import_logs.py -> data/real_turns.json), weak / reviewed gold."""
    if "logged" not in _LOGGED:
        f = HERE / "data" / "real_turns.json"
        _LOGGED["logged"] = json.loads(f.read_text())["items"] if f.exists() else []
    return [dict(x) for x in _LOGGED["logged"] if x.get("split") == split]


_LOGGED: dict = {}


def handsfree_script(rng: random.Random, split: str, seed: int) -> dict:
    """Round 6: a hands-free session with the client's screen frames: today's failure classes (pools.CLASSES) mixed
    with ordinary cabin orders / questions and the imported real turns."""
    items = []
    cl = list(CLASS_W)
    logged = logged_items(split)
    for _ in range(rng.randint(8, 14)):
        r = rng.random()
        if r < 0.7:
            items.append(P.cls_item(rng.choices(cl, [CLASS_W[c] for c in cl])[0], rng, split))
        elif r < 0.8 and logged:
            items.append(rng.choice(logged))
        elif r < 0.9:
            items.append({**P.mission_cmd(rng, split), "frame": {"screen": "cabin", "step_type": None,
                                                                  "step_options": [], "offer": None}})
        else:
            items.append({**P.explorer(rng, split), "frame": {"screen": rng.choice(["library", "map"]),
                                                               "step_type": None, "step_options": [], "offer": None}})
    return {"mode": "mission", "site": rng.choice(SITES), "seed": seed, "role": None, "items": items, "hf": True}


def class_set_items(cls: str, n: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    return [P.cls_item(cls, rng, "test") for _ in range(n)]


def set_script(items: list[dict], mode: str, seed: int, site: str | None = None) -> dict:
    return {"mode": mode, "site": site or SITES[seed % len(SITES)], "seed": seed, "role": None, "items": items}


# ------------------------------------------------------------------------------------------------- the runner
async def play_pending(sess, clock, rng, leave_playing=False):
    """The client: play unplayed say/play decisions one at a time (playback start/end)."""
    for _ in range(6):
        ds = [d for d in sess.pending.values() if d["t"] in ("say", "play")]
        if not ds:
            return None
        d = ds[0]
        kind = "guide" if d["t"] == "say" else "crew"
        text = d.get("text") or ((d.get("moment") or {}).get("text") or "")
        await sess.handle({"t": "playback", "kind": kind, "state": "start", "id": d["id"], "text": text})
        if leave_playing:
            clock.t += rng.uniform(0.6, 1.6)
            return d
        clock.t += max(1.0, len(text.split()) / 2.6) if kind == "guide" else rng.uniform(4, 12)
        await sess.handle({"t": "playback", "kind": kind, "state": "end", "id": d["id"]})
        clock.t += rng.uniform(0.2, 0.8)
    return None


def real_stream(d: dict):
    """A cached real Arc decode -> (final words, partial word lists, eager?, dd, cc)."""
    hw = FX.words_of(d["hyp"])
    ps, last = [], None
    for e in d["events"]:
        if e["t"] == "words" and not e["final"]:
            w = FX.words_of(e["text"])
            if w and w != last:
                ps.append(w)
                last = w
    if not ps or ps[-1] != hw:
        ps.append(hw)
    states = [e["state"] for e in d["events"] if e["t"] == "turn"]
    arcs = [e for e in d["events"] if e["t"] == "arc" and e.get("dd") is not None]
    dd = arcs[-1]["dd"] if arcs else None
    cc = arcs[-1]["cc"] if arcs else None
    return hw, ps, "eager" in states, dd, cc


async def run(script: dict, rng: random.Random, noise=None, arc_on=True, typed_p=0.12, real=None) -> tuple[list, dict]:
    """-> (sink steps, turn annotations by turn id). real = (RealEar, group, p): replay real Arc decodes of the turn
    texts (with probability p, when the cache has the text) instead of the fitted error model."""
    clock = Clock()
    sink: list = []
    sid = f"g-{script['seed']}-{rng.randrange(1 << 30)}"
    sess = S.Session(sid, GAZ, IDX, clock=clock, registry=registry)
    sess.dm = RT.Shadow(sess, sink=sink, run_model=False)
    mode = script["mode"]
    hello = {"t": "hello", "mode": mode, "session": sid}
    if mode == "mission":
        m = registry.create(script["site"], script["seed"])
        hello["mission_id"], hello["role"] = m.id, script.get("role")
    if mode == "academy":
        hello["lesson_id"] = script["lesson"]
    await sess.handle(hello)
    anns: dict = {}
    lesson_step = None
    frame = None
    for tid, it in enumerate(script["items"]):
        clock.t += rng.uniform(1.5, 9.0)
        if mode == "mission" and rng.random() < 0.7:
            await sess.poll()
            await play_pending(sess, clock, rng)
        op = it.get("op")
        if op == "end_shift":
            await sess.handle({"t": "ui", "event": "end_shift"})
            await play_pending(sess, clock, rng)
            continue
        if op == "emotion":
            await sess.handle({"t": "emotion", "label": it["label"]})
            continue
        if op == "tap":
            await sess.handle({"t": "ui", "event": "tap_place", "id": it["id"]})
            continue
        if op == "lesson":
            lesson_step = (it["lesson_id"], it["step"])
            await sess.handle({"t": "lesson", "lesson_id": it["lesson_id"], "step": it["step"], "status": it["status"]})
            continue
        fr = it.get("frame")
        if fr is not None and fr != frame:          # the client's screen frame (hands-free routing context)
            frame = fr
            await sess.handle({"t": "ui", "event": "screen", **{k: v for k, v in fr.items()}})
        if it.get("lesson") and fr is not None:
            if lesson_step != (it["lesson"], it["step"]):
                lesson_step = (it["lesson"], it["step"])
                await sess.handle({"t": "lesson", "lesson_id": it["lesson"], "step": it["step"], "status": "task"})
        pend_line = None
        if op in ("echo2", "offer"):
            # our line(s) end right before the kid's turn: back-to-back CAPCOM lines (echo between them) or an offer
            # taken within ~0.3 s of its end
            ln = it["lines"]
            await sess.handle({"t": "playback", "kind": "guide", "state": "start", "id": f"L{tid}a", "text": ln[0]})
            clock.t += max(1.0, len(ln[0].split()) / 2.6)
            await sess.handle({"t": "playback", "kind": "guide", "state": "end", "id": f"L{tid}a"})
            if op == "offer":
                clock.t += it.get("gap", 0.15)
            else:
                g_b, g_k = rng.uniform(0.05, 0.4), rng.uniform(0.0, 0.3)
                if g_b <= g_k:
                    clock.t += g_b
                    await sess.handle({"t": "playback", "kind": "guide", "state": "start", "id": f"L{tid}b",
                                       "text": ln[1]})
                    clock.t += g_k - g_b
                else:
                    clock.t += g_k
                    pend_line = (clock.t + g_b - g_k, f"L{tid}b", ln[1])
        playing = None
        if it.get("during_play") or op == "echo":
            if not [d for d in sess.pending.values() if d["t"] == "say"]:
                await sess.handle({"t": "typed", "text": rng.choice(["tell me about tycho", "how big is copernicus",
                                                                       "what is regolith", "status report"])})
            playing = await play_pending(sess, clock, rng, leave_playing=True)
            if playing is None:
                continue
        if op == "echo":
            pw = FX.words_of(playing.get("text") or "")
            if len(pw) < 3:
                await sess.handle({"t": "playback", "kind": "guide", "state": "end", "id": playing["id"]})
                continue
            a = rng.randrange(0, max(1, len(pw) - 3))
            cw = pw[a:a + rng.randint(3, 7)]
            it = {**it, "text": " ".join(cw), "root": "echo"}
        cw = FX.words_of(it["text"])
        rd = None
        if real is not None and noise is not None and op not in ("echo", "echo2") and "heard" not in it and \
                rng.random() < real[2]:
            d = real[0].get(real[1], it["text"], rng)
            rd = real_stream(d) if d else None
        if op == "echo2" and noise is not None and real is not None:
            d = real[0].get("app", it["lines"][0], rng)     # the line in the app's own voice, through the real ear
            if d and d.get("hyp"):
                hy = FX.words_of(d["hyp"])
                k = min(len(hy), len(cw))
                a0 = int(round(len(hy) * (len(FX.words_of(it["lines"][0])) - len(cw)) / max(1, len(FX.words_of(it["lines"][0])))))
                if k:
                    it = {**it, "heard": " ".join(hy[max(0, min(a0, len(hy) - k)):][:k])}
        if rd is not None:
            hw, al = rd[0], None
        elif "heard" in it and noise is not None:
            hw, al = FX.words_of(it["heard"]), None
        elif "heard_fallback" in it and noise is not None and rng.random() < 0.6:
            hw, al = FX.words_of(it["heard_fallback"]), None
        elif noise is not None and op != "echo":
            em, noisy, level = noise
            hw, al = em.corrupt(cw, rng, noisy=noisy, level=level)
        else:
            hw, al = list(cw), list(range(len(cw)))
        if not hw:
            continue
        ann = {"tid": tid, "item": it, "clean": cw, "heard": hw, "al": al, "words": [], "end": None,
               "lesson": (it["lesson"], it["step"]) if it.get("lesson") else lesson_step if mode == "academy" else None,
               "real": rd is not None}
        anns[tid] = ann
        dd_rng = it.get("dd") or ((0.3, 0.7) if op == "echo" else (0.55, 0.98))
        dd = rng.uniform(*dd_rng)
        if rd is not None and rd[3] is not None and rng.random() < 0.5:
            dd = rd[3]       # Arc's own device_directed on the rendered audio (TTS: always "to the device")
        typed = rng.random() < typed_p and not playing and op != "echo" and rd is None
        if typed:
            i0 = sess.dm.n
            await sess.handle({"t": "typed", "text": " ".join(hw), "source": "typed"})
            ann["end"] = i0 if sess.dm.n > i0 else None
        else:
            ann["words"].append((sess.dm.n, []))
            await sess.handle({"t": "turn", "state": "start", "text": ""})
            ps = rd[1] if rd is not None else partials(hw, rng)
            for j, p in enumerate(ps):
                clock.t += 0.32 * rng.uniform(0.7, 1.5)
                if pend_line is not None and clock.t >= pend_line[0]:
                    await sess.handle({"t": "playback", "kind": "guide", "state": "start", "id": pend_line[1],
                                       "text": pend_line[2]})
                    pend_line = None
                ann["words"].append((sess.dm.n, p))
                await sess.handle({"t": "words", "text": " ".join(p)})
                if j == min(1, len(ps) - 1) and arc_on:
                    ann["words"].append((sess.dm.n, p))
                    await sess.handle({"t": "arc", "device_directed": round(dd, 3),
                                       "command_complete": round(rng.uniform(0.5, 0.95), 3)})
            if (rd[2] if rd is not None else rng.random() < 0.4):
                clock.t += 0.25
                ann["words"].append((sess.dm.n, hw))
                await sess.handle({"t": "turn", "state": "eager", "text": " ".join(hw)})
            clock.t += rng.uniform(0.3, 0.6)
            i0 = sess.dm.n
            await sess.handle({"t": "turn", "state": "end", "text": " ".join(hw)})
            ann["end"] = i0 if sess.dm.n > i0 else None
        ann["t_end"] = clock.t
        if op == "echo2":
            if pend_line is not None:
                await sess.handle({"t": "playback", "kind": "guide", "state": "start", "id": pend_line[1],
                                   "text": pend_line[2]})
            clock.t += 1.0
            await sess.handle({"t": "playback", "kind": "guide", "state": "end", "id": f"L{tid}b"})
        if playing is not None and playing["id"] in sess.pending:
            await sess.handle({"t": "playback", "kind": "guide", "state": "interrupted", "id": playing["id"]})
        await play_pending(sess, clock, rng)
    sess.dm.flush()
    return sink, anns


# ------------------------------------------------------------------------------------------------- labels
def turn_info(sink, ann) -> dict:
    i = ann["end"]
    if i is None or i >= len(sink):
        return {}
    st = sink[i]
    say = next((d for d in st["decisions"] if d["t"] == "say"), None)
    r = st["r"] or {}
    return {"act": st["rules_act"], "cmd": FX.rules_command(r), "style": (say or {}).get("style"),
            "brain": (r.get("brain") or None), "place": r.get("place")}


def gold_turn(ann, clean: dict, mode: str) -> dict:
    """The kid's intent for one turn: hand gold > grade (Academy) > the clean run's teacher; slot-loss -> ask_clarify."""
    it = ann["item"]
    g = dict(it.get("gold") or {})
    act, cmd, src = g.get("act"), g.get("command"), "gold" if g else "teacher"
    if ann.get("lesson") and act is None:
        L = AC.lesson(ann["lesson"][0])
        ok, _ = AG.grade(L["steps"][ann["lesson"][1]], {"text": " ".join(ann["clean"])})
        act, src = ("answer" if ok else "nudge"), "grade"
    if act is None:
        act, cmd = clean.get("act", "wait"), clean.get("cmd")
    elif act == "command" and cmd is None:
        cmd = clean.get("cmd")
    if act in ("command", "confirm_yes", "confirm_no") and cmd:
        # slot loss: a slot the clean words carried (load / number / task) can no longer be read from the heard words
        sc, sh = FX.spans(ann["clean"], cmd), FX.spans(list(ann["heard"]), cmd)
        lost = any(any(sc[k]) and not any(sh[k]) for k in sc)
        if lost:
            act, cmd, src = "ask_clarify", None, src + "+slotloss"
    return {"act": act, "cmd": cmd, "attr": it.get("attr") or g.get("attr"), "src": src}


def label_session(sink, anns, clean_anns, clean_sink, meta_base: dict):
    T = len(sink)
    feats = np.zeros((T, FX.F), np.float32)
    toks = np.zeros((T, FX.K), np.int64)
    wtok = np.zeros((T, FX.W), np.int64)
    wfeat = np.zeros((T, FX.W, FX.WF), np.float32)
    y = {k: np.full(T, -1, np.int64) for k in FX.HEADS}
    yw = {k: np.full((T, FX.W), -1, np.int8) for k in FX.WORD_HEADS}
    metas = []
    prev = None
    for t, st in enumerate(sink):
        rec = st["rec"]
        feats[t] = FX.step_feats(rec, prev)
        toks[t], wtok[t], wfeat[t] = FX.step_tokens(rec)
        prev = rec
        y["act"][t] = FX.ACTS.index(st["rules_act"])
        say = next((d for d in st["decisions"] if d["t"] == "say"), None)
        for k, v in FX.style_labels((say or {}).get("style")).items():
            y[k][t] = v
        metas.append({"kind": rec["kind"], "now": rec["now"], "rules_act": st["rules_act"], "floor": rec["floor"],
                      "rules_barge": any(d["t"] == "floor" and d.get("holder") == "kid" for d in st["decisions"])
                      and rec["kind"] == "words"})
    for tid, ann in anns.items():
        it = ann["item"]
        final = ann["heard"]
        barge_gold = bool(it.get("during_play")) and it.get("op") != "echo" and not str(it.get("cat", "")).startswith("chat")
        for i, ws in ann["words"]:
            if i >= T:
                continue
            y["when"][i] = int(list(ws) == list(final))
            rec = sink[i]["rec"]
            if rec["playing_kind"] in ("guide", "crew") or rec["floor"] in ("guide", "crew"):
                y["barge"][i] = int(barge_gold and len(ws) >= 2)
            metas[i].update(tid=tid, part=len(ws), cat=it.get("cat"))
        i = ann["end"]
        if i is None or i >= T:
            continue
        clean = turn_info(clean_sink, clean_anns.get(tid, ann)) if clean_sink is not sink else turn_info(sink, ann)
        g = gold_turn(ann, clean, meta_base["mode"])
        y["act"][i] = FX.ACTS.index(g["act"])
        y["when"][i] = 1
        if g["act"] in ("command", "confirm_yes", "confirm_no"):
            c = g["cmd"] or ({"type": "confirm"} if g["act"] == "confirm_yes" else {"type": "cancel"}
                             if g["act"] == "confirm_no" else None)
            for k, v in FX.cmd_labels(c).items():
                y[k][i] = v
            sp = FX.spans(final, c)
            for k in FX.WORD_HEADS:
                arr = sp[k][-FX.W:]
                yw[k][i, :] = 0
                yw[k][i, FX.W - len(arr):] = arr
        elif g["act"] in ("answer", "ignore", "ask_clarify", "guard", "nudge"):
            y["cmd_type"][i] = 0
        if g["attr"] in FX.ATTRS:
            y["card_attr"][i] = FX.ATTRS.index(g["attr"])
        elif g["act"] == "answer" and str(it.get("cat", "")).startswith(("explorer_offtopic", "explorer_tour",
                                                                        "explorer_sound")):
            y["card_attr"][i] = 0
        for k in ("style", "s_rate", "s_loud", "s_f0_iqr"):
            y[k][i] = -1
        for k, v in FX.style_labels(clean.get("style")).items():
            y[k][i] = v
        st = sink[i]
        r = st["r"] or {}
        rattr = (r.get("brain") or {}).get("attr") or detect_attr(" ".join(final))
        if ann.get("lesson") and (not it.get("frame") or metas[i]["rules_act"] == "answer"):
            # an Academy answer: the app's rule is the grader on the heard words (hands-free: only when the router
            # passed the turn to the step as its answer; a routed-away turn keeps the router's act)
            L = AC.lesson(ann["lesson"][0])
            ok, _ = AG.grade(L["steps"][ann["lesson"][1]], {"text": " ".join(final)})
            metas[i]["rules_act"] = "answer" if ok else "nudge"
        metas[i].update(tid=tid, end=True, cat=it.get("cat"), clean=" ".join(ann["clean"]), heard=" ".join(final),
                        gold_act=g["act"], gold_cmd=g["cmd"], gold_src=g["src"], gold_attr=g["attr"],
                        rules_cmd=FX.rules_command(r), rules_attr=rattr, rules_place=r.get("place"),
                        rules_card=(r.get("brain") or {}).get("card"), t_end=ann.get("t_end"),
                        expect=it.get("expect"), ok=it.get("ok"),
                        route=(st["rec"].get("route") or {}).get("outcome"), hf=bool(it.get("frame")),
                        gold_conf=it.get("conf"))
    for m in metas:
        m.update(meta_base)
    return {"feats": feats, "toks": toks, "wtok": wtok, "wfeat": wfeat, **{f"y_{k}": v for k, v in y.items()},
            **{f"y_{k}": v for k, v in yw.items()}}, metas


# ------------------------------------------------------------------------------------------------- driver
async def make(script, rng_seed, noise, arc_on, tag_on, set_name, split, real=None):
    TAG["on"] = tag_on
    director.RULES.clear(); director.PENDING.clear(); capcom._explained.clear()
    rng = random.Random(rng_seed)
    if noise is None:
        sink, anns = await run(script, rng, None, arc_on)
        csink, canns = sink, anns
    else:
        csink, canns = await run(script, random.Random(rng_seed), None, arc_on)
        director.RULES.clear(); director.PENDING.clear()
        sink, anns = await run(script, random.Random(rng_seed), noise, arc_on, real=real)
    base = {"set": set_name, "split": split, "mode": script["mode"], "seed": script["seed"], "noise": noise is not None,
            "arc": arc_on, "tag": tag_on}
    for a in anns.values():
        if a.get("real"):
            a["item"] = {**a["item"], "real_ear": True}
    return label_session(sink, anns, canns, csink, base)


def save(out: Path, name: str, sessions: list):
    if not sessions:
        return
    arrs = {k: np.concatenate([s[0][k] for s in sessions]) for k in sessions[0][0]}
    arrs["off"] = np.cumsum([0] + [len(s[0]["feats"]) for s in sessions]).astype(np.int64)
    np.savez_compressed(out / f"{name}.npz", **arrs)
    with open(out / f"{name}.meta.jsonl", "w") as f:
        for si, s in enumerate(sessions):
            for m in s[1]:
                f.write(json.dumps({**m, "sess": si}, default=str) + "\n")
    print(f"  {name}: {len(sessions)} sessions, {len(arrs['feats'])} steps", flush=True)


def merge(out: Path, n: int):
    parts = [np.load(out / f"train_s{i}.npz") for i in range(n)]
    keys = [k for k in parts[0].files if k != "off"]
    arrs = {k: np.concatenate([p[k] for p in parts]) for k in keys}
    lens = [np.diff(p["off"]) for p in parts]
    arrs["off"] = np.cumsum([0] + [int(x) for ls in lens for x in ls]).astype(np.int64)
    np.savez_compressed(out / "train.npz", **arrs)
    base = 0
    with open(out / "train.meta.jsonl", "w") as f:
        for i in range(n):
            ns = 0
            for line in open(out / f"train_s{i}.meta.jsonl"):
                m = json.loads(line)
                ns = max(ns, m["sess"] + 1)
                m["sess"] += base
                f.write(json.dumps(m) + "\n")
            base += ns
    print(f"merged {n} shards: {len(arrs['off']) - 1} sessions, {len(arrs['feats'])} steps")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HERE / "data" / "ds"))
    ap.add_argument("--train", type=int, default=1200)
    ap.add_argument("--val", type=int, default=150)
    ap.add_argument("--test", type=int, default=200)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--only", default="", help="comma list of sets to (re)build")
    ap.add_argument("--shard", default="", help="i/n: build only train sessions k with k %% n == i -> train_s<i>.npz "
                    "(run n in parallel, then merge with --merge n)")
    ap.add_argument("--merge", type=int, default=0, help="merge train_s0..n-1 into train and exit")
    ap.add_argument("--real-p", type=float, default=0.9, help="P(use a cached real Arc decode) for a noised turn")
    ap.add_argument("--no-real", action="store_true", help="fitted error model only (rounds 1-3)")
    a = ap.parse_args()
    if a.merge:
        merge(Path(a.out), a.merge)
        return
    from real_ear import RealEar
    RE = None if a.no_real else RealEar()
    if RE is not None:
        print("real Arc decodes:", {g: RE.n(g) for g in ("train", "val", "test")}, flush=True)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    em = ErrorModel.load()
    only = set(x for x in a.only.split(",") if x)
    t0 = time.time()

    async def gen(name, split, n, seed0, noise_mode, group=None, real_p=None):
        if only and name not in only:
            return
        ss = []
        si, sn = (int(x) for x in a.shard.split("/")) if a.shard else (0, 1)
        if a.shard:
            name = f"{name}_s{si}"
        for k in range(n):
            if k % sn != si:
                continue
            rng = random.Random(seed0 + k)
            sc = kind_script(rng, split, seed0 + k)
            nz = None
            if noise_mode == "half" and rng.random() < 0.5 or noise_mode == "all":
                nz = (em, rng.random() < 0.5, rng.uniform(0.5, 1.5) if noise_mode == "half" else 1.0)
            real = (RE, group, a.real_p if real_p is None else real_p) if (RE is not None and group) else None
            if noise_mode == "real":
                txt = [it["text"] for it in sc["items"] if it.get("text") and it.get("op") not in ("echo",)]
                if any(RE.get(group, t, random.Random(0)) is None for t in txt):
                    continue        # the real set keeps only sessions whose every turn has a real decode
                nz, real = (em, False, 0.0), (RE, group, 1.0)
            ss.append(await make(sc, seed0 + k, nz, rng.random() < 0.8, rng.random() < 0.85, name, split, real))
            if k % 100 == 99:
                print(f"  {name} {k + 1}/{n} ({time.time() - t0:.0f} s)", flush=True)
        save(out, name, ss)

    await gen("train", "train", a.train, 10_000 + a.seed * 1_000_000, "half", "train")
    if a.shard:
        print(f"shard done in {time.time() - t0:.0f} s")
        return
    await gen("val", "val", a.val, 500_000, "half", "val")
    await gen("test_clean", "test", a.test, 900_000, "none")
    await gen("test_asr", "test", a.test, 900_000, "all")
    if RE is not None and RE.n("test"):
        # REAL Arc decodes of held-out sessions: unseen templates / card questions, held-out voices (real_ear.py)
        await gen("test_real", "test", a.test, 900_000, "real", "test")

    async def set_sessions(name, items, mode_of, per=8, noise=None):
        if only and name not in only:
            return
        ss = []
        for k in range(0, len(items), per):
            chunk = items[k:k + per]
            mode = mode_of(chunk[0])
            sc = set_script([dict(x) for x in chunk], mode, 950_000 + k)
            ss.append(await make(sc, 950_000 + k, noise, True, True, name, "test"))
        save(out, name, ss)

    eg = json.loads((HERE / "data" / "ear_gold.json").read_text())["items"]
    ear = [{"text": r["ref"], "heard": r["hyp"], "cat": "ear_real", "root": "ear:" + r["id"], "ear_cond": r["cond"],
            "noisy_audio": r["noisy"], **({"gold": eg[r["id"]], "attr": eg[r["id"]].get("attr")} if r["id"] in eg else {})}
           for r in ear_rows("test", [EAR / "results_arc_final.json", EAR / "results_arc_ctx_bias.json"])]
    await set_sessions("test_ear", ear, lambda x: "mission", noise=(em, False, 0.0))
    await set_sessions("test_h40", P.heldout40(), lambda x: "mission")
    await set_sessions("test_h40_asr", P.heldout40(), lambda x: "mission", noise=(em, True, 1.0))
    await set_sessions("test_q80", P.kidq80(), lambda x: "cadet")
    await set_sessions("test_q80_asr", P.kidq80(), lambda x: "cadet", noise=(em, True, 1.0))
    golds = [g for g in P.gold_items() if g["split"] == "test"]
    await set_sessions("test_gold", golds, lambda x: x.get("mode", "mission"), per=4)
    print(f"done in {time.time() - t0:.0f} s")


GAZ = Gazetteer(settings.data_dir / "places.json")
IDX = MomentIndex(settings.data_dir / "index/clips.json")

if __name__ == "__main__":
    asyncio.run(main())
