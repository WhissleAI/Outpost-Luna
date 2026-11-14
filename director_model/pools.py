"""Kid-turn text pools for the session generator. Every item: {text, cat, root, gold?}. `root` is the split key (a
template id, a bank example, a card question): the same root never appears in two splits."""
from __future__ import annotations

import json
import random
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
BACKEND = HERE.parent / "backend"

LOAD_SYN = {"shields": ["shields", "radiation shields", "shield", "force field", "protection"],
            "life_support": ["life support", "oxygen", "the air", "air machine"],
            "greenhouse": ["greenhouse", "plants", "garden", "veggies"],
            "science": ["science", "the lab", "experiments", "research"],
            "rover": ["rover", "moon buggy", "buggy"],
            "comms": ["comms", "radio", "antenna", "the dish"],
            "heaters": ["heaters", "heat", "heating"]}
NUM_WORDS = {5: "five", 10: "ten", 15: "fifteen", 20: "twenty", 25: "twenty five", 30: "thirty", 35: "thirty five",
             40: "forty", 45: "forty five", 50: "fifty", 60: "sixty", 70: "seventy", 75: "seventy five", 80: "eighty"}
VEH = ["rover", "moon buggy", "buggy"]
PLACES_X = ["shackleton", "the crater", "cabeus", "the ridge", "malapert", "de gerlache"]

ALLOC = {
    "A1": "set the {L} to {N} percent", "A2": "{L} to {N}", "A3": "make the {L} {N}", "A4": "put {N} percent on {L}",
    "A5": "move {N} percent to {L}", "A6": "give {L} {N} more percent", "A7": "take {N} from {L2} and give it to {L}",
    "A8": "more power to {L}", "A9": "give the {L} more power", "A10": "less power for the {L}",
    "A11": "turn down the {L}", "A12": "a little more {L} please", "A13": "all power to {L}",
    "A14": "half power to {L}", "A15": "turn off the {L}", "A16": "turn on the {L}", "A17": "boost the {L}",
    "A18": "can we get more {L}", "A19": "the {L} needs more power", "A20": "lower the {L} to {N} percent",
    "A21": "put the {L} at {N} percent", "A22": "add {N} to {L}", "A23": "take some power away from the {L}",
    "A24": "crank up the {L}", "A25": "we need a bit more {L}",
}
OTHER = {
    "D1": "send the rover to get ice", "D2": "{V} go collect ice", "D3": "go fix the solar panels",
    "D4": "send the {V} to explore {P}", "D5": "bring the {V} back", "D6": "drive the {V} home",
    "D7": "send the {V} to dig for ice", "D8": "{V} come back to base", "D9": "repair the solar array",
    "D10": "send the {V} to look around {P}", "D11": "we need ice send the {V}", "D12": "go mine some ice with the {V}",
    "S1": "everyone into the shelter", "S2": "go to the shelter", "S3": "take cover everybody", "S4": "leave the shelter",
    "S5": "come out of the shelter", "S6": "get out of the shelter now", "S7": "hide in the shelter",
    "Q1": "how much power do we have", "Q2": "what's our oxygen level", "Q3": "how much radiation did we get",
    "Q4": "is there a storm coming", "Q5": "when can we talk to earth", "Q6": "status report", "Q7": "how are we doing",
    "Q8": "how much battery is left", "Q9": "what's the radiation dose", "Q10": "is the air okay",
    "H1": "call houston", "H2": "houston we need help", "H3": "tell mission control we found ice",
    "H4": "message earth that we are safe", "H5": "hey houston how are you",
    "E1": "end shift", "E2": "next shift please", "E3": "time to sleep", "E4": "we're done for today",
    "E5": "end the shift",
    "R1": "if a storm comes go to the shelter", "R2": "when it gets dark turn up the heaters",
    "R3": "if power gets low turn off the science", "R4": "if the radiation gets too high everyone into the shelter",
    "R5": "if the battery runs out turn down the rover", "R6": "when the sun goes down give the heaters more power",
    "N1": "don't turn off the {L}", "N2": "don't send the rover", "N3": "please don't change the {L}",
    "N4": "let's not go to the shelter", "N5": "never turn off the heaters",
    "K1": "it's freezing in here", "K2": "brr we're so cold", "K3": "it's too cold in the base",
}
RISKY = ["all power to {L}", "turn off the heaters", "turn off life support", "give everything to {L}",
         "put {L} at 95 percent"]
YES = ["yes", "yeah do it", "yes please", "okay go ahead", "sure", "roger that", "confirm", "do it"]
NO = ["no", "nope", "never mind", "cancel that", "no wait", "forget it", "no thanks"]
TEST_TPL = {"A6", "A12", "A18", "A22", "D6", "D11", "S5", "Q7", "Q10", "H4", "E4", "R4", "R6", "N3", "K3"}

MISCON = ["the moon is made of cheese", "is the moon made out of cheese", "the moon has no craters",
          "the moon doesn't have any craters", "the moon makes its own light", "does the moon glow by itself",
          "the dark side never gets any sun", "is it always dark on the far side", "the moon is bigger than earth",
          "the moon is a planet"]
