# Adult sessions: real, labelled turns for the Director

The learned Director has only ever trained on generated turns; `test_log` (real turns, held out) is empty
(`docs/DIRECTOR_LOOP.md` §6). Early users are adults (owner decision, 2026-11-22), so the first real set comes from
adult testers: a guided 25–30 minute session in the real app, about **150–250 turns** each. **Ten sessions ≈ 2,000
turns**, enough for a real `test_log` and a first real training slice.

The pieces:

| | where |
|---|---|
| The opt-in in the app | Settings → For grown-ups → **Help improve Outpost Luna** (`frontend/src/collect_ui.js`, `backend/app/adult_collect.py`) |
| What a turn holds | `backend/app/turnlog.py` (`collect`, `reply`, the `misheard` / `barge` / `nav_back` signals; `docs/DIRECTOR_LOOP.md` §1) |
| The session protocol and the consent text | this file, §2–§3 |
| Import, gate | `make director-import LOG=<zip>`, `make director-eval-real LOG=<zip>` |
| The labelling tool | `make director-label LOG=<zip>` → `director_model/label_ui/` (§5) |

## 1. The opt-in (what the tester sees)

Settings → For grown-ups (the 3-second hold, then the teacher PIN when one is set) → **Help improve Outpost Luna**.

- **Off by default.** "Turn on" opens a consent screen. "Turn on" there stays disabled until the tester ticks
  "I'm an adult, and I agree." The backend refuses without `consent` and `adult` and the page's own header.
- **One profile.** It is tied to the cadet profile it was turned on from. A kid's profile on the same computer is never
  collected and never gets audio from it. Use a profile of your own for the session (Settings → Cadets → Add).
- **Audio is a separate switch**, off by default: "Also keep audio clips". Ask for it (§2): the ear's errors are only
  learnable with the audio.
- **While it is on** a small **Improving** tag shows in the top bar. The panel counts the turns and clips kept.
- **Export to share…** writes one zip where the tester chooses (a save dialog in the desktop app). It holds only the
  collected turns, redacted again on the way out, their outcome signals and clips, and a manifest. Nothing is sent.
- **Hold to delete everything** removes the collected turns and clips (the rest of the turn log stays).
- Reset (either level) also deletes it and turns it off.

What is kept per turn: the words heard (lowercased, call signs, names, addresses and phone-like numbers replaced), the
screen and step, the ear's numbers (confidence, end of turn, barge-in, playback), the tagger's device-directed / act,
what the router, the rules and the model decided, the order's slots, what the app said and where it navigated
(`reply`), and the signals afterwards. Never: names, the call sign, the session id, the device, clock times. A turn the
privacy guard catches keeps no words and no audio.

## 2. Consent text for adult testers

Read it out or hand it over before the session. The tester keeps a copy. Record only the date and "agreed" (no name)
in the session sheet. The in-app consent screen is the second, recorded step.

> **Outpost Luna: help us improve how the app listens**
>
> Outpost Luna is a voice app for learning about the Moon and other places. We are asking adults to use it for about
> 30 minutes and let it keep what it heard, so we can teach it to understand people better.
>
> **What is kept, on this computer only:** the words the app heard you say, written as text; the screen you were on;
> what the app decided, said and did; and short signals such as "you repeated yourself" or "you went back". If you
> also turn on audio clips, the sound of each thing you said to it. No names, no call signs, no clock times.
>
> **What is not done:** nothing is sent over the internet. The app does not upload anything, ever.
>
> **Please don't** say real names, addresses, phone numbers or anything private during the session. If you do, the
> app replaces most of it, but not all of it is guaranteed.
>
> **Your choice, at every step.** You can stop at any time, skip any task, turn audio off, or delete everything from
> Settings → For grown-ups → Help improve Outpost Luna → Hold to delete everything. At the end, you choose whether to
> export a file and give it to us. Until you do, nobody else has it.
>
> **If you give us the file,** it is used only to train and test Outpost Luna's speech understanding. A few people on
> the Outpost Luna team read the text and may listen to the clips to label them. It is kept on the team's computers,
> never published, and deleted on request (tell the person who ran your session).
>
> **You must be 18 or over.** By ticking "I'm an adult, and I agree" in the app you confirm this.

