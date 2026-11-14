"""One router for every spoken (or typed) turn, in every screen of the app (docs/HANDSFREE.md).

    turn ──► route(text, ctx) ──► ignore | navigate | answer | order | question

The mic is always open, so most of what it hears is not for us: room chatter, two adults talking, hums ("mm-mm"),
filler ("oh", "um") and, worst of all, the app's own voice coming back through the speakers. Answering any of those
starts a loop (the app speaks, hears itself, answers itself). So the first job of the router is to stay silent.

Outcomes
  ignore     not for us: echo of our own voice (the last few lines, not only the current one), filler / non-lexical,
             too short, low device-directedness, or heard while the app is speaking and not barge-in-worthy.
             `notice` is set when it was clearly device-directed but unusable (the mic chip shows "didn't catch that").
  navigate   a voice intent that moves the app: start, next, back, patch map, lesson N / by title, go to mission,
             take command, pick <site>, end shift (outside the cabin), debrief, fly again, academy, library, views,
             settings, slower / faster, say that again, yes / no to an offer.
  answer     the current lesson step's answer (the step's grader decides right or wrong), or a call sign.
  order      a mission order in the cabin (the NLU + the learned Director; risky ones ask to confirm).
  question   the Moon knowledge brain. The "I don't know that one yet" fallback may only be spoken when
             `clear_question()` holds (see session.py, which also rate-limits it).

Context-aware: in a lesson step an utterance is first an answer; on the patch screen "next"; in the cabin an order. A
question works anywhere. Pure functions, no I/O: backend/tests/test_turn_router.py covers each screen x each outcome.
"""
from __future__ import annotations

import re
import time
from collections import deque
from dataclasses import dataclass, field

from .gazetteer import norm

# ---- thresholds ------------------------------------------------------------------------------------------------------
ECHO_SHARE = 0.6          # >= 60% of the heard words appear in one of our recent lines -> echo
ECHO_WINDOW_S = 12.0      # the lines we spoke in the last 12 s are echo references (the mic + ASR lag behind)
OLD_SHARE = 0.85          # lines that ended before the turn started: only a near-verbatim repeat of >= 3 words
TAIL_S = 0.6              # hard mute after any app voice ends
DD_MIN = 0.5              # Arc device_directed under this: talking to someone else
DD_STRONG = 0.7           # a barge-in while we speak needs a clearly device-directed turn
UNKNOWN_EVERY_S = 30.0    # the "I don't know" line at most once per 30 s

# Non-lexical sounds and fillers. A turn made only of these is never for us.
FILLER = {
    "oh", "ohh", "ooh", "oo", "o", "ah", "ahh", "aah", "a", "uh", "uhh", "um", "umm", "hm", "hmm", "hmmm", "mm", "mmm",
    "mhm", "mmhm", "mmhmm", "uhhuh", "uh-huh", "er", "erm", "eh", "huh", "ha", "haha", "hah", "heh", "hehe", "wow",
    "whoa", "oops", "ugh", "aw", "aww", "yay", "la", "na", "shh", "psst", "tsk", "pfft", "boo", "ow", "ouch", "hey",
    "hi", "hello", "so", "well", "like", "and", "but", "the", "i", "you", "it", "okay so", "oh no", "oh my",
}
NONLEX = re.compile(r"^(?:[aeiou]*h+[aeiou]*h*|u+[mh]+|h+m+|m+[mh]*|a+[hw]+|o+[ho]*|e+[rh]+m*|h+u+h+|h+a+(?:h+a+)*|"
                    r"[mn]+|s+h+|p+s+t+|z+)$")
YES = re.compile(r"^(?:yes|yeah|yep|yup|sure|ok|okay|alright|all right|let s do it|let s go|lets go|do it|go|go for it|"
                 r"yes please|ready|i m ready|affirmative|roger|copy)$")