TOURS = ["show me the rovers", "what's left on the moon", "where did people land", "show me the crash sites",
         "who drove the rovers", "show me all the landers", "what junk did we leave on the moon",
         "where are the moon buggies", "show me the science instruments", "where are the mirrors"]
SOUNDS = ["play the launch", "what did liftoff sound like", "play the splashdown", "can i hear the countdown",
          "play the engine burn", "what did the record sound like"]
OFFTOPIC = ["what's your favorite color", "can you do my homework", "tell me a joke", "who won the soccer game",
            "what's two plus two", "do you like pizza", "what's the weather in chicago", "how old are you",
            "can you sing a song", "what's the capital of france", "who is the president", "are you a robot",
            "what time is it", "can we play minecraft", "what's my teacher's name", "how do i tie my shoes",
            "is mars bigger than the moon", "what do dogs eat", "where do rainbows come from", "who made you"]
NAMES = ["maya", "leo", "ava", "noah", "zara", "omar", "lily", "sam", "priya", "jack"]
STREETS = ["oak", "maple", "elm", "pine", "main", "cedar"]
CHATTER = ["no you go first", "wait what", "haha that's funny", "my turn my turn", "look at that", "stop it",
           "i'm hungry", "mom can i have a snack", "did you see that", "that's so cool", "okay okay", "shh",
           "you're doing it wrong", "let me try", "i want to be the commander", "can we play outside after",
           "where's my pencil", "that was awesome", "no it's my turn", "hey stop pushing"]
WRAP = ["{q}", "hey {q}", "um {q}", "can you tell me {q}", "i want to know {q}", "{q} please", "guide {q}",
        "so {q}", "uh {q}", "okay {q}"]
OFF_WRAP_TEST = {"i want to know {q}", "guide {q}", "okay {q}"}


def h(s: str) -> int:
    import hashlib
    return int(hashlib.md5(s.encode()).hexdigest()[:8], 16)


def split_of(root: str) -> str:
    x = h(root) % 100
    return "test" if x < 14 else "val" if x < 22 else "train"


def _num(rng, words_p=0.4):
    n = rng.choice([5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 60, 70, 75, 80])
    return (NUM_WORDS[n] if rng.random() < words_p else str(n)), n


def _load(rng, exclude=None):
    ld = rng.choice([x for x in LOAD_SYN if x != exclude])
    return ld, rng.choice(LOAD_SYN[ld])


def tpl_split(tid: str) -> str:
    if tid in TEST_TPL:
        return "test"
    return "val" if h(tid) % 100 < 8 else "train"


def _al(to, kind, v=None, frm=None):
    return {"type": "allocate", "to": to, "amount": {"kind": kind, "value": v}, "from": frm}


def _dp(task):
    return {"type": "dispatch", "vehicle": "rover", "task": task, "target": None}


# The INTENT of every template (gold, independent of the rules). Conventions follow the rules where they are right
# ("more" = +10, "a little" = +5, "turn on" = +10); where the rules are wrong the gold says what the kid meant
# (A20 "lower the shields to 20 percent" = set 20, A23, D6, R4).
TPL_GOLD = {
    "A1": lambda L, L2, n: _al(L, "percent", n), "A2": lambda L, L2, n: _al(L, "percent", n),
    "A3": lambda L, L2, n: _al(L, "percent", n), "A4": lambda L, L2, n: _al(L, "delta", n),
    "A5": lambda L, L2, n: _al(L, "delta", n), "A6": lambda L, L2, n: _al(L, "delta", n),
    "A7": lambda L, L2, n: _al(L, "delta", n, L2), "A8": lambda L, L2, n: _al(L, "delta", 10),
    "A9": lambda L, L2, n: _al(L, "delta", 10), "A10": lambda L, L2, n: _al(L, "delta", -10),
    "A11": lambda L, L2, n: _al(L, "delta", -10), "A12": lambda L, L2, n: _al(L, "little", 5),
    "A13": lambda L, L2, n: _al(L, "all", 100), "A14": lambda L, L2, n: _al(L, "half", 50),
    "A15": lambda L, L2, n: _al(L, "none", 0), "A16": lambda L, L2, n: _al(L, "delta", 10),
    "A17": lambda L, L2, n: _al(L, "delta", 10), "A18": lambda L, L2, n: _al(L, "delta", 10),
    "A19": lambda L, L2, n: _al(L, "delta", 10), "A20": lambda L, L2, n: _al(L, "percent", n),
    "A21": lambda L, L2, n: _al(L, "percent", n), "A22": lambda L, L2, n: _al(L, "delta", n),
    "A23": lambda L, L2, n: _al(L, "delta", -10), "A24": lambda L, L2, n: _al(L, "delta", 10),
    "A25": lambda L, L2, n: _al(L, "little", 5),
    "D1": lambda *a: _dp("collect_ice"), "D2": lambda *a: _dp("collect_ice"), "D3": lambda *a: _dp("repair_array"),
    "D4": lambda *a: _dp("explore"), "D5": lambda *a: _dp("return"), "D6": lambda *a: _dp("return"),
    "D7": lambda *a: _dp("collect_ice"), "D8": lambda *a: _dp("return"), "D9": lambda *a: _dp("repair_array"),
    "D10": lambda *a: _dp("explore"), "D11": lambda *a: _dp("collect_ice"), "D12": lambda *a: _dp("collect_ice"),
    **{k: (lambda *a: {"type": "shelter", "on": True}) for k in ("S1", "S2", "S3", "S7")},
    **{k: (lambda *a: {"type": "shelter", "on": False}) for k in ("S4", "S5", "S6")},
    **{k: (lambda *a, w=w: {"type": "query", "what": w}) for k, w in
       (("Q1", "power"), ("Q2", "oxygen"), ("Q3", "dose"), ("Q4", "storm"), ("Q5", "comms"), ("Q6", "all"),
        ("Q7", "all"), ("Q8", "power"), ("Q9", "dose"), ("Q10", "oxygen"))},
    **{k: (lambda *a: {"type": "call_houston", "text": ""}) for k in ("H1", "H2", "H3", "H4", "H5")},
    **{k: (lambda *a: {"type": "end_shift"}) for k in ("E1", "E2", "E3", "E4", "E5")},
    "R1": lambda *a: {"type": "rule", "when": "storm", "then": {"type": "shelter", "on": True}},
    "R2": lambda *a: {"type": "rule", "when": "dark", "then": _al("heaters", "delta", 10)},
    "R3": lambda *a: {"type": "rule", "when": "low_power", "then": _al("science", "none", 0)},
    "R4": lambda *a: {"type": "rule", "when": "dose_high", "then": {"type": "shelter", "on": True}},
    "R5": lambda *a: {"type": "rule", "when": "low_power", "then": _al("rover", "delta", -10)},
    "R6": lambda *a: {"type": "rule", "when": "dark", "then": _al("heaters", "delta", 10)},
    **{k: (lambda *a: _al("heaters", "delta", 10)) for k in ("K1", "K2", "K3")},
}
RISKY_GOLD = {"all power to {L}": lambda L: _al(L, "all", 100), "turn off the heaters": lambda L: _al("heaters", "none", 0),
              "turn off life support": lambda L: _al("life_support", "none", 0),
              "give everything to {L}": lambda L: _al(L, "all", 100),
              "put {L} at 95 percent": lambda L: _al(L, "percent", 95)}


