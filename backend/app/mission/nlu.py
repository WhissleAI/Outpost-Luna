"""Mission command understanding: a kid's words (+ Arc read-out + the current State) -> Commands (docs/MISSION_CONTRACT.md).

Rules first (synonyms, amounts, direction, compound, negation, conditionals, confirm/cancel). When the rules find
nothing, an LLM fallback (Anthropic, thinking off, as llm.py) gets the State and must answer with Commands as JSON;
every one is validated against the contract schema and anything invalid is dropped.

Returned shape: {"commands": [Command, ...], "confidence": float, "needs_clarify": str | None, "source": "rules|llm|none"}

Amount semantics for `allocate` (what the sim receives):
  percent  value = the load's new share of power (absolute, 0-100)        "set the shields to 30 percent"
  delta    value = signed change in points                               "move 20 percent to shields" (+20)
  little   value = signed small change (+5 / -5)                         "a little more for the plants"
  half / all / none   the load gets half / all / none of the power       "give all of it to life support"
Contract addition: {"type": "rule", "when": <trigger>, "then": Command}, a standing order ("if a storm comes, go to the
shelter"). The voice layer stores it and fires `then` when the trigger shows up in State (see director._mission_turn).
"""
from __future__ import annotations

import json
import re

LOADS = ("shields", "life_support", "greenhouse", "science", "rover", "comms", "heaters")
KINDS = ("percent", "delta", "all", "half", "little", "none")
TASKS = ("collect_ice", "repair_array", "explore", "return")
QUERIES = ("power", "oxygen", "life_support", "dose", "storm", "comms", "all")
TRIGGERS = ("storm", "low_power", "dark", "comm_closed", "dose_high", "low_oxygen")

# Synonyms -> load. Longest phrases first so "radiation shield" beats "shield".
LOAD_WORDS = [
    (r"radiation shields?|the shields?|shields?|shielding|protection|force ?field|armou?r", "shields"),
    (r"life support|oxygen|o2|the air|air|breathing|air machine|water", "life_support"),
    (r"greenhouse|the plants|plants|plant|garden|veggies|vegetables|food", "greenhouse"),
    (r"science|experiments?|the lab|lab|instruments?|research", "science"),
    (r"the rover|rover|moon buggy|buggy|the car|car|truck", "rover"),
    (r"comms?|radio|antenna|the dish|dish|communications?|talking to earth", "comms"),
    (r"heaters?|heating|heat|warmth|warm", "heaters"),
]
LOAD_RE = [(re.compile(rf"\b(?:{p})\b"), load) for p, load in LOAD_WORDS]

NUM_WORDS = {"zero": 0, "none": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
             "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
             "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40,
             "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90, "hundred": 100, "a hundred": 100,
             "one hundred": 100}
TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
ONES = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9}

CONFIRM = re.compile(r"^(yes|yeah|yep|yup|ya|sure|ok|okay|okey dokey|do it|confirm(ed)?|go ahead|go for it|affirmative|"
                     r"roger|roger that|correct|that s right|right|i agree|agree|agreed|yes please|yes do it|"
                     r"(ok|okay|yes|yeah) (do it|go ahead|confirm))( please| commander| captain)?$")
CANCEL = re.compile(r"^(no|nope|nah|never ?mind|cancel( that| it)?|abort|stop|wait|don t|do not|forget it|negative|"
                    r"no thanks|no thank you|undo|don t do it|no don t|no wait|no stop|i changed my mind)( please)?$")
NEGATION = re.compile(r"\b(don t|do not|dont|never|not|no don t|stop)\b")
OFF = re.compile(r"\b(turn(ing)? off|switch(ing)? off|shut(ting)? (off|down)|cut|kill|power down|unplug|no power)\b")
ON = re.compile(r"\b(turn(ing)? on|switch(ing)? on|power up|start|boot up|wake up)\b")
COND = re.compile(r"^(if|when|whenever|in case|as soon as)\s+(.+?)(?:,|\bthen\b|\s(?=(?:go|get|move|send|turn|put|give|"
                  r"everyone|everybody|all|take|bring|hide|shelter|call)\b))\s*(.+)$")
SPLIT = re.compile(r"\s*(?:,|;|\band then\b|\bthen\b|\band also\b|\balso\b|\bafter that\b|\band\b)\s*")