## 3. The session (25–30 minutes)

**Who:** one adult tester, one facilitator (sits beside them, reads the cards, plays the "someone else in the room",
never touches the keyboard). The tester talks to the app by voice the whole time (open mic, Settings → Listening →
default), with typing only where a card says so.

**Before (3 min, not counted):**

1. The app is on the latest release, the room is normal-quiet (a home or an office, not a studio).
2. Settings → Cadets → **Add** a profile for the tester (any call sign; it is redacted anyway).
3. The facilitator reads the consent text (§2). The tester turns it on: Settings → For grown-ups (hold 3 s) →
   Help improve Outpost Luna → Turn on → tick → Turn on, then **Also keep audio clips** if they agree.
4. Sound on, at a normal level: the app's own voice in the room is part of what we need (echo, barge-in). The
   facilitator's laptop or phone stays muted.

**Rules for the tester (read once):** speak naturally, as you would to a person. Don't fix your wording to please the
app. If it gets something wrong, react as you really would ("no, I said…", "go back", repeat yourself, or ignore it).
That reaction is the label.

Each block lists the target turns, then cards. A card is one thing to do; the facilitator reads it, the tester says
it in their own words (the examples are only examples; vary them). Tick the block's coverage when done.

### A. Warm-up and the map (2 min, ~15 turns)

- Say your call sign when asked (it is redacted).
- "What can I do here?" · "Help." · "What do I do?"
- "Open Flight School." / "Start the first lesson." · "Go back to the map." · "Open the library." · "Back."
- Accept and decline an offer: when it offers the next lesson, once say "yes" / "sure", once "not now".

### B. Flight School lessons (7 min, ~55 turns)

Do lessons 1–3 (Know your Moon, Lessons from Apollo, Talk on the radio), every step by voice:

- **Right answers in different words:** "the dark patch", "it's the Sea of Tranquility", "tranquility".
- **Wrong answers on purpose** (one per lesson), then the right one.
- **Hedges and thinking aloud:** "um… I think it's the far side?" · "is it… no wait, the near side".
- **Yes/no steps:** answer "yeah", "nope", "I guess so", and once say "yes" to the facilitator, not to the app (the
  facilitator asks "do you want water?").
- **Help on a step:** "I'm stuck", "give me a hint", "say that again", "slower please".
- **Radio steps:** the readback ("copy, heaters to forty percent"), and "say again" when static hits.
- Leave a step mid-way: "go to mission" then "back to the lesson".

### C. Questions about places (3 min, ~25 turns)

In the Library and on the map:

- "Tell me about Tycho." · "How big is Copernicus?" · "Where did Apollo 15 land?" · "What's Shackleton crater?"
- Follow-ups with "it" / "there": "How deep is it?" · "Who went there?"
- One place the app doesn't know ("tell me about Olympus Mons") and one mispronounced ("Coper-nickus", "Tie-ko").
- One question that is not about a place ("why is the Moon grey?").

### D. The check ride (2 min, ~12 turns)

Fly it start to finish by voice: "call Houston", "shelter now", "bring the crew out", "send the rover for ice". Once,
answer a step too early (while CAPCOM is still talking).

### E. Mission orders (7 min, ~55 turns)

Start a mission, pick a site, take command. Orders, each at least twice in different words:

- **Numbers:** "shields to thirty percent" · "give heaters 40" · "put science at a hundred" · "move twenty from comms to
  greenhouse" · "a little more to life support" · "max shields".
