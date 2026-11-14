"""Voice steering: every `say` decision carries `style:{voice, steer_voice, tag, controls, emph, markup, perform}`.

Steer TTS Edge takes a style tag (51), numeric controls (12, z-scores against the voice's own neutral speech) and inline
markup. The Director picks them from the situation with one small table plus a few rules (docs/VOICE_STEERING.md):

    persona  -> base voice + tag          (CAPCOM confident, guide warm, the hardware's story nostalgic)
    situation -> tag + controls           (storm alert, all clear, night on low power, hard word, awe, badge, retry …)
    kid affect -> overrides               (frustrated/confused: slower, calmer, more pauses; excited: match it)
    a question -> rising ending           (f0_end up)
    readbacks -> emphasis                 (key numbers and the place name, as inline *markup*)
    safety    -> never anger, contempt, disgust, sarcasm, panic or disappointment toward a kid

Tags alone are weak style switches on Steer (docs/request.md: "combine a tag with explicit controls"), so every row
pairs its tag with controls that carry the effect.
"""
from __future__ import annotations

import re

# Persona -> Steer voice (voices.json of WhissleAI/steer-tts-edge; why each, in docs/VOICE_STEERING.md).
VOICES: dict[str, str] = {
    "guide": "voice_0644",     # female, mid register, average pace (195 Hz): warm, clear explainer
    "capcom": "voice_0213",    # male, mid register, fast pace (118 Hz): crisp mission control
    "story": "voice_0602",     # male, high register, slow pace (196 Hz): distinct first-person hardware voice
    "houston": "voice_0272",   # male, low register, average pace (109 Hz): Earth on the radio, "Houston here"
}
PERSONAS = tuple(VOICES)

# Tags never used toward a kid. A row or a caller asking for one gets the persona's tag instead.
FORBIDDEN = frozenset({"anger", "contempt", "disgust", "sarcasm", "panic", "disappointment", "irritation",
                       "frustration", "skeptical", "bored"})

PERSONA_BASE: dict[str, dict] = {
    "guide": {"tag": "interest", "controls": {}},
    "capcom": {"tag": "confidence", "controls": {"rate": 0.3}},
    "story": {"tag": "nostalgia", "controls": {"rate": -0.5, "f0_med": 0.4}},
    "houston": {"tag": "enunciated", "controls": {"rate": 1.2}},   # §4d: was -0.2 (2.1 words/s); still the steadiest
}

# Situation -> tag + controls (z). The table the tests pin.
SITUATIONS: dict[str, dict] = {
    # mission state
    "storm_alert":     {"tag": "determined", "controls": {"rate": 0.6, "loud": 0.8}},
    "storm_warning":   {"tag": "emphasis", "controls": {"rate": 0.3, "loud": 0.4}},
    "failure":         {"tag": "determined", "controls": {"rate": 0.3, "loud": 0.5}},
    "all_clear":       {"tag": "relief", "controls": {"rate": -0.2, "f0_iqr": 0.5}},
    "night_low_power": {"tag": "serenity", "controls": {"rate": -0.5, "loud": -0.4, "f0_iqr": -0.3}},
    "comm_open":       {"tag": "interest", "controls": {"rate": 0.2}},
    "mission_complete": {"tag": "pride", "controls": {"loud": 0.4, "f0_iqr": 0.8}},
    "readback":        {"tag": "confidence", "controls": {"rate": 0.3}},
    # content
    "explain":         {"tag": "enunciated", "controls": {"rate": -0.8, "pause": 0.4}},
    "awe":             {"tag": "amazement", "controls": {"rate": -0.4, "f0_iqr": 0.8}},
    "badge":           {"tag": "pride", "controls": {"rate": 0.3, "loud": 0.5, "f0_iqr": 1.0}},
    "passed":          {"tag": "happiness", "controls": {"f0_iqr": 0.6}},
    "retry":           {"tag": "sympathy", "controls": {"rate": -0.4, "loud": -0.2}},
    "story":           {"tag": "nostalgia", "controls": {"rate": -0.5, "f0_med": 0.4}},
    "lesson_brief":    {"tag": "interest", "controls": {"rate": -0.2}},
    "guard":           {"tag": "serenity", "controls": {"rate": -0.3, "loud": -0.3}},
    # ---- a11y / vocabulary (docs/VOICE_STEERING.md §4b) ----
    # Slower and enunciated, with clear gaps and a little more melody: new words for younger kids, vocab exercises.
    "vocab":           {"tag": "enunciated", "controls": {"rate": -1.0, "pause": 0.6, "f0_iqr": 0.3}},
}