SHELTER_IN = re.compile(r"\b(shelter|hide|take cover|duck and cover|bunker|safe room|get inside|go inside|everyone in|"
                        r"everybody in)\b")
SHELTER_OUT = re.compile(r"\b(leave|out of|come out|get out|exit|go outside|all clear)\b")
HOUSTON = re.compile(r"\b(houston|mission control|call earth|call home|phone home|ground control|talk to earth|"
                     r"radio earth|message earth)\b")
END_SHIFT = re.compile(r"^(end( the| this| my)? (shift|turn|day)|next( shift| turn)?|next please|go to sleep|sleep|"
                       r"advance( time)?|skip( ahead)?|fast forward|time to sleep|we re done( for now)?|done( for now)?|"
                       r"finish (the )?(shift|turn))( please)?$")
QUESTION = re.compile(r"^(how|what|what s|whats|when|where|is|are|do|does|did|can|will|tell me|give me a report|report|"
                      r"status|check|show me)\b|\b(how much|how many|how long|how are|is it|status|report|left)\b")
DISPATCH_VERB = re.compile(r"\b(send|go|drive|take|use|get|move|roll|dispatch|bring|fetch|collect|dig|mine|explore|"
                            r"fix|repair|scout|come back|return|head)\b")
TASK_WORDS = [
    (re.compile(r"\b(ice|water|frozen water|dig|mine|collect)\b"), "collect_ice"),
    (re.compile(r"\b(fix|repair|mend)\b|\b(solar|panel|panels|array|arrays)\b"), "repair_array"),
    (re.compile(r"\b(come back|come home|return|back home|go home|bring (it|the rover|the buggy) back|back to base|"
                r"back here)\b"), "return"),
    (re.compile(r"\b(explore|look around|scout|adventure|investigate|go see|check out|crater)\b"), "explore"),
]
VEHICLE = re.compile(r"\b(rover|buggy|moon buggy|the car|truck|robot)\b")
POWER_WORD = re.compile(r"\b(power|energy|electricity|juice|battery|percent|electric)\b")
MORE = re.compile(r"\b(more|extra|boost|increase|raise|add|up|higher|bigger|stronger|crank)\b")
LESS = re.compile(r"\b(less|fewer|reduce|lower|decrease|down|cut back|smaller|weaker|take away|turn down)\b")
LITTLE = re.compile(r"\b(a (little|bit|tiny bit|touch|smidge)( bit)?|a little|slightly|tiny bit|bit)\b")
ALL = re.compile(r"\b(all( of)?( it| the power| power| our power| the energy)?|everything|full power|maximum|max|100 percent|"
                 r"hundred percent)\b")
HALF = re.compile(r"\b(half|50 percent|fifty percent)\b")
NONE = re.compile(r"\b(none|nothing|zero|no power)\b")
SET_TO = re.compile(r"\b(set|make|put)\b.*\b(to|at)\s+\d+|\b(at|to)\s+\d+\s*percent\b(?!.*\bfrom\b)")
FROM = re.compile(r"\b(from|out of|away from)\s+(?:the\s+)?(\w+(?:\s\w+)?)")
TARGET = re.compile(r"\bto\s+(?:the\s+)?([a-z][a-z ]{2,30}?)(?:\s+(?:for|to)\b|$)")

QUERY_WORDS = [
    (re.compile(r"\b(radiation|dose|msv|millisievert|rads?|sieverts?)\b"), "dose"),
    (re.compile(r"\b(storm|solar storm|flare|space weather|sun storm|weather)\b"), "storm"),
    (re.compile(r"\b(oxygen|air|breathe|breathing|o2|life support|water)\b"), "oxygen"),
    (re.compile(r"\b(power|battery|energy|electricity|charge|solar)\b"), "power"),
    (re.compile(r"\b(comms?|radio|talk to earth|call earth|signal|earth|contact|antenna)\b"), "comms"),
    (re.compile(r"\b(status|everything|how are we doing|how s it going|report|how is the base|how s the base|"
                r"how are things|all systems)\b"), "all"),
]
COND_WORDS = [
    (re.compile(r"\b(storm|flare|solar storm|radiation (gets |is )?high|sun storm|radiation)\b"), "storm"),
    (re.compile(r"\b(power|battery|energy)\b.*\b(low|runs? out|drops?|empty)\b|\b(low|out of)\b.*\b(power|battery|energy)\b"),
     "low_power"),
    (re.compile(r"\b(oxygen|air)\b.*\b(low|runs? out|drops?)\b|\blow\b.*\b(oxygen|air)\b"), "low_oxygen"),
    (re.compile(r"\b(dark|night|sunset|sun goes down|sun sets)\b"), "dark"),
    (re.compile(r"\b(lose|lost|no) (contact|signal|radio)|\bcomms? (go )?(down|closed?)\b|earth (goes|sets|disappears)"),
     "comm_closed"),
    (re.compile(r"\b(dose|radiation)\b.*\b(high|too much|limit)\b"), "dose_high"),
]