def mission_cmd(rng: random.Random, split: str) -> dict:
    """One templated mission command whose template belongs to `split` (train/val/test)."""
    pool = [t for t in list(ALLOC) + list(OTHER) if tpl_split(t) == split] or list(ALLOC)
    tid = rng.choice(pool)
    s = ALLOC.get(tid) or OTHER[tid]
    ld, lw = _load(rng)
    _, lw2 = _load(rng, exclude=ld)
    ld2 = next(k for k, v in LOAD_SYN.items() if lw2 in v)
    nw, n = _num(rng)
    text = s.format(L=lw, L2=lw2, N=nw, V=rng.choice(VEH), P=rng.choice(PLACES_X))
    if tid[0] == "N":
        gold = {"act": "ask_clarify"}
    else:
        gold = {"act": "command", "command": TPL_GOLD[tid](ld, ld2, n)}
    cat = {"A": "cmd_alloc", "D": "cmd_dispatch", "S": "cmd_shelter", "Q": "cmd_query", "H": "cmd_houston",
           "E": "cmd_end_shift", "R": "cmd_rule", "N": "cmd_negation", "K": "cmd_cold"}[tid[0]]
    return {"text": text, "cat": cat, "root": f"tpl:{tid}", "gold": gold}


def compound(rng, split) -> dict:
    a, b = mission_cmd(rng, split), mission_cmd(rng, split)
    while a["cat"] in ("cmd_rule", "cmd_negation", "cmd_end_shift", "cmd_query", "cmd_houston"):
        a = mission_cmd(rng, split)
    while b["cat"] in ("cmd_rule", "cmd_negation", "cmd_end_shift", "cmd_query", "cmd_houston"):
        b = mission_cmd(rng, split)
    j = rng.choice([" and ", " and then ", " then ", ", "])
    return {"text": a["text"] + j + b["text"], "cat": "cmd_compound", "root": a["root"] + "+" + b["root"],
            "gold": a["gold"]}


def risky(rng) -> dict:
    s = rng.choice(RISKY)
    ld, lw = _load(rng)
    return {"text": s.format(L=lw), "cat": "cmd_risky", "root": "risky:" + s,
            "gold": {"act": "command", "command": RISKY_GOLD[s](ld)}}


def yes_no(rng, yes: bool) -> dict:
    t = rng.choice(YES if yes else NO)
    return {"text": t, "cat": "confirm_yes" if yes else "confirm_no", "root": "yn:" + t,
            "gold": {"act": "confirm_yes" if yes else "confirm_no"}}


_BANK = None


def bank() -> list[dict]:
    global _BANK
    if _BANK is None:
        ex = json.loads((BACKEND / "data" / "mission" / "command_bank.json").read_text())["examples"]
        _BANK = [{"text": e["text"], "cat": "cmd_bank", "root": "bank:" + e["text"], "bank_cmd": e["command"]}
                 for e in ex]
    return _BANK