# Kid affect (Arc / emotion) -> overrides. Applied on top of the situation, except it never speeds up a calming line.
AFFECT: dict[str, dict] = {
    "frustrated": {"tag": "sympathy", "controls": {"rate": -0.7, "pause": 0.8, "loud": -0.2}},
    "confused":   {"tag": "serenity", "controls": {"rate": -0.7, "pause": 0.8}},
    "scared":     {"tag": "serenity", "controls": {"rate": -0.6, "pause": 0.6, "loud": -0.3}},
    "anxious":    {"tag": "serenity", "controls": {"rate": -0.6, "pause": 0.6, "loud": -0.3}},
    "excited":    {"tag": "excited", "controls": {"rate": 0.4, "f0_iqr": 0.8}},
    "happy":      {"tag": "happiness", "controls": {"f0_iqr": 0.6}},
}
# During an alarm an upset kid gets a steady line: urgency stays in the words, the voice stops racing.
ALARM_SITUATIONS = frozenset({"storm_alert", "storm_warning", "failure"})
QUESTION_F0_END = 1.5
NUMBER_SITUATIONS = frozenset({"readback", "storm_alert", "storm_warning", "night_low_power", "failure", "explain"})
CONTROL_LIMIT = 2.5
PERFORM = {"genre": "children", "strength": 0.7}

_NUM = re.compile(r"(?<![\w*])(\d+(?:\.\d+)?)(?![\w*])")


def emphasis(text: str, places: list[str] | None = None, numbers: bool = True) -> list[str]:
    """Words/phrases to emphasize: key numbers and the place name(s) that appear in the text."""
    out: list[str] = []
    if numbers:
        for m in _NUM.findall(text):
            if m not in out and len(out) < 3:
                out.append(m)
    for p in places or []:
        if p and p.lower() in text.lower() and p not in out:
            out.append(p)
    return out


def apply_emphasis(text: str, emph: list[str] | None) -> str:
    """Wrap each emphasized word/phrase in Steer markup (`*word*`, one level, first occurrence per item)."""
    for w in emph or []:
        if not w:
            continue
        pat = re.compile(rf"(?<![\w*]){re.escape(w)}(?![\w*])", re.I)
        words = w.split()
        if len(words) == 1:
            text = pat.sub(lambda m: f"*{m.group(0)}*", text, count=1)
        else:
            text = pat.sub(lambda m: f"<emph>{m.group(0)}</emph>", text, count=1)
    return text


def _merge(base: dict, over: dict, calm_only: bool = False) -> dict:
    c = dict(base)
    for k, v in over.items():
        if calm_only and k in ("rate", "loud") and v > 0:
            continue
        c[k] = v
    return c


