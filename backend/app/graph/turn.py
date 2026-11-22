"""The turn graph (docs/TURN_GRAPH.md): one kid turn, today's code as nodes, unchanged.

    intake ─► perceive ─► safety ─┬─► care                                     (one gentle line + a flag; END)
             (fan-out)            └─► route ─┬─ ignore / navigate / answer ─► model_routed ─┬─► ignore          (END)
                                             │                                               └─► heard ─► handoff (END)
                                             └─ question / command ─────────► heard ─► direct ─► readout ─► ear_readout
       ─► director_step ─┬─► model_nav                                                     (the model navigates; END)
                         └─► readback ─┬─► readback_out                                     (a bare "copy"; END)
                                       └─► privacy ─► decide ─┬─► model_ignore ─┐
                                                              ├─► model_clarify ┤
                                                              └─► director ─────┴─► fallback ─┬─► quiet (END)
                                                                  (subgraph: the 13 handlers, │
                                                                   director.HANDLERS, then    └─► story ─┬─► answer_out (END)
                                                                   steering)                             └─► compose ─► emit

Every node body is the code that was in session.Session._turn / _routed / _direct_turn (kept there as the legacy engine
for one release: TURN_ENGINE=legacy), split where it already branched. Session is the supervisor: it owns the belief,
the ear stream, barge-in and the sim poll, and starts one run of this graph per turn (Session._turn_graph).

Perception fan-out: a typed turn needs Arc Tagger twice, once for its safety read and once for the read-out; both
calls are independent of each other, so they run at once and the read-out is used if the turn reaches it with the same
words (a failed or unused prefetch costs nothing; the readout node then asks again, exactly as before).
"""
from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from typing import Any

from .. import brain_counts, care_flags, director, models_client
from .. import safety as safety_
from .. import session as S
from .. import turn_router as router_
from ..director import P_ANSWER, P_BARGE, P_GUARD, decision
from ..director_model import runtime as dmodel
from ..gazetteer import norm
from ..knowledge.answer import did_you_mean
from ..mission import nlu as mission_nlu
from ..readout import summarize
from .runtime import END, Graph, goto

_UNSET = object()


@dataclass
class TurnState:
    """Everything one turn knows, typed; the session's own state (belief, pending, prefs) stays on the Session."""
    sess: Any
    text: str
    source: str
    ctx_r: Any = None                 # turn_router.Ctx
    tags: list | None = None          # Arc Tagger's safety read
    sf: dict | None = None            # safety.classify()
    chan: str | None = None
    rt: dict | None = None            # the router's decision
    rules0: str | None = None
    ents: list = field(default_factory=list)
    out: Any = None                   # the learned Director's outputs at this turn end
    ma: str | None = None
    mp: float | None = None
    nv: dict | None = None
    pre: list = field(default_factory=list)   # cancels of older unplayed decisions (§3 rule 3)
    pre_sent: bool = False
    resolved: str | None = None
    prefetch: Any = _UNSET            # (resolved text, Arc read) from the fan-out, or _UNSET
    read: dict | None = None
    rb: dict | None = None            # radio readback
    ctx: dict | None = None           # director.direct's context
    guard: bool = False
    override: dict | None = None
    r: dict | None = None             # the turn's response (docs/CONTRACT.md) + decisions
    ds: list = field(default_factory=list)
    evs: list = field(default_factory=list)
    dm_stepped: bool = False
    dm_resulted: bool = False

    @property
    def k(self) -> dict:
        return self.sess.belief["kid"]

    @property
    def b(self) -> dict:
        return self.sess.belief


async def _emit(s: TurnState, run, ds: list):
    if s.pre and not s.pre_sent and ds[:len(s.pre)] == s.pre:
        s.pre_sent = True
    await run.emit(ds)


def _turn_result(s: TurnState, r: dict, quiet: bool = True):
    s.dm_resulted = True
    if quiet:
        with contextlib.suppress(Exception):
            s.sess.dm.turn_result(r)
    else:
        s.sess.dm.turn_result(r)