_CARDS = None


def card_qs() -> list[dict]:
    global _CARDS
    if _CARDS is None:
        qs = json.loads((DATA / "card_questions.json").read_text())["questions"]
        _CARDS = [{"text": q["q"].lower().rstrip("?"), "cat": "explorer_card", "root": "card:" + q["q"],
                   "attr": q["attr"], "card": q["card"], "place": q.get("place")} for q in qs]
    return _CARDS


def gloss_terms() -> list[str]:
    g = json.loads((BACKEND / "data" / "glossary.json").read_text())
    items = g.get("terms") if isinstance(g, dict) and "terms" in g else g
    out = []
    if isinstance(items, dict):
        out = list(items)
    elif isinstance(items, list):
        out = [x.get("term") or x.get("word") for x in items if isinstance(x, dict)]
    return [t.lower() for t in out if t][:60]


def place_names() -> list[str]:
    p = json.loads((BACKEND / "data" / "places.json").read_text())
    items = p.get("places") if isinstance(p, dict) else p
    return [x["name"].lower() for x in items if isinstance(x, dict) and x.get("name")]


def explorer(rng: random.Random, split: str) -> dict:
    r = rng.random()
    if r < 0.55:
        pool = [q for q in card_qs() if split_of(q["root"]) == split]
        q = dict(rng.choice(pool))
        wraps = [w for w in WRAP if (w in OFF_WRAP_TEST) == (split == "test")] or WRAP
        q["text"] = rng.choice(wraps).format(q=q["text"])
        return q
    if r < 0.63:
        t = rng.choice(MISCON)
        return {"text": t, "cat": "explorer_miscon", "root": "mis:" + t, "attr": "misconception"}
    if r < 0.71:
        t = rng.choice(TOURS)
        return {"text": t, "cat": "explorer_tour", "root": "tour:" + t}
    if r < 0.76:
        t = rng.choice(SOUNDS)
        return {"text": t, "cat": "explorer_sound", "root": "snd:" + t}
    if r < 0.84:
        pl = rng.choice(place_names())
        s = rng.choice(["show me {p}", "take me to {p}", "fly to {p}", "what did the crew say about {p}",
                        "where is {p}", "tell me about {p}"])
        return {"text": s.format(p=pl), "cat": "explorer_place", "root": "pl:" + s + pl}
    if r < 0.92:
        t = rng.choice(OFFTOPIC)
        return {"text": t, "cat": "explorer_offtopic", "root": "off:" + t}
    terms = gloss_terms()
    if terms:
        t = rng.choice(["what does {t} mean", "what is {t}", "what's {t}"]).format(t=rng.choice(terms))
        return {"text": t, "cat": "explorer_glossary", "root": "gl:" + t, "attr": "what"}
    return {"text": rng.choice(TOURS), "cat": "explorer_tour", "root": "tour"}


# Questions a kid asks DURING a mission that are NOT commands (gold: answer), many naming a base part, a place or a
# rover task: "how deep is shackleton", "why do we need shields", "what is a solar storm". Split by question root.
MQ_FORMS = ["how deep is {p}", "how big is {p}", "how far away is {p}", "how cold is it in {p}", "how old is {p}",
            "what is {p}", "what's at {p}", "who is {p} named after", "where is {p}", "is there ice in {p}",
            "why is {p} so dark", "how wide is {p}", "what does {p} look like", "can we see {p} from here"]
MQ_FIXED = ["why do we need shields", "what do the shields do", "how does the greenhouse work", "why do plants need light",
            "what is a solar storm", "why are solar storms dangerous", "what does life support do",
            "how does the rover drive on the moon", "why is it so cold at night", "what is radiation",
            "how far can the rover go", "why do we need heaters", "what is a millisievert", "how does the radio reach earth",
            "why can't we talk to earth all the time", "what is the shelter made of", "how long is a day on the moon",
            "why is there ice in the craters", "what is regolith", "how do solar panels work", "why does the rover need power",
            "what happens if the power runs out", "who built the first moon base", "how fast does the rover go",
            "how heavy is the rover", "what are the experiments for", "why do astronauts need oxygen",
            "how do we make water on the moon", "what is science power for", "why is the sky black on the moon",
            "how do the heaters work", "where does the power come from", "what does capcom mean",
            "how many astronauts live here", "why does the sun hurt us", "what is a crater", "how did the craters get there",
            "what is the dish for", "why is the moon gray", "how hot does it get in the sun"]
MQ_WRAP = ["{q}", "um {q}", "hey {q}", "wait {q}", "so {q}", "guide {q}", "{q} guide", "okay but {q}"]


def mission_question(rng: random.Random, split: str) -> dict:
    if rng.random() < 0.5:
        pool = [q for q in MQ_FIXED if split_of("mq:" + q) == split] or MQ_FIXED
        q = rng.choice(pool)
        root = "mq:" + q
    else:
        forms = [f for f in MQ_FORMS if split_of("mqf:" + f) == split] or MQ_FORMS
        f = rng.choice(forms)
        q = f.format(p=rng.choice(place_names() + PLACES_X))
        root = "mqf:" + f
    return {"text": rng.choice(MQ_WRAP).format(q=q), "cat": "explorer_mission_q", "root": root,
            "gold": {"act": "answer"}}


