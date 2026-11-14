"""The learned Director's step stream: ONE definition used by training (director_model/gen_sessions.py) and serving
(runtime.py), the same discipline as Head Start's `server/director.step_feats`.

One STEP per session event the Session sees (session.py `handle`, `_turn`, `poll`):

    hello · ui · playback start/end · typed · words (partial) · turn start/eager/end/resumed · arc · emotion · lesson
    · poll (telemetry + new sim events)

A step = `record(sess, ev, read)` (a plain JSON-able dict of everything the Director can see at that moment, BEFORE it
decides) -> `step_feats(rec, prev)` (F floats, documented in FEATS below) + `step_tokens(rec)` (hashed newest K words;
the last W words with per-word features for the span pointer heads).

Heads (labels in `labels_for`, decoding in `decode_command`): act, when, cmd_type, sub_type (a rule's `then`), amount,
load_to, load_from, task, query, rule_when, per-word spans w_load / w_num / w_task, card_attr, style tag + 3 control
bins, barge. Every head is optional per step (-1 = masked) so each data source labels only what it knows.
"""
from __future__ import annotations

import hashlib
import math
import re

import numpy as np

from ..mission import nlu

# ---------------------------------------------------------------------------------------------------- label spaces
ACTS = ["wait", "answer", "command", "confirm_yes", "confirm_no", "ask_clarify", "guard", "alert", "nudge", "ignore"]
CMD_TYPES = ["none", "allocate", "dispatch", "shelter_on", "shelter_off", "query", "call_houston", "end_shift", "rule",
             "confirm", "cancel"]
AMOUNTS = ["na", "percent", "delta_up", "delta_down", "little_up", "little_down", "all", "half", "none"]
LOADS = ["na", *nlu.LOADS]
TASKS = ["na", *nlu.TASKS]
QUERIES = ["na", *nlu.QUERIES]
TRIGGERS = ["na", *nlu.TRIGGERS]
ATTRS = ["na", "size", "where", "when", "who", "why", "what", "story", "about", "science", "misconception", "sun",
         "earth", "ice"]
# Steer tags the policy may choose (every tag steering.py's tables can produce). Forbidden tags are not in the space.
STYLE_TAGS = ["interest", "confidence", "nostalgia", "enunciated", "determined", "emphasis", "relief", "serenity",
              "pride", "amazement", "happiness", "sympathy", "excited"]
CTRL = ("rate", "loud", "f0_iqr")          # each binned: 0 lower (< -0.15), 1 neutral, 2 higher (> 0.15)

EVENTS = ["hello", "ui", "playback_start", "playback_end", "typed", "words", "turn_start", "turn_eager", "turn_end",
          "turn_resumed", "arc", "emotion", "lesson", "poll"]
UI_EVENTS = ["tap_place", "tap_artifact", "button", "end_shift", "lesson_answer", "barge_in", "kid_done",
             "mission_start", "other"]
SIM_EVENTS = ["solar_storm", "storm_warning", "comm_open", "storm_end", "dose_alert", "low_power", "sunset", "failure",
              "mission_complete", "other"]
EMOTIONS = ["neutral", "happy", "excited", "frustrated", "confused", "scared", "bored"]
MODES = ["mission", "academy", "cadet"]
FLOOR = ["none", "kid", "guide", "crew"]
ACCEPT = ["intent", "command", "tap", "keywords", "choice"]
LESSON_ST = ["brief", "task", "passed", "retry", "done"]
K, W = 8, 16                       # hashed newest K words (bag); last W words for the span pointer heads
WF = 6                             # per-word features (step_tokens)

# Model heads: name -> number of classes (1 = sigmoid). Word heads (per word of the last W) are listed in WORD_HEADS.
HEADS = {"act": len(ACTS), "when": 1, "cmd_type": len(CMD_TYPES), "sub_type": len(CMD_TYPES), "amount": len(AMOUNTS),
         "load_to": len(LOADS), "load_from": len(LOADS), "task": len(TASKS), "query": len(QUERIES),
         "rule_when": len(TRIGGERS), "card_attr": len(ATTRS), "style": len(STYLE_TAGS), "s_rate": 3, "s_loud": 3,
         "s_f0_iqr": 3, "barge": 1}