# ---- intake and perception ------------------------------------------------------------------------------------------
def intake(s: TurnState, run):
    """The answer to the ear's "Did you mean X?" (one try), then the routing context."""
    sess = s.sess
    if sess.learning.offer is not None:      # the answer to "Did you mean X?" teaches the learner (never an echo)
        with contextlib.suppress(Exception):
            sess.learning.on_reply(s.text, sess._echoish(s.text, s.source))
    said = sess._confirm_reply(s.text)
    if said:            # "yes" to "Did you mean Tycho?": the turn is the name, as if its option was tapped
        s.text, s.source = said, "typed"
    s.ctx_r = sess.route_ctx(s.source)
    s.tags = s.k.get("safety") if s.source in S.OPEN_MIC or s.source == "ptt" else None


async def _safety_tags(s: TurnState, run):
    if s.tags is None:   # no read from the ear: ask Arc Tagger on the words (~20 ms on the local model server)
        return {"tags": await safety_.tagger_read(s.text, safety_.command_context(s.sess.screen_name()))}
    return None


def _resolved(s: TurnState) -> str:
    return s.sess.resolve_referent(s.text) if s.b["mission_id"] else s.text


async def _readout_prefetch(s: TurnState, run):
    """A typed turn's read-out, while its safety read runs (the same model server, an independent call)."""
    if s.tags is not None or s.source in S.OPEN_MIC:
        return None
    want = _resolved(s)
    try:
        got = await models_client.tag(want, "assistant")
    except Exception:   # noqa: BLE001  (the readout node asks again and fails the way it always did)
        return None
    return {"prefetch": (want, got)}


def safety(s: TurnState, run):
    """[P0] safety first (safety.py): Arc's tags, then the word list. A crisis or grooming cue gets one gentle line and a
    flag for the grown-ups; a rude / toxic turn is ignored (never graded, never a question)."""
    sess = s.sess
    s.sf = sf = safety_.classify(s.text, s.tags)
    s.ctx_r.unsafe = sf["mask"]
    s.chan = sess._channel(s.source, s.ctx_r)
    if sf["mask"]:   # [D1] a filtered turn: counted by kind and channel, never the word (app/brain_counts.py)
        prof = sf["words"] or any(t.startswith("safety.profanity") for t in sf["tags"])
        sess._count_safety("profanity" if prof else "mask", s.chan)
    if sf["care"]:
        sess.flags.append({"kind": "care", "tags": [t for t in sf["tags"] if t.startswith(safety_.CARE_TAGS)],
                           "screen": sess.screen_name(), "ts": sess.clock(),
                           "profile": sess.prefs.get("profile")})   # never the words themselves
        del sess.flags[:-50]
        sess._count_safety("care", s.chan)
        if sess.prefs.get("profile"):   # [D4] kept until a grown-up marks it seen, 30 days at most (app/care_flags.py)
            care_flags.add(sess.prefs["profile"], care_flags.kind_of(sf["tags"]))
        return "care"
    return "route"


async def care(s: TurnState, run):
    s.k["open"] = False
    await s.sess._note({"outcome": "care", "reason": "safety"}, s.text, safety=True)
    await _emit(s, run, [decision("say", P_ANSWER, text=safety_.CARE_LINE, voice="capcom")])
    return END