def pii(rng) -> dict:
    s = rng.choice(["my name is {n}", "call me {n}", "i live at {k} {s} street", "my phone number is 555 {k}",
                    "hi i'm {n} and i live on {s} street", "my address is {k} {s} road"])
    return {"text": s.format(n=rng.choice(NAMES), k=rng.randint(10, 999), s=rng.choice(STREETS)), "cat": "pii",
            "root": "pii:" + s, "gold": {"act": "guard"}}


def chatter(rng) -> dict:
    t = rng.choice(CHATTER)
    return {"text": t, "cat": "chatter", "root": "chat:" + t, "gold": {"act": "ignore"}, "dd": (0.02, 0.42)}


def gold_items() -> list[dict]:
    g = json.loads((DATA / "gold.json").read_text())["items"]
    if (DATA / "gold_more.json").exists():
        g = g + json.loads((DATA / "gold_more.json").read_text())["items"]
    out = []
    for x in g:
        out.append({"text": x["text"], "cat": "gold_fix", "root": "gold:" + x["text"], "mode": x.get("mode", "mission"),
                    "gold": {k: x[k] for k in ("act", "command", "attr") if k in x}, "split": x.get("split", "train")})
    return out


def heldout40() -> list[dict]:
    d = json.loads((BACKEND / "tests" / "eval" / "commands_heldout.json").read_text())["commands"]
    return [{"text": x["text"], "cat": "heldout40", "root": "h40:" + x["text"], "expect": x["expect"],
             "gold": {"act": "command"}} for x in d]


def kidq80() -> list[dict]:
    d = json.loads((BACKEND / "tests" / "eval" / "kid_questions.json").read_text())["questions"]
    out = []
    for x in d:
        ok = x["ok"]
        attr = None if ok == ["unknown"] or not ok else ok[0].split("|")[-1]
        out.append({"text": x["q"].lower().rstrip("?"), "cat": "kidq80", "root": "q80:" + x["q"], "attr": attr,
                    "ok": ok, "gold": {"act": "answer"}})
    return out


def academy_items(rng: random.Random, lesson: dict, step_i: int) -> dict:
    """One answer to an Academy step: correct / wrong / hint / paraphrase. gold act: pass -> answer, else nudge."""
    st = lesson["steps"][step_i]
    a = st["accept"]
    r = rng.random()
    kind = "correct" if r < 0.5 else "wrong" if r < 0.8 else "hint"
    if kind == "hint":
        t = rng.choice(["i don't know", "can i have a hint", "help", "i'm stuck", "what do i say", "hmm"])
    elif a["type"] == "choice":
        opts = a["options"]
        o = next(x for x in opts if x["id"] == a["answer"]) if kind == "correct" else \
            rng.choice([x for x in opts if x["id"] != a["answer"]] or opts)
        w = rng.choice([o["label"]] + list(o.get("say") or []))
        t = rng.choice(["{w}", "i think {w}", "is it {w}", "the answer is {w}", "{w} i guess"]).format(w=w.lower())
    elif a["type"] == "keywords":
        groups = a.get("all") or a.get("any") or []
        if kind == "correct":
            ws = [rng.choice(g) for g in (a.get("all") or [])] or [rng.choice(rng.choice(a["any"]))]
            t = " ".join(ws)
            t = rng.choice(["{t}", "okay {t}", "{t} over"]).format(t=t)
        else:
            t = rng.choice(["hello", "i like the moon", "what", "okay", "rover", "hmm shields"])
        _ = groups
    elif a["type"] == "command":
        e = a["expect"]
        if kind == "correct":
            if e["type"] == "allocate":
                lw = rng.choice(LOAD_SYN[e["to"]])
                t = rng.choice(["more power to {l}", "give the {l} more power", "boost the {l}", "{l} up please"]).format(l=lw)
            elif e["type"] == "shelter":
                t = rng.choice(["everyone into the shelter", "go to the shelter", "take cover"]) if e.get("on") else \
                    rng.choice(["leave the shelter", "come out of the shelter"])
            else:
                t = rng.choice(["send the rover for ice", "rover go get ice", "go collect ice"])
        else:
            t = rng.choice(["turn off the heaters", "send the rover home", "end shift", "what is the moon"])
    elif a["type"] == "intent":
        t = ("show me " + a["place"].replace("_", " ")) if kind == "correct" else "show me tycho"
    else:  # tap: answered by a tap; a spoken answer is not graded
        t = rng.choice(["is it here", "where is it", "this one"])
    return {"text": t, "cat": f"academy_{kind}", "root": f"ac:{lesson['id']}:{step_i}:{t}", "lesson": lesson["id"],
            "step": step_i}


