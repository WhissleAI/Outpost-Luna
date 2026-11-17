"""The voice pack's line inventory (docs/VOICE_PACK.md): every fixed line the app speaks -> backend/data/voice_pack/lines.json.

    make voice-pack-lines        (= cd backend && uv run python tools/voice_pack_lines.py)

Two halves:
  backend (this file)   Flight School replies composed exactly as app/academy/routes.py and guide.py compose them
                        (success, reveal, "Here it is.", the hint ladder, route progress, the check ride), the session
                        Director's fixed lines, the mission's task cards, acks, story beats, alerts and readbacks. Code
                        lines are harvested from the source with `ast` in the positions the app speaks from (a `say`,
                        a `decision("say", text=…)`, a task's label / ack, a readback's return), so a new fixed line is
                        picked up without editing this file, and an f-string with an open placeholder is reported live.
  frontend              frontend/tools/voice_lines.mjs: story.js copy, the course prompts, the tour, the Now strip,
                        debrief beats, each composed as the UI composes it. It also splits every line into the units
                        the floor requests (floor.js sayLines: one /api/tts request per sentence).

Placeholders with a small finite set of values (preset call signs, the five sites, hours 1-12, warp factors, scores
0-5) are expanded; the rest stays live. Lines the pack never covers: Houston and the hardware's story voice (their own
role voices), vocabulary lines (slowed and stressed on purpose), anything with an open number or a name.

Output: lines.json {"version", "voice_hint", "lines": [{key, text, source, role, sources}]} sorted by key, and
lines_live.md, the report of what stays live and why. Keys are model_server/app/os_voices.pack_key(text).
"""
from __future__ import annotations

import ast
import importlib.util
import json
import subprocess
import sys
import tempfile
from collections import OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
OUT_DIR = BACKEND / "data" / "voice_pack"

ROLE_GUIDE, ROLE_CAPCOM = "guide", "capcom"
PACK_ROLES = (ROLE_GUIDE, ROLE_CAPCOM)   # Houston and the story voice keep their own role voices: never in the pack


def _os_voices():
    spec = importlib.util.spec_from_file_location("os_voices", ROOT / "model_server/app/os_voices.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pack_key = _os_voices().pack_key


# ================================================================================================ the AST harvester
class Harvest:
    """String literals in the positions a module speaks from. `says` = [(text, source:line)], `live` = f-strings with
    an open placeholder in those positions."""

    def __init__(self, rel: str):
        self.rel = rel
        self.src = (ROOT / rel).read_text()
        self.tree = ast.parse(self.src)
        self.consts = {t.id: n.value.value for n in self.tree.body if isinstance(n, ast.Assign)
                       for t in n.targets if isinstance(t, ast.Name) and isinstance(n.value, ast.Constant)
                       and isinstance(n.value.value, str)}
        self.says: list[tuple[str, str]] = []
        self.live: list[tuple[str, str]] = []

    def where(self, node) -> str:
        return f"{self.rel}:{node.lineno}"

    def strings(self, node) -> list[str] | None:
        """Every value a string expression can take, or None when one part is open (a name, a number, a call)."""
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return [node.value]
        if isinstance(node, ast.Name) and node.id in self.consts:
            return [self.consts[node.id]]
        if isinstance(node, ast.IfExp):
            a, b = self.strings(node.body), self.strings(node.orelse)
            return None if a is None or b is None else a + b
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            a, b = self.strings(node.left), self.strings(node.right)
            return None if a is None or b is None else [x + y for x in a for y in b]
        if isinstance(node, ast.JoinedStr):
            out = [""]
            for v in node.values:
                part = self.strings(v.value) if isinstance(v, ast.FormattedValue) and v.format_spec is None and \
                    v.conversion == -1 else ([v.value] if isinstance(v, ast.Constant) else None)
                if part is None:
                    return None
                out = [x + y for x in out for y in part]
            return out
        return None

    def take(self, node, why: str = "") -> None:
        if node is None:
            return
        vals = self.strings(node)
        if vals is not None:
            self.says += [(v, self.where(node)) for v in vals if v.strip() and v.strip() != "?"]
            return
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):     # "Okay, we've got this. " + short(line)
            left = self.strings(node.left)
            if left:
                self.says += [(v, self.where(node)) for v in left if v.strip()]
        if isinstance(node, (ast.JoinedStr, ast.BinOp, ast.IfExp)):
            self.live.append((self.where(node), (ast.get_source_segment(self.src, node) or "")[:140]))

    def run(self, *, say_keys=("say",), assign_names=("say", "line"), returns: tuple[str, ...] = (),
            step_helpers: dict[str, tuple[int, ...]] | None = None, kw_names=("say", "wait_text"),
            decision_say=False) -> "Harvest":
        step_helpers = step_helpers or {}
        for fn in [n for n in ast.walk(self.tree) if isinstance(n, (ast.FunctionDef, ast.Lambda))]:
            if isinstance(fn, ast.FunctionDef) and fn.name in returns:
                for r in ast.walk(fn):
                    if isinstance(r, ast.Return):
                        self.take(r.value)
        for n in ast.walk(self.tree):
            if isinstance(n, ast.Dict):
                for k, v in zip(n.keys, n.values):
                    if isinstance(k, ast.Constant) and k.value in say_keys:
                        self.take(v)
            elif isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id in assign_names for t in n.targets):
                self.take(n.value)
            elif isinstance(n, ast.Assign) and any(isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant)
                                                    and t.slice.value in kw_names for t in n.targets):
                self.take(n.value)                         # sh["wait_text"] = "…"
            elif isinstance(n, ast.Call):
                fname = n.func.id if isinstance(n.func, ast.Name) else n.func.attr if isinstance(n.func, ast.Attribute) else ""
                for kw in n.keywords:
                    if kw.arg in kw_names and fname != "decision":
                        self.take(kw.value)
                if decision_say and fname == "decision" and n.args and isinstance(n.args[0], ast.Constant) and \
                        n.args[0].value == "say":
                    for kw in n.keywords:
                        if kw.arg == "text" and not (isinstance(kw.value, ast.BoolOp)):
                            self.take(kw.value)
                        elif kw.arg == "text" and isinstance(kw.value, ast.BoolOp):
                            for v in kw.value.values:
                                if self.strings(v):
                                    self.take(v)
                if fname in step_helpers:
                    for i in step_helpers[fname]:
                        if i < len(n.args):
                            self.take(n.args[i])
        return self