WORD_HEADS = ("w_load", "w_num", "w_task")

# ---------------------------------------------------------------------------------------------------- lexicon
STOP = set("a an the to of in on at for and or but is are was were be do does did it its this that these those i you "
           "we me my our us he she they them his her their what s".split())
WH = re.compile(r"^(what|whats|where|when|who|whose|why|how|which|is|are|can|could|do|does|did|will|tell)\b")
NAME_GIVEN = re.compile(r"\b(my name is|my name s|i m called|call me|i live (at|on|in)|my address|my phone|my number is)\b")
PRONOUN = re.compile(r"\b(it|that|this one|that one)\b")
CORRECTION = re.compile(r"\b(no wait|wait no|no no|i mean|sorry|actually|not that)\b")
DEFINE = re.compile(r"\b(what does|what s|what is|whats|what are|mean|means|meaning)\b")
MISCON = re.compile(r"\b(cheese|no craters|own light|moon is a star|always dark|bigger than (the )?earth|moon is (a )?planet|"
                    r"never gets? (any )?(sun|light))\b")
TOUR = re.compile(r"\b(rovers?|buggies|landers|landing sites|crash(es| sites)?|impacts?|instruments|experiments|"
                  r"reflectors|mirrors|hardware|left (behind )?on the moon|left behind|junk|trash)\b")
SOUND = re.compile(r"\b(launch|liftoff|lift off|blast ?off|countdown|splash ?down|burn|record|loud and clear)\b")
CREW = re.compile(r"\b(astronauts?|crew|hear|listen|say about|recording|play)\b")
NUMW = re.compile(r"^(\d+(\.\d+)?|zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|"
                  r"fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|"
                  r"hundred|percent)$")
LOAD_WORD = set()
for _p, _l in nlu.LOAD_WORDS:
    for _alt in _p.split("|"):
        for _w in re.sub(r"[^a-z ]", " ", _alt.replace("?", "")).split():
            if _w not in STOP:
                LOAD_WORD.add(_w)
TASK_WORD = {"ice", "water", "dig", "mine", "collect", "fix", "repair", "mend", "solar", "panel", "panels", "array",
             "arrays", "return", "home", "back", "explore", "scout", "investigate", "adventure", "crater", "look"}
QUERY_WORD = {"how", "what", "status", "report", "left", "much", "many", "level", "check"}


def norm(text: str) -> str:
    return nlu._words_to_digits(nlu.norm(text or ""))


def words_of(text: str) -> list[str]:
    return norm(text).split()


def hash_tok(w: str, buckets: int = 1 << 20) -> int:
    """Stable word hash (0 = pad); the model folds it into its own table size."""
    w = re.sub(r"[^a-z0-9']", "", (w or "").lower())
    return 1 + int(hashlib.blake2b(w.encode(), digest_size=4).hexdigest(), 16) % (buckets - 1) if w else 0


def _emo(e: str | None) -> str:
    e = (e or "").lower()
    if e in ("anxious",):
        return "scared"
    if e in ("joy", "joyful"):
        return "happy"
    return e if e in EMOTIONS else "neutral"


def _clip_log(s: float | None, cap: float = 60.0) -> float:
    if s is None or s < 0:
        return 1.0
    return math.log1p(min(s, cap)) / math.log1p(cap)


