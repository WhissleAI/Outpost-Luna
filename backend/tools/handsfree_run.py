"""A scripted hands-free run with no clicks (docs/HANDSFREE.md): a simulated client that only talks.

    call sign -> start -> lesson 1 by voice -> patch -> next -> ... -> check ride -> yes (mission) -> pick Malapert ->
    take command -> tour -> first job ("shields to 40") -> "start the clock" -> the live clock runs (POST /step) and the
    kid does the Now card's jobs by voice ("yes" / "do it", a choice by its name) -> "skip to next event" x N ->
    "time warp four" -> "pause the clock" -> "end shift" (early) -> debrief -> fly again

Every kid turn goes in exactly as the ear posts it (turn start / arc / turn end on the session), and room noise is mixed
in at every screen: "Oh.", "Mm-mm.", "um", an echo of the last line we spoke, two adults chatting. The simulated client
does what frontend/src/main.js does with the decisions: `nav` moves the screens, `answer`/`nav:answer` grades the step
(POST /api/academy/attempt), every line it speaks is reported as playback (so the session hears its own voice).

    in-process (CI):   backend/tests/test_handsfree_run.py
    live server:       uv run python tools/handsfree_run.py --base http://127.0.0.1:8330 [--audio]
                       --audio renders each kid line with Steer /v1/tts on the model server and feeds the PCM to
                       /ws/listen (the Arc ear), so the turns come from real speech recognition.
Prints a short transcript and the count of spoken "I don't know that one yet".
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import time

UNKNOWN = "I don't know that one yet"
CS = "Nova"
# What the UI speaks (frontend/src/story.js, copy v3): the offers are short questions, said once, as their own line.
OFFER = {"next_lesson": "Ready for the next lesson?", "ride": "Ready for your check ride?",
         "mission": "Ready to take command?", "fly_again": "Fly again?", "next_step": "Ready for the next one?"}
CAPCOM = {"patch": lambda name: f"Patch earned: {name}. Nice work, {CS}.",
          "qualified": lambda name: f"{name} patch earned. You're qualified, Commander {CS}."}
NOISE = [("Oh.", 0.9), ("Mm-mm.", 0.8), ("um", 0.6), ("did you remember to buy the milk", 0.2)]


def tour_beats(level: str = "cadet") -> list[str]:
    """The first-mission cabin tour as frontend/src/story.js TOUR has it (one source of truth: read from the file)."""
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[2] / "frontend" / "src" / "story.js").read_text()
    block = re.search(rf"\b{level}: \[(.*?)\n  \]", src, re.S)
    return re.findall(r'text: "([^"]+)"', block.group(1)) if block else []


# ---------------------------------------------------------------------------------------------- what a kid would say
def answer_for(step: dict, gaz=None, vocab=None) -> str:
    acc = step["accept"]
    k = acc["type"]
    if k == "choice":
        return next(o["label"] for o in acc["options"] if o["id"] == acc["answer"])
    if k in ("intent", "tap"):
        name = gaz.places[acc["place"]].name if gaz and acc["place"] in gaz.places else acc["place"].replace("_", " ")
        return ("show me " if k == "intent" else "") + re.sub(r"\s*\(.*?\)", "", name)
    if k == "command":
        e = acc["expect"]
        if e["type"] == "allocate":
            return f"more power to the {e['to'].replace('_', ' ')}"
        if e["type"] == "shelter":
            return "everyone into the shelter" if e["on"] else "everyone out of the shelter"
        if e["type"] == "dispatch":
            return "send the rover for ice"
        if e["type"] == "call_houston":
            return "Houston, any space weather?"
        if e["type"] == "power_save":
            return "night mode on"
    # globe steps (docs/LEARNING_DESIGN.md §3): what a kid says with no hands
    if k in ("predict", "compare"):
        return next(o["label"] for o in acc["options"] if o["id"] == acc["answer"])
    if k == "globe_side":
        return "show me the far side" if acc["want"] == "far" else "show me the near side"
    if k == "terminator":
        return "the terminator, where day meets night"
    if k == "route":
        names = [gaz.places[x].name if gaz and x in gaz.places else x for x in acc["stops"]]
        return " then ".join(re.sub(r"\s*\(.*?\)", "", n) for n in names)
    if k == "earth_view":
        from app.academy.grade import earth_answer
        return {"yes": "yes, Earth is up there", "no": "no, never", "sometimes": "sometimes"}[earth_answer(acc["place"])]
    if k == "keywords":
        q = re.findall(r'"([^"]+)"', step.get("prompt", ""))
        groups = acc.get("all") or acc.get("any") or []
        if q and acc.get("all"):
            return "Copy. " + q[0].replace("Commander, ", "").rstrip(".")
        return " ".join(g[0] for g in groups) or "copy"
    if k.startswith("vocab_"):
        t = (vocab.term(acc["term"]) if vocab else None) or {}
        return t.get("explain", acc["term"]) if k == "vocab_match" else acc["term"]
    return "next"


# ---------------------------------------------------------------------------------------------- the simulated client
class Client:
    """Mirrors main.js + academy/ui.js + mission/ui.js for voice-only use."""

    def __init__(self, t, course: dict, gaz=None, vocab=None, log=print):
        self.t, self.course, self.gaz, self.vocab, self.log = t, course, gaz, vocab, log
        self.mode, self.view, self.L, self.i, self.misses, self.waiting, self.ride = "academy", "callsign", None, 0, 0, False, None
        self.badges: list[str] = []
        self.qualified = False
        self.mscreen, self.site, self.mid = "brief", "shackleton_rim", None
        self.spoken: list[str] = []          # every line the app spoke
        self.tour: list[str] = []            # cabin tour beats still to show (first mission: mission/tour.js)
        self.toured = 0                      # beats the kid moved through by voice
        self.replies_to_noise = 0
        self.clock = {"started": False, "paused": True, "warp": 1}   # the live mission clock (mission/clock.js)
        self.task: dict | None = None        # the Now card's job (State.task), as the client shows it
        self.task_steps_by_voice = 0         # job steps done by "yes" / "do it" / a choice's name
        self.skips = 0                       # "skip to next event" by voice that moved the clock
        self.clock_cmds: list[str] = []      # time_pause / time_resume / time_warp heard
        self.bad_unknowns = 0                # "I don't know" spoken for anything but a real question (once)
        self.n_say = 0

    # -- screens --
    def lessons(self):
        return self.course["lessons"]

    def next_lesson(self):
        return next((l for l in self.lessons() if l["badge"]["id"] not in self.badges), None)

    def frame(self) -> dict:
        if self.mode == "mission":
            t, st = self.task, (self.task or {}).get("step") or {}
            job = {"offer": "task", "step_options": [o["label"] for o in st.get("options") or []]} \
                if t and st.get("ready") and self.mscreen == "cabin" else {}
            return {"screen": {"brief": "brief", "cabin": "cabin", "debrief": "debrief"}[self.mscreen],
                    **({"offer": "fly_again"} if self.mscreen == "debrief" else {"offer": "take_command"}
                       if self.mscreen == "brief" else {"offer": "tour"} if self.tour else job)}
        if self.view == "callsign":
            return {"screen": "callsign"}
        if self.view in ("map", "patch"):
            nx = self.next_lesson()
            return {"screen": self.view, "offer": "mission" if self.qualified else "next_lesson" if nx else None}
        if self.waiting:
            return {"screen": "lesson_done", "offer": "next_step"}
        acc = self.L["steps"][self.i]["accept"]
        opts = acc.get("options") or (self.vocab.options(acc) if self.vocab and acc["type"].startswith("vocab_")
                                       and acc["type"] != "vocab_say" else [])
        return {"screen": "ride" if self.L.get("ride") else "lesson", "step_type": acc["type"],
                "step_options": [o["label"] for o in opts], "lesson_id": self.L["id"], "step": self.i}

    async def push(self):
        await self.t.send({"t": "ui", "event": "screen", **self.frame()})

    # -- the app's own voice --
    async def speak(self, text: str, did: str | None = None):
        if not text:
            return
        self.spoken.append(text)
        self.n_say += 1
        did = did or f"c{self.n_say}"
        await self.t.send({"t": "playback", "kind": "guide", "state": "start", "id": did, "text": text})
        await self.t.wait(min(4.0, 0.25 * len(text.split())))
        await self.t.send({"t": "playback", "kind": "guide", "state": "end", "id": did})
        self.log(f"   APP  ▸ {text[:110]}")

    # -- decisions --
    async def apply(self, ds: list[dict]) -> bool:
        acted = False
        for d in ds:
            t = d["t"]
            if t == "heard":
                continue
            if t == "nav":
                acted = True
                await self.nav(d.get("intent"), d.get("arg"), d.get("text") or "")
            elif t == "answer":
                acted = True
                await self.speak((d.get("r") or {}).get("say") or "")
            elif t == "say":
                acted = True
                await self.speak(d.get("text") or "", d.get("id"))
            elif t == "hud":
                self.task = (d.get("state") or {}).get("task")
                if d.get("state", {}).get("over"):
                    self.mscreen = "debrief"
        await self.push()
        return acted

    async def nav(self, intent: str, arg, text: str):
        if intent == "answer":
            if self.view == "callsign":
                self.view = "map"
                await self.speak(f"Copy that, {CS}. Welcome to Flight School.")
            elif self.L is not None:
                await self.grade(text)
            return
        if intent in ("go_mission",) or (intent == "accept_offer" and arg == "mission"):
            self.mode, self.mscreen = "mission", "brief"
            return
        if intent == "academy":
            self.mode, self.view = "academy", "map"
            return
        if self.mode == "academy":
            if intent == "lesson":
                await self.open(next(l for l in self.lessons() if l["id"] == arg))
            elif intent in ("map", "back"):
                self.view, self.L = "map", None
            elif intent in ("next", "start", "accept_offer"):
                if self.L is not None and self.waiting:
                    await self.step_next()
                elif self.view in ("map", "patch"):
                    if self.qualified:
                        self.mode, self.mscreen = "mission", "brief"
                    elif self.next_lesson():
                        await self.open(self.next_lesson())
            return
        # mission: the cabin tour takes next / yes / skip first (mission/ui.js nav)
        if self.mscreen == "cabin" and self.tour and intent in ("next", "accept_offer", "start"):
            self.tour.pop(0)
            self.toured += 1
            await self.push()
            await self.speak(self.tour[0] if self.tour else "Set power: raise the shields.")
            return
        if self.mscreen == "cabin" and self.tour and intent in ("skip_tour", "decline_offer"):
            self.tour = []
            await self.push()
            return
        if self.mscreen == "cabin" and (intent == "help" or (intent == "a11y" and "what do i do" in text.lower())):
            await self.speak("Here's your next job. " + self.job_line())   # mission/objective.js nowSpoken
            return
        # the live clock and the Now card (mission/ui.js nav): what the client does with these decisions
        if self.mscreen == "cabin" and intent == "skip_event":
            before = (await self.state())["mission_time_h"]
            r = await self.t.post(f"/api/mission/{self.mid}/skip", {})
            self.task = r["state"].get("task")
            if r["state"]["mission_time_h"] > before:
                self.skips += 1
            await self.speak(r.get("say") or "")
            return
        if self.mscreen == "cabin" and intent in ("time_pause", "time_resume", "time_warp"):
            self.clock_cmds.append(intent)
            if intent == "time_warp":
                self.clock["warp"] = arg or 2
            self.clock["started"] = self.clock["started"] or intent != "time_pause"
            self.clock["paused"] = intent == "time_pause"
            await self.speak("Clock paused." if intent == "time_pause" else f"Clock running, {self.clock['warp']} times.")
            return
        if self.mscreen == "cabin" and (intent == "task_choice" or (intent == "accept_offer" and arg == "task")):
            await self.do_job(arg if intent == "task_choice" else None)
            return
        if intent == "pick_site" and self.mscreen in ("brief", "debrief"):
            self.site, self.mscreen = arg, "brief"
            await self.speak(f"{arg.replace('_', ' ').title()}. Good choice. Say take command when you're ready.")
        elif self.mscreen == "brief" and intent in ("take_command", "start", "next", "accept_offer"):
            await self.start_mission()
        elif self.mscreen == "debrief" and intent in ("fly_again", "accept_offer", "start"):
            await self.start_mission()
        elif self.mscreen == "cabin" and intent in ("debrief", "fly_again"):
            await self.debrief()

    # -- the mission's live clock and its jobs (what mission/ui.js does) --
    async def state(self) -> dict:
        s = await self.t.get(f"/api/mission/{self.mid}")
        self.task = s.get("task")
        return s

    def job_line(self) -> str:
        st = (self.task or {}).get("step") or {}
        return st.get("label") or "All steady. Time warp?"

    async def run_clock(self, hours: float):
        """The clock runs while the kid is quiet (the client posts the hours that passed)."""
        if not self.mid or not self.clock["started"] or self.clock["paused"] or self.mscreen != "cabin":
            return
        r = await self.t.post(f"/api/mission/{self.mid}/step", {"dt_h": hours * self.clock["warp"]})
        self.task = r["state"].get("task")
        if r["state"].get("over"):
            self.mscreen = "debrief"
        await self.push()

    async def do_job(self, choice_label: str | None):
        """The Now card's button: its order, its press, or the named choice."""
        t = self.task or {}
        st = t.get("step") or {}
        if not st.get("ready"):
            return
        if st["kind"] == "order":
            r = await self.t.post(f"/api/mission/{self.mid}/command", {"command": st["cmd"]})
        else:
            opt = next((o for o in st.get("options") or [] if o["label"] == choice_label), None) or \
                (st.get("options") or [None])[0]
            cmd = {"type": "task", "task": t["id"], "step": st["id"], **({"choice": opt["id"]} if opt else {})}
            r = await self.t.post(f"/api/mission/{self.mid}/command", {"command": cmd})
        if r["result"].get("needs_confirm"):
            r = await self.t.post(f"/api/mission/{self.mid}/command", {"command": {"type": "confirm"}})
        if r["result"].get("ok"):
            self.task_steps_by_voice += 1
        self.task = r["state"].get("task")
        await self.speak(r["result"].get("ack") or r["result"].get("say") or "")
        await self.push()

    async def open(self, L: dict):
        self.L, self.i, self.misses, self.waiting, self.view = L, 0, 0, False, "lesson"
        if L.get("ride"):
            self.ride = await self.t.post("/api/academy/ride", {})
        await self.push()
        await self.speak(f"{L['brief']} {L['steps'][0]['prompt']}")

    async def step_next(self):
        if self.i + 1 >= len(self.L["steps"]):
            self.view, self.L = "map", None
            return
        self.i, self.waiting, self.misses = self.i + 1, False, 0
        await self.push()
        await self.speak(self.L["steps"][self.i]["prompt"])

    async def grade(self, text: str):
        L = self.L
        r = await self.t.post("/api/academy/attempt", {"lesson_id": L["id"], "step": self.i, "input": {"text": text},
                                                       "misses": self.misses,
                                                       "ride_id": (self.ride or {}).get("ride_id")})
        st = r.get("status")
        self.log(f"   GRADE {L['id']}#{self.i}: {st}")
        if st in ("passed", "missed", "done"):
            if r.get("badge") and (st != "done" or r.get("passed")):
                self.badges.append(r["badge"]["id"])
                if r.get("unlocks") == "mission":
                    self.qualified = True
                self.view, self.L, self.waiting = "patch", None, False
                nx = self.next_lesson()
                # academy/ui.js: the grader's line, then showBadge's patch line and the offer, each its own line
                offer = OFFER["mission"] if self.qualified else \
                    (OFFER["ride"] if nx.get("ride") else OFFER["next_lesson"]) if nx else ""
                await self.push()
                await self.speak(r.get("say", ""))
                name = r["badge"].get("name") or r["badge"]["id"]
                await self.speak(CAPCOM["qualified" if self.qualified else "patch"](name))
                await self.speak(offer)
                return
            if st == "done":            # check ride not passed: fly it again
                await self.open(L)
                return
            self.waiting = True
            if L.get("ride"):           # the ride moves on by itself
                self.i, self.waiting, self.misses = r.get("next_step", self.i + 1), False, 0
                await self.push()
                await self.speak(r.get("say", "") + " " + L["steps"][self.i]["prompt"])
                return
            await self.push()
            await self.speak(r.get("say", ""))
            return
        self.misses += 1
        await self.speak(r.get("say", ""))

    async def start_mission(self):
        st = await self.t.post("/api/mission/start", {"site": self.site, "seed": 7, "roles": []})
        self.mid, self.mscreen = st["id"], "cabin"
        await self.t.send({"t": "hello", "mode": "mission", "mission_id": self.mid, "role": None})
        await self.push()
        name = self.site.replace("_", " ").title()
        await self.speak(f"Outpost Luna is online at {name}. Day one, {CS}.")
        if not self.toured:                       # the first mission: CAPCOM's cabin tour, one beat at a time
            self.tour = tour_beats("cadet")
            await self.push()
            await self.speak(self.tour[0])

    async def debrief(self):
        d = await self.t.get(f"/api/mission/{self.mid}/debrief")
        self.mscreen = "debrief"
        await self.push()
        # mission/ui.js showDebrief: "<head>. Nice flying, <cs>. Grade G, N points. Fly again?"
        outcome = d.get("outcome") or "in_progress"
        head = "Mission complete" if outcome in ("survived", "success") else \
            "Mission paused" if outcome == "in_progress" else "Mission over"
        line = f"{head}." if outcome == "in_progress" else \
            f"{head}. Nice flying, {CS}. Grade {d.get('grade')}, {round(d.get('score') or 0)} points."
        await self.speak(f"{line} {OFFER['fly_again']}")

    # -- the kid --
    async def say(self, text: str, dd: float = 0.9, expect_reply: bool = True, question: bool = False) -> list[dict]:
        """One kid turn. `question`: a real question, the only kind of turn that may get "I don't know that one yet"
        (once each)."""
        self.log(f"   KID  ▸ {text}" + ("" if expect_reply else "   (noise)"))
        ds = await self.t.turn(text, dd)
        heard = [d for d in ds if d["t"] == "heard"]
        if heard:
            self.log(f"          router: {heard[-1]['outcome']} ({heard[-1].get('reason')})")
        n0 = self.unknowns()
        acted = await self.apply(ds)
        if not expect_reply and acted:
            self.replies_to_noise += 1
            self.log("          !! replied to noise")
        new = self.unknowns() - n0
        if new and (not question or new > 1):
            self.bad_unknowns += new - (1 if question else 0)
            self.log("          !! 'I don't know' for a turn that was not a real question")
        return ds

    async def noise(self):
        for t, dd in NOISE:
            await self.say(t, dd, expect_reply=False)
        if self.spoken:           # our last line, heard back through the speakers right away
            await self.t.send({"t": "playback", "kind": "guide", "state": "start", "id": "echo",
                               "text": self.spoken[-1]})
            await self.say(self.spoken[-1], 0.9, expect_reply=False)
            await self.t.send({"t": "playback", "kind": "guide", "state": "end", "id": "echo"})

    def unknowns(self) -> int:
        return sum(s.startswith(UNKNOWN) for s in self.spoken)