- **Negation:** "don't send the rover" · "not the heaters, the shields" · "turn off power save" · "stop the rover".
- **Conditionals and rules:** "if a storm comes, go to the shelter" · "when power drops below 20, turn on power save".
- **Questions mid-mission:** "how much power do we have?" · "what's the weather?" · "how long till the storm?"
- **Readback** when Houston gives an order: "copy, shields up to thirty".
- **Undo and cancel:** give an order, then "cancel that" / "undo" / put it back by hand.
- **Confirms:** when it asks "are you sure?", once "yes", once "no".
- End the shift by voice ("end shift"), and say "fly again" on the debrief.

### F. Navigation by voice (2 min, ~20 turns)

From each screen: "open settings" · "close" · "open the power panel" · "show the comm panel" · "back" · "go to the map" ·
"open the library" · "go to the archaeology course" · "skip the tour" · "pause the video" · "mute the sound" ·
"unmute". Once, on purpose, say a navigation the app gets wrong and react ("no, the *library*").

### G. Barge-in (1.5 min, ~10 turns)

While the app is talking (a long place answer, CAPCOM's briefing): "stop" · "okay okay, got it" · "next" · "wait,
what about Tycho?" · cut it off with a new question. Once, talk over it with something not for the app ("sorry, one
sec").

### H. Someone else in the room (2 min, ~15 turns)

The facilitator talks to the tester while the app is listening: small talk, a question about lunch, reading something
aloud, a phone ringing and the tester answering ("hello? yeah, I'm in a session"). Include room talk that sounds like
an order: "turn it up" (about music), "go back to the start" (about a story), "yes, that one" (pointing at a cup). The
app should stay quiet. Laugh, sigh, swear mildly once if it is natural.

### I. Mis-speaks and corrections (2 min, ~15 turns)

- Start and restart: "send the rover to… no, get ice" · "shields to thirty, I mean forty".
- Say a wrong word, then fix it: "tell me about Tychy… Tycho".
- After any mishearing: "that's not what I said" · "I said Tycho" · "no, the other one".
- Repeat yourself once without changing anything, as if it didn't hear.

### J. Archaeology course (4 min, ~30 turns)

Settings → For grown-ups → Get or remove courses (if needed) → switch to Archaeology. Do lessons 1–2 by voice:
"Mesa Verde" (find it), "photo it and leave it" (decide), "stratigraphy" / "survey" (keywords), a describe step
("it's flat on top with steep cliffs"), and two questions to the Field Director about places in the course. Switch
back to the Moon by voice ("go back to the Moon course").

### K. Wrap-up (1 min, not counted)

Settings → For grown-ups → Help improve Outpost Luna: check the counter (aim: 150+), **Turn off**, then **Export to
share…** (§4).

### Coverage: every decision class

| decision class | blocks |
|---|---|
| ignore (room talk, echo of our voice, chatter on a lesson step, talking to someone else) | B, G, H |
| answer (lesson steps: choice, predict, find, keywords, describe, decide, readback) | B, D, J |
| command (numbers, negation, conditionals, undo, cancel, power save) | D, E, I |
| navigate (each panel, map, library, academy, settings, back, offers, video, mute, course switch) | A, B, F, J |
| question about a place (known, unknown, mispronounced, follow-up "it") | C, J |
| ask_clarify (mishearings, "did you mean …?", near names) | C, I |
| nudge (wrong lesson answers) | B |
| confirm_yes / confirm_no | E |
| barge-in | G |
| corrections and repeats (the weak labels: misheard, negate, repeat, nav_back, undo) | E, F, I |
| a second course (Archaeology) | J |

## 4. Export and hand-over

1. Settings → For grown-ups → Help improve Outpost Luna → **Export to share…** → save the zip
   (`outpost-luna-help-<date>.zip`) somewhere you can find it.
2. Give it to the facilitator by hand: a USB stick, or a shared folder **the tester** chooses. Never by email to a
   list, never to a public link.
3. After the hand-over, the tester may **Hold to delete everything** in the app (recommended on a shared computer).
4. The facilitator writes on the session sheet: date, session number, "consent: yes", "audio: yes/no", the zip's file
   name and turn count. No name of the tester in the sheet or the file name.

Deleting a session on request: delete the zip, the session's lines from `director_model/data/real_turns.json` and
`data/review/*.jsonl`, and `data/real_audio/<zip stem>/` (all git-ignored, never committed). Each turn's `s` tag
identifies its session.

## 5. Import and labelling (the team)

```
make director-import LOG=~/handover/outpost-luna-help-2026-11-22.zip      # weak labels + clips -> data/
make director-label  LOG=~/handover/outpost-luna-help-2026-11-22.zip      # http://127.0.0.1:8377 (BY=kr)
make director-eval-real LOG=~/handover/outpost-luna-help-2026-11-22.zip   # the shipped config vs the rules
```

The label tool (`director_model/label_ui/serve.py` + `index.html`) is a local page: it binds 127.0.0.1, loads nothing
from the network, and its POSTs need its own header. For each turn it shows the heard words (and plays the clip), the
screen, the ear's numbers, the tagger's device-directed / act, what the router, rules and model decided, the order's
slots, what the app said and where it went, the signals, and the import's weak label. The form starts from the
existing label, else from what the engine did, so a correct turn is one key: **Enter**.

| key | does |
|---|---|
| `j` / `k` | next / previous turn · `u` next not labelled |
| `1`–`8` | act: ignore, answer, command, navigate, ask clarify, nudge, confirm yes, confirm no |
| `n` | navigate + jump to the navigation select (`features.NAV_INTENTS`) and its argument |
| `o` | command + jump to the order slots: `allocate to=heaters amount=percent:40`, `shelter_on`, `dispatch task=collect_ice`, `power_save on=true` |
| `p` | the place the turn is about (a `places.json` id) |
| `r` / `q` | next reply-line candidate (what it said, "Say again? I missed that.", "I don't know that one yet.", stay quiet, or type one) / should have stayed quiet |
| `t` | held out (the test split) |
| `a` / Space | play the clip |
| `x` | skip the turn (out of the set) |
| `Enter` | save and next |

Each save appends a row to `data/review/reviewed.jsonl` (the last row per turn wins) and rebuilds
`data/real_turns.json` with `import_logs.run`, the file `gen_sessions` and `eval_real` read. A labelled item's gold is
`{"act", "nav", "nav_arg", "cmd", "place", "reply"}` (only what applies), at confidence 1.0, `why: "reviewed"`.
`eval_real` counts a navigation to the wrong place as a wrong action when the gold names which one.

**Labelling guide.** Label what the app *should* have done for the words *actually said*, given the screen:

- talk not meant for the app, our own voice heard back, thinking aloud → `ignore`;
- a lesson step's answer, right or wrong → `answer` (a wrong one the app should coach → `nudge`);
- an order the sim can run → `command`, with its slots;
- a request to go somewhere or control the app → `navigate`, with which one;
- the words are unclear or the ear clearly misheard them, and acting would be a guess → `ask_clarify`;
- a turn you can't judge (cut off, two people at once) → `x` skip.

**Held out.** Hold out whole sessions, not single turns: the same speaker in train and test flatters the model. Mark
every turn of sessions 3 and 8 (and every fifth session after) with `t`. Without a mark, the import's hash split
applies (about 15 % test).

## 6. Open questions for the owner

- **Consent wording** (§2 and the in-app screen): reviewed by a lawyer before testers outside the team? The text says
  "a few people on the team may listen to the clips"; confirm who.
- **Who runs the sessions**, and where the zips are kept (one team folder, access list, deletion on request).
- **Persistence:** the opt-in stays on for the profile until turned off (the Playtest switches itself off after 3 h).
  Should it also expire, for example after 4 hours or at quit?
- **Audio default:** off, a separate switch, as asked. Sessions get far more value with audio; the facilitator asks.
- **Pay or thank-you** for testers, and whether testers may be team members' family (adults only).