# ---------------------------------------------------------------------------------------------------- the record
def record(sess, ev: dict, read: dict | None = None) -> dict:
    """Everything the Director sees at this event, BEFORE it decides. `sess` is a session.Session (or the generator's,
    which is the same class); `ev` the incoming message ({"t": ...}); `read` the Arc Tagger read-out (readout.summarize)
    when the Session has one (only at the turn end: the Session tags the final words)."""
    b = sess.belief
    k = b["kid"]
    now = sess.clock()
    t = ev.get("t")
    kind = t
    if t == "playback":
        kind = "playback_start" if ev.get("state") == "start" else "playback_end"
    elif t == "turn":
        kind = {"start": "turn_start", "eager": "turn_eager", "end": "turn_end", "resumed": "turn_resumed"}.get(
            ev.get("state"), "words")
    elif t not in EVENTS:
        kind = "poll" if t == "poll" else "ui"
    if kind in ("words", "turn_start", "turn_eager", "turn_resumed", "turn_end"):
        text = ev.get("text") or (k.get("words") if kind != "turn_start" else "") or ""
    elif kind == "typed":
        text = ev.get("text") or ""
    else:
        text = ""
    st = b.get("state") or {}
    playing = b.get("playing") or {}
    lesson = b.get("lesson") or {}
    new_ev = []
    if kind == "poll":
        mi = sess._mission()
        evs = list(getattr(mi, "events", []) or [])
        for e in evs[sess.ev_seen:]:
            kd = e.get("kind")
            if kd == "solar_storm":
                stm = sess._storm_of(e)
                kd = "storm_warning" if (stm and e.get("t_h", 0) < stm.start_h) else "solar_storm"
            new_ev.append(kd)
    from .. import director as _dir
    mid = b.get("mission_id")
    pend = bool(st.get("pending")) or bool(mid and mid in _dir.PENDING)
    return {
        "kind": kind, "ui": ev.get("event") if t == "ui" else None, "source": ev.get("source"),
        "text": text, "mode": b.get("mode"), "mission": bool(mid), "role": b.get("role"),
        "floor": b.get("floor"), "kid_open": bool(k.get("open")),
        "dd": k.get("device_directed") if t != "arc" or ev.get("device_directed") is None else ev["device_directed"],
        "cc": k.get("command_complete") if t != "arc" or ev.get("command_complete") is None else ev["command_complete"],
        "emotion": (ev.get("label") if t == "emotion" else None) or k.get("emotion"),
        "playing_kind": playing.get("kind"), "playing_text": playing.get("text") or "",
        "since_play": (now - playing["since"]) if playing.get("since") is not None else None,
        "since_turn_start": (now - k["start"]) if k.get("start") is not None and k.get("open") else None,
        "since_speech": now - sess.last_speech if sess.last_speech > -1e8 else None,
        "since_nudge": now - sess.last_nudge if sess.last_nudge > -1e8 else None,
        "now": now, "n_pending": len(sess.pending), "n_held": sum(len(x[1]) for x in sess.held),
        "last_place": bool(b.get("last_place")), "referent": bool(b.get("referent")),
        "state": _state_view(st) if st else None, "pending_confirm": pend,
        "lesson": {"active": bool(lesson), "step": lesson.get("step") or 0, "status": lesson.get("status"),
                   "accept": lesson.get("accept") or _accept_of(lesson)} if lesson else None,
        "new_events": new_ev,
        "read": _read_view(read),
    }


def _accept_of(lesson: dict) -> str | None:
    try:
        from ..academy.content import lesson as _lesson
        L = _lesson(lesson.get("lesson_id") or "")
        return L["steps"][int(lesson.get("step") or 0)]["accept"]["type"] if L else None
    except Exception:  # noqa: BLE001
        return None


def _state_view(s: dict) -> dict:
    r, env, loads = s.get("resources") or {}, s.get("env") or {}, s.get("loads") or {}
    storm = env.get("storm") or {}
    return {"power": r.get("power_pct"), "life": r.get("life_support_pct"), "dose": r.get("dose_msv"),
            "dose_limit": r.get("dose_limit_msv") or 50, "dose_rate": r.get("dose_rate_msv_h"),
            "loads": {x: loads.get(x) for x in nlu.LOADS}, "storm": bool(storm.get("active")),
            "sev": storm.get("severity") or 0, "in_sun": env.get("in_sun"), "earth": env.get("earth_visible"),
            "next_comm": env.get("next_comm_window_h"), "shelter": bool(s.get("shelter")),
            "rover_busy": bool((s.get("rover") or {}).get("busy")), "alerts": len(s.get("alerts") or []),
            "day": s.get("day") or 1, "over": bool(s.get("over"))}


def _read_view(read: dict | None) -> dict | None:
    if not read or not read.get("available"):
        return None
    act = set(read.get("act") or [])
    intent = set(read.get("intent") or [])
    return {"q": "question" in act, "cmd": "command_request" in act, "stmt": "statement" in act,
            "dd": "device_directed" in act, "intents": sorted(intent)[:8], "n_mentions": len(read.get("mentions") or []),
            "n_numbers": len(read.get("numbers") or []), "pii": bool(read.get("pii")),
            "hard_pii": bool(read.get("hard_pii")), "complete": bool(read.get("complete"))}