# ================================================================================================ round 6: hands-free
# Today's real failure classes (docs/DIRECTOR_LOOP.md). Every item carries the client's screen `frame` (the router's
# context) and a gold act; lesson answers carry lesson/step so the gold is the Academy grader on the CLEAN words.
GLOBE_TYPES = ("predict", "globe_side", "terminator", "compare", "route", "earth_view")
LESSON_CHATTER = ["oh it's", "okay", "alright", "oh it's the", "okay okay", "alright alright", "oh cool", "it's",
                  "oh wait", "yeah", "oh okay", "wait wait", "alright so", "oh it's a", "okay so", "oh nice",
                  "okay okay okay", "oh my gosh", "alright then", "oh it's that", "yeah okay", "oh look", "oh right",
                  "yeah yeah", "okay wait", "oh is it", "it's it's", "alright alright alright", "oh yeah",
                  "okay let me see", "hold on", "one sec", "wait what", "oh i see"]
# CAPCOM / guide lines that run back to back (the echo comes back between them); the app's own voices say them
CAPCOM_LINES = ["Copy. Radiation shields up 20 percent. Less for the greenhouse.",
                "Solar particle storm. Shields up, or crew to the shelter.",
                "Battery's low. Turn down what you don't need.", "Sunset. Give the heaters a little more.",
                "Life support is low. The rover can fetch ice.", "Earth has set. No radio until it rises.",
                "Dose is climbing. Shields, or the shelter.", "Set your power, then end the shift.",
                "Copy. Rover heading out to collect ice.", "Crew dose: 12 of 50 mSv.",
                "Earth is up. Houston can hear us.", "Next window in about 6 hours.",
                "Copy. Heaters up 10 percent.", "Standing order set: if a storm comes, go to the shelter.",
                "Commander, set the heaters to 40 percent.", "Find where Apollo 11 landed.",
                "Turn the Moon to show the far side.", "Tap the line where day meets night.",
                "Which outpost can talk to Earth more often?", "Night is coming at Malapert. Move power to the heaters.",
                "Great work, Commander. That's the patch.", "Do people on Earth ever see the Moon's far side?"]
OFFERS = {"next_lesson": ("Ready for the next lesson?", ["lesson_done", "patch"]),
          "next_step": ("Ready for the next one?", ["lesson"]),
          "mission": ("Ready to take command?", ["patch", "map"]),
          "fly_again": ("Fly again?", ["debrief"])}
OFFER_TAKE = ["next", "yes", "yeah", "okay", "sure", "next one", "yes please", "let's go", "ready", "okay next",
              "yep", "next please", "i'm ready", "go"]
OFFER_DECLINE = ["no", "not now", "no thanks", "maybe later", "nope"]
PANEL_NAV = ["open the {p} panel", "show me the {p} panel", "go to the {p} station", "open the {p}",
             "take me to the {p} panel", "the {p} panel please", "pull up the {p} panel", "switch to the {p} panel",
             "back to my seat", "close the panel", "go back to my seat", "okay open the {p} panel"]
PANEL_NAMES = ["power", "comm", "comms", "radio", "habitat", "rover", "radiation"]
PANEL_ORDERS = ["turn off the radio", "radio off", "more power to the radio", "turn on the radio", "comms to 30",
                "turn down the radio", "power to the habitat heaters", "turn off the rover", "less power for comms",
                "shields to 40", "more power to the heaters", "send the rover for ice", "turn up the shields"]
HELP_NAV = ["what can i say", "help me", "what are my options", "where am i", "what can i do", "what screen is this",
            "move the voice bar to the top right", "put the voice bar on the left", "move the mic bar to the bottom",
            "reset the voice bar", "move the voice bar to the top", "say that again", "repeat that", "slow down",
            "speak slower", "open the settings", "what do i do", "what do i do now", "give me a tour",
            "show me around", "start the tour", "how do i play", "i need help"]
MODE_NAV = ["go to mission", "go to the mission", "let's do the mission", "open the library", "go to the academy",
            "go to the map", "back to the map", "open the patch map", "start the mission", "take command",
            "go to outpost luna", "explore the moon", "go on a mission", "open the missions"]
# kid-style mishears the real Arc ear makes (fallback when no real decode is cached): word -> heard
MISHEAR = {"ice": ["eyes", "i s", "rice", "ice"], "rover": ["rover", "roller", "row ver"], "far": ["far", "four", "father"],
           "shields": ["shield", "she ields", "fields"], "heaters": ["heater", "eaters", "heat yours"],
           "terminator": ["termination", "terminate her"], "shackleton": ["shackle ton", "shackleton"],
           "malapert": ["mallow pert", "malla part"], "side": ["side", "sight"], "never": ["never", "nev er"],
           "forty": ["forty", "four tea"], "radio": ["radio", "ready oh"]}
MISHEAR_KID = ["send the rover for ice", "rover go get ice", "go collect ice", "the far side", "far side",
               "show me the far side", "it's the terminator", "the terminator", "shackleton", "malapert",
               "more power to the heaters", "shields up", "never", "heaters forty", "go dig ice with the rover",
               "where is the ice", "is there ice on the moon", "turn off the radio", "the rover", "malapert mountain"]


def mishear(rng: random.Random, text: str) -> str:
    out = []
    for w in text.split():
        alts = MISHEAR.get(w)
        out.append(rng.choice(alts) if alts and rng.random() < 0.7 else w)
    return " ".join(out)


def _course():
    from app.academy import content
    return content.course()["lessons"]


