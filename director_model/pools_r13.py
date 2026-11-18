"""Round 13 item pools (director_model/RESULTS.md, Round 13).

  lesson_answer   short spoken answers to a lesson's option step, right after (or a while after) its prompt: the
                  option's number ("one", "the first one", "1"), its letter ("a", "B."), its label or a few words of
                  it, a short definition ("mare means a sea of cooled lava"). Right and wrong options; the gold is the
                  grader on the words (answer / nudge), so a model that silences them loses act ok. Round 12's `answer`
                  class passed the offline gate and failed the backend suite on exactly these (test_step_tries).
  roomtalk_ctrl   (train only) kids talking to each other in the room with a control word in it ("is it my turn
                  next", "no stop it", "wait for me"): r12's hot-class losses were room talk that names a control
                  (cls_prep_roomtalk, "can i go next not yet"). The held-out cls_prep_roomtalk phrases never train.

Steps are split by (lesson, step) with pools.cls_split, so the held-out set cls_lesson_answer asks steps no train
session saw. The answer forms ("one", "a") are shared: the forms are the point.
"""
from __future__ import annotations

import random
import re

import pools as P

OPTION_TYPES = ("choice", "predict", "compare", "vocab_match", "earth_view")
NUM = ["one", "two", "three", "four", "five"]
ORD = ["first", "second", "third", "fourth", "fifth"]
LET = ["a", "b", "c", "d", "e"]

ROOM_CTRL = ["is it my turn next", "we're done with the flour", "i'm done you do it", "help me hold it", "skip it no wait",
             "watch this watch", "where's the bowl mom", "no stop it", "wait for me", "you go next", "stop copying me", "can i go first",
             "skip me i don't want to", "no you pause it", "mom can we play after", "i said wait", "go back to your room",
             "next time it's mine", "hold it like this", "stop stop stop that tickles", "wait i'm not ready",
             "do it again do it again", "no not that one the other one", "come back here", "okay okay you can have it",
             "help me carry it", "show me yours", "turn it around", "open it open it", "close the door",
             "can you zoom in on your phone", "play with me", "it's my go", "start over you messed it up",
             "is it done yet", "no more cookies"]


def _steps():
    from app.academy import content as AC
    out = []
    for L in AC.course()["lessons"]:
        for i, st in enumerate(L["steps"]):
            if st["accept"]["type"] in OPTION_TYPES:
                out.append((L, i))
    return out


_STEPS: list = []


def option_steps():
    if not _STEPS:
        _STEPS.extend(_steps())
    return _STEPS


def _words(s: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", (s or "").lower())


def short_answer(rng: random.Random, L: dict, i: int, correct: bool) -> tuple[str, str]:
    """(text, form) of a short spoken answer to option step i of lesson L."""
    from app.academy import grade as G
    st = L["steps"][i]
    acc = st["accept"]
    opts = G.step_options(acc)
    ids = [o for o, _ in opts]
    ans = acc.get("answer")
    k = ids.index(ans) if ans in ids else 0
    if not correct and len(opts) > 1:
        k = rng.choice([j for j in range(len(opts)) if j != k])
    say = [w for w in opts[k][1] if w]
    label = _words(say[0]) if say else []
    form = rng.choices(["number", "letter", "label", "few", "define"], [3, 3, 2, 2, 1])[0]
    if form == "number":
        t = rng.choice([NUM[k], NUM[k], f"the {ORD[k]} one", str(k + 1), f"number {NUM[k]}", f"{ORD[k]}",
                        f"option {NUM[k]}"])
    elif form == "letter":
        t = rng.choice([LET[k], LET[k], LET[k].upper() + ".", f"letter {LET[k]}", f"{LET[k]} please",
                        f"is it {LET[k]}"])
    elif form == "label" or len(label) < 3:
        t = " ".join(label) if label else NUM[k]
        if len(say) > 1 and rng.random() < 0.5:
            t = " ".join(_words(rng.choice(say[1:]))) or t
        form = "label"
    elif form == "few":
        n = rng.randint(2, min(5, len(label)))
        t = " ".join(label[:n])
    else:
        term = _words(acc.get("term") or "") or [w for w in _words(st.get("prompt") or "") if len(w) > 3][-1:]
        t = f"{' '.join(term)} means {' '.join(label[:6])}" if term else "it means " + " ".join(label[:6])
    return t, form


def lesson_answer_item(rng: random.Random, split: str) -> dict:
    """One short answer on a lesson option step, in its frame, mostly right after its prompt line."""
    steps = [s for s in option_steps() if P.cls_split(f"la:{s[0]['id']}:{s[1]}") == split] or option_steps()
    L, i = rng.choice(steps)
    correct = rng.random() < 0.6
    t, form = short_answer(rng, L, i, correct)
    it = {"text": t, "cat": f"lesson_answer_{form}_{'right' if correct else 'wrong'}", "root": f"la:{L['id']}:{i}:{t}",
          "frame": P.step_frame(L, i), "lesson": L["id"], "step": i}
    prompt = L["steps"][i].get("prompt")
    if prompt and rng.random() < 0.7:          # the step's prompt just ended: the answer comes 0.3-2 s after it
        it.update(op="offer", lines=[prompt], gap=round(rng.uniform(0.3, 2.0), 2))
    return it


def roomtalk_ctrl_item(rng: random.Random) -> dict:
    """Train only: room talk between kids that names a control, in the prep / cabin / lesson frames."""
    import pools_r8 as P8
    t = rng.choice(ROOM_CTRL)
    fr = rng.choice([P8._frame("prep", offer="prep_task"), {"screen": "cabin", "step_type": None, "step_options": [],
                                                            "offer": None}, P8._frame("video")])
    return {"text": t, "cat": "r13_roomtalk_ctrl", "root": "rc:" + t, "frame": fr, "gold": {"act": "ignore"},
            "dd": (0.4, 0.95)}


def r13_items(seed: int, split: str, p: float) -> list[dict]:
    """The round-13 items appended to a hands-free session (their own random stream: the session's other items and
    every earlier draw are unchanged). Train: lesson answers and room talk with a control word; val: lesson answers."""
    rng = random.Random(seed * 19 + 5)
    if not p or rng.random() >= p:
        return []
    out = []
    for _ in range(rng.randint(1, 2)):
        if split == "train" and rng.random() < 0.3:
            out.append(roomtalk_ctrl_item(rng))
        else:
            it = lesson_answer_item(rng, split)
            if split == "train" and rng.random() < 0.15:
                it["bare"] = True       # the turn reaches the Session with no partials and no arc read (the backend
            out.append(it)              # tests' form, and an ear that sends only the turn's text)
    return out