# ================================================================================================ backend lines
def academy_says() -> tuple[list[dict], list[dict]]:
    """Flight School replies, composed by the real code (routes.py constants, guide.ladder)."""
    from app.academy import content, guide
    from app.academy.routes import GUESS_OTHER, GUESS_RIGHT, SHOWN
    says, live = [], []
    src = "backend/app/academy/routes.py"
    add = lambda t, s=src: says.append({"lines": [t], "source": s, "role": ROLE_CAPCOM})  # noqa: E731
    for L in content.course()["lessons"]:
        n = len(L["steps"])
        for k, st in enumerate(L["steps"]):
            kind = st["accept"]["type"]
            if kind.startswith("vocab_"):
                continue                  # slowed + stressed on purpose (situation vocab): live, listed by the frontend half
            if L.get("ride"):
                # a miss: why (step.wrong per order, else fail), then the hint (routes._ride_attempt)
                for lead in [st["fail"], *(st.get("wrong") or {}).values()]:
                    add(lead + " " + guide._end(st["hint"]))
                add(st["success"])
                add("Time's up. " + st["hint"])
                exp = (st["accept"] or {}).get("expect")   # "help" on a ride step (routes.academy_hint)
                add(guide._end(st["hint"]) + (f" Tap {guide.order_label(exp)}." if exp else ""))
                continue
            for line in [st["success"], st.get("reveal")]:
                if line:
                    add(line)
                    add(SHOWN + line)
            if kind == "video" and (st["accept"].get("guess") or {}).get("options"):   # the guess, then the answer
                add(GUESS_RIGHT + st["success"])
                add(GUESS_OTHER + st["success"])
            # "help" / "I don't know" / "where is it?": the ladder's rungs, no miss (guide.help_rung)
            for rung in (1, 2, 3):
                add(guide.help_rung(st, rung)["say"], "backend/app/academy/guide.py")
                if kind == "route":
                    for j in range(1, len(st["accept"]["stops"])):
                        add(guide.help_rung(st, rung, st["accept"]["stops"][:j])["say"], "backend/app/academy/guide.py")
            # a real order, the wrong one: why it isn't the one (step.wrong), on both rungs
            for heard in (st.get("wrong") or {}):
                for misses in (0, 1):
                    add(guide.ladder(st, misses, {}, {"heard_order": heard})["say"], "backend/app/academy/guide.py")
            # the hint ladder: rung 1 and rung 2 with nothing tapped (a tapped place's name makes it live)
            for misses in (0, 1):
                extra = {"got": []} if kind == "route" else {}
                add(guide.ladder(st, misses, {}, extra)["say"], "backend/app/academy/guide.py")
            if kind == "route":
                stops = st["accept"]["stops"]
                for j, x in enumerate(stops[1:], 1):   # a later stop tapped first (guide.ladder)
                    add(f"That's {guide.short(x)}. Start with 1: {guide.short(stops[0])}.", "backend/app/academy/guide.py")
                for j in range(len(stops) - 1):
                    add(f"Yes, {guide.short(stops[j])}. Now {guide.short(stops[j + 1])}.")
                    for misses in (0, 1):
                        add(guide.ladder(st, misses, {}, {"got": stops[: j + 1]})["say"], "backend/app/academy/guide.py")
        if L.get("ride"):
            ride_end = [st["success"] for st in L["steps"][-1:]] + ["Time's up. " + L["steps"][-1]["hint"]]
            for said in ride_end:
                for score in range(n + 1):
                    summary = f"Check ride done. {score} of {n} orders right."
                    add(said + " " + summary + " You're qualified, Commander.")
                    add(said + " " + summary + " Not qualified yet. Fly it again.")
    live.append({"source": "backend/app/academy/guide.py", "text": "\"That's <tapped place>. <hint>\"",
                 "reason": "names whatever place the kid tapped (any of the Moon's places)"})
    live.append({"source": "backend/app/academy/routes.py", "text": "the check ride's sim reply (sim_say)",
                 "reason": "readbacks with live numbers"})
    return says, live


