"""Round 8 pools: the app capabilities and flows added since round 7 (docs/DIRECTOR_COVERAGE.md).

Each class is a held-out set (`cls_<name>`) and a share of the hands-free train / val sessions. Items carry the client's
screen frame and an explicit gold (act, and `nav` for navigation the router may not know yet), so the set measures
the gap before a feature branch lands and the fix after.

  video_ctrl       while a video plays only play / pause / stop / skip count ("pause it", "skip the video", "watch")
  video_echo       the video's own audio leaking into the mic: NASA crew narration (backend/data/index/clips.json
                   transcripts; the real-ear path renders the real NASA audio) and music -> ignore, never a control
  prep             hands-on Mission prep tasks: "done!", "skip", "wait", "hold on", "I need help", "where's the flour"
  prep_roomtalk    kids away from the screen with flour / cookies / flashlights: laughter, sibling talk -> ignore
  voice_echo_os    the app's own lines (backend/data/voice_pack/lines.json on feat/voice-pack, else the CAPCOM lines)
                   heard back in the OS voices / the Nora pack, between or after lines -> ignore
  gesture_cooccur  a voice command while a hand gesture runs (fist-joystick spin): the voice intent stands
  lesson_new       answers to the new lessons (phases and eclipses, Moon gravity and dust) and the `video` step
  offers_new       the first-mission briefing video and the debrief "learn more" offers: take / decline
Pending = the feature is on an unmerged branch; the frame names the screen the branch adds.
"""
from __future__ import annotations

import json
import random
import re
from pathlib import Path

import pools as P

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent / "backend"

VIDEO_CTRL = {"video_pause": ["pause", "pause it", "pause the video", "stop it for a sec", "hold the video", "wait pause"],
              "video_play": ["play", "play it", "keep going", "resume", "play the video", "start it again"],
              "video_stop": ["stop", "stop the video", "close the video", "no more video", "turn it off"],
              "video_skip": ["skip", "skip it", "skip the video", "skip this", "next"]}
PREP_SAY = {"prep_done": ["done", "done!", "i'm done", "we did it", "finished", "all done", "ok done", "it's ready"],
            "prep_skip": ["skip", "skip this one", "we don't have flour", "can we skip it", "next one please"],
            "prep_wait": ["wait", "hold on", "one sec", "give me a minute", "not yet", "we're still doing it"],
            "prep_help": ["i need help", "what do i do", "how do we do this", "help me", "say it again"],
            "prep_where": ["where's the flour", "where is the flashlight", "where are the cookies", "do we need a bowl",
                           "what's a flashlight for"]}
PREP_ROOM = ["ha ha ha", "oh no the flour went everywhere", "mom look", "can i eat the cookie", "it's on my shirt",
             "that's so messy", "give me the spoon", "my turn my turn", "the light is too bright", "oops",
             "hahaha look at it", "it looks like a crater", "wow it made a hole", "do it again", "i dropped it",
             "it's all white", "shh", "wait wait wait not yet", "where did the marble go", "eww sticky"]
MULTI_KID = ["no it's my turn", "stop it", "i want to do it", "mom he took it", "you're not doing it right",
             "can i go next", "give it back", "that's not fair", "look at mine", "mine is bigger"]
MUSIC = ["(music)", "la la la", "da da da da", "hmm hmm hmm", "ooh ooh"]
GESTURE_VOICE = [("go to shackleton", "pick_site"), ("show me the far side", "answer"), ("zoom out", "view_orbit"),
                 ("show me the rover", "view_rover"), ("open the comm panel", "panel_comm"), ("next", "next"),
                 ("go to the map", "map"), ("what's that crater", "question")]