def style_for(voice: str = "guide", text: str = "", situation: str | None = None, emotion: str | None = None,
              places: list[str] | None = None, tag: str | None = None, controls: dict | None = None,
              vocab: list[str] | None = None) -> dict:
    """The style of one `say`. voice: persona (guide|capcom|story|houston). situation: a SITUATIONS key.
    emotion: the kid's affect (Arc / emotion stream). places: names to emphasize. tag/controls: explicit overrides."""
    persona = voice if voice in VOICES else "guide"
    if situation == "story":
        persona = "story"
    row = dict(PERSONA_BASE[persona])
    st = {"tag": row["tag"], "controls": dict(row["controls"])}
    if situation in SITUATIONS:
        s = SITUATIONS[situation]
        st = {"tag": s["tag"], "controls": _merge(st["controls"], s["controls"])}
    emo = (emotion or "").lower()
    if emo in AFFECT:
        a = AFFECT[emo]
        upset = emo in ("frustrated", "confused", "scared", "anxious")
        if situation in ALARM_SITUATIONS and upset:
            # keep the alert's tag (determined / emphasis) but drop the speed-up and loudness boost: steady, slower
            st["controls"] = {**{k: v for k, v in st["controls"].items() if k not in ("rate", "loud")},
                              "rate": -0.3, "pause": 0.5}
        elif situation in ("badge", "passed", "mission_complete") and upset:
            st["controls"] = _merge(st["controls"], {"rate": -0.3})       # good news stays good news, just gentler
        elif situation in ("night_low_power", "guard", "retry") and not upset:
            pass                                                          # an excited kid doesn't hype a calm line
        else:
            st = {"tag": a["tag"], "controls": _merge(st["controls"], a["controls"])}
    if tag:
        st["tag"] = tag
    if controls:
        st["controls"] = _merge(st["controls"], controls)
    if text.rstrip().endswith("?"):
        st["controls"]["f0_end"] = max(st["controls"].get("f0_end", 0.0), QUESTION_F0_END)
    if st["tag"] in FORBIDDEN:
        st["tag"] = PERSONA_BASE[persona]["tag"]
    st["controls"] = {k: round(max(-CONTROL_LIMIT, min(CONTROL_LIMIT, float(v))), 2) for k, v in st["controls"].items()}
    emph = emphasis(text, places, numbers=situation in NUMBER_SITUATIONS)
    out = {"voice": persona, "steer_voice": VOICES[persona], "tag": st["tag"], "controls": st["controls"],
           "perform": dict(PERFORM)}
    if situation:
        out["situation"] = situation
    if emph:
        out["emph"], out["markup"] = emph, True
    vw = vocab_words(text, vocab)          # a11y: vocabulary words said slower and stressed (§4b)
    if vw:
        out["vocab"], out["markup"] = vw, True
    return out


def situation_for(r: dict) -> str | None:
    """A Director response (the old single-action shape) -> the situation it speaks in."""
    a, src = r.get("action"), r.get("source") or ""
    if a == "guard":
        return "guard"
    if "glossary" in src:
        return "explain"
    if a == "play":
        return "awe"
    if a == "command":
        return "readback"
    if a == "status":
        st = r.get("state") or {}
        storm = (st.get("env") or {}).get("storm") or {}
        if storm.get("active"):
            return "storm_alert"
        if ((st.get("resources") or {}).get("power_pct") or 100) < 35 and not (st.get("env") or {}).get("in_sun", True):
            return "night_low_power"
        return "readback"
    return None


def event_situation(kind: str, warning: bool = False) -> str | None:
    """A mission sim event kind -> situation."""
    return {"solar_storm": "storm_warning" if warning else "storm_alert", "storm_end": "all_clear",
            "all_clear": "all_clear", "comm_open": "comm_open", "failure": "failure",
            "mission_complete": "mission_complete", "low_power": "night_low_power"}.get(kind)


def lesson_situation(status: str, badge: bool = False) -> str:
    """Academy attempt status -> situation."""
    if badge:
        return "badge"
    return {"passed": "passed", "retry": "retry", "hint": "retry", "missed": "retry", "brief": "lesson_brief",
            "done": "passed"}.get(status, "lesson_brief")


# ---- a11y: speaking pace + vocabulary emphasis (docs/VOICE_STEERING.md §4b, docs/ACCESSIBILITY.md) -------------------
SPEEDS = (0.75, 1.0, 1.25, 1.5)       # the kid's caption-bar speed setting
SPEED_RANGE = (0.6, 1.6)
# rate z per octave of speed. 3 (was 2): the model server build in use ignores `pace`, so rate carries the setting;
# 0.75x = rate -1.25 on top of the faster baseline (below) = slower than the old 1x.
SPEED_RATE_SLOPE = 4.0

# ---- the delivery baseline (docs/VOICE_STEERING.md §4d): Steer sounded low and slow --------------------------------
# Native controls first, added on top of every style at 1x: shorter phrase pauses (pause z), a faster articulation rate,
# a little more vocal energy (loud z). Then the backend caps long silences and loudness-normalises (app/loudness.py).
# Measured on the two eval lines: 2.96 -> 3.59 words/s (guide), 2.81 -> 3.37 (Nebula), WER unchanged (docs/VOICES.md).
BASE_CONTROLS = {"rate": 1.0, "pause": -1.5, "loud": 0.4}
SLOW_SITUATIONS = frozenset({"explain", "vocab"})   # slower on purpose: no baseline rate / pause, gentle gap cap
SLOW_PAUSE = 0.5          # at 0.75x and below: a little more pause than Steer's natural (comfortable, not choppy)
GAP_FAST_S, GAP_SLOW_S, GAP_KEEP_S =0.25, 0.45, 0.6  # inner silence cap at >= 1x, at <= 0.75x, on slow lines


