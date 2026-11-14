"""Generate data/mission/command_bank.json: example phrasings -> Commands, for the embedding fallback of mission NLU.

Built from the NLU rule tables (load synonyms, task words, query words) and the contract command types, plus kid-style
paraphrase shapes the rules don't cover. Every command is checked with nlu.valid(). Run: `uv run python tools/gen_command_bank.py`.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.mission import nlu  # noqa: E402

SYN = {  # spoken names per load (subset of nlu.LOAD_WORDS, plus kid words)
    "shields": ["shields", "radiation shields", "force field", "protection"],
    "life_support": ["life support", "oxygen", "the air machine", "breathing machine"],
    "greenhouse": ["greenhouse", "plants", "garden", "food plants"],
    "science": ["science lab", "experiments", "the lab"],
    "rover": ["rover", "moon buggy"],
    "comms": ["radio", "antenna", "comms"],
    "heaters": ["heaters", "heating", "warmth"],
}
MORE = ["give more power to the {l}", "the {l} need more power", "pump up the {l}", "crank up the {l}",
        "boost the {l}", "we need extra juice for the {l}", "feed the {l} more energy", "power up the {l} more",
        "can the {l} have more electricity", "make the {l} stronger"]
LESS = ["give less power to the {l}", "the {l} can have less power", "turn down the {l}", "dial back the {l}",
        "save power on the {l}", "the {l} are using too much power", "take some power away from the {l}"]
OFF = ["turn off the {l}", "shut down the {l}", "we don't need the {l} right now", "power off the {l}"]
ALL = ["put everything into the {l}", "all the power to the {l}", "give the {l} every bit of power"]
HALF = ["give half the power to the {l}", "split it so the {l} get half"]
PCT = ["set the {l} to {n} percent", "put the {l} at {n} percent", "make the {l} {n} percent", "{l} to {n} percent please"]
DELTA = ["move {n} percent to the {l}", "add {n} percent to the {l}", "give the {l} {n} more percent"]

FEELINGS = [  # situation -> command (kid says how things are, not what to do)
    ("it's freezing in here", {"type": "allocate", "to": "heaters", "amount": {"kind": "little", "value": 5}}),
    ("my toes are cold", {"type": "allocate", "to": "heaters", "amount": {"kind": "little", "value": 5}}),
    ("the crew is shivering", {"type": "allocate", "to": "heaters", "amount": {"kind": "little", "value": 5}}),
    ("the plants look sad and droopy", {"type": "allocate", "to": "greenhouse", "amount": {"kind": "little", "value": 5}}),
    ("the plants are dying", {"type": "allocate", "to": "greenhouse", "amount": {"kind": "little", "value": 5}}),
    ("it's hard to breathe", {"type": "allocate", "to": "life_support", "amount": {"kind": "little", "value": 5}}),
    ("the air feels stuffy", {"type": "allocate", "to": "life_support", "amount": {"kind": "little", "value": 5}}),
    ("we're getting too much radiation", {"type": "allocate", "to": "shields", "amount": {"kind": "little", "value": 5}}),
    ("protect us from the radiation", {"type": "allocate", "to": "shields", "amount": {"kind": "little", "value": 5}}),
    ("we can't hear earth", {"type": "allocate", "to": "comms", "amount": {"kind": "little", "value": 5}}),
]
DISPATCH = {
    "collect_ice": ["send the rover to get ice", "go dig for ice", "we need water, go get some ice", "rover, fetch frozen water",
                    "go mine some ice in the crater", "drive the buggy to the ice", "get us some water from the crater"],
    "repair_array": ["fix the solar panels", "go repair the array", "the solar panels are broken", "send the rover to fix the panels",
                     "patch up the solar array", "the panels need fixing"],
    "explore": ["go explore", "send the rover exploring", "go look around the crater", "drive around and see what's out there",
                "go on an adventure with the rover", "scout the area"],
    "return": ["bring the rover back", "rover come home", "come back to base", "park the rover at home", "drive back to the base",
               "the rover should return now"],
}
SHELTER = {True: ["everyone into the shelter", "go to the shelter", "hide from the storm", "take cover", "get in the bunker",
                  "everybody get inside now", "go somewhere safe from the storm", "duck and cover"],
           False: ["leave the shelter", "come out of the shelter", "it's safe now, everyone out", "all clear, get out",
                   "the storm is over, go back to work"]}
QUERY = {
    "power": ["how much power do we have", "how's the battery", "is the battery full", "how much energy is left",
              "are we running out of power"],
    "oxygen": ["how much air do we have", "is there enough oxygen", "how much oxygen is left", "can we still breathe ok"],
    "dose": ["how much radiation did we get", "what's our dose", "is the radiation bad", "are we safe from radiation"],
    "storm": ["is a storm coming", "what's the space weather", "is the sun calm", "any solar storms"],
    "comms": ["can we talk to earth", "is the radio working", "can earth hear us", "when can we call home"],
    "all": ["how are we doing", "give me a status report", "how is the base", "is everything okay", "how are things"],
}
HOUSTON = ["call houston", "tell mission control we're okay", "radio earth", "phone home", "send a message to houston",
           "ask houston for help", "talk to ground control"]
END = ["end the shift", "next day please", "go to sleep", "we're done for today", "skip to tomorrow", "time for bed", "fast forward"]
RULES = [("if a storm comes go to the shelter", "storm", {"type": "shelter", "on": True}),
         ("when the sun storm hits hide in the bunker", "storm", {"type": "shelter", "on": True}),
         ("if the power gets low turn off the science lab", "low_power",
          {"type": "allocate", "to": "science", "amount": {"kind": "none", "value": 0}}),
         ("when it gets dark turn up the heaters", "dark", {"type": "allocate", "to": "heaters", "amount": {"kind": "delta", "value": 10}}),
         ("if the air gets low give more to life support", "low_oxygen",
          {"type": "allocate", "to": "life_support", "amount": {"kind": "delta", "value": 10}})]


def A(load: str, kind: str, v: float) -> dict:
    return {"type": "allocate", "to": load, "amount": {"kind": kind, "value": v}}


def main() -> None:
    ex: list[dict] = []
    for load, names in SYN.items():
        for i, l in enumerate(names):
            pick = lambda xs, k: [xs[(i * k + j) % len(xs)] for j in range(k)]  # noqa: E731 - spread shapes over synonyms
            ex += [{"text": t.format(l=l), "command": A(load, "delta", 10)} for t in pick(MORE, 4)]   # more = +10
            ex += [{"text": t.format(l=l), "command": A(load, "delta", -10)} for t in pick(LESS, 3)]  # less = -10
            ex += [{"text": t.format(l=l), "command": A(load, "none", 0)} for t in pick(OFF, 2)]
            ex += [{"text": t.format(l=l), "command": A(load, "all", 100)} for t in pick(ALL, 1)]
            ex += [{"text": t.format(l=l), "command": A(load, "half", 50)} for t in pick(HALF, 1)]
            n = [20, 30, 40, 50, 60][i % 5]
            ex += [{"text": t.format(l=l, n=n), "command": A(load, "percent", n)} for t in pick(PCT, 2)]
            ex += [{"text": t.format(l=l, n=10), "command": A(load, "delta", 10)} for t in pick(DELTA, 1)]
    ex += [{"text": t, "command": c} for t, c in FEELINGS]
    ex += [{"text": t, "command": {"type": "dispatch", "vehicle": "rover", "task": k, "target": None}} for k, ts in DISPATCH.items() for t in ts]
    ex += [{"text": t, "command": {"type": "shelter", "on": on}} for on, ts in SHELTER.items() for t in ts]
    ex += [{"text": t, "command": {"type": "query", "what": k}} for k, ts in QUERY.items() for t in ts]
    ex += [{"text": t, "command": {"type": "call_houston", "text": ""}} for t in HOUSTON]
    ex += [{"text": t, "command": {"type": "end_shift"}} for t in END]
    ex += [{"text": t, "command": {"type": "rule", "when": w, "then": th}} for t, w, th in RULES]
    bad = [e for e in ex if nlu.valid(e["command"]) is None]
    assert not bad, bad[:3]
    out = Path(__file__).resolve().parent.parent / "data/mission/command_bank.json"
    out.write_text(json.dumps({"_note": "Generated by tools/gen_command_bank.py. Example phrasings -> contract Commands for the "
                                        "embedding fallback in mission/nlu.py (slots re-read from the words).",
                               "examples": ex}, indent=1))
    print(len(ex), "examples ->", out)


if __name__ == "__main__":
    main()