# ---------------------------------------------------------------------------------------------------- features
FEATS: list[str] = (
    [f"ev_{e}" for e in EVENTS]                                    # which event this step is (one-hot)
    + [f"ui_{u}" for u in UI_EVENTS]                               # the UI event (taps, buttons, end shift, barge_in…)
    + ["src_voice"]                                                 # a typed turn that came from the voice path
    + ["dt_prev", "since_turn_start", "since_speech", "since_nudge", "since_play"]  # log-scaled seconds (1 = unknown)
    + [f"mode_{m}" for m in MODES] + ["mission_on", "role_set"]
    + [f"floor_{f}" for f in FLOOR] + ["kid_open", "play_guide", "play_crew", "n_pending", "n_held"]
    # words: what the kid said so far (the Arc ear's partial/final words)
    + ["nw", "n_changed", "revised", "changed", "has_num", "n_loads", "lx_task", "lx_vehicle", "lx_question", "lx_wh",
       "lx_confirm", "lx_cancel", "lx_negation", "lx_cond", "lx_more", "lx_less", "lx_little", "lx_all", "lx_half",
       "lx_off", "lx_on", "lx_shelter", "lx_houston", "lx_end_shift", "lx_cold", "lx_define", "lx_name_given",
       "lx_pronoun", "lx_correction", "lx_miscon", "lx_tour", "lx_sound", "lx_crew", "echo_share", "gaz_match",
       "gaz_artifact", "last_stop"]
    # the mission NLU rules on these words (the rules as evidence, not as the answer)
    + ["nlu_n", "nlu_clarify", "nlu_conf"] + [f"nlu_{c}" for c in CMD_TYPES[1:]]
    # Arc Tagger read-out (turn end only; tag_avail = 0 elsewhere or with no model server)
    + ["tag_avail", "tag_q", "tag_cmd", "tag_stmt", "tag_dd", "tag_mentions", "tag_numbers", "tag_pii", "tag_hard_pii",
       "tag_complete"]
    # Arc audio metadata
    + ["dd_avail", "dd", "cc_avail", "cc"] + [f"emo_{e}" for e in EMOTIONS]
    # mission telemetry / state
    + ["st_avail", "power", "life", "dose_frac", "dose_rate", *[f"load_{x}" for x in nlu.LOADS], "storm", "storm_sev",
       "in_sun", "earth_vis", "next_comm", "shelter", "rover_busy", "alerts", "day", "over", "pending_confirm",
       "d_power", "d_life", "d_dose", "low_power_night", "referent", "last_place"]
    + [f"sim_{e}" for e in SIM_EVENTS]                              # new sim events this poll
    # lesson state
    + ["lesson_on", "lesson_step"] + [f"acc_{a}" for a in ACCEPT] + [f"ls_{s}" for s in LESSON_ST]
)
F = len(FEATS)
_IDX = {k: i for i, k in enumerate(FEATS)}


def _gaz():
    from ..academy.grade import gaz
    return gaz()