def norm(text: str) -> str:
    t = text.lower().replace("%", " percent ").replace("’", "'")
    t = re.sub(r"'", " ", t)
    t = re.sub(r"[^a-z0-9.\s]", " ", t)
    t = re.sub(r"(?<!\d)\.|\.(?!\d)", " ", t)
    t = re.sub(r"\bper cent\b", "percent", t)
    return re.sub(r"\s+", " ", t).strip()


def _words_to_digits(t: str) -> str:
    """'twenty five percent' -> '25 percent'; 'a hundred' -> '100'."""
    t = re.sub(r"\b(a|one) hundred\b", "100", t)
    t = re.sub(r"\b(" + "|".join(TENS) + r")[ -](" + "|".join(ONES) + r")\b",
               lambda m: str(TENS[m.group(1)] + ONES[m.group(2)]), t)
    def word(m):
        return str(NUM_WORDS[m.group(1)])
    return re.sub(r"\b(" + "|".join(k for k in NUM_WORDS if k not in ("none", "zero", "a hundred", "one hundred")) +
                  r")(?= percent| points?\b| per\b)", word, t)


def find_loads(t: str) -> list[str]:
    hits = []
    for rx, load in LOAD_RE:
        for m in rx.finditer(t):
            hits.append((m.start(), load))
    seen, out = set(), []
    for _, load in sorted(hits):
        if load not in seen:
            seen.add(load)
            out.append(load)
    return out


def _load_of(phrase: str) -> str | None:
    ls = find_loads(phrase)
    return ls[0] if ls else None


def _number(t: str, read: dict | None = None) -> float | None:
    m = re.search(r"\b(\d+(?:\.\d+)?)\s*(percent|points?)?\b", t)
    if m:
        return float(m.group(1))
    for s in (read or {}).get("numbers") or []:
        d = _words_to_digits(norm(s))
        mm = re.search(r"\d+(?:\.\d+)?", d)
        if mm:
            return float(mm.group(0))
    return None


def _num(v: float) -> int | float:
    return int(v) if float(v).is_integer() else v


# ---------------------------------------------------------------------------------------------------- one clause
def _allocate(t: str, read: dict | None, prev: dict | None) -> tuple[dict | None, str | None]:
    loads = find_loads(t)
    src = None
    fm = FROM.search(t)
    if fm:
        src = _load_of(fm.group(2))
        if src:
            # the load named after "from" is the source, not the target
            rest = t[:fm.start()] + " " + t[fm.end():]
            loads = [x for x in find_loads(rest) if x != src] or [x for x in loads if x != src]
    to = loads[0] if loads else None
    off = bool(OFF.search(t))
    n = _number(t, read)
    amount = None
    neg = bool(LESS.search(t)) and not MORE.search(t)
    if off or (NONE.search(t) and to):
        amount = {"kind": "none", "value": 0}
    elif HALF.search(t):
        amount = {"kind": "half", "value": 50}
    elif ALL.search(t) and to:
        amount = {"kind": "all", "value": 100}
    elif n is not None and "percent" not in t and not POWER_WORD.search(t) and n > 100:
        return None, None
    elif n is not None:
        absolute = bool(SET_TO.search(t)) and not MORE.search(t) and not LESS.search(t) and not re.search(
            r"\b(move|give|add|send|shift|transfer|take)\b", t)
        if absolute:
            amount = {"kind": "percent", "value": _num(min(n, 100))}
        else:
            amount = {"kind": "delta", "value": _num(-n if neg else n)}
    elif LITTLE.search(t) and (MORE.search(t) or LESS.search(t)):
        amount = {"kind": "little", "value": -5 if neg else 5}
    elif MORE.search(t) or LESS.search(t):
        amount = {"kind": "delta", "value": -10 if neg else 10}
    elif ON.search(t) and to:
        amount = {"kind": "delta", "value": 10}
    if amount is None and to is None:
        return None, None
    if to is None:
        if prev and prev.get("type") == "allocate" and amount:
            to = prev["to"]
        else:
            return None, "Which part of the base should get that? Shields, air, greenhouse, science, rover, radio or heaters?"
    if amount is None:
        if prev and prev.get("type") == "allocate":   # "...and the heaters too" -> same amount
            amount = dict(prev["amount"])
        elif POWER_WORD.search(t) or re.search(r"\b(give|move|put|send|shift|power)\b", t):
            amount = {"kind": "delta", "value": 10}
        else:
            return None, None
    return {"type": "allocate", "to": to, "amount": amount, "from": src}, None


