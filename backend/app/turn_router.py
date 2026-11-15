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

from . import safety as safety_
from .gazetteer import norm

# ---- thresholds ------------------------------------------------------------------------------------------------------
ECHO_SHARE = 0.6          # >= 60% of the heard words appear in one of our recent lines -> echo
ECHO_WINDOW_S = 12.0      # the lines we spoke in the last 12 s are echo references (the mic + ASR lag behind)
SHOWN_WINDOW_S = 90.0     # round 8: our lines (spoken or on the HUD) this recent catch a near-verbatim repeat
SHOWN_SHARE = 0.9
SHOWN_COVER = 0.6
OLD_SHARE = 0.85          # lines that ended before the turn started: only a near-verbatim repeat of >= 3 words
TAIL_S = 0.6              # hard mute after any app voice ends
DD_MIN = 0.5              # Arc device_directed under this: talking to someone else
DD_STRONG = 0.7           # a barge-in while we speak needs a clearly device-directed turn
UNKNOWN_EVERY_S = 30.0    # the "I don't know" line at most once per 30 s
# The kid's Settings "listening filter" (docs/VOICES.md): (DD_MIN, DD_STRONG) per level. Normal is today's 0.5 / 0.7.
# Relaxed answers a turn Arc is less sure about (a shy or quiet kid); strict wants a clearly directed turn (a noisy room,
# siblings). Only the device-directed gates move: echo, filler, the hard mute and the too-short rules are the same at
# every level.
FILTERS: dict[str, tuple[float, float]] = {"relaxed": (0.35, 0.55), "normal": (DD_MIN, DD_STRONG),
                                           "strict": (0.65, 0.85)}


def thresholds(level: str | None) -> tuple[float, float]:
    return FILTERS.get(level or "normal", FILTERS["normal"])


# Non-lexical sounds and fillers. A turn made only of these is never for us.
FILLER = {
    "oh", "ohh", "ooh", "oo", "o", "ah", "ahh", "aah", "a", "uh", "uhh", "um", "umm", "hm", "hmm", "hmmm", "mm", "mmm",
    "mhm", "mmhm", "mmhmm", "uhhuh", "uh-huh", "er", "erm", "eh", "huh", "ha", "haha", "hah", "heh", "hehe", "wow",
    "whoa", "oops", "ugh", "aw", "aww", "yay", "la", "na", "shh", "psst", "tsk", "pfft", "boo", "ow", "ouch", "hey",
    "hi", "hello", "so", "well", "like", "and", "but", "the", "i", "you", "it", "okay so", "oh no", "oh my",
}
# Room exclamations and swearing (round 7): Arc Tagger rates "shit shit oh" device_directed 0.91, so device_directed
# alone never makes these a turn for us. A turn made only of these words (or one of the phrases) is filler.
EXCLAIM = {"shit", "damn", "dammit", "damnit", "crap", "heck", "frick", "fudge", "gosh", "omg", "god", "jeez", "geez",
           "ugh", "argh", "yikes", "whoops", "cool", "nice", "awesome", "yay", "woah", "wow", "bruh", "dude", "man",
           "aw", "oof", "phew", "eww", "ew", "hey", "ha", "lol", "nooo", "noo", "yesss", "ouch", "hell", "sucks",
           "stupid", "dumb", "seriously", "really", "what", "huh", "oh", "no", "yes", "yeah", "okay", "ok"}
EXCLAIM_PHRASE = re.compile(r"^(?:oh (?:my )?(?:god|gosh|no|man|wow|shit|crap|dear)|what the (?:heck|hell|heck is that)|"
                            r"come on|no way|you re kidding|are you kidding(?: me)?|that s (?:so )?(?:cool|awesome|"
                            r"weird|gross|funny)|so cool|stop it|give it back|leave me alone|that s mine|"
                            r"i m (?:so )?bored|this is (?:so )?(?:hard|boring|easy))(?: \w+)?$")
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

WORDNUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
           "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8,
           "ninth": 9, "1": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8, "9": 9, "won": 1, "to": 2,
           "too": 2, "for": 4, "ate": 8}