def lexical(ws: list[str], playing_text: str = "") -> dict:
    t = " ".join(ws)
    d: dict = {}
    d["has_num"] = float(any(re.fullmatch(r"\d+(\.\d+)?", w) for w in ws))
    d["n_loads"] = min(len(nlu.find_loads(t)), 3) / 3
    d["lx_task"] = float(any(rx.search(t) for rx, _ in nlu.TASK_WORDS))
    d["lx_vehicle"] = float(bool(nlu.VEHICLE.search(t)))
    d["lx_question"] = float(bool(nlu.QUESTION.search(t)))
    d["lx_wh"] = float(bool(WH.search(t)))
    d["lx_confirm"] = float(bool(nlu.CONFIRM.match(t)))
    d["lx_cancel"] = float(bool(nlu.CANCEL.match(t)))
    d["lx_negation"] = float(bool(nlu.NEGATION.search(t)))
    d["lx_cond"] = float(bool(re.match(r"(if|when|whenever|in case|as soon as)\b", t)))
    d["lx_more"] = float(bool(nlu.MORE.search(t)))
    d["lx_less"] = float(bool(nlu.LESS.search(t)))
    d["lx_little"] = float(bool(nlu.LITTLE.search(t)))
    d["lx_all"] = float(bool(nlu.ALL.search(t)))
    d["lx_half"] = float(bool(nlu.HALF.search(t)))
    d["lx_off"] = float(bool(nlu.OFF.search(t)))
    d["lx_on"] = float(bool(nlu.ON.search(t)))
    d["lx_shelter"] = float(bool(nlu.SHELTER_IN.search(t)))
    d["lx_houston"] = float(bool(nlu.HOUSTON.search(t)))
    d["lx_end_shift"] = float(bool(nlu.END_SHIFT.match(t)))
    d["lx_cold"] = float(bool(nlu.COLD.search(t)))
    d["lx_define"] = float(bool(DEFINE.search(t)))
    d["lx_name_given"] = float(bool(NAME_GIVEN.search(t)))
    d["lx_pronoun"] = float(bool(PRONOUN.search(t)))
    d["lx_correction"] = float(bool(CORRECTION.search(t)))
    d["lx_miscon"] = float(bool(MISCON.search(t)))
    d["lx_tour"] = float(bool(TOUR.search(t)))
    d["lx_sound"] = float(bool(SOUND.search(t)))
    d["lx_crew"] = float(bool(CREW.search(t)))
    pw = set(words_of(playing_text))
    d["echo_share"] = (sum(w in pw for w in ws) / len(ws)) if (ws and pw) else 0.0
    p = _gaz().match_text(t) if ws else None
    d["gaz_match"] = float(p is not None)
    d["gaz_artifact"] = float(p is not None and p.kind == "artifact")
    d["last_stop"] = float(bool(ws) and ws[-1] in STOP)
    return d


def nlu_view(ws: list[str]) -> dict:
    """The mission NLU rules (no LLM) on the words: the first command's type, how many, clarify, confidence."""
    if not ws:
        return {"n": 0, "type": None, "clarify": False, "conf": 0.0}
    r = nlu.parse(" ".join(ws))
    cmds = [c for c in map(nlu.valid, r["commands"]) if c]
    return {"n": len(cmds), "type": cmd_type_of(cmds[0]) if cmds else None, "clarify": bool(r["needs_clarify"]),
            "conf": float(r["confidence"] or 0.0)}