async def script(c: Client, shifts: int = 3):
    await c.push()
    await c.noise()
    await c.say("call me Nova")
    await c.say("start")
    guard = 0
    while not c.qualified and guard < 80:   # every lesson by voice, then the check ride
        guard += 1
        if c.view == "patch":
            await c.noise()
            await c.say("next")
            continue
        if c.view == "map":
            await c.say("start")
            continue
        if c.waiting:
            await c.say("next")
            continue
        await c.noise() if c.i == 0 else None
        await c.say(answer_for(c.L["steps"][c.i], c.gaz, c.vocab))
    await c.say("yes")                      # the offer: take command of Outpost Luna
    await c.noise()
    await c.say("pick Malapert")
    await c.say("take command")
    while c.tour:                           # the first-mission cabin tour, answered by "next" (with noise mid-way)
        if c.toured == 3:
            await c.noise()
        await c.say("next")
    await c.say("what do I do?")            # the objective, spoken
    await c.noise()
    for panel in ["open the comm panel", "back to my seat", "move the voice bar to the top right"]:   # 3D cabin + a11y
        await c.say(panel)
    await c.state()
    await c.say("shields to 40")            # the first job: any power change counts ("Power set. Good.")
    await c.say("start the clock")          # the live clock (time_resume)
    for _ in range(6):                      # the clock runs; whatever the Now card asks, the kid says yes / names a choice
        await c.run_clock(1.5)
        await c.state()
        st = (c.task or {}).get("step") or {}
        if st.get("ready"):
            await c.say(st["options"][0]["label"] if st.get("options") else "yes")
        await c.noise()
    for order in ["what's the power level"]:
        await c.say(order)
    await c.say("time warp four")
    await c.run_clock(1.0)
    for _ in range(shifts):                 # skip to next event replaces end shift as the forward action
        await c.say("skip to next event")
        await c.state()
        st = (c.task or {}).get("step") or {}
        if st.get("ready"):
            await c.say(st["options"][0]["label"] if st.get("options") else "yes")
        await c.noise()
    await c.say("pause the clock")
    await c.say("end shift")                # still there: end the shift early
    await c.say("what is the weirdest thing about moon dust", question=True)   # answered, or one "I don't know"
    await c.say("debrief")
    await c.noise()
    await c.say("fly again")