# Navigation intents: (intent, pattern over the normalised text). First match wins; the screen decides if it applies.
_N = r"(?:please )?"
NAV: list[tuple[str, re.Pattern]] = [
    # frontend/src/a11y.js parseCommand (the client runs them): where am I, options, text size, contrast, press X, option N
    ("a11y", re.compile(r"^(?:where am i|what screen is this|what s on (?:the )?screen|describe (?:the )?screen|"
                        r"what can i do|what can i say|help me|options|what are my options|normal speed|regular speed|"
                        # "what do I do?": the screen's current hint (window.__outpost.help, docs/PLAYTEST.md)
                        r"help|help please|hint|give me a hint|i need (?:a hint|help)|what do i do(?: now| here)?|"
                        r"what should i do|what am i supposed to do|i m stuck|i don t get it|i don t know what to do|"
                        r"i don t know|how do i do this|"
                        # docs/STORY.md: the same help, a few more ways to say it
                        r"what do i do next|what should i do (?:now|next)|i m lost|i am lost|what s my job|whats my job|"
                        r"what do i have to do|"
                        r"(?:bigger|larger|smaller) (?:text|words)|high contrast(?: on| off)?|"
                        r"(?:describe things|audio description)(?: on| off)?|stop describing|"
                        r"(?:press|tap|click) (?:the )?.+|(?:option|answer|number) (?:\d|one|two|three|four))$")),
    # The cabin's Center view (the seat pose): "center", "look forward"
    ("recenter", re.compile(r"^(?:center|centre|recenter|recentre|look forward|look ahead|face forward|"
                            r"(?:center|centre|reset) (?:the |my )?view)$")),
    # Settings → Reset (docs/RESET.md): voice only OPENS the confirm view (a11y.js parseCommand); a 3-second hold resets
    ("a11y", re.compile(r"^(?:reset|reset (?:the |my )?(?:whole )?(?:app|game|progress|outpost luna)|"
                        r"(?:reset|start over|erase) (?:everything|it all|all)|erase (?:my )?progress|"
                        r"start the (?:whole )?(?:app|game) over)$")),
    # The top bar's Mute (every screen; output only, the mic stays as it is)
    ("mute_sound", re.compile(r"^(?:mute|mute (?:the )?(?:sound|audio|app|voices?)|sound off|turn (?:the )?sound off|be quiet)$")),
    ("unmute_sound", re.compile(r"^(?:unmute|unmute (?:the )?(?:sound|audio|app|voices?)|sound on|turn (?:the )?sound (?:back )?on)$")),
    # The live mission clock (docs/GAMEPLAY.md), cabin only: skip to the next event, pause / run time, time warp.
    # Before "start" (which takes "resume") and "skip_tour" (which takes a bare "skip").
    ("skip_event", re.compile(r"^(?:skip|jump|fast forward|go|warp)(?: ahead| forward)?(?: to)?(?: the)? next "
                              r"(?:event|thing|job|task)$|^(?:skip|jump) (?:ahead|forward)$|^fast forward$|"
                              r"^next event$|^skip (?:the )?(?:wait|waiting)$")),
    ("time_pause", re.compile(r"^(?:pause|stop|freeze|hold)(?: the)? (?:clock|time|game|mission)$|^pause(?: it)?$|"
                              r"^time out$|^wait a (?:sec|second|minute)$")),
    ("time_resume", re.compile(r"^(?:start|resume|run|unpause|restart)(?: the)? (?:clock|time|game|mission clock)$|"
                               r"^(?:resume|unpause|play|let time run|go go go)$|^start the clock$")),
    ("time_warp", re.compile(r"^(?:time ?warp|warp(?: speed)?|speed up (?:the )?(?:time|clock)|(?:double|quad) "
                             r"(?:time|speed)|(?:normal|slow) (?:time|speed)|time (?:normal|slow)|"
                             r"(?:time ?warp|warp|time|clock)(?: speed)? (?:one|two|four|1|2|4)(?: x| times)?|"
                             r"(?:one|two|four|1|2|4)(?: x| times) (?:time|speed|warp))$")),
    # The cabin tour (mission/tour.js): replay it, or skip it.
    ("cabin_tour", re.compile(r"^(?:show me around|give me (?:a|the) tour|(?:start |replay |do )?(?:the )?(?:cabin )?tour|"
                              r"show me the cabin|what s in (?:the|this) cabin|teach me the cabin)$")),
    ("skip_tour", re.compile(r"^(?:skip|skip (?:the |this )?tour|skip it|end (?:the )?tour|stop (?:the )?tour|"
                             r"no more tour|i know (?:it|this)|(?:i ve|i have) got it)$")),
    ("repeat", re.compile(rf"^{_N}(?:say (?:that|it) again|repeat(?: that| it)?|read (?:that|it) again|come again|"
                          r"what did you say|pardon|i didn t hear(?: that| you)?|one more time please)$")),
    ("slower", re.compile(r"^(?:speak |talk )?(?:slower|slow down|more slowly)(?: please)?$")),
    ("faster", re.compile(r"^(?:speak |talk )?(?:faster|speed up|quicker)(?: please)?$")),
    ("settings", re.compile(r"^(?:access |open |show )?(?:the )?(?:accessibility|settings)(?: settings| panel)?$")),
    ("lesson", re.compile(r"^(?:start |open |go to |play |do |begin )?lesson (?:number )?(\w+)$")),
    ("map", re.compile(r"^(?:go )?(?:back )?(?:to )?(?:the )?(?:(?:patch|course|lesson|academy) ?)?map$|^(?:show (?:me )?)?"
                       r"(?:my |the )?patch(?:es)?(?: map)?$|^(?:go |take me |let s go )?(?:back )?(?:to )?(?:the )?map$|"
                       r"^(?:show (?:me )?|open )(?:the )?map$")),   # [audit2] "back to the map", "go to the map"; [r7] bare "map"
    ("academy", re.compile(r"^(?:go (?:back )?to |take me (?:back )?to |open |back to )?(?:the )?(?:academy|flight school|lessons)$")),
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
# 3D cabin panels (frontend mission/ui.js nav: panel_power | panel_comm | panel_habitat | panel_back; rover and radiation
# are routed too). Panel navigation must never reach the mission NLU: "open the comm panel" once turned the radio OFF.
PANELS = {"power": "power", "energy": "power", "battery": "power", "comm": "comm", "comms": "comm",
          "communications": "comm", "communication": "comm", "radio": "comm", "habitat": "habitat", "hab": "habitat",
          "rover": "rover", "radiation": "radiation", "rad": "radiation", "shield": "radiation", "shields": "radiation"}
_PANEL_NAME = "|".join(sorted(PANELS, key=len, reverse=True))
PANEL_OPEN = re.compile(rf"^(?:open|show|show me|go to|take me to|look at|switch to|bring up|pull up|let s see|"
                        rf"let me see|check)(?: up)? (?:the |my )?({_PANEL_NAME})(?: (panels?|station|console|screen|"
                        rf"desk|board))?$|^(?:the )?({_PANEL_NAME}) (?:panels?|station|console)(?: please)?$")
PANEL_BACK = re.compile(r"^(?:go )?back(?: to (?:my|the) (?:seat|chair|cockpit|window))?$|^(?:close|leave|exit|shut) "
                        r"(?:the |this )?(?:panel|station|console)$|^(?:my )?seat$|^(?:sit|go) (?:back )?(?:down|to (?:my|the) "
                        r"seat)$|^back to (?:my|the) (?:seat|chair)$")
# The voice bar (frontend voicebar.js parseBarCommand): "move the voice bar to the top right", "reset the voice bar".
VBAR_MOVE = re.compile(r"^(?:move|put|drag|send|place) (?:the |my )?(?:voice|mic|microphone|talk) ?bar (?:to |on |at )?"
                       r"(?:the )?(top|bottom|up|down|left|right|middle|centre|center)(?: (left|right|middle|centre|center))?"
                       r"(?: (?:side|corner|edge))?$")
VBAR_RESET = re.compile(r"^(?:reset|restore) (?:the |my )?(?:voice|mic|microphone|talk) ?bar(?: position)?$")


CLOCK_INTENTS = ("skip_event", "time_pause", "time_resume", "time_warp")
_WARP_WORDS = {"one": 1, "1": 1, "normal": 1, "slow": 1, "two": 2, "2": 2, "double": 2, "four": 4, "4": 4, "quad": 4}


def warp_of(q: str) -> int | None:
    """The speed in a time-warp turn ("time warp four" -> 4, "normal speed" -> 1); None: the next speed up."""
    for w in q.split():
        if w in _WARP_WORDS:
            return _WARP_WORDS[w]
    return None


def task_choice(q: str, options: list[str]) -> str | None:
    """A spoken pick on the cabin's task card ("left", "the ridge", "shelter now"): the one option it names, or None."""
    if not options or len(q.split()) > 5:
        return None
    stop = {"the", "a", "an", "go", "now", "please", "take", "pick", "choose", "route", "i", "want", "lets", "let", "s",
            "steer", "to", "and", "or", "up", "it"}
    qw = set(q.split()) - stop
    if not qw:
        return None
    hits = [o for o in options if qw & (set(norm(o).split()) - stop)]
    return hits[0] if len(hits) == 1 else None


def voicebar_intent(q: str) -> str | None:
    """The canonical command voicebar.js parses ("move the voice bar to the top right" / "reset the voice bar")."""
    if VBAR_RESET.match(q):
        return "reset the voice bar"
    m = VBAR_MOVE.match(q)
    if not m:
        return None
    w = [x for x in m.groups() if x]
    return "move the voice bar to the " + " ".join("centre" if x in ("middle", "center") else x for x in w)


def panel_intent(q: str) -> tuple[str, str] | None:
    m = PANEL_OPEN.match(q)
    if m:
        name = m.group(1) or m.group(3)
        has_panel_word = bool(m.group(2)) or bool(m.group(3))
        if not has_panel_word:
            # Without "panel": only a clear move verb, and never rover / radiation ("show me the rover" is the rover
            # view, "check the power" / "show the shields" are status questions).
            if PANELS[name] in ("rover", "radiation") or \
                    not q.startswith(("open", "go to", "take me to", "switch to", "bring up", "pull up")):
                return None
        return "panel_" + PANELS[name], PANELS[name]
    if PANEL_BACK.match(q):
        return "panel_back", "seat"
    return None


PICK = re.compile(r"^(?:pick|choose|select|land (?:at|on)|go to|let s go to|build (?:it )?(?:at|on)|i choose|i pick)"
                  r" (?:the )?(.+)$")


@dataclass
class Ctx:
    """What the router knows about the app at this turn (session.belief + the client's screen frame)."""
    screen: str = "map"                # map|callsign|lesson|lesson_done|ride|patch|brief|cabin|debrief|library|video|prep
    step_type: str | None = None       # the lesson step's accept.type (choice, keywords, command, tap, intent, vocab_*)
    step_options: list[str] = field(default_factory=list)   # choice labels (an answer that names one is an answer)
    step: dict | None = None           # the open course step (content.lesson(lesson_id).steps[i]): what a try sounds like
    step_age: float | None = None      # seconds since that step opened (the session stamps the screen frame); None unknown
    offer: str | None = None           # a pending spoken offer ("next_lesson", "mission", "fly_again"): yes/next goes
    source: str = "typed"              # typed (keyboard, button) | voice (client mic) | listen (server relay)
    dd: float | None = None            # Arc device_directed for this turn (None: unknown)
    speaking: bool = False             # an app voice is playing now, or ended < TAIL_S ago
    playing: bool = False              # a line of ours was playing when this turn started (Spoken.playing_at)
    on_air: bool | None = None         # a line still playing at the turn start, no ear-lag tail (Spoken.on_air);
                                       # None: timing unknown, the lines in `recent` count as on air
    recent: list[str] = field(default_factory=list)   # lines playing when the turn started (or just ended): Spoken.fresh
    older: list[str] = field(default_factory=list)    # lines that ended before that, within ECHO_WINDOW_S
    shown: list[str] = field(default_factory=list)    # round 8: lines said or shown (HUD) within SHOWN_WINDOW_S
    lessons: list[tuple[str, str]] = field(default_factory=list)   # [(lesson_id, title)]
    sites: list[tuple[str, str]] = field(default_factory=list)     # [(site_id, name)]
    callsigns: list[str] = field(default_factory=list)
    unsafe: bool = False               # [P0] Arc Tagger's safety tags flagged the turn (profanity, toxicity, child.*): safety.py
    dd_min: float = DD_MIN             # the Settings filter (FILTERS): below this, talking to someone else
    dd_strong: float = DD_STRONG       # barge-in while we speak / a yes-no question / a notice needs this much


def words(text: str) -> list[str]:
    return [w for w in norm(text or "").split() if w]


def is_filler(text: str) -> bool:
    """Only non-lexical sounds and fillers ("Oh.", "Mm-mm.", "um, uh", "hmm okay so"), or room exclamations
    ("shit shit oh", "oh my god", "what the heck", "come on"): never a turn for us, however device-directed."""
    ws = words(text)
    if not ws:
        return True
    return all(w in FILLER or NONLEX.match(w) for w in ws) or norm(text) in FILLER or is_exclaim(text)


def is_exclaim(text: str) -> bool:
    ws = words(text)
    if not ws:
        return False
    q = norm(text)
    if all(w in EXCLAIM or w in FILLER or NONLEX.match(w) for w in ws) and any(w in EXCLAIM - {"no", "yes", "yeah",
                                                                                                  "okay", "ok", "what"}
                                                                                for w in ws):
        return True
    return bool(EXCLAIM_PHRASE.match(q))


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


_NUM_WORDS = {"plus", "minus", "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
              "percent", "point"}


def _shown_words(text: str) -> list[str]:
    """Words for the shown-line echo, without numbers ("Science +2." is read back as "science plus two")."""
    return [w for w in words(text) if not w.isdigit() and w not in _NUM_WORDS]


def shown_echo(text: str, lines: list[str]) -> bool:
    """Near-verbatim repeat of ONE line we said or showed: >= SHOWN_SHARE of the heard words are in it AND the turn
    covers >= SHOWN_COVER of the line. A kid taking our advice ("skip this one" after "You can skip this one, or use
    something else") reuses a few of its words; an echo carries most of the line."""
    ws = _shown_words(text)
    for ln in lines or []:
        if not ws or ln.rstrip().endswith("?"):
            continue     # our questions / offers: the kid repeats those as the answer
        ref = _shown_words(ln)
        if ref and sum(w in set(ref) for w in ws) / len(ws) >= SHOWN_SHARE and \
                sum(w in set(ws) for w in ref) / len(ref) >= SHOWN_COVER:
            return True
    return False


def echo(text: str, ctx: "Ctx") -> bool:
    """Our own voice coming back: the current / fresh lines at 60% overlap; older lines only near-verbatim. On a
    readback step (the kid repeats CAPCOM's order on purpose) only what is playing right now counts.

    The ear-lag tail (a line that ended < LAG_S before the turn start, Spoken.fresh) is an echo reference for room
    talk, but never for the reply the screen is waiting for: the kid taking an offer ("Ready for the next lesson?" ->
    "next") or answering a lesson step (which often repeats the prompt's words) a moment after our line ended. Only a
    line still on air at the turn start makes those an echo."""
    air = ctx.on_air if ctx.on_air is not None else bool(ctx.recent)   # timing unknown: `recent` is on air
    nav = nav_intent(text, ctx)
    if nav and not air and answers_offer(nav, ctx):
        return False          # the kid taking the offer, even inside the tail of the offer line (or of its echo)
    if nav and not ctx.playing:
        return False          # any other navigation word once our line is over (beyond the ear lag)
    if ctx.step_type in ("keywords", "vocab_say") and ctx.screen in ("lesson", "ride"):
        return ctx.speaking and echo_of(text, ctx.recent, 0.85)
    if ctx.screen in ("lesson", "ride"):
        # a step answer often repeats the prompt's words ("I heard you", "where day meets night"): only a line still
        # playing makes it an echo; older lines are never used here
        return air and echo_of(text, ctx.recent)
    if echo_of(text, ctx.recent):
        return True
    if len(words(text)) >= 3 and echo_of(text, ctx.older, OLD_SHARE):
        return True
    # round 8: a line we said or showed (the HUD, a task ack) up to SHOWN_WINDOW_S ago, heard back near-verbatim
    # ("Sample logged. Science +2." read out and then picked up again by the mic)
    return len(words(text)) >= 3 and shown_echo(text, ctx.shown)


# The navigation intents that take each spoken offer (Ctx.offer). "next" / "start" / "yes" take any of them.
OFFER_TAKERS = {"next_lesson": set(), "next_step": set(), "mission": {"go_mission", "take_command"},
                "take_command": {"take_command"}, "fly_again": {"fly_again"}, "tour": {"skip_tour"}}


def answers_offer(nav: tuple[str, str | None] | None, ctx: "Ctx") -> bool:
    """The turn is the kid's yes to the pending offer (not a decline, not some other navigation)."""
    if not nav or not ctx.offer:
        return False
    intent = nav[0]
    return intent in ("accept_offer", "next", "start") or intent in OFFER_TAKERS.get(ctx.offer, set())


def clear_question(text: str, dd: float | None = None, act: list[str] | None = None,
                   strong: float = DD_STRONG) -> bool:
    """A device-directed question worth an honest "I don't know that one yet": a wh-question, or "tell me / show me /
    can you / is ..." style, at least 3 words, and Arc (when it ran) agrees the kid is talking to us."""
    q = norm(text)
    ws = q.split()
    if len(ws) < 3:
        return False
    if dd is not None and float(dd) < strong:
        return False
    if act and not any(a in ("question", "request", "command") for a in act) and not text.strip().endswith("?") and \
            not WH.match(q):
        return False
    if WH.match(q) or ASKY.match(q):
        return True
    return bool((YESNO.match(q) or text.strip().endswith("?")) and dd is not None and float(dd) >= strong)


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


OFFER_FILLERS = {"um", "uh", "like", "so", "well", "hmm", "oh", "er"}


def offer_reply(text: str) -> str | None:
    """Round 8 rules: a short yes / no to a pending offer, read as said ("not now" loses its "now" to nav_intent's
    strip) and without the ear's fillers ("okay so", "not like now"): accept_offer / decline_offer, else None."""
    ws = norm(text or "").split()
    r = " ".join(w for w in ws if w not in OFFER_FILLERS) if len(ws) <= 4 else ""
    if r and NO.match(r):
        return "decline_offer"
    if r and YES.match(r):
        return "accept_offer"
    return None


OFFER_LEAD_MAX = 7
_ACCEPT_LEAD = {"yes", "yeah", "yep", "yup", "sure", "okay", "ok", "alright", "ready"}
_DECLINE_LEAD = ("not now", "no thanks", "no thank", "maybe later")
_NEG = {"no", "not", "nope", "nah", "later", "don", "dont", "stop", "wait", "never"}
_WH_ANY = {"what", "whats", "where", "wheres", "when", "why", "who", "which", "how"}


def offer_lead(text: str) -> str | None:
    """Round 8 rules: a short turn that opens with the reply to the pending offer and trails ear noise ("ready all day
    ready olly", "alright okay oh it s good", "not now but a late one minute"): accept_offer / decline_offer. An
    accept needs no negation and no question word anywhere in the turn; a decline needs a two-word decline up front
    (a bare "no ..." inside chatter is not one)."""
    raw = norm(text or "").split()
    if not raw or len(raw) > OFFER_LEAD_MAX:
        return None
    ws = [w for w in raw if w not in OFFER_FILLERS]
    if " ".join(ws[:2]) in _DECLINE_LEAD:
        return "decline_offer"
    if ws and ws[0] in _ACCEPT_LEAD and not (set(ws) & (_NEG | _WH_ANY)):
        return "accept_offer"
    return None


def nav_intent(text: str, ctx: Ctx) -> tuple[str, str | None] | None:
    """(intent, arg) for a navigation turn in this screen, else None."""
    q = norm(text)
    q = re.sub(r"^(?:okay|ok|um|uh|so|hey|capcom|please)\s+", "", q)
    q = re.sub(r"\s+(?:please|now|capcom)$", "", q)
    if not q:
        return None
    vb = voicebar_intent(q)
    if vb:
        return "a11y", vb                      # on every screen; the client runs `arg` (voicebar.handleText)
    if ctx.screen == "cabin":
        pn = panel_intent(q)
        if pn:
            return pn
        if ctx.offer == "task":   # a choice on the task card (route, steer, shelter or wait, normal or high)
            tc = task_choice(q, ctx.step_options)
            if tc:
                return "task_choice", tc
    for intent, pat in NAV:
        m = pat.match(q)
        if not m:
            continue
        if intent == "lesson":
            lid = lesson_number(m.group(1), ctx.lessons)
            if lid:
                return "lesson", lid
            continue
        if intent == "go_mission" and ctx.screen == "brief" and dict(NAV)["take_command"].match(q):
            return "take_command", None     # on the picker "start the mission" flies the selected site
        if intent == "end_shift" and ctx.screen == "cabin":
            return None              # in the cabin "end shift" is an order (the sim advances; the session handles it)
        if intent in ("view_orbit", "view_rover", "view_site") and ctx.screen not in ("cabin", "brief"):
            continue
        if intent == "back" and ctx.screen in ("cabin",):
            continue
        if intent == "recenter" and ctx.screen != "cabin":
            continue
        if intent in ("cabin_tour", "skip_tour") and ctx.screen != "cabin":
            continue
        if intent in CLOCK_INTENTS:
            if ctx.screen != "cabin" or ctx.offer == "tour":
                continue
            return intent, (warp_of(q) if intent == "time_warp" else None)
        if intent == "skip_tour" and q in ("skip", "skip it", "i know it", "i know this", "i ve got it", "i have got it") and \
                ctx.offer != "tour":
            continue                 # a bare "skip" is a tour word only while the tour runs
        return intent, None
    if ctx.offer and (YES.match(q) or q in ("next", "next one")):
        return "accept_offer", ctx.offer
    if ctx.offer and NO.match(q):
        return "decline_offer", ctx.offer
    reply = offer_reply(text) if ctx.offer else None
    if reply:
        return reply, ctx.offer
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


# ---- round 7: navigation heard with extra words or a sound-alike ------------------------------------------------------
# The real ear adds words around a short command ("next liz liz", "tuesday next week", "give me a tour lance", "back to
# the map the other one", "i go back to my seat") and mishears panel names ("the comp panel"). nav_fuzzy() finds a
# navigation phrase INSIDE the turn: a contiguous span that nav_intent() reads, with at most max(2, span length) other
# words around it (at most one before it). One-word spans count only for taking the pending offer ("next", "yes"). It runs after the echo check
# and keeps every gate (device-directed, the hard mute), and a lesson step's own answer always wins over it.
PANEL_WORD = re.compile(r"\b(panels?|station|console)\b")


def _panel_soundalike(q: str) -> str:
    """"show me the comp panel" -> "show me the comm panel": the word before "panel" read as the closest panel name
    (a clear winner only)."""
    from . import soundalike
    ws = q.split()
    for i, w in enumerate(ws):
        if i and PANEL_WORD.fullmatch(w) and ws[i - 1] not in PANELS and soundalike.content(ws[i - 1]):
            sc = sorted(((soundalike.similar(ws[i - 1], p), p) for p in PANELS if len(p) >= 3), reverse=True)
            if sc and sc[0][0] >= 0.5 and sc[0][0] - sc[1][0] >= 0.08:
                return " ".join(ws[:i - 1] + [sc[0][1]] + ws[i:])
    return q


def nav_fuzzy(text: str, ctx: Ctx) -> tuple[str, str | None, int] | None:
    """(intent, arg, span words) for a navigation phrase inside a longer / misheard turn; None if nav_intent already
    reads the whole turn (that is the exact path) or nothing is close enough."""
    q = norm(text)
    if not q or nav_intent(q, ctx):
        return None
    if ctx.screen == "cabin" and PANEL_WORD.search(q):
        q2 = _panel_soundalike(q)
        if q2 != q:
            nv = nav_intent(q2, ctx)
            if nv:
                return nv[0], nv[1], len(q2.split())
            q = q2
    ws = q.split()
    best = None
    for n in range(len(ws) - 1, 0, -1):
        extra = len(ws) - n
        if extra > max(2, n):
            continue
        for i in range(0, min(1, len(ws) - n) + 1):       # at most one word before the phrase, the rest after it
            nv = nav_intent(" ".join(ws[i:i + n]), ctx)
            if not nv:
                continue
            if nv[0] == "a11y" and extra > 2:
                continue     # "i don't know that one yet" (our own fallback line) is not a call for help
            if n == 1 and not answers_offer(nv, ctx):
                continue     # one word inside chatter is navigation only when it takes the offer on screen
            if nv[0] in ("back", "decline_offer", "lesson", "pick_site"):
                continue     # never from a fragment: "it s back" is a globe answer, "no i don t" is not a decline
            best = (nv[0], nv[1], n)
            break
        if best:
            break
    if best is None and ctx.offer:
        lead = offer_lead(q)
        if lead:
            best = (lead, ctx.offer, 1)
    return best


# A video is playing (docs/MEDIA.md; frontend/src/media/video.js mirrors this): only its own four controls get through.
VIDEO_CMDS = (
    ("video_pause", re.compile(r"^(?:pause|pause it|pause (?:the|this) video|wait|hold on|hang on|freeze)$")),
    ("video_play", re.compile(r"^(?:play|play it|resume|unpause|keep going|go on|continue|keep playing|start it)$")),
    ("video_skip", re.compile(r"^(?:skip|skip it|skip (?:the|this) video|skip this|next)$")),
    ("video_stop", re.compile(r"^(?:stop|stop it|stop (?:the|this) video|close|close it|close (?:the|this) video|"
                              r"that s enough|enough|i m done|done)$")),
)


VIDEO_MAX_WORDS = 8          # longer is narration leaking from the video, never a command
VIDEO_LEAD = 3               # the control word must be among the first words ("...and then we pause" is narration)
_V_CLOSE = {"close", "exit", "done", "enough", "quit", "finished"}
_V_WORDS = (("video_stop", {"stop"}), ("video_pause", {"pause", "wait", "freeze", "hold", "hang"}),
            ("video_skip", {"skip"}), ("video_play", {"play", "resume", "unpause", "continue", "watch"}))


def video_command(text: str, fuzzy: bool = True) -> str | None:
    """The video overlay's control in this turn. Exact phrases first; then (round 8 rules) the control word inside a
    short turn, since the ear adds tails ("play the video with lena hargrove", "next pause at 12 p m"): close / exit /
    done win (stop), a "stop ... for a sec" is a pause, pause beats skip, skip beats play. Narration-like turns (more
    than VIDEO_MAX_WORDS words, or no control word among the first VIDEO_LEAD) are never commands."""
    q = re.sub(r"^(?:okay |ok |please |capcom |hey |um |uh |oh )+|(?: please| now| capcom)+$", "", norm(text or "")).strip()
    hit = next((name for name, rx in VIDEO_CMDS if rx.match(q)), None)
    if hit or not fuzzy:
        return hit
    ws = q.split()
    if not ws or len(ws) > VIDEO_MAX_WORDS:
        return None
    lead = set(ws[:VIDEO_LEAD])
    if lead & _V_CLOSE or (lead & {"stop"} and {"close", "exit"} & set(ws)):
        return "video_stop"
    if "stop" in lead and set(ws) & {"sec", "second", "minute", "moment"}:
        return "video_pause"
    best = None
    for name, keys in _V_WORDS:
        pos = min((i for i, w in enumerate(ws[:VIDEO_LEAD]) if w in keys), default=None)
        if pos is not None and best is None:
            best = name
    return best


# Mission prep (learning v1, docs/LEARNING_DESIGN.md §11.4): a hands-on task away from the screen. The kid says done,
# skip, wait or asks for help; our own prep lines never say "done", so a heard "done" is the kid's.
PREP_CMDS = (
    ("prep_done", re.compile(r"^(?:done|done done|i m done|we re done|i did it|we did it|did it|finished|i m finished|"
                             r"we re finished|all done|ok done|okay done|it s ready|it s done|ready|yes|yeah|yep|"
                             r"yes we did it|thumbs up)$")),
    ("prep_skip", re.compile(r"^(?:skip|skip it|skip this|skip this one|can we skip it|no|no thanks|not now|"
                             r"next one|next one please|we don t have (?:any |the )?\w+|maybe later|later)$")),
    ("prep_wait", re.compile(r"^(?:wait|hold on|hang on|one sec|one second|just a sec|give me a minute|give us a minute|"
                             r"not yet|we re still doing it|still going|almost)$")),
    ("prep_help", re.compile(r"^(?:help|help me|i need help|what do i do|what do we do|how do (?:i|we) do this|"
                             r"say it again|say that again|again|repeat|what was it|what s next)$")),
)


# Round 8 rules: a missing thing for the hands-on task ("we don't have flour", "I can't find the flashlight",
# "where's the flour") is a call for help, answered with a gentle "you can skip this one" (session.PREP_MISSING_LINE),
# never a skip the kid did not ask for and never a mission order.
PREP_MISSING = re.compile(r"^(?:(?:we|i) don t have (?:any |the |a |an )?\w+(?: \w+)?|(?:we|i) (?:can t|cannot|couldn t) find "
                          r"(?:any |the |a |an |my |our )?\w+(?: \w+)?|(?:there s|there is) no \w+(?: \w+)?|"
                          r"we re out of \w+|no \w+ here)$")
PREP_WAIT_MORE = re.compile(r"^(?:not yet|not done yet|wait a (?:sec|second|minute)|give (?:me|us) (?:a|one) (?:sec|second|minute|"
                            r"moment)|one (?:more )?(?:sec|second|minute|moment)|just a (?:sec|second|minute|moment)|"
                            r"hold on a (?:sec|second|minute)|almost done|still doing it)$")


PREP_MAX_WORDS = 10           # longer is room talk, never a prep control
PREP_LEAD = 3                 # the control phrase starts among the first words ("give uh give me a minute")


def prep_fuzzy(text: str) -> str | None:
    """A prep control inside a short turn: the ear repeats ("i'm done i'm done i'm done") and adds tails ("give me a
    minute to leave"). The longest span of >= 2 words that starts among the first PREP_LEAD words and is a control
    on its own wins."""
    ws = norm(text or "").split()
    if not ws or len(ws) > PREP_MAX_WORDS:
        return None
    for i in range(min(PREP_LEAD, len(ws))):
        for j in range(len(ws), i + 1, -1):
            span = " ".join(ws[i:j])
            cmd = prep_command(span) or ("prep_wait" if PREP_WAIT_MORE.match(span) else None)
            if cmd:
                return cmd
    return None


def prep_missing(text: str) -> bool:
    q = re.sub(r"^(?:okay |ok |um |uh |so |oh |but |mom |hey )+|(?: please| now)+$", "", norm(text or "")).strip()
    return bool(PREP_MISSING.match(q))


def prep_command(text: str) -> str | None:
    q = re.sub(r"^(?:okay |ok |um |uh |so |please |capcom |hey )+|(?: please| now| capcom)+$", "", norm(text or "")).strip()
    return next((name for name, rx in PREP_CMDS if rx.match(q)), None)


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
    # [P0] a rude or unsafe turn is never an answer, a question or an order (Arc's safety tags, then the word list):
    # silent, no notice, and the client never shows it
    if ctx.unsafe or safety_.has_profanity(raw):
        return out("ignore", "safety")
    if heard and is_filler(raw) and not _option_key(raw, ctx) and not (ctx.offer and offer_reply(raw)) and \
            not (ctx.screen in ("video", "prep") and (video_command(raw, fuzzy=False) or prep_command(raw))):
        return out("ignore", "filler")     # ("stop it", "wait" are filler elsewhere, but controls on these screens)
    if ctx.screen == "video":            # the video overlay is up: pause / play / skip / stop, nothing else
        cmd = video_command(raw, fuzzy=False)
        if cmd is None and not (heard and not explicit and ctx.dd is not None and ctx.dd < ctx.dd_min):
            cmd = video_command(raw)     # the word inside a short turn, only when Arc does not say "not for us"
        return out("navigate", "video", intent=cmd, arg=None) if cmd else out("ignore", "video")
    if heard and not explicit and echo(raw, ctx):
        return out("ignore", "echo")
    dd = ctx.dd if heard and not explicit else None
    if ctx.screen == "prep":             # Mission prep: done / skip / wait / help; a real question still works
        if prep_missing(raw):
            return out("navigate", "prep", intent="prep_help", arg="missing")
        cmd = prep_command(raw) or ("prep_wait" if PREP_WAIT_MORE.match(norm(raw)) else None)
        if cmd is None and not (dd is not None and dd < ctx.dd_min):
            cmd = prep_fuzzy(raw)        # the control inside a short turn, only when Arc does not say "not for us"
        if cmd:
            return out("navigate", "prep", intent=cmd, arg=None)
        if clear_question(raw, dd, act, ctx.dd_strong):
            return out("question", "question")
        return out("ignore", "prep", notice=bool(not heard or (dd is not None and dd >= ctx.dd_strong)))
    nav = nav_intent(raw, ctx)
    fz = nav_fuzzy(raw, ctx) if heard and not nav else None
    air = ctx.on_air if ctx.on_air is not None else bool(ctx.recent)
    fz_offer = fz is not None and answers_offer(fz[:2], ctx) and not air
    # 2. While the app is speaking (and for TAIL_S after), only barge-in-worthy turns get through: a navigation /
    #    control word, or >= 3 words that are clearly device-directed.
    if heard and not explicit and ctx.speaking and not nav and not fz_offer:
        strong = len(ws) >= 3 and (dd is None or dd >= ctx.dd_strong)
        if not strong:
            return out("ignore", "speaking")
    # 3. Not for us: Arc says the kid is talking to someone else. Except the open step's own answer, said as it is
    #    written ("Right now" for the option "Right now"): Arc rates short exact answers as not directed, and the live
    #    run showed a kid stuck on that step forever (round 7, handsfree_run --audio).
    if dd is not None and dd < ctx.dd_min and not (nav and len(ws) <= 4) and not exact_option(raw, ctx):
        return out("ignore", "not_directed")
    if nav:
        return out("navigate", "intent", intent=nav[0], arg=nav[1])
    if fz is not None:
        if ctx.speaking and not explicit and not fz_offer:
            fz = None        # a fragment is never barge-in-worthy, except taking the offer once its line is over
        elif ctx.screen in ("lesson", "ride") and ctx.step_type and _plausible(raw, ctx, dd, strict=True):
            fz = None        # the step's own answer wins ("is it the far side": an answer, not navigation)
    if fz is not None:
        return out("navigate", "intent_fuzzy", intent=fz[0], arg=fz[1])
    # 4. One word that is not an intent, heard from the room: too thin to act on.
    single = len(ws) == 1 and heard
    s = ctx.screen
    if s == "callsign":
        hit = next((c for c in ctx.callsigns if c.lower() in ws or norm(c) in norm(raw)), None)
        if hit or re.search(r"\b(call me|my call sign|surprise|random|you pick|pick for me)\b", norm(raw)):
            return out("answer", "callsign")
        if clear_question(raw, dd, act, ctx.dd_strong):
            return out("question", "question")
        if not heard:   # [audit2] typed on the call-sign screen: the kid typed a name; the screen says what to do with it
            return out("answer", "callsign_typed")
        return out("ignore", "callsign_other", notice=bool(dd is not None and dd >= ctx.dd_strong))
    if s in ("lesson", "ride") and ctx.step_type:
        # A real question mid-lesson still works ("what is an mSv?"), but only on steps whose answer is not itself a
        # request: an intent step's answer IS "show me …", a command step's is an order, a readback repeats words.
        if ctx.step_type not in ("intent", "keywords", "vocab_say") and WH.match(norm(raw)) and \
                clear_question(raw, dd, act, ctx.dd_strong) and not _names_option(raw, ctx):
            return out("question", "question_in_lesson")
        if single and ctx.step_type in ("keywords", "command") and not _names_option(raw, ctx):
            return out("ignore", "too_short", notice=bool(dd is not None and dd >= ctx.dd_strong))
        if heard and len(ws) > 14 and not _names_option(raw, ctx) and (dd is None or dd < ctx.dd_strong):
            return out("ignore", "chatter")      # a long ramble with no answer in it, not clearly to us
        if not _plausible(raw, ctx, dd):
            # "Oh, it's", "okay", "alright": not a try. Silent, and never a miss (the grader agrees: grade.plausible).
            return out("ignore", "not_an_answer", notice=bool(not heard or (dd is not None and dd >= ctx.dd_strong)))
        if heard and not explicit and not yesno_counts(raw, ctx, dd):
            return out("ignore", "room_yes_no")   # a room "yes" / "no" while the question is still being asked
        return out("answer", "step")
    if s == "cabin":
        if clear_question(raw, dd, act, ctx.dd_strong) and not re.search(r"\b(power|shields?|rover|shelter|heaters?|science|"
                                                          r"greenhouse|comms|life support|oxygen|battery|dose|"
                                                          r"radiation|houston|storm)\b", norm(raw)):
            return out("question", "question_in_cabin")
        return out("order", "cabin")
    if single:
        return out("ignore", "too_short", notice=bool(dd is not None and dd >= ctx.dd_strong))
    if s == "library":
        return out("question", "library")
    # map, patch, lesson_done, brief, debrief, callsign: a question still works anywhere; anything else is not for us.
    if clear_question(raw, dd, act, ctx.dd_strong) or (not heard and len(ws) >= 2):
        return out("question", "question")
    if heard and len(ws) >= 3 and (dd is not None and dd >= ctx.dd_strong):
        return out("question", "directed")       # the brain answers or stays quiet (never the fallback unless a question)
    # [audit2] a typed turn was meant for us: never silent (the bar shows "Didn't catch that")
    return out("ignore", "unclear", notice=bool(not heard or (dd is not None and dd >= ctx.dd_strong)))


YESNO_STEPS = ("predict", "earth_view")
YESNO_MIN_AGE_S = 1.5   # a bare yes / no on a yes-no step counts only once the step has been open this long ...
BARE_YESNO = re.compile(r"^(?:(?:yes|yeah|yep|yup|no|nope|nah|sure|always|never|sometimes)(?: (?:please|i think|it does|"
                        r"it did|they did|you can|i can|it can t|they didn t|never))?)$")


def yesno_counts(text: str, ctx: Ctx, dd: float | None) -> bool:
    """On a predict / earth_view step a bare "yes" / "no" names an option, so room talk answered the step. It counts
    when Arc says it was for us (dd >= the strong threshold), or when it came after the question finished playing
    (not speaking / on air) and the step had been open >= YESNO_MIN_AGE_S. Anything longer is graded as usual."""
    if ctx.step_type not in YESNO_STEPS or not BARE_YESNO.match(norm(text)):
        return True
    if dd is not None and dd >= ctx.dd_strong:
        return True
    quiet = not ctx.speaking and not (ctx.on_air if ctx.on_air is not None else ctx.playing)
    return quiet and (ctx.step_age is None or ctx.step_age >= YESNO_MIN_AGE_S)


def _option_key(text: str, ctx: Ctx) -> bool:
    """On a step with lettered / numbered options, a bare "A" is option A, not filler."""
    if ctx.screen not in ("lesson", "ride") or not ctx.step_type:
        return False
    from .academy.grade import option_index, step_options
    n = len(step_options(ctx.step["accept"])) if ctx.step else len(ctx.step_options)
    return n > 0 and option_index(text, n) is not None


def _plausible(text: str, ctx: Ctx, dd: float | None, strict: bool = False) -> bool:
    """A real try at the open step (academy/grade.plausible: an option, the expected content, or >= 3 content words
    that Arc says were for us). Everything else on a step screen is ignored and never counts as a miss. strict: only
    the step's own words count (not the >= 3 content words fallback)."""
    from .academy.grade import plausible
    return plausible(ctx.step, text, dd, ctx.dd_min, step_type=ctx.step_type, options=ctx.step_options, strict=strict)


_LEAD = re.compile(r"^(?:(?:um|uh|oh|okay|ok|so|i think|it s|its|it is|my answer is|i say|i pick)\s+)+")


def exact_option(text: str, ctx: Ctx) -> bool:
    """On a lesson / ride step with options, the whole turn (after "um", "i think", "it's") IS one option's label or say
    phrase of >= 2 words or >= 4 letters ("Right now", "Never", "Malapert Massif"): the step's answer, said as written.
    Bare yes / no stay with yesno_counts (they are room talk as often as answers)."""
    if ctx.screen not in ("lesson", "ride") or not ctx.step_type:
        return False
    q = _LEAD.sub("", norm(text)).strip()
    if not q or BARE_YESNO.match(q):
        return False
    phrases = list(ctx.step_options)
    if ctx.step:
        from .academy.grade import step_options
        phrases += [w for _, say in step_options(ctx.step["accept"]) for w in say if w]
    if any(norm(p) == q and (len(q.split()) >= 2 or len(q) >= 4) for p in phrases if p):
        return True
    # a keywords / command step has no options: a short turn (2-4 words) the step's grader passes on is its answer
    # said as written (round 8 live run: "say again" on the radio step was rated not directed every time)
    if ctx.step and ctx.step_type in ("keywords", "command") and 2 <= len(q.split()) <= 4:
        try:
            from .academy.grade import _grade
            return bool(_grade(ctx.step, {"text": q})[0])
        except Exception:  # noqa: BLE001
            return False
    return False


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

    HOLD_S = 4.0       # a line ended with another one queued (`more`): on air until the next starts, at most this long

    def __init__(self, clock=time.monotonic, n: int = 10):
        self.clock = clock
        self.lines: deque = deque(maxlen=n)       # {"id", "text", "start", "end" (None while playing)}
        self.ended = -1e9
        self.gaps: list[tuple[float, float]] = []   # (from, until): the gaps inside a queued multi-line sequence

    def said(self, text: str):
        """A say decision we emitted (not yet reported as played): a reference for LAG_S from now."""
        if text:
            now = self.clock()
            self.lines.append({"id": None, "text": text, "start": now, "end": now})

    def start(self, pid: str, text: str):
        now = self.clock()
        self.gaps = [(a, min(b, now)) for a, b in self.gaps[-8:]]     # the next line is on air: the gap closes here
        self.lines.append({"id": pid or "-", "text": text or "", "start": now, "end": None})

    def end(self, pid: str, more: bool = False):
        """A line ended. `more`: the client has the next line of the same sequence queued (CAPCOM's brief → beat →
        prompt): the whole sequence is one on-air span, so the gap until the next line starts is on air too."""
        now = self.clock()
        for ln in self.lines:
            if ln["end"] is None and (not pid or ln["id"] == pid):
                ln["end"] = now
        self.ended = now
        if more:
            self.gaps.append((now, now + self.HOLD_S))

    def held(self, t0: float | None = None) -> bool:
        """t0 falls inside a queued sequence's gap (one line ended, the next one is coming)."""
        t0 = self._t0(t0)
        return any(a <= t0 <= b for a, b in self.gaps)

    def playing_at(self, t0: float | None = None) -> bool:
        """A line of ours was playing when the turn started (the hallmark of an acoustic echo)."""
        t0 = self._t0(t0)
        return self.held(t0) or any(ln["start"] <= t0 and (ln["end"] is None or ln["end"] >= t0 - self.LAG_S)
                                    for ln in self.lines if ln["id"])

    def on_air(self, t0: float | None = None) -> bool:
        """A line of ours was on air at or after t0 (still playing, or started during the turn): no ear-lag tail. An
        offer's or a step's answer that starts right after the line ended is the kid, not the echo (Ctx.on_air). A gap
        inside a queued sequence is on air."""
        t0 = self._t0(t0)
        return self.held(t0) or any(ln["end"] is None or ln["end"] > t0 for ln in self.lines if ln["id"])

    def _t0(self, t0):
        return self.clock() if t0 is None else t0

    def speaking(self, t0: float | None = None) -> bool:
        """The hard mute: a line playing, a queued sequence between its lines, or < TAIL_S after the last line."""
        t0 = self._t0(t0)
        now = self.clock()
        return any(ln["end"] is None for ln in self.lines if ln["id"]) or self.held(t0) or self.held(now) or \
            t0 - self.ended < TAIL_S

    def recent(self, window: float = ECHO_WINDOW_S) -> list[str]:
        now = self.clock()
        return [ln["text"] for ln in self.lines if ln["text"] and (ln["end"] is None or now - ln["end"] <= window)]

    def fresh(self, t0: float | None = None) -> list[str]:
        """Lines playing at t0, ended < LAG_S before it, or started since."""
        t0 = self._t0(t0)
        return [ln["text"] for ln in self.lines if ln["text"] and (ln["end"] is None or ln["end"] >= t0 - self.LAG_S)]

    def show(self, text: str):
        """A line put on screen (the HUD, a task ack, a card) without being played: an echo reference too."""
        if text:
            now = self.clock()
            self.shown_lines = (getattr(self, "shown_lines", []) + [(now, text)])[-20:]

    def shown(self, t0: float | None = None, window: float = SHOWN_WINDOW_S) -> list[str]:
        """Every line said or shown within `window` before t0 (near-verbatim echo references). Not our questions and
        offers ("Ready for the next lesson?"): a kid repeats those as the answer, long after the 12 s echo window."""
        t0 = self._t0(t0)
        said = [ln["text"] for ln in self.lines if ln["text"] and (ln["end"] is None or t0 - ln["end"] <= window)]
        lines = said + [t for ts, t in getattr(self, "shown_lines", []) if t0 - ts <= window]
        return [t for t in lines if not t.rstrip().endswith("?")]

    def older(self, t0: float | None = None) -> list[str]:
        t0 = self._t0(t0)
        return [ln["text"] for ln in self.lines if ln["text"] and ln["end"] is not None and
                t0 - ECHO_WINDOW_S <= ln["end"] < t0 - self.LAG_S]