def step_feats(rec: dict, prev: dict | None) -> np.ndarray:
    x = np.zeros(F, np.float32)

    def s(k, v):
        x[_IDX[k]] = float(v)
    s(f"ev_{rec['kind']}", 1)
    if rec.get("ui"):
        s(f"ui_{rec['ui'] if rec['ui'] in UI_EVENTS else 'other'}", 1)
    s("src_voice", rec.get("source") in ("voice", "listen"))
    s("dt_prev", _clip_log(rec["now"] - prev["now"]) if prev else 1.0)
    for k in ("since_turn_start", "since_speech", "since_nudge", "since_play"):
        s(k, _clip_log(rec.get(k)))
    if rec.get("mode") in MODES:
        s(f"mode_{rec['mode']}", 1)
    s("mission_on", rec.get("mission"))
    s("role_set", bool(rec.get("role")))
    if rec.get("floor") in FLOOR:
        s(f"floor_{rec['floor']}", 1)
    s("kid_open", rec.get("kid_open"))
    s("play_guide", rec.get("playing_kind") == "guide")
    s("play_crew", rec.get("playing_kind") == "crew")
    s("n_pending", min(rec.get("n_pending") or 0, 6) / 6)
    s("n_held", min(rec.get("n_held") or 0, 6) / 6)
    ws = words_of(rec.get("text") or "")
    pws = words_of(prev.get("text") or "") if prev else []
    n = len(ws)
    k = 0
    while k < min(len(pws), n) and pws[k] == ws[k]:
        k += 1
    s("nw", min(n, 24) / 24)
    s("changed", float(k < len(pws) or n != len(pws)))
    s("revised", float(k < len(pws)))
    s("n_changed", min(n - k, 6) / 6)
    for key, v in lexical(ws, rec.get("playing_text") or "").items():
        s(key, v)
    nv = nlu_view(ws)
    s("nlu_n", min(nv["n"], 3) / 3)
    s("nlu_clarify", nv["clarify"])
    s("nlu_conf", nv["conf"])
    if nv["type"]:
        s(f"nlu_{nv['type']}", 1)
    rd = rec.get("read")
    if rd:
        s("tag_avail", 1)
        s("tag_q", rd["q"]); s("tag_cmd", rd["cmd"]); s("tag_stmt", rd["stmt"]); s("tag_dd", rd["dd"])
        s("tag_mentions", min(rd["n_mentions"], 3) / 3); s("tag_numbers", min(rd["n_numbers"], 3) / 3)
        s("tag_pii", rd["pii"]); s("tag_hard_pii", rd["hard_pii"]); s("tag_complete", rd["complete"])
    if rec.get("dd") is not None:
        s("dd_avail", 1); s("dd", rec["dd"])
    if rec.get("cc") is not None:
        s("cc_avail", 1); s("cc", rec["cc"])
    s(f"emo_{_emo(rec.get('emotion'))}", 1)
    st = rec.get("state")
    if st:
        s("st_avail", 1)
        s("power", (st["power"] or 0) / 100); s("life", (st["life"] or 0) / 100)
        s("dose_frac", min((st["dose"] or 0) / (st["dose_limit"] or 50), 1.5))
        s("dose_rate", min((st["dose_rate"] or 0) / 2, 2))
        for ld in nlu.LOADS:
            s(f"load_{ld}", (st["loads"].get(ld) or 0) / 100)
        s("storm", st["storm"]); s("storm_sev", st["sev"] / 3); s("in_sun", bool(st["in_sun"]))
        s("earth_vis", bool(st["earth"]))
        s("next_comm", min(st["next_comm"], 48) / 48 if st["next_comm"] is not None else 1.0)
        s("shelter", st["shelter"]); s("rover_busy", st["rover_busy"]); s("alerts", min(st["alerts"], 3) / 3)
        s("day", st["day"] / 10); s("over", st["over"])
        s("low_power_night", float((st["power"] or 100) < 35 and st["in_sun"] is False))
        pst = (prev or {}).get("state")
        if pst:
            s("d_power", np.clip(((st["power"] or 0) - (pst["power"] or 0)) / 10, -2, 2))
            s("d_life", np.clip(((st["life"] or 0) - (pst["life"] or 0)) / 10, -2, 2))
            s("d_dose", np.clip(((st["dose"] or 0) - (pst["dose"] or 0)), -2, 2))
    s("pending_confirm", rec.get("pending_confirm"))
    s("referent", rec.get("referent")); s("last_place", rec.get("last_place"))
    for e in rec.get("new_events") or []:
        s(f"sim_{e if e in SIM_EVENTS else 'other'}", 1)
    ls = rec.get("lesson")
    if ls and ls.get("active"):
        s("lesson_on", 1); s("lesson_step", min(ls.get("step") or 0, 10) / 10)
        if ls.get("accept") in ACCEPT:
            s(f"acc_{ls['accept']}", 1)
        if ls.get("status") in LESSON_ST:
            s(f"ls_{ls['status']}", 1)
    return x


def word_feats(w: str, playing: set) -> list[float]:
    return [float(bool(NUMW.match(w))), float(w in LOAD_WORD), float(w in TASK_WORD), float(w in STOP),
            float(w in playing), float(w in QUERY_WORD)]


def step_tokens(rec: dict):
    """(toks [K], wtok [W], wfeat [W, WF]): hashes of the newest K words; the last W words (left-padded) with
    [number word, load synonym, task word, stop word, in what's playing, query word]."""
    ws = words_of(rec.get("text") or "")
    toks = np.zeros(K, np.int64)
    tk = [hash_tok(w) for w in ws[-K:]]
    if tk:
        toks[K - len(tk):] = tk
    wtok = np.zeros(W, np.int64)
    wfeat = np.zeros((W, WF), np.float32)
    playing = set(words_of(rec.get("playing_text") or ""))
    last = ws[-W:]
    off = W - len(last)
    for j, w in enumerate(last):
        wtok[off + j] = hash_tok(w)
        wfeat[off + j] = word_feats(w, playing)
    return toks, wtok, wfeat