def director_says() -> list[dict]:
    from app import director, safety
    out = [{"lines": [getattr(director, k)], "source": "backend/app/director.py", "role": ROLE_GUIDE}
           for k in ("FAR", "NEAR", "EARTHRISE", "SAY_AGAIN", "UNKNOWN", "GUARD", "MISSION", "NO_MOMENT")]
    out += [{"lines": [fix], "source": "backend/app/director.py", "role": ROLE_GUIDE}
            for _, fix, *_ in getattr(director, "MISCONCEPTIONS", [])]
    out.append({"lines": [director.NOT_STARTED], "source": "backend/app/director.py", "role": ROLE_CAPCOM})
    out.append({"lines": [safety.CARE_LINE], "source": "backend/app/safety.py", "role": ROLE_CAPCOM})
    return out


def mission_says() -> tuple[list[dict], list[dict]]:
    from app.mission import gameplay
    from app import session
    says, live = [], []
    hs = [
        Harvest("backend/app/session.py").run(say_keys=(), assign_names=("line",), kw_names=(), decision_say=True),
        Harvest("backend/app/mission/gameplay.py").run(returns=("_not_ready",),
                                                      step_helpers={"_order": (1, 5), "_press": (1, 2), "_wait": (1, 3),
                                                                    "_choice": (1,)}),
        Harvest("backend/app/mission/sim.py").run(returns=("_shift_say", "_risky")),
        Harvest("backend/app/mission/capcom.py").run(say_keys=(), assign_names=(), kw_names=(),
                                                    returns=("readback", "status")),
    ]
    for h in hs:
        says += [{"lines": [t], "source": w, "role": ROLE_CAPCOM} for t, w in h.says]
        live += [{"source": w, "text": seg, "reason": "a placeholder with open values (numbers, names)"} for w, seg in h.live]
    # story beats CAPCOM says (session.SPOKEN_BEATS; gameplay.BEATS: id -> (title, line, visual, objective))
    for beat in sorted(getattr(session, "SPOKEN_BEATS", set(gameplay.BEATS))):
        if beat in gameplay.BEATS:
            says.append({"lines": [gameplay.BEATS[beat][1]], "source": "backend/app/mission/gameplay.py", "role": ROLE_CAPCOM})
    for beat in ("settle", "comm_gap", "first_dark", "ice_return", "final_downlink"):   # frontend SPOKEN_BEATS
        says.append({"lines": [gameplay.BEATS[beat][1]], "source": "backend/app/mission/gameplay.py", "role": ROLE_CAPCOM})
    # the cabin's nudge: "<task title>. Next: <step label>", per task builder (frontend objective.js nudgeLine)
    g = Harvest("backend/app/mission/gameplay.py")
    for fn in [n for n in g.tree.body if isinstance(n, ast.FunctionDef)]:
        titles, labels = [], []
        for n in ast.walk(fn):
            if isinstance(n, ast.Call):
                fname = n.func.id if isinstance(n.func, ast.Name) else ""
                for kw in n.keywords:
                    if fname == "dict" and kw.arg == "title":
                        titles += g.strings(kw.value) or []
                if fname in ("_order", "_press", "_wait", "_choice") and len(n.args) > 1:
                    labels += g.strings(n.args[1]) or []
        for t in titles:
            for lab in labels:
                says.append({"lines": [f"{t}. Next: {lab}"], "source": f"{g.rel}:{fn.lineno}", "role": ROLE_CAPCOM})
            says.append({"lines": [f"{t}: done."], "source": f"{g.rel}:{fn.lineno}", "role": ROLE_CAPCOM})
    live.append({"source": "backend/app/director.py", "text": "answers, place facts, tours, crew-clip intros, readbacks joined with the sim's reply",
                 "reason": "composed per turn from the knowledge base and the live sim"})
    return says, live