GESTURES = ["fist_spin", "pinch_zoom", "point", "thumbs_up", "open_palm"]
NEW_LESSONS = {"phases": {"options": ["New Moon", "Full Moon", "Half Moon", "Crescent"],
                          "answers": ["full moon", "it's a new moon", "a half moon", "crescent", "the earth's shadow",
                                      "a lunar eclipse", "the sun lights half", "waxing", "waning"]},
               "gravity": {"options": ["Same time", "Feather first", "Hammer first"],
                           "answers": ["same time", "they land together", "the hammer and the feather", "one sixth",
                                       "dust floats", "regolith", "it sticks to everything", "ejecta", "a crater"]},
               # explorer lessons, unlocked after missions 1 and 2 (the core track: Moon, Phases, Power, Radio,
               # Radiation, Ice, Ride)
               "apollo": {"options": ["Apollo 11", "Apollo 15", "Apollo 17"],
                          "answers": ["apollo 11", "the lunar rover", "neil armstrong", "the flag", "moon rocks",
                                      "the lunar module", "apollo seventeen", "they drove a rover"]},
               "video_step": {"options": ["Watch", "Skip"],
                              "answers": ["watch", "skip", "watch it", "show me", "i saw it", "they jumped high"]}}
# The new offers as the merged app frames them: the first-mission Moon Base briefing card sits on the picker (its
# frame keeps offer take_command: "yes" / "watch" takes it); the practice shift is its own offer on the map / patch.
NEW_OFFERS = {"take_command": ("Before you fly: watch the Moon Base briefing?", ["brief"]),
              "practice": ("Want to try a practice shift?", ["map", "patch"])}
# Houston is relayed by CAPCOM ("Houston says: ..."), in the one Nora voice, after a static beep: the echo of it
HOUSTON_RELAY = ["Houston says: storm watch, keep the shields ready.", "Houston says: good work on the power, Commander.",
                 "Houston says: the rover is cleared to drive.", "Houston says: next radio window in six hours.",
                 "Houston says: dose is fine, carry on."]
TAKE = ["yes", "yeah", "watch it", "sure", "okay", "yes please", "show me"]
DECLINE = ["no", "no thanks", "skip it", "not now", "nope"]
CLASSES_R8 = ("video_ctrl", "video_echo", "prep", "prep_roomtalk", "voice_echo_os", "gesture_cooccur", "lesson_new",
              "offers_new")
# Every round-8 feature is merged (main 4b4b7e1): nothing is pending; the sets gate. (Kept as a map for the next branch.)
PENDING: dict = {}


NEW_LESSON_IDS = ("phases", "gravity", "history")


def new_lesson_answer(rng: random.Random, L: dict, i: int, kind: str) -> str:
    """A spoken answer to a step of the new lessons (the gold is the grader on these words)."""
    a = L["steps"][i]["accept"]
    t = a["type"]
    if t == "video":
        return rng.choice(["watch", "watch it", "skip", "skip it", "play it"]) if kind == "correct" else \
            rng.choice(["the moon is big", "hmm", "i like it"])
    if t in ("vocab_say",):
        return a.get("term", "regolith") if kind == "correct" else rng.choice(["moon dust", "sand", "dirt"])
    if t in ("vocab_match", "vocab_fill", "vocab_listen"):
        from app.academy import vocab
        os_ = vocab.options(a)
        return (rng.choice(os_)["label"] if os_ else "regolith").lower()
    if t in P.GLOBE_TYPES:
        return P.globe_answer(rng, L, i, kind)
    return P.academy_items(rng, L, i)["text"]


def _frame(screen: str, step_type=None, options=None, offer=None, **k) -> dict:
    return {"screen": screen, "step_type": step_type, "step_options": list(options or []), "offer": offer, **k}


_NARR: list = []


def narration() -> list[dict]:
    """NASA crew narration segments: (clip file, start s, duration s, words) from the clip transcripts."""
    if not _NARR:
        try:
            clips = json.loads((BACKEND / "data" / "index" / "clips.json").read_text())["clips"]
        except Exception:  # noqa: BLE001
            clips = []
        for c in clips:
            ws = c.get("words") or []          # [start s, word, speaker, end s]
            for a, b in c.get("utterances") or []:   # word index spans
                seg = ws[a:b]
                if not (3 <= len(seg) <= 18):
                    continue
                t0, t1 = float(seg[0][0]), float(seg[-1][3])
                if t1 - t0 < 8:
                    _NARR.append({"file": c.get("file"), "start": t0, "dur": t1 - t0,
                                  "text": " ".join(str(w[1]) for w in seg)})
    return _NARR


_LINES: list = []