# ---------------------------------------------------------------------------------------------------- labels
def cmd_type_of(c: dict | None) -> str:
    if not c:
        return "none"
    t = c.get("type")
    if t == "shelter":
        return "shelter_on" if c.get("on") else "shelter_off"
    return t if t in CMD_TYPES else "none"


def amount_of(c: dict) -> str:
    a = c.get("amount") or {}
    k, v = a.get("kind"), a.get("value") or 0
    if k == "delta":
        return "delta_down" if v < 0 else "delta_up"
    if k == "little":
        return "little_down" if v < 0 else "little_up"
    return k if k in AMOUNTS else "na"


def cmd_labels(c: dict | None) -> dict:
    """Class labels of one Command (indices; -1 = masked for this command)."""
    out = {"cmd_type": CMD_TYPES.index(cmd_type_of(c))}
    if not c:
        return out
    body = c.get("then") if c.get("type") == "rule" else c
    if c.get("type") == "rule":
        out["rule_when"] = TRIGGERS.index(c["when"]) if c.get("when") in TRIGGERS else -1
        out["sub_type"] = CMD_TYPES.index(cmd_type_of(body))
    else:
        out["rule_when"] = 0
        out["sub_type"] = 0
    body = body or {}
    bt = body.get("type")
    out["amount"] = AMOUNTS.index(amount_of(body)) if bt == "allocate" else 0
    out["load_to"] = LOADS.index(body["to"]) if bt == "allocate" and body.get("to") in LOADS else 0
    out["load_from"] = LOADS.index(body["from"]) if bt == "allocate" and body.get("from") in LOADS else 0
    out["task"] = TASKS.index(body["task"]) if bt == "dispatch" and body.get("task") in TASKS else 0
    out["query"] = QUERIES.index(body["what"]) if bt == "query" and body.get("what") in QUERIES else 0
    return out


def spans(ws: list[str], c: dict | None) -> dict[str, list[int]]:
    """Per-word span labels over `ws` (the heard words): which words carry the load, the number, the task."""
    body = (c or {}).get("then") if (c or {}).get("type") == "rule" else c
    body = body or {}
    out = {"w_load": [0] * len(ws), "w_num": [0] * len(ws), "w_task": [0] * len(ws)}
    t = " ".join(ws)
    if body.get("type") == "allocate":
        for rx, load in nlu.LOAD_RE:
            for m in rx.finditer(t):
                if load in (body.get("to"), body.get("from")):
                    _mark(out["w_load"], t, m.start(), m.end())
        a = body.get("amount") or {}
        if a.get("kind") in ("percent", "delta") and a.get("value") is not None:
            v = abs(float(a["value"]))
            for m in re.finditer(r"\b\d+(\.\d+)?\b", t):
                if abs(float(m.group(0)) - v) < 1e-6:
                    _mark(out["w_num"], t, m.start(), m.end())
    if body.get("type") == "dispatch":
        for rx, name in nlu.TASK_WORDS:
            if name == body.get("task"):
                for m in rx.finditer(t):
                    _mark(out["w_task"], t, m.start(), m.end())
    return out


def _mark(arr: list[int], t: str, a: int, b: int):
    i0 = len(t[:a].split()) if t[:a].strip() else 0
    i1 = len(t[:b].split())
    for i in range(i0, max(i1, i0 + 1)):
        if i < len(arr):
            arr[i] = 1


def style_labels(style: dict | None) -> dict:
    if not style:
        return {}
    c = style.get("controls") or {}
    out = {"style": STYLE_TAGS.index(style["tag"]) if style.get("tag") in STYLE_TAGS else -1}
    for k in CTRL:
        v = float(c.get(k, 0.0))
        out[f"s_{k}"] = 0 if v < -0.15 else 2 if v > 0.15 else 1
    return out


def rules_act(r: dict | None) -> str:
    """A director.direct() response -> the act it amounts to (the rules' decision at a turn end)."""
    if r is None:
        return "wait"
    a = r.get("action")
    if a == "guard":
        return "guard"
    if a == "none":
        return "ignore"
    if a == "ask":
        return "ask_clarify"
    if a in ("command", "status", "houston"):
        ty = (r.get("command") or {}).get("type")
        cmds = (r.get("nlu") or {}).get("commands") or []
        if cmds and cmds[0].get("type") in ("confirm", "cancel"):
            ty = cmds[0]["type"]
        return "confirm_yes" if ty == "confirm" else "confirm_no" if ty == "cancel" else "command"
    return "answer"