NO = re.compile(r"^(?:no|nope|nah|not now|no thanks|no thank you|negative|later|maybe later|stop|cancel)$")
WH = re.compile(r"^(?:what|whats|what s|where|wheres|where s|when|why|who|whos|who s|whose|which|how|hows|how s)\b")
ASKY = re.compile(r"^(?:tell me|show me|can you (?:tell|show)|could you (?:tell|show)|explain|i want to know|"
                  r"teach me|let me (?:see|hear))\b")
# Yes/no question starts ("did you…", "is it…") are just as often one adult asking another: they count as a question
# for us only when Arc says the turn is clearly device-directed.
YESNO = re.compile(r"^(?:can you|could you|would you|do you|did|does|do|is|are|was|were|will|can|could|should|"
                   r"have you|has|i wonder)\b")

WORDNUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "first": 1,
           "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8, "1": 1, "2": 2,
           "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8, "won": 1, "to": 2, "too": 2, "for": 4, "ate": 8}

# Navigation intents: (intent, pattern over the normalised text). First match wins; the screen decides if it applies.
_N = r"(?:please )?"
NAV: list[tuple[str, re.Pattern]] = [
    # frontend/src/a11y.js parseCommand (the client runs them): where am I, options, text size, contrast, press X, option N
    ("a11y", re.compile(r"^(?:where am i|what screen is this|what s on (?:the )?screen|describe (?:the )?screen|"
                        r"what can i do|what can i say|help me|options|what are my options|normal speed|regular speed|"
                        r"(?:bigger|larger|smaller) (?:text|words)|high contrast(?: on| off)?|"
                        r"(?:describe things|audio description)(?: on| off)?|stop describing|"
                        r"(?:press|tap|click) (?:the )?.+|(?:option|answer|number) (?:\d|one|two|three|four))$")),
    ("repeat", re.compile(rf"^{_N}(?:say (?:that|it) again|repeat(?: that| it)?|read (?:that|it) again|come again|"
                          r"what did you say|pardon|i didn t hear(?: that| you)?|one more time please)$")),
    ("slower", re.compile(r"^(?:speak |talk )?(?:slower|slow down|more slowly)(?: please)?$")),
    ("faster", re.compile(r"^(?:speak |talk )?(?:faster|speed up|quicker)(?: please)?$")),
    ("settings", re.compile(r"^(?:access |open |show )?(?:the )?(?:accessibility|settings)(?: settings| panel)?$")),
    ("lesson", re.compile(r"^(?:start |open |go to |play |do |begin )?lesson (?:number )?(\w+)$")),
    ("map", re.compile(r"^(?:go )?(?:back )?(?:to )?(?:the )?(?:patch|course|lesson|academy) ?map$|^(?:show (?:me )?)?"
                       r"(?:my |the )?patch(?:es)?(?: map)?$|^(?:the )?map$")),
    ("academy", re.compile(r"^(?:go (?:back )?to |open |back to )?(?:the )?(?:academy|flight school|lessons)$")),
    ("library", re.compile(r"^(?:go to |open )?(?:the )?(?:moon )?(?:library|explorer)$|^explore the moon$")),
    ("go_mission", re.compile(r"^(?:go to |open |start |begin )?(?:the )?(?:mission|missions|outpost|outpost luna)"
                              r"(?: mode)?$|^(?:let s|lets) (?:go to|do) the mission$|^go on (?:a|the) mission$")),
    ("take_command", re.compile(r"^(?:i ll |i will |let me )?(?:take command|take the command|start the shift|"
                                r"start (?:my |the )?(?:first )?shift|launch|start the mission|begin the mission|"
                                r"i m ready to command)$")),
    ("debrief", re.compile(r"^(?:go to |show (?:me )?)?(?:the |my )?debrief$|^(?:end|finish|stop) (?:the )?mission$|"
                           r"^how did i do$")),
    ("fly_again", re.compile(r"^(?:fly|play|go) again$|^(?:fly|play) (?:it )?one more time$|^(?:restart|replay) "
                             r"(?:the )?mission$|^another (?:mission|shift|go)$|^new mission$")),
    ("new_site", re.compile(r"^(?:another|a different|new) (?:site|place|landing site)$")),
    ("view_orbit", re.compile(r"^(?:zoom out|orbit|whole moon|show (?:me )?the whole moon|go up)$")),
    ("view_rover", re.compile(r"^(?:rover view|show (?:me )?the rover|follow the rover|where is the rover|"
                              r"where s the rover)$")),
    ("view_site", re.compile(r"^(?:zoom in|outpost view|site view|back to the (?:outpost|base|site)|show (?:me )?the "
                             r"(?:outpost|base|site))$")),
    ("start", re.compile(r"^(?:start|begin|let s start|lets start|start (?:the )?lesson|start learning|let s begin|"
                         r"start (?:flight school|the academy)|continue|resume)$")),
    ("next", re.compile(r"^(?:next|next one|next please|next lesson|next step|go on|keep going|move on|"
                        r"what s next|whats next|okay next|ok next|carry on)$")),
    ("back", re.compile(r"^(?:go back|back|previous|go back please|take me back)$")),
    ("end_shift", re.compile(r"^(?:end|finish|next) (?:the |my |this )?shift$")),
]
PICK = re.compile(r"^(?:pick|choose|select|land (?:at|on)|go to|let s go to|build (?:it )?(?:at|on)|i choose|i pick)"
                  r" (?:the )?(.+)$")