# ================================================================================================ build
def build() -> dict:
    a_says, a_live = academy_says()
    m_says, m_live = mission_says()
    backend = {"says": a_says + director_says() + m_says, "live": a_live + m_live}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(backend, f)
        tmp = f.name
    try:
        out = subprocess.run(["node", str(ROOT / "frontend/tools/voice_lines.mjs"), tmp], capture_output=True,
                             text=True, check=True, cwd=ROOT).stdout
    finally:
        Path(tmp).unlink(missing_ok=True)
    data = json.loads(out)
    lines: "OrderedDict[str, dict]" = OrderedDict()
    for u in data["units"]:
        if u["role"] not in PACK_ROLES:
            continue
        k = pack_key(u["text"])
        if not k or len(k) < 2:
            continue
        if k not in lines:
            lines[k] = {"key": k, "text": " ".join(u["text"].split()), "source": u["source"], "role": u["role"],
                        "sources": [u["source"]]}
        elif u["source"] not in lines[k]["sources"]:
            lines[k]["sources"].append(u["source"])
        if u["role"] == ROLE_CAPCOM:        # a line both personas say is listed as CAPCOM's (the common one)
            lines[k]["role"] = ROLE_CAPCOM
    items = sorted(lines.values(), key=lambda x: x["key"])
    return {"lines": items, "live": data["live"], "says": data["says"]}


def write(res: dict) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    doc = {"version": 1, "voice": "com.apple.siri.natural.Nora", "voice_name": "Siri Voice 1 (Nora)",
           "note": "Generated by backend/tools/voice_pack_lines.py (make voice-pack-lines). Do not edit by hand.",
           "rate": "native (no say -r: the voice's own pace and pauses, as the app speaks at 1x)", "count": len(res["lines"]), "lines": res["lines"]}
    (OUT_DIR / "lines.json").write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    seen, rows = set(), []
    for l in res["live"]:
        k = (l["source"], l["text"])
        if k not in seen:
            seen.add(k)
            rows.append(f"| `{l['source']}` | {l['text'].replace('|', '/')} | {l['reason']} |")
    roles = {}
    for l in res["lines"]:
        roles[l["role"]] = roles.get(l["role"], 0) + 1
    (OUT_DIR / "lines_live.md").write_text(
        "# Voice pack: what stays live\n\n"
        "Generated by `make voice-pack-lines` (backend/tools/voice_pack_lines.py). The pack holds "
        f"{len(res['lines'])} lines ({', '.join(f'{v} {k}' for k, v in sorted(roles.items()))}); everything below is "
        "spoken live by the OS voice engine.\n\n"
        "Always live, by design:\n\n"
        "- **Houston** and the **hardware's story voice**: they keep their own role voices.\n"
        "- **Vocabulary lines** (Space words, a glossary word's \"hear it\"): slowed and stressed on purpose.\n"
        "- **Answers**: the Director's replies, place facts, tours, crew-clip intros.\n"
        "- Any line at a pace other than 1x, or with the recorded guide voice turned off in Settings, or with a chosen "
        "voice other than the default guide voice (docs/VOICE_PACK.md).\n\n"
        "| Source | Line | Why live |\n|---|---|---|\n" + "\n".join(rows) + "\n")


def main() -> int:
    res = build()
    write(res)
    roles = {}
    for l in res["lines"]:
        roles[l["role"]] = roles.get(l["role"], 0) + 1
    words = sum(len(l["text"].split()) for l in res["lines"])
    print(f"voice pack lines: {len(res['lines'])} unique ({roles}), {words} words, from {res['says']} says; "
          f"{len({(l['source'], l['text']) for l in res['live']})} live patterns -> {OUT_DIR.relative_to(ROOT)}/lines.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