def _dispatch(t: str) -> dict | None:
    if not VEHICLE.search(t) and not re.search(r"\b(go get ice|get ice|collect ice|fetch ice|dig for ice|fix the "
                                               r"(solar|panel|array))", t):
        return None
    if VEHICLE.search(t) and POWER_WORD.search(t) and not re.search(r"\b(send|drive|dispatch|go)\b", t):
        return None   # "more power to the rover" is an allocate
    if VEHICLE.search(t) and not DISPATCH_VERB.search(t):
        return None
    task = None
    for rx, name in TASK_WORDS:
        if rx.search(t):
            task = name
            break
    if task is None:
        mm = re.search(r"\b(?:to|toward|towards)\s+(?:the\s+)?([a-z]+(?:\s[a-z]+)?)\s*$", t)
        if mm and re.search(r"\b(send|drive|go|take|head)\b", t):
            task = "explore"
    if task is None:
        return None
    target = None
    mm = re.search(r"\b(?:to|at|near|toward|towards)\s+(?:the\s+)?([a-z]+(?:\s[a-z]+)?)\s*$", t)
    if mm and task in ("explore", "collect_ice"):
        cand = mm.group(1).strip()
        if not re.search(r"\b(get|collect|find|ice|water|explore|look|base|home|here|shelter|it)\b", cand):
            target = cand.replace(" ", "_")
    return {"type": "dispatch", "vehicle": "rover", "task": task, "target": target}


def _query(t: str) -> dict | None:
    if not QUESTION.search(t) and not re.search(r"\b(status|report)\b", t):
        return None
    for rx, what in QUERY_WORDS:
        if rx.search(t):
            return {"type": "query", "what": what}
    if re.search(r"\b(how are we|how s everything|how is everything|are we ok|are we okay|are we safe|status|report)\b",
                 t):
        return {"type": "query", "what": "all"}
    return None


def _shelter(t: str) -> dict | None:
    if not SHELTER_IN.search(t):
        return None
    out = bool(SHELTER_OUT.search(t))
    return {"type": "shelter", "on": not out}


def clause(t: str, read: dict | None = None, prev: dict | None = None) -> tuple[dict | None, str | None]:
    """One clause -> (Command | None, clarify question | None)."""
    t = t.strip()
    if not t:
        return None, None
    if CONFIRM.match(t):
        return {"type": "confirm"}, None
    if CANCEL.match(t):
        return {"type": "cancel"}, None
    if END_SHIFT.match(t):
        return {"type": "end_shift"}, None
    if HOUSTON.search(t):
        rest = HOUSTON.sub(" ", t)
        rest = re.sub(r"^\s*(hey|hi|hello|ok|okay|call|please|calling|this is (the )?(commander|base))\b", " ", rest)
        return {"type": "call_houston", "text": re.sub(r"\s+", " ", rest).strip()}, None
    q = _query(t)
    if q and not re.search(r"\b(give|move|send|put|set|turn|switch|shut)\b", t):
        return q, None
    s = _shelter(t)
    if s:
        return s, None
    if re.search(r"\b(rover|buggy)\b.*\b(power|percent)\b", t) and not re.search(r"\bsend\b", t):
        pass
    else:
        d = _dispatch(t)
        if d:
            return d, None
    return _allocate(t, read, prev)