# ---- routing --------------------------------------------------------------------------------------------------------
async def route(s: TurnState, run):
    sess, k, text, source = s.sess, s.k, s.text, s.source
    if sess.dm is not None:      # round 15 (shadow only): the learned Director's pre-routing read of this turn
        with contextlib.suppress(Exception):
            await sess.dm.perceive(sess._end_event(text, source))
    rt = router_.route(text, s.ctx_r, act=k.get("act"))
    if source in S.OPEN_MIC and rt["outcome"] != "ignore" and S.ear_playback(k.get("ear"), sess.playback_threshold()):
        rt = {"outcome": "ignore", "reason": "echo"}   # our own playback, heard back (libarc's echo reference)
    if sess.prefs.get("profile") and rt.get("reason") != "echo":   # [D2] talk counts without the turn log
        brain_counts.record_turn(sess.prefs["profile"], source, rt.get("outcome"), sess.prefs.get("room"))
    with contextlib.suppress(Exception):           # on-device learning: leak labels, pace, cut-offs (app/learn)
        sess.learning.on_routed(text, source, rt, k.get("ear") if source in S.OPEN_MIC else None,
                                rt.get("reason") == "echo" or S.ear_playback(k.get("ear"), sess.playback_threshold()))
    ents: list[dict] = []
    if rt["outcome"] != "ignore":   # what the kid talked about (to us): the session's entity memory
        with contextlib.suppress(Exception):
            ear = (k.get("ear") or {}) if source in S.OPEN_MIC or source == "ptt" else {}
            ents = sess.memory.note_turn(ear.get("names"), ear.get("spoken") or text, sess.screen_name())
    s.rt, s.ents = rt, ents
    # the turn log keeps no words of a turn Arc marked private or unsafe: it is stored as private (the guard path)
    sess._dm_out, sess._tl_text = None, text
    sess._tl = sess.tlog.begin(text, source, s.ctx_r, rt, k)
    clip, sess.pending_clip = sess.pending_clip, None
    if sess._tl is not None and clip and source in S.OPEN_MIC and clip[0] == norm(text) and \
            sess.clock() - clip[2] <= 10.0:
        sess._tl["_pcm"] = clip[1]
    if sess._tl is not None and ents:   # entity ids + how they were heard (no words)
        sess._tl["entities"] = [{"id": e["id"], "how": e["how"], "p": e["p"], "state": e["state"]} for e in ents]
    if sess._tl is not None and (s.sf["pii"] or s.sf["mask"]):
        sess._tl["_guard"] = True
    s.rules0 = rt["outcome"] if rt["outcome"] in ("ignore", "navigate", "answer") else None   # before any model act
    return "model_routed" if s.rules0 else "heard"


def model_routed(s: TurnState, run):
    """The learned Director steps on every routed turn end (the same stream it was trained on); on a lesson step's answer
    it may silence the turn (room chatter: "oh, it's", "okay") when it is sure enough; in `on` mode it may navigate."""
    sess, rt = s.sess, s.rt
    out = None
    if sess.dm is not None:
        with contextlib.suppress(Exception):
            out = sess.dm.step(sess._end_event(s.text, s.source, rt), {"available": False})
        s.dm_stepped = True
        sess._dm_out = out
        nv = sess._model_nav(out, rt)
        if nv is not None:
            rt = nv
        elif rt["outcome"] == "answer" and out is not None and sess.dm.decide_answer(out):
            rt = {"outcome": "ignore", "reason": "model_chatter"}
            with contextlib.suppress(Exception):
                sess.learning.on_model_ignore(s.text)
            dmodel.STATS["model_overrides"] += 1
            if sess._tl is not None:
                sess._tl["router"]["model"] = "ignore"
    s.rt, s.out = rt, out
    s.ma, s.mp = sess.dm.model_act(out) if (sess.dm is not None and out is not None) else (None, None)
    return goto("ignore") if rt["outcome"] == "ignore" else goto("heard")


async def ignore(s: TurnState, run):
    """Stay silent. Never cancel what we are saying for something we didn't mean to hear (our own echo)."""
    sess, b, k, rt = s.sess, s.b, s.k, s.rt
    if sess.dm is not None:
        _turn_result(s, {"action": "none", "source": "router+" + rt["reason"]})
    sess._log_dir(rules=s.rules0 or "ignore", model=s.ma, p=S._p(s.mp), final="ignore")
    k["open"] = False
    if b["floor"] == "kid":
        b["floor"] = "none"
    await sess._note(rt, s.text)
    return END


async def heard(s: TurnState, run):
    await s.sess._note(s.rt, s.text, hes=s.sess._hesitant(s.text, s.source))
    return "handoff" if s.rt["outcome"] in ("navigate", "answer") else "direct"


