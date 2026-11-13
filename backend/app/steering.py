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
    "houston": {"tag": "enunciated", "controls": {"rate": -0.2}},
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
              places: list[str] | None = None, tag: str | None = None, controls: dict | None = None) -> dict:
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