def _negated(t: str) -> tuple[bool, str | None]:
    """'don't turn off the heaters' -> (True, the clarify question). Not a command; ask what they want instead."""
    if CANCEL.match(t):
        return False, None
    m = re.search(r"\b(don t|do not|dont|never|please don t|let s not|we shouldn t|shouldn t)\b\s*(.*)", t)
    if not m:
        return False, None
    rest = m.group(2)
    load = _load_of(rest)
    if OFF.search(rest) and load:
        nice = LOAD_NAMES.get(load, load)
        return True, f"Okay, the {nice} stay on. Do you want to give them more power, or keep them the same?"
    if load:
        nice = LOAD_NAMES.get(load, load)
        return True, f"Okay, I won't change the {nice}. What would you like to do instead?"
    if re.search(r"\b(send|go|drive)\b", rest) and VEHICLE.search(rest):
        return True, "Okay, the rover stays home. What should we do instead?"
    if SHELTER_IN.search(rest):
        return True, "Okay, nobody goes to the shelter. What should the crew do?"
    return True, "Okay, I won't do that. What would you like to do?"


LOAD_NAMES = {"shields": "radiation shields", "life_support": "life support", "greenhouse": "greenhouse",
              "science": "science lab", "rover": "rover", "comms": "radio", "heaters": "heaters"}


def _condition(t: str) -> tuple[str | None, str]:
    m = COND.match(t)
    if not m:
        return None, t
    cond, action = m.group(2), m.group(3)
    for rx, trig in COND_WORDS:
        if rx.search(cond):
            return trig, action
    return "unknown", action


def parse(text: str, read: dict | None = None, state: dict | None = None) -> dict:
    """Rules only. -> {commands, confidence, needs_clarify, source}"""
    t = _words_to_digits(norm(text))
    t = re.sub(r"^(um+|uh+|so|okay so|ok so|hey|hi|please|can you|could you|can we|let s|lets|i want to|i want you to|"
               r"we need to|i think we should|we should)\s+", "", t)
    t = re.sub(r"\s+please$", "", t)
    out = {"commands": [], "confidence": 0.0, "needs_clarify": None, "source": "rules"}
    if not t:
        out["source"] = "none"
        return out
    # Standing orders: "if a storm comes go to the shelter".
    trig, action = _condition(t)
    if trig is not None:
        sub = parse(action, read, state)
        then = sub["commands"][0] if sub["commands"] else None
        if trig == "unknown" or then is None:
            out["needs_clarify"] = "I didn't catch the rule. Try: if a storm comes, everyone into the shelter."
            out["confidence"] = 0.4
            return out
        out["commands"] = [{"type": "rule", "when": trig, "then": then}]
        out["confidence"] = 0.9
        return out
    neg, ask = _negated(t)
    if neg:
        out["needs_clarify"] = ask
        out["confidence"] = 0.85
        return out
    # Whole-utterance matches first (so "go ahead and do it" isn't split).
    whole, ask = clause(t, read, None)
    if whole and whole["type"] in ("confirm", "cancel", "end_shift", "call_houston", "query"):
        out["commands"], out["confidence"] = [whole], 0.95
        return out
    if whole and whole["type"] == "allocate" and whole.get("from"):   # "take 10 from science and give it to shields"
        out["commands"], out["confidence"] = [whole], 0.9
        return out
    parts = [p for p in SPLIT.split(t) if p and p.strip()]
    cmds, asks, missed, prev = [], [], 0, None
    if len(parts) > 1:
        for p in parts:
            c, a = clause(p, read, prev)
            if c:
                cmds.append(c)
                prev = c
            else:
                missed += 1
                if a:
                    asks.append(a)
        # "power to shields and heaters": a clause that is only a load name inherits the previous allocate
        if not cmds and whole:
            cmds = [whole]
    else:
        if whole:
            cmds = [whole]
        elif ask:
            asks.append(ask)
            missed = 1
    out["commands"] = cmds
    if cmds:
        out["confidence"] = 0.9 if missed == 0 else 0.6
    if asks and not cmds:
        out["needs_clarify"] = asks[0]
        out["confidence"] = 0.5
    return out