def app_lines() -> list[dict]:
    """The app's own spoken lines: the voice pack's lines.json when present (feat/voice-pack), else the CAPCOM lines."""
    if not _LINES:
        for p in [BACKEND / "data" / "voice_pack" / "lines.json",
                  HERE.parent.parent.parent.parent.parent / "wt-moon-voicepack" / "backend" / "data" / "voice_pack" /
                  "lines.json"]:
            try:
                d = json.loads(Path(p).read_text())
                _LINES.extend({"text": x["text"], "role": x.get("role", "capcom")} for x in d["lines"] if x.get("text"))
                break
            except Exception:  # noqa: BLE001
                continue
        if not _LINES:
            _LINES.extend({"text": t, "role": "capcom"} for t in P.CAPCOM_LINES)
    return _LINES


def _pick(rng, pool, tag, split):
    ps = [p for p in pool if P.cls_split(f"{tag}:{p}") == split] or list(pool)
    return rng.choice(ps)


def cls_item(cls: str, rng: random.Random, split: str) -> dict:
    """One round-8 item. Gold carries `nav` for navigation intents the router may not know yet."""
    if cls == "video_ctrl":
        intent = rng.choice(list(VIDEO_CTRL))
        t = _pick(rng, VIDEO_CTRL[intent], "vc", split)
        return {"text": t, "cat": "cls_video_ctrl", "root": "vc:" + t, "frame": _frame("video"),
                "gold": {"act": "navigate", "nav": intent}, "dd": (0.6, 0.98), "pending": PENDING.get(cls)}
    if cls == "video_echo":
        if rng.random() < 0.8 and narration():
            seg = rng.choice([s for s in narration() if P.cls_split("ve:" + s["text"]) == split] or narration())
            ws = re.sub(r"[^a-z0-9' ]", " ", seg["text"].lower()).split()
            return {"op": "video_leak", "text": " ".join(ws), "cat": "cls_video_echo", "root": "ve:" + seg["text"],
                    "audio": {"kind": "file", **{k: seg[k] for k in ("file", "start", "dur")}},
                    "frame": _frame("video"), "gold": {"act": "ignore"}, "dd": (0.3, 0.95),
                    "pending": PENDING.get(cls)}
        t = rng.choice(MUSIC)
        return {"op": "video_leak", "text": t, "cat": "cls_video_echo", "root": "vm:" + t, "audio": {"kind": "music"},
                "frame": _frame("video"), "gold": {"act": "ignore"}, "dd": (0.2, 0.8),
                "pending": PENDING.get(cls)}
    if cls == "prep":
        intent = rng.choice(list(PREP_SAY))
        t = _pick(rng, PREP_SAY[intent], "pp", split)
        g = {"act": "navigate", "nav": intent} if intent != "prep_where" else {"act": "answer"}
        return {"text": t, "cat": "cls_prep", "root": "pp:" + t, "frame": _frame("prep", offer="prep_task"),
                "gold": g, "dd": (0.5, 0.98), "pending": PENDING.get(cls)}
    if cls == "prep_roomtalk":
        t = _pick(rng, PREP_ROOM + MULTI_KID, "pr", split)
        return {"text": t, "cat": "cls_prep_roomtalk", "root": "pr:" + t, "frame": _frame("prep", offer="prep_task"),
                "gold": {"act": "ignore"}, "dd": (0.4, 0.95), "pending": PENDING.get(cls)}
    if cls == "voice_echo_os":
        ls = app_lines() + [{"text": t, "role": "houston_relay"} for t in HOUSTON_RELAY]
        a = rng.choice([x for x in ls if P.cls_split("vo:" + x["text"]) == split] or ls)
        ws = re.sub(r"[^a-z0-9' ]", " ", a["text"].lower()).split()
        k = rng.randint(2, min(7, max(2, len(ws))))
        st = rng.randint(0, max(0, len(ws) - k))
        b = rng.choice(ls)
        return {"op": "echo2", "text": " ".join(ws[st:st + k]) or a["text"].lower(), "lines": [a["text"], b["text"]],
                "cat": "cls_voice_echo_os", "root": "vo:" + a["text"],
                "audio": {"kind": "os_voice", "line": a["text"], "beep": a.get("role") == "houston_relay"},
                "frame": _frame(rng.choice(["cabin", "cabin", "lesson", "brief", "map"])), "gold": {"act": "ignore"},
                "dd": (0.4, 0.9), "pending": PENDING.get(cls)}
    if cls == "gesture_cooccur":
        t, intent = GESTURE_VOICE[rng.randrange(len(GESTURE_VOICE))]
        screen = "cabin" if intent.startswith(("panel_", "view_")) else "brief" if intent == "pick_site" else \
            rng.choice(["library", "map"])
        g = {"act": "answer"} if intent in ("answer", "question") else {"act": "navigate", "nav": intent}
        return {"text": t, "cat": "cls_gesture_cooccur", "root": "gc:" + t, "frame": _frame(screen),
                "gesture": rng.choice(GESTURES), "gold": g, "dd": (0.6, 0.98), "pending": PENDING.get(cls)}
    if cls == "lesson_new":        # the merged lessons: Phases (core), Moon gravity and dust + Apollo (explorer)
        steps = [(L, i) for L in P._course() if L["id"] in NEW_LESSON_IDS for i in range(len(L["steps"]))
                 if L["steps"][i]["accept"]["type"] != "tap"]
        L, i = rng.choice(steps)
        t = new_lesson_answer(rng, L, i, "correct" if rng.random() < 0.65 else "wrong")
        return {"text": t, "cat": "cls_lesson_new_" + L["steps"][i]["accept"]["type"], "root": f"ln:{L['id']}:{i}:{t}",
                "frame": P.step_frame(L, i), "lesson": L["id"], "step": i, "dd": (0.6, 0.98)}
    if cls == "offers_new":
        kind = rng.choice(list(NEW_OFFERS))
        line, screens = NEW_OFFERS[kind]
        take = rng.random() < 0.75
        t = _pick(rng, TAKE if take else DECLINE, "on", split)
        return {"op": "offer", "text": t, "lines": [line], "gap": rng.uniform(0.05, 0.6), "cat": "cls_offers_new",
                "root": "on:" + t, "frame": _frame(rng.choice(screens), offer=kind),
                "gold": {"act": "navigate", "nav": "accept_offer" if take else "decline_offer"}, "dd": (0.6, 0.98),
                "pending": PENDING.get(cls)}
    raise ValueError(cls)