async def handoff(s: TurnState, run):
    """The client owns the screens: it runs the navigation / grades the step answer (one decision, visual)."""
    sess, b, k, rt, text = s.sess, s.b, s.k, s.rt, s.text
    if sess.dm is not None:
        _turn_result(s, {"action": "navigate" if rt["outcome"] == "navigate" else "answer_step",
                         "source": "router+" + str(rt.get("intent") or rt["outcome"])})
    fin = "navigate" if rt["outcome"] == "navigate" else "answer"
    sess._log_dir(rules=s.rules0 or fin, model=s.ma, p=S._p(s.mp), final=fin)
    k["open"] = False
    if b["floor"] == "kid":
        b["floor"] = "none"
    # a11y nav with a canonical command (the voice bar): the client runs `text`, so send the canonical form
    if rt.get("intent") == "prep_help" and rt.get("arg") == "missing":   # round 8: a gentle way out
        await _emit(s, run, [decision("say", P_ANSWER, text=S.PREP_MISSING_LINE, voice="capcom")])
    run_text = rt["arg"] if rt.get("intent") == "a11y" and rt.get("arg") else text
    await _emit(s, run, [decision("nav", P_ANSWER, intent=rt.get("intent") or "answer", arg=rt.get("arg"),
                                  text=run_text, heard=text if run_text != text else None)])
    return END


# ---- a question or an order: the Director ----------------------------------------------------------------------------
def direct(s: TurnState, run):
    sess, b, k = s.sess, s.b, s.k
    sess.history.append({"in": s.source, "text": s.text, "ts": sess.clock()})
    # §3 rule 3: a newer turn cancels older, unplayed decisions.
    old = [i for i, d in sess.pending.items() if d["priority"] > P_GUARD]
    for i in old:
        sess.pending.pop(i, None)
    s.pre = [decision("cancel", P_BARGE, ids=old)] if old else []
    s.pre_sent = not s.pre
    if b["floor"] == "kid":
        b["floor"] = "none"
    k["open"] = False
    s.resolved = _resolved(s)


async def readout(s: TurnState, run):
    """Arc Tagger's read-out of the (referent-resolved) words: the prefetched one when the fan-out already asked."""
    if s.prefetch is not _UNSET and s.prefetch[0] == s.resolved:
        got = s.prefetch[1]
    else:
        got = await models_client.tag(s.resolved, "assistant")
    s.read = summarize(got)


def ear_readout(s: TurnState, run):
    """The ear's names for THIS turn: director._link routes on names[i].entity (when its link_p is high enough), else on
    what the ear heard (`spoken`, before the list spelling replaced it)."""
    k, read = s.k, s.read
    ear = (k.get("ear") or {}) if s.source in S.OPEN_MIC or s.source == "ptt" else {}
    if ear:
        read = {**read, "ear_names": list(ear.get("names") or [])}
        if ear.get("spoken"):
            read["ear_spoken"] = ear["spoken"]
        if ear.get("almost"):           # libarc ABI 2: sound-alike names, offered back ("Did you mean ...?")
            read["ear_almost"] = list(ear["almost"])
        if ear.get("quantities"):       # typed numbers / percents / distances (mission amounts)
            read["ear_quantities"] = list(ear["quantities"])
        if ear.get("clean_text"):       # the words without fillers / restarts (mission parsing)
            read["ear_clean"] = ear["clean_text"]
    s.read = read


def director_step(s: TurnState, run):
    """The learned Director steps on the turn end with the read-out; round 7: it may navigate a question / order turn
    (fitted, guarded). The learned aliases (app/learn) reach the read only after this step (the director node)."""
    sess = s.sess
    out = None
    if sess.dm is not None:
        with contextlib.suppress(Exception):
            out = sess.dm.step(sess._end_event(s.text, s.source, s.rt), s.read)
        s.dm_stepped = True
        sess._dm_out = out
    s.out = out
    s.nv = sess._model_nav(out, s.rt)
    return goto("model_nav") if s.nv is not None else goto("readback")


def _est_rules(resolved: str) -> str:
    est = "answer"
    with contextlib.suppress(Exception):
        est = "command" if [c for c in map(mission_nlu.valid, mission_nlu.parse(resolved).get("commands")
                                            or []) if c] else "answer"
    return est


async def model_nav(s: TurnState, run):
    sess, nv = s.sess, s.nv
    s.dm_resulted = True
    with contextlib.suppress(Exception):
        sess.dm.turn_result({"action": "navigate", "source": "director_model+" + nv["intent"]})
    ma, mp = sess.dm.model_act(s.out)
    est = _est_rules(s.resolved)
    sess._log_dir(rules=est, rules_est=True, model=ma, p=S._p(mp), override="navigate", final="navigate",
                  source="director_model")
    await _emit(s, run, s.pre + [decision("nav", P_ANSWER, intent=nv["intent"], arg=nv["arg"], text=s.text)])
    return END