def delivery(controls: dict | None, speed: float | None = None, slow: bool = False) -> tuple[dict, float, float]:
    """The style's controls -> (controls with the baseline + the kid's speed, pace, max inner gap in s).
    The pause baseline fades out toward 0.75x (a kid who slows the voice down gets its natural pauses back)."""
    try:
        s = max(SPEED_RANGE[0], min(SPEED_RANGE[1], float(speed or 1.0)))
    except (TypeError, ValueError):
        s = 1.0
    f = max(0.0, min(1.0, (s - 0.75) / 0.25))
    c = dict(controls or {})

    def add(k, v):
        c[k] = round(max(-CONTROL_LIMIT, min(CONTROL_LIMIT, float(c.get(k, 0.0)) + v)), 2)
    add("loud", BASE_CONTROLS["loud"])
    if slow:
        gap = GAP_KEEP_S
    else:
        add("rate", BASE_CONTROLS["rate"])
        p = BASE_CONTROLS["pause"] * f + (SLOW_PAUSE * (1 - f) if s < 1 else 0.0)
        if p:
            add("pause", p)
        gap = GAP_SLOW_S - (GAP_SLOW_S - GAP_FAST_S) * f
    c, pace = with_speed(c, s)
    return c, pace, round(gap, 3)


def speed_steer(speed: float | None) -> tuple[float, float]:
    """The kid's speed (0.75×–1.5×) → (rate z-offset, pace). `rate` is added on top of the Director's style so the
    voice still sounds like itself (an articulation change, not a tape speed-up); `pace` (Steer's global duration
    divisor) carries the rest, since rate z-scores are clamped at ±2.5. 1× → (0, 1)."""
    import math
    try:
        s = float(speed or 1.0)
    except (TypeError, ValueError):
        s = 1.0
    s = max(SPEED_RANGE[0], min(SPEED_RANGE[1], s))
    if abs(s - 1.0) < 1e-3:
        return 0.0, 1.0
    return round(SPEED_RATE_SLOPE * math.log2(s), 2), round(s ** 0.55, 2)


def with_speed(controls: dict | None, speed: float | None) -> tuple[dict, float]:
    """Controls with the speed's rate offset added (clamped) → (controls, pace)."""
    d, pace = speed_steer(speed)
    c = dict(controls or {})
    if d:
        c["rate"] = round(max(-CONTROL_LIMIT, min(CONTROL_LIMIT, float(c.get("rate", 0.0)) + d)), 2)
    return c, pace


def vocab_words(text: str, vocab: list[str] | None) -> list[str]:
    """The vocabulary words (lesson terms) that appear in `text`, in order, at most 3."""
    out: list[str] = []
    for w in vocab or []:
        w = str(w).strip()
        if w and w not in out and re.search(rf"(?<![\w*]){re.escape(w)}(?![\w*])", text, re.I) and len(out) < 3:
            out.append(w)
    return out


def apply_vocab(text: str, vocab: list[str] | None) -> str:
    """Wrap each vocabulary word in `<slow><emph>…</emph></slow>` (first occurrence): ×1.4 × 1.2 duration, +2.5 st,
    +4 dB on just that word, so a new word stands out without slowing the whole line."""
    for w in vocab or []:
        if not w:
            continue
        pat = re.compile(rf"(?<![\w*>]){re.escape(w)}(?![\w*<])", re.I)
        text = pat.sub(lambda m: f"<slow><emph>{m.group(0)}</emph></slow>", text, count=1)
    return text


def apply_markup(text: str, emph: list[str] | None = None, vocab: list[str] | None = None) -> str:
    """Vocabulary markup first, then emphasis on anything not already inside a vocab span."""
    vs = {v.lower() for v in vocab or []}
    return apply_emphasis(apply_vocab(text, vocab), [e for e in (emph or []) if e.lower() not in vs])


