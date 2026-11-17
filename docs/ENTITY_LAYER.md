# The entity layer

One registry of the named things an app knows. Speech, storytelling and the Director all use it:
- the ear's names lists are derived from it, moment by moment;
- what the ear links (and what the kid says) comes back as entity ids;
- a session memory of those ids feeds the router, the director, the learned Director's features, story callbacks
  and the UI.

Code: `backend/app/entities/` (app-agnostic). Data: `backend/data/entities/outpost_luna.json`. Measurements:
`docs/SPEECH_SIGNALS_AUDIT.md`.

```
 registry file (JSON, schema whissle.entities/1)
   │  ids · names · aliases · spoken forms · mishears · related · lessons · states · screen profiles · refs
   ▼
 Registry ───────────────► ear_list(Moment) ──► /ws/listen {"t":"context","names"} ──► Arc ear (biasing, kb prompt,
   │   resolve / mentions /        ▲                (every 0.25 s on change;              linking; applied from the
   │   mishear_of / by_ref         │                 mid-turn included)                   next decode)
   │                               │ Moment: screen · step targets · what we just said ·
   │                               │         what the kid named (decayed) · place on screen · mission states
   │                               │
   │                        EntityMemory (session, in memory only)
   │                               ▲  note_turn: ear links (id, p, state) + the words' mentions, per routed turn
   │                               │  note_line: names in our own lines (guide / capcom / crew)
   ▼                               │
 director._link ── acts on the ear's linked id (p >= LINK_ACT_P), else offers it back ("Did you mean Tycho?");
                   a known mishearing ("siakowski") or a sound-alike → the same offer
 mission layer ─── a dispatch takes the linked SITE id (target_id), not the raw words after "to"
 session ───────── "yes" to the offer = the name; story callback "You asked about Tycho earlier."
 Director model ── round-12 features: ear_* (link) + ent_* (memory), appended
 UI ────────────── linked names marked in the kid's words (solid when sure, dotted + "?" when the app will ask)
 turn log (opt-in) entity ids + how heard + p, never words
```

## 1. The registry

One record per thing. The domain payloads (coordinates, facts, physics, lesson steps) stay in their own files, and
`ref` points at them, so nothing is stored twice.