@dataclass
class Ctx:
    """What the router knows about the app at this turn (session.belief + the client's screen frame)."""
    screen: str = "map"                # map|callsign|lesson|lesson_done|ride|patch|brief|cabin|debrief|library
    step_type: str | None = None       # the lesson step's accept.type (choice, keywords, command, tap, intent, vocab_*)
    step_options: list[str] = field(default_factory=list)   # choice labels (an answer that names one is an answer)
    offer: str | None = None           # a pending spoken offer ("next_lesson", "mission", "fly_again"): yes/next goes
    source: str = "typed"              # typed (keyboard, button) | voice (client mic) | listen (server relay)
    dd: float | None = None            # Arc device_directed for this turn (None: unknown)
    speaking: bool = False             # an app voice is playing now, or ended < TAIL_S ago
    playing: bool = False              # a line of ours was playing when this turn started (Spoken.playing_at)
    recent: list[str] = field(default_factory=list)   # lines playing when the turn started (or just ended): Spoken.fresh
    older: list[str] = field(default_factory=list)    # lines that ended before that, within ECHO_WINDOW_S
    lessons: list[tuple[str, str]] = field(default_factory=list)   # [(lesson_id, title)]
    sites: list[tuple[str, str]] = field(default_factory=list)     # [(site_id, name)]
    callsigns: list[str] = field(default_factory=list)


def words(text: str) -> list[str]:
    return [w for w in norm(text or "").split() if w]


def is_filler(text: str) -> bool:
    """Only non-lexical sounds and fillers ("Oh.", "Mm-mm.", "um, uh", "hmm okay so")."""
    ws = words(text)
    if not ws:
        return True
    return all(w in FILLER or NONLEX.match(w) for w in ws) or norm(text) in FILLER


def echo_of(text: str, recent: list[str], share: float = ECHO_SHARE) -> bool:
    """>= `share` of the heard words appear in ONE of our recent lines (or in all of them together for 1-2 words)."""
    ws = words(text)
    if not ws or not recent:
        return False
    refs = [set(words(r)) for r in recent if r]
    if any(sum(w in r for w in ws) / len(ws) >= share for r in refs if r):
        return True
    every = set().union(*refs) if refs else set()
    return len(ws) <= 3 and all(w in every for w in ws)