def readback(s: TurnState, run):
    """[0.6] Radio readback (mission/readback.py): a bare "copy" is a readback, never a new order."""
    b, rb = s.b, None
    if b["mission_id"] and b["mode"] == "mission":
        with contextlib.suppress(Exception):
            rb = s.sess._readback(s.text, s.source)
    s.rb = rb
    return "readback_out" if rb and rb["swallow"] else "privacy"


async def readback_out(s: TurnState, run):
    sess, rb = s.sess, s.rb
    if sess.dm is not None:
        _turn_result(s, {"action": "say" if rb["line"] else "none", "say": rb["line"] or "",
                         "source": "mission+readback"})
    sess._log_dir(rules="readback", final="readback")
    await _emit(s, run, s.pre + ([decision("say", P_ANSWER, text=rb["line"], voice="capcom", situation="readback")]
                                 if rb["line"] else []))
    return END


def privacy(s: TurnState, run):
    """The Director's context, and the privacy guard: a name given, or Arc's hard PII on the words."""
    sess, b, k = s.sess, s.b, s.k
    ctx: dict = {"session": sess.id}   # template rotation in the local brain is deterministic per session
    ctx["level"] = sess.level          # Settings: cadet | commander (passed through; docs/VOICES.md)
    if b["last_place"]:
        ctx["last_place"] = b["last_place"]
    if b["mission_id"] and b["mode"] == "mission":
        ctx["mission"] = {"id": b["mission_id"], "role": b["role"], "level": sess.level}
    if k.get("device_directed") is not None and s.source == "listen":
        ctx["device_directed"] = k["device_directed"]
    s.ctx = ctx
    guard = bool(director.NAME_GIVEN.search(norm(s.resolved)))
    with contextlib.suppress(Exception):
        guard = guard or bool(sess.gaz is not None and director._hard_pii(s.read, sess.gaz))
    s.guard = guard


def decide(s: TurnState, run):
    """The decision node: the learned Director may override the rules (ignore / ask_clarify / a command it read)."""
    sess, b, rb = s.sess, s.b, s.rb
    override = None
    if sess.dm is not None and s.out is not None and not (rb and rb.get("cmd")):
        override = sess.dm.decide_turn(s.out, s.resolved, s.guard)
    if override and override["act"] == "command" and not (b["mission_id"] and b["mode"] == "mission"):
        override = None
    s.override = override
    if override and override["act"] == "ignore":
        return goto("model_ignore")
    if override and override["act"] == "ask_clarify":
        return goto("model_clarify")
    return goto("director")


def model_ignore(s: TurnState, run):
    s.r = {"action": "none", "say": "", "source": "director_model", "decisions": []}
    with contextlib.suppress(Exception):
        s.sess.learning.on_model_ignore(s.text)
    return "fallback"


def model_clarify(s: TurnState, run):
    opts = s.override.get("clarify") or []
    q = did_you_mean(opts) if len(opts) == 2 else director.SAY_AGAIN
    r = {"action": "ask", "say": q, "source": "director_model", "ask": {"question": q, "options": opts}}
    r["decisions"] = director.decisions_for(r, s.text, s.ctx)
    s.r = r
    return "fallback"


async def director_node(s: TurnState, run):
    """The rules: director.direct() as a subgraph of its 13 ordered handlers (privacy, mission nlu, ..., the local brain),
    then steering (the typed decisions)."""
    sess, ctx, override, rb = s.sess, s.ctx, s.override, s.rb
    if override and override["act"] == "command":
        ctx["commands"] = [override["command"]]
    if rb and rb.get("cmd"):    # a good readback runs the order it read back: the card's own
        ctx["commands"] = [rb["cmd"]]
    # this cadet's learned aliases and bounded thresholds (app/learn): added after the Director model's step, so its
    # features never see them
    read = s.read
    with contextlib.suppress(Exception):
        read = {**read, **sess.learning.read_extras()}
    s.read = read
    tok = director.RUN.set(run)     # director.direct runs its handlers as a subgraph of this run (traced)
    try:
        s.r = await director.direct(s.resolved, read, sess.gaz, sess.index, ctx)
    finally:
        director.RUN.reset(tok)
    return "fallback"