# ------------------------------------------------------------------------------------------------- validation
def valid(c) -> dict | None:
    """A Command if `c` matches the contract schema exactly (rule included), else None."""
    if not isinstance(c, dict):
        return None
    ty = c.get("type")
    if ty == "allocate":
        a = c.get("amount")
        if c.get("to") not in LOADS or not isinstance(a, dict) or a.get("kind") not in KINDS:
            return None
        v = a.get("value")
        if v is not None and not isinstance(v, (int, float)):
            return None
        if a["kind"] == "percent" and not (0 <= (v or 0) <= 100):
            return None
        if a["kind"] in ("percent", "delta", "little") and v is None:
            return None
        src = c.get("from")
        if src is not None and (src not in LOADS or src == c["to"]):
            return None
        return {"type": "allocate", "to": c["to"], "amount": {"kind": a["kind"], "value": v}, "from": src}
    if ty == "dispatch":
        if c.get("vehicle", "rover") != "rover" or c.get("task") not in TASKS:
            return None
        tg = c.get("target")
        return {"type": "dispatch", "vehicle": "rover", "task": c["task"], "target": tg if isinstance(tg, str) else None}
    if ty == "shelter":
        return {"type": "shelter", "on": bool(c.get("on"))} if isinstance(c.get("on"), bool) else None
    if ty == "query":
        return {"type": "query", "what": c["what"]} if c.get("what") in QUERIES else None
    if ty == "call_houston":
        return {"type": "call_houston", "text": str(c.get("text") or "")[:300]}
    if ty in ("end_shift", "confirm", "cancel"):
        return {"type": ty}
    if ty == "rule":
        then = valid(c.get("then"))
        if c.get("when") in TRIGGERS and then and then["type"] not in ("rule", "confirm", "cancel"):
            return {"type": "rule", "when": c["when"], "then": then}
    return None


# --------------------------------------------------------------------------------------------------- LLM fallback
SCHEMA = """Command JSON objects (exact keys):
{"type":"allocate","to":LOAD,"amount":{"kind":"percent|delta|all|half|little|none","value":NUMBER},"from":LOAD|null}
  percent = the load's new share (0-100); delta = signed change in points ("move 20% to shields" = +20); little = +5/-5
{"type":"dispatch","vehicle":"rover","task":"collect_ice|repair_array|explore|return","target":null}
{"type":"shelter","on":true|false}
{"type":"query","what":"power|oxygen|life_support|dose|storm|comms|all"}
{"type":"call_houston","text":"..."}
{"type":"end_shift"}  {"type":"confirm"}  {"type":"cancel"}
{"type":"rule","when":"storm|low_power|dark|comm_closed|dose_high|low_oxygen","then":<one Command>}
LOAD is one of: shields, life_support, greenhouse, science, rover, comms, heaters."""

_client = None


async def llm_parse(text: str, state: dict | None = None) -> list[dict] | None:
    """None when the LLM is off or fails; else the validated Commands (possibly empty)."""
    global _client
    from ..config import settings
    if not settings.anthropic_api_key:
        return None
    if _client is None:
        from anthropic import AsyncAnthropic
        _client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    st = {k: (state or {}).get(k) for k in ("resources", "loads", "env", "rover", "shelter", "alerts")}
    prompt = (f"A child (7-12) is commanding a Moon base by voice in a training game. They said: \"{text}\"\n"
              f"Current base state: {json.dumps(st)}\n\n{SCHEMA}\n\n"
              'Reply ONLY with JSON: {"commands": [ ... ]}. Use [] if they did not give a command or ask about the base. '
              "Never invent commands they didn't ask for. A negated request (\"don't ...\") is not a command.")
    try:
        msg = await _client.messages.create(model=settings.ask_model, max_tokens=300,
                                            extra_body={"thinking": {"type": "disabled"}},
                                            messages=[{"role": "user", "content": prompt}])
        raw = "".join(b.text for b in msg.content if b.type == "text")
        m = re.search(r"\{[\s\S]*\}", raw)
        data = json.loads(m.group(0)) if m else {}
    except Exception:  # noqa: BLE001 (fail open to rules)
        return None
    cmds = data.get("commands") if isinstance(data, dict) else None
    return [v for v in map(valid, cmds if isinstance(cmds, list) else []) if v]


async def understand(text: str, read: dict | None = None, state: dict | None = None, use_llm: bool = True) -> dict:
    out = parse(text, read, state)
    out["commands"] = [v for v in map(valid, out["commands"]) if v]
    if out["commands"] or out["needs_clarify"] or not use_llm:
        if not out["commands"] and not out["needs_clarify"]:
            out["source"] = "none"
        return out
    cmds = await llm_parse(text, state)
    if cmds:
        return {"commands": cmds, "confidence": 0.7, "needs_clarify": None, "source": "llm"}
    return {**out, "source": "none"}