# ------------------------------------------------------------------------------------------------- coverage sweep
# One item for any inventory cell (director_model/coverage.json): the generator fills the cells with a gap, so every
# screen x intent has training data, not only the ones the scripted flows happen to visit.
NAV_SAY = {
    "mute_sound": ["mute", "mute the sound", "sound off", "turn the sound off", "be quiet"],     # the top bar's Mute
    "unmute_sound": ["unmute", "sound on", "turn the sound back on", "unmute the app"],
    "recenter": ["center", "look forward", "center the view", "reset view", "look ahead"],                # Center view
    "a11y": ["what do i do", "help me", "where am i", "what can i say", "i'm stuck", "give me a hint",
             "move the voice bar to the top", "reset the voice bar"],
    "skip_event": ["skip to the next event", "fast forward", "skip ahead", "jump to the next job"],
    "time_pause": ["pause the clock", "pause", "freeze time", "stop the clock"],
    "time_resume": ["start the clock", "resume the clock", "unpause", "run the clock"],
    "time_warp": ["time warp", "warp speed", "speed up time", "time warp four"],
    "cabin_tour": ["show me around", "give me the tour", "replay the tour"],
    "skip_tour": ["skip the tour", "end the tour", "i've got it"],
    "repeat": ["say that again", "repeat that", "what did you say", "come again"],
    "slower": ["slow down", "speak slower", "slower please"], "faster": ["speak faster", "speed up", "faster"],
    "settings": ["open settings", "show the settings", "accessibility settings"],
    "map": ["go to the map", "back to the map", "the patch map", "show me my patches"],
    "academy": ["go to the academy", "flight school", "back to the lessons"],
    "library": ["open the library", "explore the moon", "go to the library"],
    "go_mission": ["go to mission", "start the mission", "let's do the mission", "go on a mission"],
    "take_command": ["take command", "i'll take command", "start the shift", "launch"],
    "debrief": ["show me the debrief", "how did i do", "end the mission"],
    "fly_again": ["fly again", "play again", "new mission", "another mission"],
    "new_site": ["another site", "a different site", "new landing site"],
    "view_orbit": ["zoom out", "show me the whole moon", "go up"],
    "view_rover": ["show me the rover", "where is the rover", "follow the rover"],
    "view_site": ["back to the outpost", "zoom in", "show me the base"],
    "start": ["start", "let's start", "begin", "continue"], "next": ["next", "next one", "keep going", "what's next"],
    "back": ["go back", "back", "previous"], "end_shift": ["end the shift", "finish my shift"],
    "panel_power": ["open the power panel", "go to the power station", "the power panel please"],
    "panel_comm": ["open the comm panel", "show me the radio panel", "the comms panel"],
    "panel_habitat": ["open the habitat panel", "take me to the hab"],
    "panel_rover": ["open the rover panel", "the rover panel please"],
    "panel_radiation": ["open the radiation panel", "show me the shield panel"],
    "panel_back": ["back to my seat", "close the panel", "go back to my seat"],
    "accept_offer": ["yes", "yeah", "sure", "okay", "yes please", "let's go"],
    "decline_offer": ["no", "no thanks", "not now", "maybe later"],
    "pick_site": ["pick malapert massif", "go to shackleton rim", "land at the connecting ridge",
                  "choose de gerlache"],
    "task_choice": ["the ridge", "the crater", "left", "shelter now"], "lesson": ["lesson one", "lesson two"]}