def fallback(s: TurnState, run):
    """The brain's "I don't know that one yet" (and its guesses) only for a clear device-directed question
    (Session._gate_fallback), the ear's confirm offer, the Director's turn result and the turn log's decision."""
    sess, k, text, source, override = s.sess, s.k, s.text, s.source, s.override
    if override:
        dmodel.STATS["model_overrides"] += 1
    r = sess._gate_fallback(s.r, text, s.ctx_r, k.get("act"))
    if r.get("source") in ("ear_confirm", "ear_near") and r.get("action") == "ask":
        labels = (r.get("ask") or {}).get("labels") or []
        if len(labels) == 1:
            sess.belief["confirm_name"] = {"label": labels[0], "at": sess.clock()}
            with contextlib.suppress(Exception):
                sess.learning.on_offer(r, k.get("ear"), sess._echoish(text, source))
    if sess.dm is not None:
        _turn_result(s, r, quiet=False)
    if r.get("action") == "guard":   # [D1] the privacy guard kept a name or an address private: counted, never the words
        sess._count_safety("pii", sess._channel(source, s.ctx_r))
    if sess._tl is not None:
        from ..director_model import features as _fx
        out, ctx = s.out, s.ctx
        ma, mp = sess.dm.model_act(out) if (sess.dm is not None and out is not None) else (None, None)
        rc = _fx.rules_command(r) if not override else None
        fc = _fx.rules_command(r) or ((ctx.get("commands") or [None])[0] if override else None)
        # v2: when the model overrode, direct() never ran: the rules' act is estimated from the deterministic parse
        est = _est_rules(s.resolved) if override else None
        sess._log_dir(rules=est if override else _fx.rules_act(r), rules_est=True if override else None,
                      rules_cmd=(rc or {}).get("type"),
                      model=ma, p=S._p(mp), override=(override or {}).get("act"), final=_fx.rules_act(r),
                      source=r.get("source"), _cmd=fc,
                      confirm=bool(r.get("needs_confirm")) or any(d.get("t") == "ask_confirm"
                                                                   for d in r.get("decisions") or []))
        # or-ed: the safety step may already have marked it private (Arc's PII / mask tags)
        sess._tl["_guard"] = bool(sess._tl.get("_guard")) or s.guard or r.get("action") == "guard"
    s.r = r
    return "quiet" if r.get("action") == "none" else "story"


async def quiet(s: TurnState, run):
    await _emit(s, run, s.pre)
    return END


def story(s: TurnState, run):
    """A story callback ("You asked about Tycho earlier."), then: a hands-free explorer client renders the answer itself."""
    sess, b, r = s.sess, s.b, s.r
    if r.get("place") and not b["mission_id"] and r.get("say"):
        line = None
        with contextlib.suppress(Exception):
            line = sess.memory.recall_line(r["place"])
        if line:
            r["say"] = f"{line} {r['say']}"
            for d in r.get("decisions") or []:
                if d.get("t") == "say" and d.get("text"):
                    d["text"] = f"{line} {d['text']}"
                    break
    if sess.screen and sess.screen_name() != "cabin" and s.rt["outcome"] == "question":
        return "answer_out"
    return "compose"


async def answer_out(s: TurnState, run):
    slim = {k_: v for k_, v in s.r.items() if k_ not in ("decisions", "readout")}
    await _emit(s, run, s.pre + [decision("answer", P_ANSWER, r=slim, asked=s.text)])
    return END


async def compose(s: TurnState, run):
    """The answer's decisions, the state it changed, the readback praise, a storm in the next shift, the sim's events."""
    sess, b, r, rb = s.sess, s.b, s.r, s.rb
    ds = list(r.get("decisions") or [])
    if r.get("place"):
        b["last_place"] = r["place"]
    if r.get("state"):
        sess._observe_state(r["state"])
    if s.resolved != s.text:
        for d in ds:
            if d["t"] == "card":
                d["resolved"] = s.resolved
    if rb and rb.get("line"):   # "Good readback." after CAPCOM's own line (its own say: the 20-word budget holds)
        first = next((d for d in ds if d["t"] == "say"), None)
        ds.append(decision("say", P_ANSWER, after=first["id"] if first else None, text=rb["line"], voice="capcom",
                           situation="readback"))
    # Multi-stream: a storm starting within the next shift -> one warning alongside the answer.
    if b["mission_id"] and r.get("action") in ("command", "status"):
        ds += sess._storm_lookahead()
    s.evs = await sess._new_events(spoken=False) if b["mission_id"] else []
    s.ds = ds