def lesson_steps(types=None) -> list[tuple[dict, int]]:
    return [(L, i) for L in _course() for i, st in enumerate(L["steps"])
            if not L.get("ride") and (types is None or st["accept"]["type"] in types)]


def step_frame(L: dict, i: int) -> dict:
    a = L["steps"][i]["accept"]
    opts = [o["label"] for o in a.get("options") or []]
    return {"screen": "lesson", "step_type": a["type"], "step_options": opts, "offer": None, "lesson_id": L["id"],
            "step": i}


def globe_answer(rng: random.Random, L: dict, i: int, kind: str) -> str:
    """A spoken answer to one of the 6 globe step types: correct / wrong / paraphrase (kid style)."""
    from app.academy import grade as G
    a = L["steps"][i]["accept"]
    t = a["type"]
    wrap = rng.choice(["{w}", "i think {w}", "um {w}", "{w} i guess", "is it {w}", "it's {w}", "{w}"])
    if t in ("predict", "compare"):
        opts = a["options"]
        o = next(x for x in opts if x["id"] == a["answer"]) if kind == "correct" else \
            rng.choice([x for x in opts if x["id"] != a["answer"]] or opts)
        if t == "predict" and kind == "wrong":   # a predict guess always passes: a wrong one is not naming any option
            return rng.choice(["hmm i don't know", "the blue one", "maybe", "uh the other one"])
        return wrap.format(w=rng.choice([o["label"].lower()] + list(o.get("say") or [])))
    if t == "globe_side":
        want = a["want"]
        other = "near" if want == "far" else "far"
        ws = G.SIDE_WORDS[want if kind == "correct" else other]
        return wrap.format(w=rng.choice(ws[:6]))
    if t == "terminator":
        return wrap.format(w=rng.choice(["the terminator", "where day meets night", "the shadow line", "terminator",
                                         "between day and night"] if kind == "correct" else
                                        ["the middle", "the bright part", "over there", "the dark part"]))
    if t == "route":
        names = [G.gaz().places[s].name.lower() for s in a["stops"]]
        if kind == "correct":
            return rng.choice(["{a} then {b}", "{a} and then {b}", "go to {a} then {b}", "first {a} then {b}"]).format(
                a=names[0], b=names[-1])
        return rng.choice(["{b} then {a}", "just {b}", "tycho then copernicus"]).format(a=names[0], b=names[-1])
    if t == "earth_view":
        ok, _ = G.grade(L["steps"][i], {"text": "yes"})
        right = "yes" if ok else ("no" if G.grade(L["steps"][i], {"text": "no"})[0] else "sometimes")
        wrong = rng.choice([x for x in ("yes", "no", "sometimes") if x != right])
        w = right if kind == "correct" else wrong
        return wrap.format(w=rng.choice([w, w + " you could", w + " always" if w == "yes" else w]))
    return "hmm"


def cls_split(root: str) -> str:
    """The class pools are small (a dozen phrases): a third of each is held out, so a class set is not one phrase."""
    x = h(root) % 100
    return "test" if x < 34 else "val" if x < 44 else "train"


