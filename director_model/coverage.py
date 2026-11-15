"""The Director's capability x flow inventory (docs/DIRECTOR_COVERAGE.md): every screen / state the Director runs in x
every intent or act valid there, the training data the generator makes for it today, and the gap.

Built from the code so it stays current:
  screens            features.SCREENS (+ the screens the round-8 branches add: video, prep)
  navigation         every turn_router intent, probed on every screen with a phrase (PROBES): a cell exists where
                     nav_intent() returns that intent on that screen (offers probed with each offer kind)
  lesson answers     every accept.type in backend/data/academy/course.json (answer / wrong answer / chatter)
  mission orders     features.CMD_TYPES + confirm yes / no in the cabin
  questions          every screen
  silence            chatter, echo, filler / room talk on every screen
  pending            the capabilities on unmerged branches (pools_r8.PENDING): video controls, prep tasks, the video
                     step, the new offers, gesture + voice, OS-voice echo, video audio leaking into the mic
Counts: the generator's own items (gen_sessions.kind_script for the train / val splits at the loop's sizes, and every
class set), mapped to cells by item_cell(). The collection kit (collect.py) prompts the same cells.

  uv run --project backend python director_model/coverage.py [--train 2400 --val 200 --cls-n 160]
    -> director_model/coverage.json + the summary; backend/tests/test_director_coverage.py checks it is current.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent / "backend"
OUT = HERE / "coverage.json"
TARGET = {"train": 40, "heldout": 8}     # per cell: generated train items, held-out items (class sets / test splits)
MODE_SCREEN = {"mission": "cabin", "cadet": "library", "academy": "lesson"}
# Screens the router has beyond features.SCREENS (no one-hot slot: the shipped weights keep their layout). Both branches
# are merged on integ/v1, so their cells are real, not pending.
ROUTER_SCREENS = {"video": "feat/media-v1", "prep": "feat/learning-v1"}
PENDING_SCREENS: dict = {}
# A phrase per router intent: the inventory probes nav_intent() with it on every screen. A new intent without a probe
# fails backend/tests/test_director_coverage.py.
PROBES = {"a11y": "what do i do", "skip_event": "skip to the next event", "time_pause": "pause the clock",
          "time_resume": "start the clock", "time_warp": "time warp", "cabin_tour": "show me around",
          "skip_tour": "skip the tour", "repeat": "say that again", "slower": "slow down", "faster": "speak faster",
          "settings": "open settings", "lesson": "lesson one", "map": "go to the map", "academy": "go to the academy",
          "library": "open the library", "go_mission": "go to mission", "take_command": "take command",
          "debrief": "show me the debrief", "fly_again": "fly again", "new_site": "another site",
          "view_orbit": "zoom out", "view_rover": "show me the rover", "view_site": "back to the outpost",
          "start": "start", "next": "next", "back": "go back", "end_shift": "end the shift",
          "panel_power": "open the power panel", "panel_comm": "open the comm panel",
          "panel_habitat": "open the habitat panel", "panel_rover": "open the rover panel",
          "panel_radiation": "open the radiation panel", "panel_back": "back to my seat",
          "accept_offer": "yes", "decline_offer": "no thanks", "pick_site": "pick malapert massif",
          "task_choice": "the ridge", "mute_sound": "mute", "unmute_sound": "unmute", "recenter": "look forward",
          "zoom_in": "closer", "zoom_out": "farther",
          # the landing-site navigator (docs/SITE_NAVIGATOR.md), the picker screen only
          "site_layer": "show sunlight", "site_query": "which site has the most ice", "site_preset": "ice first",
          "why": "why is power low"}   # the cabin's "Why?" cards (docs/PHYSICS.md)
# The screens' own intents (turn_router.VIDEO_CMDS / PREP_CMDS). video_watch stays pending: "watch" is the lesson's
# video-step answer (step:video), not a router intent on the video screen.
SCREEN_INTENTS = {"video": ["video_play", "video_pause", "video_stop", "video_skip"],
                  "prep": ["prep_done", "prep_skip", "prep_wait", "prep_help"]}
PENDING_INTENTS: dict = {}     # all merged (main 4b4b7e1)
OFFERS = ["next_lesson", "next_step", "mission", "take_command", "fly_again", "tour", "task", "practice",
          "practice_done", "moon_base", "prep_task"]


def _setup():
    sys.path.insert(0, str(BACKEND))
    sys.path.insert(0, str(HERE))
    os.environ.setdefault("MODEL_SERVER_URL", "http://127.0.0.1:1")


def router_intents() -> list[str]:
    from app import turn_router as R
    names = [n for n, _ in R.NAV] + ["panel_" + p for p in sorted(set(R.PANELS.values()))] + \
        ["panel_back", "accept_offer", "decline_offer", "pick_site", "task_choice"]
    return sorted(set(names))


def nav_cells() -> dict:
    """(screen, nav:<intent>) -> the probe phrase, wherever the router reads the probe as that intent."""
    from app import turn_router as R
    from app.director_model import features as FX
    from app import session as S
    out = {}
    for screen in FX.SCREENS:
        for intent in router_intents():
            q = PROBES.get(intent)
            if not q:
                continue
            for offer in ([None] + OFFERS if intent in ("accept_offer", "decline_offer", "next", "task_choice")
                          else [None]):
                opts = ["The ridge", "The crater"] if offer == "task" else []
                ctx = R.Ctx(screen=screen, offer=offer, step_options=opts, lessons=S._lessons(), sites=S._sites())
                nv = R.nav_intent(q, ctx)
                if nv and nv[0] == intent:
                    out[(screen, "nav:" + intent)] = q
                    break
    return out


def step_types() -> list[str]:
    course = json.loads((BACKEND / "data" / "academy" / "course.json").read_text())
    return sorted({st["accept"]["type"] for L in course["lessons"] for st in L["steps"]})


def capabilities() -> dict:
    """Every cell: {key: {"screen", "intent", "kind", "pending"?}}."""
    from app.director_model import features as FX
    cells = {}

    def add(screen, intent, kind, pending=None, probe=None):
        k = f"{screen}|{intent}"
        cells[k] = {"screen": screen, "intent": intent, "kind": kind, **({"pending": pending} if pending else {}),
                    **({"probe": probe} if probe else {})}
    for (screen, intent), q in sorted(nav_cells().items()):
        add(screen, intent, "navigate", probe=q)
    for t in step_types():
        for sc in ("lesson", "ride"):
            for outcome in ("answer", "wrong"):
                add(sc, f"step:{t}:{outcome}", "lesson")
    for c in FX.CMD_TYPES[1:]:
        add("cabin", "cmd:" + c, "order")
    for screen in FX.SCREENS:
        add(screen, "question", "answer")
        for neg in ("chatter", "echo", "roomtalk"):
            add(screen, "ignore:" + neg, "ignore")
    for screen in ("cabin", "library"):
        add(screen, "guard:pii", "guard")
    for screen in ROUTER_SCREENS:
        for intent in SCREEN_INTENTS[screen]:
            add(screen, "nav:" + intent, "navigate")
        for intent, b in PENDING_INTENTS.items():
            if intent.startswith(screen):
                add(screen, "nav:" + intent, "navigate", pending=b)
        for neg in ("chatter", "echo", "roomtalk"):
            add(screen, "ignore:" + neg, "ignore", pending=PENDING_SCREENS.get(screen))
        add(screen, "question", "answer", pending=PENDING_SCREENS.get(screen))
    add("video", "ignore:video_audio", "ignore")
    for screen in FX.SCREENS:
        add(screen, "ignore:echo_os_voice", "ignore")
    for screen in ("library", "map", "brief", "cabin"):
        add(screen, "gesture+voice", "cooccur")
    return cells


def item_cell(it: dict, mode: str, lesson_types: dict) -> str | None:
    """The cell one generator item exercises (None: a non-turn op)."""
    from app.director_model import features as FX
    op = it.get("op")
    if op in ("end_shift", "emotion", "tap", "lesson"):
        return None
    fr = it.get("frame") or {"screen": MODE_SCREEN.get(mode, "map")}
    screen = fr.get("screen") or "map"
    g = it.get("gold") or {}
    cat = str(it.get("cat") or "")
    if it.get("gesture"):
        return f"{screen}|gesture+voice"
    if cat == "cls_video_echo":
        return "video|ignore:video_audio"
    if cat == "cls_voice_echo_os":
        return f"{screen}|ignore:echo_os_voice"
    if op in ("echo", "echo2"):
        return f"{screen}|ignore:echo"
    if cat in ("chatter", "cls_chatter") or cat.startswith("barge_chat"):
        return f"{screen}|ignore:chatter"
    if cat in ("cls_roomtalk", "cls_prep_roomtalk"):
        return f"{screen}|ignore:roomtalk"
    if cat == "pii":
        return f"{screen}|guard:pii"
    if g.get("act") == "navigate":
        nav = g.get("nav") or FX.nav_label(it.get("text") or "", fr)
        if fr.get("offer") in ("briefing_video", "learn_more", "explorer_lesson") and \
                nav in ("accept_offer", "decline_offer"):
            return f"{screen}|nav:{nav}@{fr['offer']}"
        if nav in ("none", "other"):
            from app import turn_router as R
            nv = R.nav_intent(it.get("text") or "", R.Ctx(screen=screen, offer=fr.get("offer"),
                                                         step_options=fr.get("step_options") or []))
            nav = nv[0] if nv else nav
        return f"{screen}|nav:{nav}"
    if it.get("lesson") or (screen in ("lesson", "ride") and fr.get("step_type")):
        st = fr.get("step_type") or lesson_types.get((it.get("lesson"), it.get("step")))
        ok = g.get("act") != "nudge" and not cat.endswith(("wrong", "hint")) and it.get("kind") != "wrong"
        return f"{screen}|step:{st}:{'answer' if ok else 'wrong'}"
    if g.get("act") in ("command", "confirm_yes", "confirm_no") or cat.startswith(("cmd", "tpl", "confirm")) or \
            it.get("bank_cmd"):
        c = g.get("command") or it.get("bank_cmd")
        if g.get("act") == "confirm_yes" or cat == "confirm_yes":
            return "cabin|cmd:confirm"
        if g.get("act") == "confirm_no" or cat == "confirm_no":
            return "cabin|cmd:cancel"
        if not c:
            from app.mission import nlu
            cs = [x for x in map(nlu.valid, nlu.parse(it.get("text") or "").get("commands") or []) if x]
            c = cs[0] if cs else None
        return f"cabin|cmd:{FX.cmd_type_of(c)}" if c else "cabin|cmd:none"
    if cat.startswith(("explorer", "barge_explorer", "kidq", "gold", "ear")) or g.get("act") == "answer":
        return f"{screen}|question"
    return f"{screen}|other:{cat or op or 'turn'}"


def count(train: int, val: int, test: int, cls_n: int, hf_p: float = 0.3, r8_p: float = 0.35,
          cov_p: float = 0.0, cov_sessions: int = 0, cov_heldout: int = 0) -> dict:
    sys.argv = [sys.argv[0]]
    import gen_sessions as G
    import pools as P
    from app.academy import content as AC
    G.R8["p"], G.R8["cov"] = r8_p, cov_p
    lt = {(L["id"], i): st["accept"]["type"] for L in AC.course()["lessons"] for i, st in enumerate(L["steps"])}
    c = {"train": Counter(), "heldout": Counter()}

    def items_of(sc):
        cur = None
        for it in sc["items"]:
            if it.get("op") == "lesson":
                cur = (it["lesson_id"], it["step"])
            elif sc["mode"] == "academy" and cur and "lesson" not in it:
                it = {**it, "lesson": cur[0], "step": cur[1]}
            yield it
    for split, n, seed0, group in (("train", train, 10_000, "train"), ("val", val, 500_000, "train"),
                                   ("test", test, 900_000, "heldout")):
        for k in range(n):
            rng = random.Random(seed0 + k)
            sc = G.kind_script(rng, split, seed0 + k, hf_p=hf_p if split in ("train", "val") else 0.0)
            for it in items_of(sc):
                cell = item_cell(it, sc["mode"], lt)
                if cell:
                    c[group][cell] += 1
    for k in range(cov_sessions):
        sc = G.coverage_script(2_000_000 + k, "train")
        for it in (sc or {}).get("items") or []:
            cell = item_cell(it, "mission", lt)
            if cell:
                c["train"][cell] += 1
    if cov_heldout:
        import pools_r8 as P8
        rng = random.Random(999_000)
        for cc in G.gap_cells():          # cls_coverage (merged cells) + cls_coverage_pending (report-only)
            for _ in range(cov_heldout):
                it = P8.cell_item(cc, rng, "test")
                cell = item_cell(it, "mission", lt) if it else None
                if cell:
                    c["heldout"][cell] += 1
    for ci, cls in enumerate(P.CLASSES):
        for it in G.class_set_items(cls, cls_n, 990_000 + 1000 * ci):
            cell = item_cell(it, "mission", lt)
            if cell:
                c["heldout"][cell] += 1
    for ci, cls in enumerate(G.R8_CLASSES):
        for it in G.class_set_items(cls, cls_n, 995_000 + 1000 * ci):
            cell = item_cell(it, "mission", lt)
            if cell:
                c["heldout"][cell] += 1
    return c


def build(a) -> dict:
    caps = capabilities()
    cnt = count(a.train, a.val, a.test, a.cls_n, a.hf_p, a.r8_p, a.cov_p, a.cov_sessions, a.cov_heldout)
    cells = []
    for k, v in sorted(caps.items()):
        tr, ho = cnt["train"].get(k, 0), cnt["heldout"].get(k, 0)
        gap = []
        if tr < TARGET["train"]:
            gap.append(f"train {tr} < {TARGET['train']}")
        if ho < TARGET["heldout"]:
            gap.append(f"held-out {ho} < {TARGET['heldout']}")
        cells.append({"cell": k, **v, "train": tr, "heldout": ho, "gap": gap})
    extra = sorted(set(cnt["train"]) | set(cnt["heldout"]) - set(caps))
    by_kind = defaultdict(lambda: Counter())
    for c in cells:
        by_kind[c["kind"]]["cells"] += 1
        by_kind[c["kind"]]["covered"] += not c["gap"]
        by_kind[c["kind"]]["pending"] += bool(c.get("pending"))
    summary = {"cells": len(cells), "covered": sum(not c["gap"] for c in cells),
               "gap": sum(bool(c["gap"]) for c in cells), "pending": sum(bool(c.get("pending")) for c in cells),
               "by_kind": {k: dict(v) for k, v in sorted(by_kind.items())}}
    return {"note": "Generated by director_model/coverage.py; do not edit by hand (docs/DIRECTOR_COVERAGE.md).",
            "sizes": {"train": a.train, "val": a.val, "test": a.test, "cls_n": a.cls_n, "hf_p": a.hf_p,
                      "r8_p": a.r8_p, "cov_p": a.cov_p, "cov_sessions": a.cov_sessions,
                      "cov_heldout": a.cov_heldout},
            "target": TARGET, "screens": sorted({c["screen"] for c in cells}), "router_intents": router_intents(),
            "step_types": step_types(), "summary": summary, "cells": cells,
            "uncounted_cells": [k for k in extra if k not in caps][:200]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", type=int, default=2400)
    ap.add_argument("--val", type=int, default=200)
    ap.add_argument("--test", type=int, default=200)
    ap.add_argument("--cls-n", type=int, default=160)
    ap.add_argument("--hf-p", type=float, default=0.3)
    ap.add_argument("--r8-p", type=float, default=0.35)
    ap.add_argument("--cov-sessions", type=int, default=0, help="count the round-8 coverage sweep sessions too")
    ap.add_argument("--cov-heldout", type=int, default=0)
    ap.add_argument("--cov-p", type=float, default=0.0, help="count WITH the coverage sweep (the round-8 generator); "
                    "0 = what the round-7 generator makes (the inventory's 'today')")
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args()
    _setup()
    d = build(a)
    Path(a.out).write_text(json.dumps(d, indent=1) + "\n")
    s = d["summary"]
    print(f"{s['cells']} cells: {s['covered']} covered, {s['gap']} with a gap ({s['pending']} pending a branch)")
    for k, v in s["by_kind"].items():
        print(f"  {k:9} {v}")


if __name__ == "__main__":
    main()