CELL_SCREEN_OFFER = {"accept_offer": ["next_lesson", "mission", "fly_again", "tour"],
                     "decline_offer": ["next_lesson", "mission", "fly_again"], "task_choice": ["task"]}


def cell_item(cell: dict, rng: random.Random, split: str) -> dict | None:
    """An item that exercises one coverage cell ({"screen", "intent", "pending"?}), held-out phrases kept apart by
    pools.cls_split. None when the cell has no generator (reported as a gap)."""
    sc, intent = cell["screen"], cell["intent"]
    offer_of = {"video": "video", "prep": "prep_task"}
    if intent == "ignore:echo_os_voice":
        return {**cls_item("voice_echo_os", rng, split), "frame": _frame(sc, offer=offer_of.get(sc))}
    if intent == "gesture+voice":
        for _ in range(20):
            it = cls_item("gesture_cooccur", rng, split)
            if it["frame"]["screen"] == sc:
                return it
        return {**it, "frame": _frame(sc)}
    if "@" in intent:                                  # the new offers: nav:<accept|decline>_offer@<offer kind>
        nav, kind = intent[4:].split("@")
        t = _pick(rng, TAKE if nav == "accept_offer" else DECLINE, "on", split)
        return {"op": "offer", "text": t, "lines": [NEW_OFFERS[kind][0]], "gap": rng.uniform(0.05, 0.6),
                "cat": "cls_offers_new", "root": "on:" + t, "frame": _frame(sc, offer=kind),
                "gold": {"act": "navigate", "nav": nav}, "dd": (0.6, 0.98), "pending": PENDING.get("offers_new")}
    if intent.startswith("nav:") and intent[4:] in (*VIDEO_CTRL, *PREP_SAY):
        nav = intent[4:]
        pool = VIDEO_CTRL.get(nav) or PREP_SAY[nav]
        t = _pick(rng, pool, "vc" if nav.startswith("video") else "pp", split)
        return {"text": t, "cat": "cls_video_ctrl" if nav.startswith("video") else "cls_prep", "root": f"cv:{nav}:{t}",
                "frame": _frame(sc, offer=offer_of.get(sc)), "gold": {"act": "navigate", "nav": nav},
                "dd": (0.6, 0.98), "pending": cell.get("pending")}
    if intent == "ignore:video_audio":
        return cls_item("video_echo", rng, split)
    if intent == "step:video:answer":
        return cls_item("lesson_new", rng, split)
    if sc in offer_of and intent in ("ignore:chatter", "ignore:echo", "ignore:roomtalk", "question"):
        it = cell_item({"screen": "map", "intent": intent}, rng, split)
        return {**it, "frame": _frame(sc, offer=offer_of[sc]), "pending": cell.get("pending")} if it else None
    if intent.startswith("nav:"):
        nav = intent[4:]
        say = NAV_SAY.get(nav)
        if not say:
            return None
        t = _pick(rng, say, "nv:" + nav, split)
        offer = rng.choice(CELL_SCREEN_OFFER[nav]) if nav in CELL_SCREEN_OFFER else None
        opts = ["The ridge", "The crater", "Left", "Shelter now"] if offer == "task" else []
        fr = _frame(sc, offer=offer, options=opts)
        if sc in ("lesson", "ride"):
            L, i = rng.choice(P.lesson_steps())
            fr = {**P.step_frame(L, i), "offer": offer, "screen": sc}
        return {"text": t, "cat": "cov_nav", "root": f"nv:{nav}:{t}", "frame": fr,
                "gold": {"act": "navigate", "nav": nav}, "dd": (0.6, 0.98)}
    if intent.startswith("step:"):
        _, typ, outcome = intent.split(":")
        steps = [(L, i) for L in P._course() for i, st in enumerate(L["steps"])
                 if st["accept"]["type"] == typ and (sc == "ride") == bool(L.get("ride"))] or \
            [(L, i) for L in P._course() for i, st in enumerate(L["steps"]) if st["accept"]["type"] == typ]
        if not steps:
            return None
        L, i = rng.choice(steps)
        if typ in P.GLOBE_TYPES:
            t = P.globe_answer(rng, L, i, "correct" if outcome == "answer" else "wrong")
        else:
            for _ in range(12):
                it = P.academy_items(rng, L, i)
                if (outcome == "answer") == it["cat"].endswith("correct"):
                    break
            t = it["text"]
        fr = P.step_frame(L, i)
        fr["screen"] = sc
        return {"text": t, "cat": f"cov_step_{outcome}", "root": f"cs:{L['id']}:{i}:{t}", "frame": fr,
                "lesson": L["id"], "step": i}
    if intent == "question":
        it = P.explorer(rng, split)
        return {**it, "frame": _frame(sc)}
    if intent == "ignore:chatter":
        t = _pick(rng, P.LESSON_CHATTER, "lc", split)
        return {"text": t, "cat": "cls_chatter", "root": "lc:" + t, "frame": _frame(sc), "gold": {"act": "ignore"},
                "dd": (0.3, 0.95)}
    if intent == "ignore:roomtalk":
        t = _pick(rng, P.ROOM_TALK + MULTI_KID, "rt", split)
        return {"text": t, "cat": "cls_roomtalk", "root": "rt:" + t, "frame": _frame(sc), "gold": {"act": "ignore"},
                "dd": (0.75, 0.98)}
    if intent == "ignore:echo":
        it = P.cls_item("echo", rng, split)
        return {**it, "frame": _frame(sc)}
    if intent == "ignore:echo_os_voice":
        it = cls_item("voice_echo_os", rng, split)
        return {**it, "frame": _frame(sc)}
    if intent.startswith("cmd:"):
        want = intent[4:]
        if want in ("confirm", "cancel"):
            return {**P.yes_no(rng, want == "confirm"), "frame": _frame("cabin")}
        special = {"call_houston": ["call houston", "tell houston the shields are up", "houston we need help",
                                    "ask houston about the storm"],
                   "rule": ["if a storm comes go to the shelter", "when the power is low turn off science",
                            "if it gets dark more power to the heaters", "whenever the dose is high close the shields"],
                   "shelter_off": ["leave the shelter", "everyone out of the shelter", "come out of the shelter"],
                   "shelter_on": ["everyone into the shelter", "go to the shelter", "take cover in the shelter"],
                   "power_save": ["night mode on", "turn on night mode", "power save mode", "save power for the night"]}
        if want in special:
            from app.mission import nlu
            t = _pick(rng, special[want], "cm:" + want, split)
            cs = [c for c in map(nlu.valid, nlu.parse(t).get("commands") or []) if c]
            return {"text": t, "cat": "cov_cmd", "root": f"cm:{want}:{t}", "frame": _frame("cabin"),
                    "gold": {"act": "command", **({"command": cs[0]} if cs else {})}}
        for _ in range(40):
            it = P.mission_cmd(rng, split) if rng.random() < 0.7 else P.compound(rng, split)
            c = (it.get("gold") or {}).get("command")
            from app.director_model import features as FX
            if c and FX.cmd_type_of(c) == want:
                return {**it, "frame": _frame("cabin")}
        return None
    if intent == "guard:pii":
        return {**P.pii(rng), "frame": _frame(sc)}
    return None