# ---- Settings: the kid's voice, rate and expressiveness (docs/VOICES.md, docs/VOICE_STEERING.md §4c) ------------------
EXPR_DEFAULT = 0.5                    # today's delivery: expressiveness 0.5 changes nothing
EXPR_F0_IQR = 0.8                     # f0_iqr offset at the lively end (1 → +0.8)
EXPR_F0_IQR_CALM = 1.4                # ... and at the calm end (0 → −1.4): at the faster delivery −0.8 barely moved
                                      # the melody (guide f0 IQR 4.1 → 3.7 st), +0.8 moved it a lot (→ 6.0 st)
EXPR_STRENGTH = (0.4, 1.0)            # the performance director's strength at 0 and 1 (0.7 at 0.5, as today)
# Calm end (< 0.25): the bounciest tags soften to their calm sibling. Alarm tags are never touched.
EXPR_CALM_TAGS = {"excited": "interest", "amazement": "interest", "happiness": "contentment", "pride": "contentment",
                  "ecstasy": "contentment"}


def clamp_expr(e) -> float:
    try:
        v = float(e)
    except (TypeError, ValueError):
        return EXPR_DEFAULT
    return EXPR_DEFAULT if v != v else max(0.0, min(1.0, v))


def with_expressiveness(tag: str, controls: dict | None, perform: dict | None, expr) -> tuple[str, dict, dict | None]:
    """Expressiveness 0–1 → (tag, controls, perform). k = 2·(e − 0.5) ∈ [−1, 1]:
    f0_iqr += 0.8·k above 0.5, 1.4·k below (melody range; clamped ±2.5), performance-director strength = 0.4 + 0.6·e (0.7 at 0.5: how much
    each sentence is shaped, its pitch, range, endings and pauses), and below 0.25 the liveliest tags soften (excited →
    interest, pride → contentment …). Rate, pace and loudness stay with the situation and the rate setting, so an alert
    is still urgent at every level."""
    e = clamp_expr(expr)
    c = dict(controls or {})
    if abs(e - EXPR_DEFAULT) < 1e-3:
        return tag, c, perform
    k = 2 * (e - EXPR_DEFAULT)
    c["f0_iqr"] = round(max(-CONTROL_LIMIT, min(CONTROL_LIMIT, float(c.get("f0_iqr", 0.0)) + (EXPR_F0_IQR if k > 0 else EXPR_F0_IQR_CALM) * k)), 2)
    if perform is not None:
        lo, hi = EXPR_STRENGTH
        perform = {**perform, "strength": round(lo + (hi - lo) * e, 2)}
    if e < 0.25:
        tag = EXPR_CALM_TAGS.get(tag, tag)
    return tag, c, perform


def pref_voice(persona: str, prefs: dict | None) -> str | None:
    """The Steer voice the kid's Settings choose for this persona, or None (the persona's own voice). The chosen voice
    is the guide's; CAPCOM, Houston and the story voice stay distinct unless the kid picked one voice for all."""
    p = prefs or {}
    v = p.get("voice")
    if not v:
        return None
    if persona == "guide" or p.get("voice_all"):
        return v
    return None


def apply_prefs(style: dict | None, persona: str, prefs: dict | None) -> dict | None:
    """A say's style with the Settings attached declaratively (`steer_voice`, `speed`, `expr`, `volume`). /api/tts resolves them
    (tts.clean_style + speed_steer), so one place applies them, for session lines and client-written lines alike."""
    if not prefs or style is None:
        return style
    out = dict(style)
    v = pref_voice(persona, prefs)
    if v:
        out["steer_voice"] = v
    rate = prefs.get("rate")
    if rate is not None and abs(float(rate) - 1.0) > 1e-3:
        out["speed"] = float(rate)
    e = prefs.get("expressiveness")
    if e is not None and abs(clamp_expr(e) - EXPR_DEFAULT) > 1e-3:
        out["expr"] = clamp_expr(e)
    vol = prefs.get("volume")
    if vol is not None and abs(float(vol) - 1.0) > 1e-3:
        out["volume"] = float(vol)
    return out