| Field | Meaning | Used by |
|---|---|---|
| `id` | Stable id; for places, artifacts and sites, the same id their data files use | everything |
| `type` | `place` `site` `hardware` `mission` `crew` `spacecraft` `control` `unit` `lesson` (open set) | director (`place_of`), memory, features |
| `group` | The bucket a screen profile picks from; file order = rank inside the group | `screen_entities` |
| `name` | Canonical name: what the ear's list and the UI show | ear list, UI, story lines |
| `kind` | The ear's kind (arc.h: lunar_feature, site, spacecraft, mission, crew, ...) | ear list |
| `aliases` | Other names, said as written ("Mare Imbrium") | ear list (biasing **and linking**), `resolve`, `mentions` |
| `spoken` | Spoken forms ("Sea of Rain") | same as aliases |
| `mishears` | What the ear hears for it ("siakowski", "the jelly"). Never sent to the ear | `mishear_of` → "Did you mean …?", feature `ent_mishear` |
| `related` | Ids (hardware ↔ mission ↔ crew, site ↔ crater) | ear-list boost (one hop) |
| `lessons` | Lesson ids that use it | relevance, content tooling |
| `states` | Mission states that make it relevant (`storm`, `dark`, `low_power`, `dose_high`) | ear-list boost, feature `ent_state_rel` |
| `exclude_screens` | Screens where it must not be offered (the cabin's twin "de Gerlache" feature: the site owns the name) | ear list |
| `ear` | `false`: never an ear entry (controls, units, lessons): the ear rewrites a linked span in the list's spelling | ear list |
| `ref` | `{source, id}` of the domain record | `place_of`, `by_ref` |

Screen profiles live in the same file:

```json
"screens": {"library": {"cap": 80, "groups": [["hardware"], ["place"], ["crew_now", 6], ...]},
            "brief": {"same_as": "cabin"}}
```

Outpost Luna's file (136 entities) was migrated from the tables that used to be hard-coded in `names_list.py`:
places, sites, crew, missions, craft, hardware and old crew. The migration also added:
- the mission loads (`load_*`, from `mission/nlu.py` LOADS) as `control` entities;
- the units;
- the 9 Flight School lessons (`lesson_<id>`) with the places they use;
- mishearings seeded from round 11's `ear_analysis.md`.

The derived lists are identical to the pre-migration ones on every screen; that equivalence was checked when
`names_list.py` became an adapter.

**What is not migrated, and why:**
- The gazetteer's `aliases` in `places.json` stay. They are search keywords ("ice", "rings", "first landing"), not
  names. Treating them as names would make the ear link "ice" to Shackleton.
- The mission NLU's regexes stay. They parse amounts and verbs.
- Lesson and story content still holds place ids (`accept.place`) and free text. Those ids are already registry
  ids. New content should name things by id; `Registry.mentions()` finds them in free text.

## 2. Per-moment ear lists (`entities/context.py`)

The ear takes one ordered list. Order is its only weight: the first ~10-15 entries reach its decoder prompt, and
every entry biases the words and can be linked. `ear_list(registry, Moment)` scores the entities that matter right
now, then fills the rest from the screen profile.

| Boost | Weight |
|---|---|
| The open step's targets (`names_list.step_targets`) | 1000 |
| Names in our last two lines | 600 |
| What the kid named, halving every 120 s | 500 |
| The place on screen | 400 |
| Mission-state relevance | 300 |
| One hop of `related` | 150 |

Then:
- aliases are de-duplicated (an alias must name one entry);
- the list is capped (40 focused, 80 Moon).

`session.ear_names()` builds the Moment. `/ws/listen` polls it every 0.25 s and sends a new list when it changes.
libarc applies names "at the time each utterance closes", so a change mid-turn reaches that turn's final decode.

## 3. Link results as events (`entities/memory.py`)

`EntityMemory` is per session and in memory only. It records mention events:

```
{"id": "tycho", "by": "kid" | "guide" | "capcom" | "crew", "how": "ear_link" | "words",
 "p": 1.0, "state": "linked", "screen": "map", "t": ...}
```

Where events come from:
- every routed kid turn: the ear's linked / abstained names and the registry's matches of the heard words;
  router-ignored turns are not mentions;
- every line we play: `on_playback start`.

Who reads it:

| Reader | What |
|---|---|
| Ear list | `kid_recent()`: the decayed W_KID boost |
| Director rules | `director._link` acts on the linked id (`ear_place` → `place_of`, through `ref`), not a re-match of the text; `linked_entity(read, ("site",))` gives the mission's dispatch its `target_id` |
| Story | `recall_line(id)`: "You asked about Tycho earlier." When the kid returns to a place they named ≥ 120 s ago, at most once per 5 min per place, it is prefixed to the explorer answer |
| Learned Director | the `ent_*` features (below) |
| Turn log (opt-in) | `entities: [{id, how, p, state}]` per turn: ids, never words |

Privacy:
- Nothing is persisted.
- The memory dies with the session.
- The opt-in turn log follows its existing rules (local file, redacted text, off by default).

## 4. Director features (round 12; append-only)

| Block | Features | Source |
|---|---|---|
| F 0-241 | unchanged (r10 reads this prefix) | |
| 242-252 `ear_*` | `ear_names_avail`, `ear_linked`, `ear_link_p`, `ear_link_sure`, `ear_abstain`, `ear_not_in_list`, `ear_link_step`, `ear_link_screen`, `ear_dec_avail`, `ear_agree`, `ear_dec_name` | `features.link_view` (the ear's names + decoder text) |
| 253-260 `ent_*` | `ent_any`, `ent_step_target`, `ent_seen_before`, `ent_recency`, `ent_guide_said`, `ent_state_rel`, `ent_mishear`, `ent_control` | `features.entity_view` (registry + memory) |

What round 12 should use: all 19.

The six round-7 slots (`ear_conf`, `ear_alts`, `ear_alt_hot`, `ear_rescored`, `ear_tier_step`,
`ear_tier_screen`):
- stay 0;
- should be ignored or dropped in the next layout version;
- their meaning moved to `ear_link_p` / `ear_agree` / `ear_dec_name` / `ear_link_step` / `ear_link_screen`.

Fix `cc` first (SPEECH_SIGNALS_AUDIT.md §4: the generator fabricates it).

Data the generator needs:
- `gen_sessions.py` must replay the ear's `names`, `spoken`, `decoder_text` and `agree` into the final words event.
  The round-11 cache stores them in `x`.
- The session's memory fills itself as the generator plays the session through `Session`.

Shipped decisions are unchanged:
- The r10 weights have `F = 242`, and `runtime.Model.step` slices `feats[:F]`.
- `test_entities.py::test_entity_features_never_reach_the_shipped_weights` and
  `test_speech_signals.py::test_new_features_never_reach_the_shipped_weights` run the shipped weights with and
  without the new read-outs. Every head is bit-identical.

## 5. Plugging in another app

1. Write `data/entities/<app>.json` (schema `whissle.entities/1`): your entities, groups and screen profiles. Point
   `ref` at your own data files.
2. `Registry.load(path)`. Then, per moment, `ear_list(reg, Moment(screen=..., step_ids=..., said=..., kid=...,
   looking=..., states=...))`. Send the result as the ear's names list whenever it changes.
3. Keep an `EntityMemory(reg, clock)` per session:
   - call `note_turn(final_words.names, final_words.spoken, screen)` on every turn you act on;
   - call `note_line(text, by)` on every line you speak;
   - read `kid_recent()`, `last()`, `count()` and `recall_line()`.
4. Act on ids: resolve the ear's `names[i].entity` with `reg.resolve(...)`, and gate on its `p` (see
   SPEECH_SIGNALS_AUDIT.md §3 for why p < 0.99 should ask). Offer `mishear_of()` hits back as a question; never act
   on them.

Nothing in `app/entities/` imports Outpost Luna code; `test_a_tiny_app_registry_plugs_in` builds a zoo registry
inline.

## 6. Measurements

See `docs/SPEECH_SIGNALS_AUDIT.md` §5. On the round-11 paired re-decode, the derived lists are the ones measured
there (identical lists). The "Did you mean" rate, the id-based linking and the r10 invariance are summarised in the
PR body.