def echo(text: str, ctx: "Ctx") -> bool:
    """Our own voice coming back: the current / fresh lines at 60% overlap; older lines only near-verbatim. On a
    readback step (the kid repeats CAPCOM's order on purpose) only what is playing right now counts."""
    if not ctx.playing and nav_intent(text, ctx):
        return False          # "Say next when you're ready." -> "next": the kid answering the offer, not its echo
    if ctx.step_type in ("keywords", "vocab_say") and ctx.screen in ("lesson", "ride"):
        return ctx.speaking and echo_of(text, ctx.recent, 0.85)
    if echo_of(text, ctx.recent):
        return True
    if ctx.screen in ("lesson", "ride"):
        return False          # a step answer often repeats the prompt's words ("more power to the heaters")
    return len(words(text)) >= 3 and echo_of(text, ctx.older, OLD_SHARE)


def clear_question(text: str, dd: float | None = None, act: list[str] | None = None) -> bool:
    """A device-directed question worth an honest "I don't know that one yet": a wh-question, or "tell me / show me /
    can you / is ..." style, at least 3 words, and Arc (when it ran) agrees the kid is talking to us."""
    q = norm(text)
    ws = q.split()
    if len(ws) < 3:
        return False
    if dd is not None and float(dd) < DD_STRONG:
        return False
    if act and not any(a in ("question", "request", "command") for a in act) and not text.strip().endswith("?") and \
            not WH.match(q):
        return False
    if WH.match(q) or ASKY.match(q):
        return True
    return bool((YESNO.match(q) or text.strip().endswith("?")) and dd is not None and float(dd) >= DD_STRONG)


def lesson_number(tok: str, lessons: list[tuple[str, str]]) -> str | None:
    n = WORDNUM.get(tok)
    if n is None and tok.isdigit():
        n = int(tok)
    if n and 1 <= n <= len(lessons):
        return lessons[n - 1][0]
    return None


def _match_title(q: str, items: list[tuple[str, str]]) -> str | None:
    """An item named by its title ("space words", "power from the sun", "malapert")."""
    best = None
    for iid, title in items:
        t = norm(title)
        short = norm(re.sub(r"\(.*?\)", "", title))
        keys = {t, short, iid.replace("_", " ")} | ({short.split()[0]} if len(short.split()[0]) >= 6 else set())
        for k in keys:
            if k and re.search(rf"\b{re.escape(k)}\b", q):
                if best is None or len(k) > best[1]:
                    best = (iid, len(k))
    return best[0] if best else None


def nav_intent(text: str, ctx: Ctx) -> tuple[str, str | None] | None:
    """(intent, arg) for a navigation turn in this screen, else None."""
    q = norm(text)
    q = re.sub(r"^(?:okay|ok|um|uh|so|hey|capcom|please)\s+", "", q)
    q = re.sub(r"\s+(?:please|now|capcom)$", "", q)
    if not q:
        return None
    for intent, pat in NAV:
        m = pat.match(q)
        if not m:
            continue
        if intent == "lesson":
            lid = lesson_number(m.group(1), ctx.lessons)
            if lid:
                return "lesson", lid
            continue
        if intent == "end_shift" and ctx.screen == "cabin":
            return None              # in the cabin "end shift" is an order (the sim advances; the session handles it)
        if intent in ("view_orbit", "view_rover", "view_site") and ctx.screen not in ("cabin", "brief"):
            continue
        if intent == "back" and ctx.screen in ("cabin",):
            continue
        return intent, None
    if ctx.offer and (YES.match(q) or q in ("next", "next one")):
        return "accept_offer", ctx.offer
    if ctx.offer and NO.match(q):
        return "decline_offer", ctx.offer
    if ctx.screen in ("patch", "lesson_done", "map") and YES.match(q):
        return "next", None
    m = PICK.match(q)
    if m and ctx.sites and ctx.screen in ("brief", "debrief", "cabin", "map", "patch", "library"):
        sid = _match_title(m.group(1), ctx.sites)
        if sid:
            return "pick_site", sid
    if ctx.screen == "brief" and ctx.sites:
        sid = _match_title(q, ctx.sites)
        if sid and len(q.split()) <= 4:
            return "pick_site", sid
    if ctx.lessons and ctx.screen in ("map", "patch", "lesson_done", "library", "brief", "debrief"):
        m2 = re.match(r"^(?:start |open |go to |do |play |begin |let s do |i want )?(?:the )?(.+?)(?: lesson)?$", q)
        if m2 and len(q.split()) <= 5:
            lid = _match_title(m2.group(1), ctx.lessons)
            if lid:
                return "lesson", lid
    return None