def rules_command(r: dict | None) -> dict | None:
    if not r:
        return None
    cmds = (r.get("nlu") or {}).get("commands") or []
    return cmds[0] if cmds else r.get("command")


# ---------------------------------------------------------------------------------------------------- decoding
def _num_from(ws: list[str]) -> float | None:
    t = nlu._words_to_digits(" ".join(ws) + " percent")
    m = re.search(r"\d+(?:\.\d+)?", t)
    return float(m.group(0)) if m else None


def decode_command(o: dict, ws: list[str]) -> dict | None:
    """Model outputs at one step (probabilities, numpy) + the heard words -> a Command (validated by nlu.valid)."""
    ty = CMD_TYPES[int(np.argmax(o["cmd_type"]))]
    if ty == "none":
        return None
    last = ws[-W:]
    off = W - len(last)

    def span(key):
        p = o[key][off:]
        return [w for w, q in zip(last, p) if q >= 0.5]

    def body(t):
        if t == "allocate":
            am = AMOUNTS[int(np.argmax(o["amount"]))]
            to = LOADS[int(np.argmax(o["load_to"]))]
            fr = LOADS[int(np.argmax(o["load_from"]))]
            v = _num_from(span("w_num"))
            if am == "percent":
                amount = {"kind": "percent", "value": v}
            elif am in ("delta_up", "delta_down"):
                vv = v if v is not None else 10
                amount = {"kind": "delta", "value": -vv if am == "delta_down" else vv}
            elif am in ("little_up", "little_down"):
                amount = {"kind": "little", "value": -5 if am == "little_down" else 5}
            elif am == "all":
                amount = {"kind": "all", "value": 100}
            elif am == "half":
                amount = {"kind": "half", "value": 50}
            elif am == "none":
                amount = {"kind": "none", "value": 0}
            else:
                return None
            if amount.get("value") is not None and float(amount["value"]).is_integer():
                amount["value"] = int(amount["value"])
            return {"type": "allocate", "to": to, "amount": amount, "from": None if fr == "na" else fr}
        if t == "dispatch":
            return {"type": "dispatch", "vehicle": "rover", "task": TASKS[int(np.argmax(o["task"]))], "target": None}
        if t in ("shelter_on", "shelter_off"):
            return {"type": "shelter", "on": t == "shelter_on"}
        if t == "query":
            return {"type": "query", "what": QUERIES[int(np.argmax(o["query"]))]}
        if t == "call_houston":
            return {"type": "call_houston", "text": re.sub(r"\s+", " ", nlu.HOUSTON.sub(" ", " ".join(ws))).strip()}
        if t in ("end_shift", "confirm", "cancel"):
            return {"type": t}
        return None
    if ty == "rule":
        then = body(CMD_TYPES[int(np.argmax(o["sub_type"]))])
        c = {"type": "rule", "when": TRIGGERS[int(np.argmax(o["rule_when"]))], "then": then}
    else:
        c = body(ty)
    return nlu.valid(c) if c else None


def same_command(a: dict | None, b: dict | None) -> bool:
    """Exact match on type + slots (dispatch target and Houston text are not compared)."""
    if not a or not b or a.get("type") != b.get("type"):
        return False
    t = a["type"]
    if t == "allocate":
        aa, ba = a.get("amount") or {}, b.get("amount") or {}
        if a.get("to") != b.get("to") or (a.get("from") or None) != (b.get("from") or None):
            return False
        if aa.get("kind") != ba.get("kind"):
            return False
        if aa.get("kind") in ("percent", "delta", "little"):
            return aa.get("value") is not None and ba.get("value") is not None and \
                abs(float(aa["value"]) - float(ba["value"])) < 1e-6
        return True
    if t == "dispatch":
        return a.get("task") == b.get("task")
    if t == "shelter":
        return a.get("on") == b.get("on")
    if t == "query":
        return a.get("what") == b.get("what")
    if t == "rule":
        return a.get("when") == b.get("when") and same_command(a.get("then"), b.get("then"))
    return True