# ---------------------------------------------------------------------------------------------- transports
class InProc:
    """The Session object and the app's HTTP routes in this process (TestClient)."""

    def __init__(self, sess, http, clock):
        self.s, self.http, self.clock = sess, http, clock
        self.trace: list[dict] = []           # every kid turn with its screen (tools: replay against older code)

    async def send(self, m: dict):
        await self.s.handle(m)

    async def wait(self, sec: float):
        self.clock.t += min(sec, 2.0)         # Live.wait: a line "plays" for at most 2 s

    def _since(self, last) -> list[dict]:
        ob = self.s.outbox                    # capped at 400: find where we were by identity, not by length
        for i in range(len(ob) - 1, -1, -1):
            if ob[i] is last:
                return ob[i + 1:]
        return list(ob) if last is not None else list(ob)

    async def turn(self, text: str, dd: float) -> list[dict]:
        last = self.s.outbox[-1] if self.s.outbox else None
        self.trace.append({"text": text, "dd": dd, "screen": self.s.screen_name(), "mode": self.s.belief["mode"]})
        # Exactly Live.turn's timing: the turn starts right after the previous event (e.g. the end of our echo's
        # playback, still inside the ear-lag tail), and the drain comes AFTER the turn. Advancing the clock before
        # the turn start hid the live-only bug where the kid's "next" was taken for the offer's echo.
        self.clock.t += Live.GAP_S
        await self.s.handle({"t": "turn", "state": "start", "text": ""})
        await self.s.handle({"t": "arc", "device_directed": dd})
        self.clock.t += 0.3 * max(1, len(text.split()))
        await self.s.handle({"t": "turn", "state": "end", "text": text})
        out = self._since(last)
        self.clock.t += Live.DRAIN_S
        return out

    async def post(self, path, body):
        return self.http.post(path, json=body).json()

    async def get(self, path):
        return self.http.get(path).json()