async def emit(s: TurnState, run):
    await _emit(s, run, s.pre + s.ds)
    if s.evs:   # sim events this turn caused (an "end shift" said aloud): proactive, under the floor rules
        await s.sess.offer(s.evs)
    return END


def _view_rt(s: TurnState):
    rt = s.rt or {}
    return {"outcome": rt.get("outcome"), "reason": rt.get("reason"), "intent": rt.get("intent")}


def _view_r(s: TurnState):
    r = s.r or {}
    return {"action": r.get("action"), "source": r.get("source")}


def build() -> Graph:
    g = Graph("turn")
    g.node("intake", intake)
    g.parallel("perceive", {"safety_tags": _safety_tags, "readout_prefetch": _readout_prefetch})
    g.node("safety", safety, view=lambda s: {"mask": s.sf["mask"], "care": s.sf["care"], "pii": s.sf["pii"]})
    g.node("care", care, commit=True)
    g.node("route", route, view=_view_rt)
    g.node("model_routed", model_routed, view=lambda s: {**_view_rt(s), "model": s.ma, "p": S._p(s.mp)})
    g.node("ignore", ignore, commit=True)
    g.node("heard", heard)
    g.node("handoff", handoff, commit=True)
    g.node("direct", direct)
    g.node("readout", readout)
    g.node("ear_readout", ear_readout)
    g.node("director_step", director_step)
    g.node("model_nav", model_nav, commit=True)
    g.node("readback", readback)
    g.node("readback_out", readback_out, commit=True)
    g.node("privacy", privacy, view=lambda s: {"guard": s.guard})
    g.node("decide", decide, view=lambda s: {"override": (s.override or {}).get("act")})
    g.node("model_ignore", model_ignore)
    g.node("model_clarify", model_clarify)
    g.node("director", director_node, view=_view_r)
    g.node("fallback", fallback, view=_view_r)
    g.node("quiet", quiet, commit=True)
    g.node("story", story)
    g.node("answer_out", answer_out, commit=True)
    g.node("compose", compose, commit=True)
    g.node("emit", emit, commit=True)
    g.chain("intake", "perceive", "safety")
    g.chain("direct", "readout", "ear_readout", "director_step")
    g.edge("privacy", "decide")
    g.edge("compose", "emit")

    @g.on_cancel
    async def cancelled(s: TurnState, run):
        """A barge-in cancelled the turn before it changed anything: the client still hears about the older decisions
        this turn dropped, and the learned Director's stream gets its turn result (none)."""
        if s.pre and not s.pre_sent:
            s.pre_sent = True
            await s.sess.emit(s.pre)
        if s.dm_stepped and not s.dm_resulted and s.sess.dm is not None:
            with contextlib.suppress(Exception):
                s.sess.dm.turn_result({"action": "none", "source": "graph+cancelled"})
    return g.check()


TURN = build()


# ---- the poll: one run per sim tick (Session.poll) ------------------------------------------------------------------
@dataclass
class PollState:
    sess: Any
    st: dict | None = None
    ds: list = field(default_factory=list)


def _p_observe(p: PollState, run):
    p.st = p.sess._state()
    if p.st is None:
        return END
    p.sess._observe_state(p.st)
    if p.sess.dm is not None:
        with contextlib.suppress(Exception):
            p.sess.dm.step({"t": "poll"})


async def _p_events(p: PollState, run):
    p.ds = await p.sess._new_events(spoken=True)


async def _p_offer(p: PollState, run):
    if p.ds:
        await p.sess.offer(p.ds)
    await p.sess.release_held()


def build_poll() -> Graph:
    g = Graph("poll")
    g.node("observe", _p_observe)
    g.node("events", _p_events, view=lambda p: {"n": len(p.ds)})
    g.node("offer", _p_offer, commit=True)
    g.chain("observe", "events", "offer")
    return g.check()


POLL = build_poll()