def route(text: str, ctx: Ctx, act: list[str] | None = None) -> dict:
    """-> {"outcome": ignore|navigate|answer|order|question, "reason", "intent"?, "arg"?, "notice"?}."""
    raw = (text or "").strip()
    ws = words(raw)
    heard = ctx.source in ("voice", "listen", "ptt")
    explicit = ctx.source == "ptt"       # Space held: the kid meant us (filler still dropped; no echo / mute / dd gate)
    out = lambda o, why, **k: {"outcome": o, "reason": why, **k}  # noqa: E731

    # 1. Silence first: nothing, filler, our own voice.
    if not ws:
        return out("ignore", "empty")
    if heard and is_filler(raw):
        return out("ignore", "filler")
    if heard and not explicit and echo(raw, ctx):
        return out("ignore", "echo")
    dd = ctx.dd if heard and not explicit else None
    nav = nav_intent(raw, ctx)
    # 2. While the app is speaking (and for TAIL_S after), only barge-in-worthy turns get through: a navigation /
    #    control word, or >= 3 words that are clearly device-directed.
    if heard and not explicit and ctx.speaking and not nav:
        strong = len(ws) >= 3 and (dd is None or dd >= DD_STRONG)
        if not strong:
            return out("ignore", "speaking")
    # 3. Not for us: Arc says the kid is talking to someone else.
    if dd is not None and dd < DD_MIN and not (nav and len(ws) <= 4):
        return out("ignore", "not_directed")
    if nav:
        return out("navigate", "intent", intent=nav[0], arg=nav[1])
    # 4. One word that is not an intent, heard from the room: too thin to act on.
    single = len(ws) == 1 and heard
    s = ctx.screen
    if s == "callsign":
        hit = next((c for c in ctx.callsigns if c.lower() in ws or norm(c) in norm(raw)), None)
        if hit or re.search(r"\b(call me|my call sign|surprise|random|you pick|pick for me)\b", norm(raw)):
            return out("answer", "callsign")
        if clear_question(raw, dd, act):
            return out("question", "question")
        return out("ignore", "callsign_other", notice=bool(dd is not None and dd >= DD_STRONG))
    if s in ("lesson", "ride") and ctx.step_type:
        # A real question mid-lesson still works ("what is an mSv?"), but only on steps whose answer is not itself a
        # request: an intent step's answer IS "show me …", a command step's is an order, a readback repeats words.
        if ctx.step_type not in ("intent", "keywords", "vocab_say") and WH.match(norm(raw)) and \
                clear_question(raw, dd, act) and not _names_option(raw, ctx):
            return out("question", "question_in_lesson")
        if single and ctx.step_type in ("keywords", "command") and not _names_option(raw, ctx):
            return out("ignore", "too_short", notice=bool(dd is not None and dd >= DD_STRONG))
        if heard and len(ws) > 14 and not _names_option(raw, ctx) and (dd is None or dd < DD_STRONG):
            return out("ignore", "chatter")      # a long ramble with no answer in it, not clearly to us
        return out("answer", "step")
    if s == "cabin":
        if clear_question(raw, dd, act) and not re.search(r"\b(power|shields?|rover|shelter|heaters?|science|"
                                                          r"greenhouse|comms|life support|oxygen|battery|dose|"
                                                          r"radiation|houston|storm)\b", norm(raw)):
            return out("question", "question_in_cabin")
        return out("order", "cabin")
    if single:
        return out("ignore", "too_short", notice=bool(dd is not None and dd >= DD_STRONG))
    if s == "library":
        return out("question", "library")
    # map, patch, lesson_done, brief, debrief, callsign: a question still works anywhere; anything else is not for us.
    if clear_question(raw, dd, act) or (not heard and len(ws) >= 2):
        return out("question", "question")
    if heard and len(ws) >= 3 and (dd is not None and dd >= DD_STRONG):
        return out("question", "directed")       # the brain answers or stays quiet (never the fallback unless a question)
    return out("ignore", "unclear", notice=bool(dd is not None and dd >= DD_STRONG))