class Live:
    """A running backend: /ws/session (and /ws/listen with --audio)."""
    GAP_S = 0.02          # from the last event we sent to the turn start (one WS hop; InProc uses the same)
    DRAIN_S = 1.2         # quiet time we wait for the decisions after a turn ends

    def __init__(self, base: str, audio: bool = False, models: str | None = None):
        import httpx
        self.base, self.audio, self.models = base.rstrip("/"), audio, models
        self.http = httpx.AsyncClient(base_url=self.base, timeout=30)
        self.sid = f"hf-{int(time.time())}"
        self.ws = None

    async def open(self):
        import websockets
        self.ws = await websockets.connect(self.base.replace("http", "ws") + "/ws/session")
        await self.ws.send(json.dumps({"t": "hello", "session": self.sid, "mode": "academy"}))
        await self.drain(1.0)

    async def drain(self, quiet: float = 1.0, total: float = 12.0) -> list[dict]:
        out, end = [], time.monotonic() + total
        while time.monotonic() < end:
            try:
                m = json.loads(await asyncio.wait_for(self.ws.recv(), quiet))
            except asyncio.TimeoutError:
                break
            if m.get("t") not in ("ready", "floor"):
                out.append(m)
        return out

    async def send(self, m: dict):
        await self.ws.send(json.dumps(m))

    async def wait(self, sec: float):
        await asyncio.sleep(min(sec, 2.0))       # our line "plays" (the playback events carry the timing)

    async def turn(self, text: str, dd: float) -> list[dict]:
        if self.audio and not text.startswith(("Mm", "Oh", "um")) and dd >= 0.5:
            return await self.turn_audio(text)
        await self.ws.send(json.dumps({"t": "turn", "state": "start", "text": ""}))
        await self.ws.send(json.dumps({"t": "arc", "device_directed": dd}))
        await self.ws.send(json.dumps({"t": "turn", "state": "end", "text": text}))
        return await self.drain(self.DRAIN_S)

    async def turn_audio(self, text: str) -> list[dict]:
        await asyncio.sleep(0.6)                 # a kid's reaction time after our line
        """Render the line with Steer TTS (the backend's /api/tts), resample to 16 kHz PCM16, stream it into /ws/listen (the Arc ear)."""
        import io
        import wave

        import httpx
        import numpy as np
        import websockets
        r = await self.http.get("/api/tts", params={"text": text, "voice": "story"})   # Steer TTS, a kid-ish voice
        r.raise_for_status()
        w = wave.open(io.BytesIO(r.content))
        sr, x = w.getframerate(), np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32)
        n = int(len(x) * 16000 / sr)
        pcm = np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.int16)
        pcm = np.concatenate([np.zeros(4000, np.int16), pcm, np.zeros(24000, np.int16)])
        async with websockets.connect(self.base.replace("http", "ws") + f"/ws/listen?session={self.sid}") as ws:
            for i in range(0, len(pcm), 1280):
                await ws.send(pcm[i:i + 1280].tobytes())
                await asyncio.sleep(0.04)
            await asyncio.sleep(1.5)
            await ws.send(json.dumps({"t": "stop"}))
        return await self.drain(2.0, total=20)

    async def post(self, path, body):
        return (await self.http.post(path, json=body)).json()

    async def get(self, path):
        return (await self.http.get(path)).json()