def cls_item(cls: str, rng: random.Random, split: str) -> dict:
    """One item of a round-6 class. `root` is the split key (the phrase / step), so test phrases never train."""
    def pick(pool, tag):
        ps = [p for p in pool if cls_split(f"{tag}:{p}") == split] or pool
        return rng.choice(ps)
    if cls == "chatter":                    # room chatter during a lesson step: never an answer, never a miss
        L, i = rng.choice(lesson_steps())
        t = pick(LESSON_CHATTER, "lc")
        return {"text": t, "cat": "cls_chatter", "root": "lc:" + t, "frame": step_frame(L, i),
                "gold": {"act": "ignore"}, "dd": (0.3, 0.95), "lesson": L["id"], "step": i}
    if cls == "echo":                       # our own line heard back between two back-to-back CAPCOM lines
        a = pick(CAPCOM_LINES, "cl")
        b = rng.choice([x for x in CAPCOM_LINES if x != a])
        ws = re.sub(r"[^a-z0-9' ]", " ", a.lower()).split()
        k = rng.randint(2, min(6, len(ws)))
        st = rng.randint(max(0, len(ws) - k - 2), len(ws) - k)
        return {"op": "echo2", "text": " ".join(ws[st:st + k]), "lines": [a, b], "cat": "cls_echo", "root": "cl:" + a,
                "frame": {"screen": rng.choice(["cabin", "cabin", "lesson", "brief"]), "step_type": None,
                          "step_options": [], "offer": None}, "gold": {"act": "ignore"}, "dd": (0.4, 0.9)}
    if cls == "offer":                      # "next" / "yes" within 0.3 s of the offer line ending: navigate
        kind = rng.choice(list(OFFERS))
        line, screens = OFFERS[kind]
        t = pick(OFFER_TAKE, "ot") if rng.random() < 0.8 else pick(OFFER_DECLINE, "od")
        return {"op": "offer", "text": t, "lines": [line], "gap": rng.uniform(0.02, 0.3), "cat": "cls_offer",
                "root": "ot:" + t, "frame": {"screen": rng.choice(screens), "step_type": None, "step_options": [],
                                             "offer": kind}, "gold": {"act": "navigate"}, "dd": (0.6, 0.98)}
    if cls == "panel":                      # panel navigation vs a real order, in the cabin
        if rng.random() < 0.55:
            f = pick(PANEL_NAV, "pn")
            t = f.format(p=rng.choice(PANEL_NAMES))
            g = {"act": "navigate"}
            root = "pn:" + f
        else:
            t = pick(PANEL_ORDERS, "po")
            g, root = {"act": "command"}, "po:" + t
        return {"text": t, "cat": "cls_panel", "root": root, "gold": g,
                "frame": {"screen": "cabin", "step_type": None, "step_options": [], "offer": None}}
    if cls == "help":                       # voice bar, tour, help, "what do i do"
        t = pick(HELP_NAV, "hn")
        sc = rng.choice(["map", "lesson", "cabin", "library", "patch", "brief"])
        fr = {"screen": sc, "step_type": None, "step_options": [], "offer": None}
        if sc == "lesson":
            L, i = rng.choice(lesson_steps())
            fr = step_frame(L, i)
        return {"text": t, "cat": "cls_help", "root": "hn:" + t, "frame": fr, "gold": {"act": "navigate"}}
    if cls == "mode":                       # a mode switch in the middle of a lesson
        L, i = rng.choice(lesson_steps())
        t = pick(MODE_NAV, "mn")
        return {"text": t, "cat": "cls_mode", "root": "mn:" + t, "frame": step_frame(L, i), "gold": {"act": "navigate"}}
    if cls == "globe":                      # the 6 globe step types answered by voice (gold = the grader)
        L, i = rng.choice(lesson_steps(GLOBE_TYPES))
        kind = "correct" if rng.random() < 0.6 else "wrong"
        t = globe_answer(rng, L, i, kind)
        return {"text": t, "cat": "cls_globe_" + L["steps"][i]["accept"]["type"], "root": f"gl:{L['id']}:{i}:{t}",
                "frame": step_frame(L, i), "lesson": L["id"], "step": i}
    if cls == "mishear":                    # kid-style mishears from the real Arc ear ("eyes" for "ice")
        t = pick(MISHEAR_KID, "mh")
        sc = rng.choice(["cabin", "lesson"])
        it = {"text": t, "cat": "cls_mishear", "root": "mh:" + t, "heard_fallback": mishear(rng, t)}
        if sc == "lesson":                 # the step's correct answer, heard through the kid-style ear
            L, i = rng.choice(lesson_steps(("command", "keywords", "intent", *GLOBE_TYPES)))
            ty = L["steps"][i]["accept"]["type"]
            for _ in range(8):
                t = globe_answer(rng, L, i, "correct") if ty in GLOBE_TYPES else academy_items(rng, L, i)["text"]
                if not t.startswith(("i don", "can i", "help", "i m stuck", "what do", "hmm")):
                    break
            it.update(text=t, root=f"mhl:{L['id']}:{i}", heard_fallback=mishear(rng, t), frame=step_frame(L, i),
                      lesson=L["id"], step=i)
        else:
            it.update(frame={"screen": "cabin", "step_type": None, "step_options": [], "offer": None},
                      gold={"act": "command"} if not t.startswith(("where", "is ", "the ", "far", "show",
                                                                     "it s", "it's", "never", "shackleton", "malapert"))
                      else None)
            if it["gold"] is None:
                it.pop("gold")
        return it
    if cls == "roomtalk":                   # room talk Arc rates device-directed: never a turn for us
        t = pick(ROOM_TALK, "rt")
        sc = rng.choice(["lesson", "cabin", "map", "library", "patch"])
        fr = {"screen": sc, "step_type": None, "step_options": [], "offer": None}
        it = {"text": t, "cat": "cls_roomtalk", "root": "rt:" + t, "gold": {"act": "ignore"}, "dd": (0.75, 0.98)}
        if sc == "lesson":
            L, i = rng.choice(lesson_steps())
            fr = step_frame(L, i)
        return {**it, "frame": fr}
    raise ValueError(cls)


# Round 7: real room talk that Arc Tagger rates highly device-directed ("shit shit oh": dd 0.91, docs/ARC_FEEDBACK.md):
# exclamations, swearing, sibling talk, on any screen. gold ignore, with device_directed drawn HIGH (0.75-0.98).
ROOM_TALK = ["shit shit oh", "oh shit", "oh my god", "oh my gosh", "what the heck", "damn it", "come on", "no way",
             "ugh this is so hard", "stop it", "give it back", "that's mine", "mom", "mom can i have a snack",
             "dude look at that", "that's so cool", "whoa cool", "crap", "oh no no no", "are you kidding me",
             "leave me alone", "i'm so bored", "what the hell", "yay", "awesome", "oh man", "jeez", "seriously",
             "shut up", "ha ha ha", "you're so annoying", "can i go outside", "where's my cup", "it's my turn",
             "nooo", "oh crap", "this is boring", "wow wow wow", "hey give me that", "be quiet"]
CLASSES = ("chatter", "echo", "offer", "panel", "help", "mode", "globe", "mishear", "roomtalk")