def _names_option(text: str, ctx: Ctx) -> bool:
    q = norm(text)
    if re.search(r"\b(?:a|b|c|d|option|answer|number)\b", q) and len(q.split()) <= 3:
        return True
    return any(norm(o) and norm(o) in q for o in ctx.step_options)


# ---- the spoken-line memory (server side: every say we emit, every playback the client reports) ---------------------
class Spoken:
    """The lines the app said, with when each one played, for the echo check and the hard mute. Times are compared with
    the kid's turn START (t0): our acoustic echo can only start while a line plays (or within LAG_S of its end, the
    mic + ear latency). A kid repeating words of a prompt that already ended is an answer, not an echo."""

    LAG_S = 0.3        # the ear reports a turn start ~0.3 s after the sound: echo starts WHILE we play

    def __init__(self, clock=time.monotonic, n: int = 10):
        self.clock = clock
        self.lines: deque = deque(maxlen=n)       # {"id", "text", "start", "end" (None while playing)}
        self.ended = -1e9

    def said(self, text: str):
        """A say decision we emitted (not yet reported as played): a reference for LAG_S from now."""
        if text:
            now = self.clock()
            self.lines.append({"id": None, "text": text, "start": now, "end": now})

    def start(self, pid: str, text: str):
        self.lines.append({"id": pid or "-", "text": text or "", "start": self.clock(), "end": None})

    def end(self, pid: str):
        now = self.clock()
        for ln in self.lines:
            if ln["end"] is None and (not pid or ln["id"] == pid):
                ln["end"] = now
        self.ended = now

    def playing_at(self, t0: float | None = None) -> bool:
        """A line of ours was playing when the turn started (the hallmark of an acoustic echo)."""
        t0 = self._t0(t0)
        return any(ln["start"] <= t0 and (ln["end"] is None or ln["end"] >= t0 - self.LAG_S) for ln in self.lines
                   if ln["id"])

    def _t0(self, t0):
        return self.clock() if t0 is None else t0

    def speaking(self, t0: float | None = None) -> bool:
        t0 = self._t0(t0)
        return any(ln["end"] is None for ln in self.lines if ln["id"]) or t0 - self.ended < TAIL_S

    def recent(self, window: float = ECHO_WINDOW_S) -> list[str]:
        now = self.clock()
        return [ln["text"] for ln in self.lines if ln["text"] and (ln["end"] is None or now - ln["end"] <= window)]

    def fresh(self, t0: float | None = None) -> list[str]:
        """Lines playing at t0, ended < LAG_S before it, or started since."""
        t0 = self._t0(t0)
        return [ln["text"] for ln in self.lines if ln["text"] and (ln["end"] is None or ln["end"] >= t0 - self.LAG_S)]

    def older(self, t0: float | None = None) -> list[str]:
        t0 = self._t0(t0)
        return [ln["text"] for ln in self.lines if ln["text"] and ln["end"] is not None and
                t0 - ECHO_WINDOW_S <= ln["end"] < t0 - self.LAG_S]