def with_course(course: dict, full: dict) -> dict:
    """The server's public course (its order: course.json) with the local answer keys, matched by lesson id, never by
    position: a reordered course must not grade one lesson with another's keys."""
    keys = {fl["id"]: fl for fl in full["lessons"]}
    missing = [pl["id"] for pl in course["lessons"] if pl["id"] not in keys]
    if missing:
        raise SystemExit(f"server lessons with no local answer keys (backend out of date?): {missing}")
    for pl in course["lessons"]:
        pl["steps"] = keys[pl["id"]]["steps"]
    return course


async def main_live(a):
    t = Live(a.base, a.audio, a.models)
    await t.open()
    course = (await t.http.get("/api/academy/course")).json()
    full = __import__("app.academy.content", fromlist=["course"]).course()   # the answer keys (local data)
    with_course(course, full)
    from app.academy import vocab
    from app.config import settings
    from app.gazetteer import Gazetteer
    c = Client(t, course, Gazetteer(settings.data_dir / "places.json"), vocab)
    await script(c, a.shifts)
    print(f"\nspoken 'I don't know that one yet': {c.unknowns()} (for non-questions: {c.bad_unknowns})   "
          f"replies to noise: {c.replies_to_noise}   qualified: {c.qualified}   mission: {c.mid}")
    # one summary line a script (or a person) can check: no replies to noise, "I don't know" only for a real question
    # (once), the whole flow reached
    fails = [k for k, bad in (("replies to noise", c.replies_to_noise), ("fallback for a non-question", c.bad_unknowns),
                              ("not qualified", not c.qualified), ("no mission", not c.mid),
                              ("tour not finished by voice", c.toured < len(tour_beats("cadet"))),
                              ("no skip to next event by voice", c.skips < 1),
                              ("no Now-card job done by voice", c.task_steps_by_voice < 1),
                              ("clock voice commands not routed", not {"time_resume", "time_warp", "time_pause"} <= set(c.clock_cmds)))
             if bad]
    print(f"live clock: {c.skips} skips by voice, {c.task_steps_by_voice} job steps by voice, clock commands {c.clock_cmds}")
    print(f"cabin tour: {c.toured} of {len(tour_beats('cadet'))} beats by voice")
    print(f"HANDSFREE RESULT: {'PASS' if not fails else 'FAIL (' + ', '.join(fails) + ')'}", flush=True)
    if fails:
        raise SystemExit(1)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8330")
    ap.add_argument("--models", default="http://127.0.0.1:8230")
    ap.add_argument("--audio", action="store_true")
    ap.add_argument("--shifts", type=int, default=3)
    asyncio.run(main_live(ap.parse_args()))
