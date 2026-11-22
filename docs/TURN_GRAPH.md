# The turn graph

One kid turn runs as one run of a small graph (`backend/app/graph/`). The graph borrows LangGraph's ideas (typed
state, nodes, conditional edges, a decision node that says where to go next, fan-out, streaming, interrupt / resume,
a step limit, a trace) and none of its code: the runtime is ~400 lines of our own asyncio, with no new dependency. The
app is offline and ships in a kids' installer, so the engine stays small enough to read in one sitting.

This is the first step of the plan "Outpost Luna turn engine: one graph, one learned Director": re-platform the turn
onto the graph **with zero behaviour change**. The nodes are today's code, moved, not rewritten. A later step lets the
learned Director pick the next node directly (the `decide` node is where it already chooses).

## Who does what

| part | file | owns |
|---|---|---|
| Supervisor | `backend/app/session.py` `Session` | the belief, the ear stream (`words` / `turn` / `arc`), barge-in, the floor rules, held proactive decisions, the WS sockets. It starts **one graph run per turn** (`_turn_graph`) and **one per sim poll** (`poll`). |
| Runtime | `backend/app/graph/runtime.py` | `Graph`, `Run`, `RunHandle`, `Goto`, `Checkpoint`, `Result`: running, routing, fan-out, streaming, interrupt / resume, cancel, step limit, trace. Knows nothing about turns. |
| Turn graph | `backend/app/graph/turn.py` | `TurnState` (typed) and the nodes; `TURN` and `POLL`. |
| Director handlers | `backend/app/director.py` `HANDLERS` | the 13 ordered rules of `director.direct()`, each a function; inside a graph run they are the nodes of the `direct` subgraph. |
| Turn log | `backend/app/turnlog.py` `trace_view` | the per-node trace on each logged turn line. |

## The graph

```
intake ─► perceive ─► safety ─┬─► care                                              one gentle line + a flag (END)
          (fan-out)           └─► route ─┬─ ignore / navigate / answer ─► model_routed ─┬─► ignore                (END)
                                         │                                              └─► heard ─► handoff      (END)
                                         └─ question / order ─────────────────────────────► heard ─► direct
direct ─► readout ─► ear_readout ─► director_step ─┬─► model_nav                     the model navigates (END)
                                                   └─► readback ─┬─► readback_out    a bare "copy" (END)
                                                                 └─► privacy ─► decide ─┬─► model_ignore  ─┐
                                                                                        ├─► model_clarify ─┤
                                                                                        └─► director ──────┴─► fallback
fallback ─┬─► quiet                                                                     nothing to say (END)
          └─► story ─┬─► answer_out                                                     a hands-free explorer answer (END)
                     └─► compose ─► emit                                                the decisions + sim events (END)

director = the `direct` subgraph:
  privacy ─► mission ─► correction ─► misconception ─► glossary ─► earthrise ─► sounds ─► tour ─► link ─► sides
          ─► artifact ─► place ─► brain          (the first handler to answer goes to:) ─► steering
```

| node | was | what it does |
|---|---|---|
| `intake` | `_turn` | the yes to the ear's "Did you mean X?", the routing context |
| `perceive` | `_turn` | **fan-out**: Arc Tagger's safety read and, for a typed / Space turn that needs the tagger anyway, the read-out, at once |
| `safety` | `_turn` | `safety.classify`, counts, care flags |
| `care` | `_turn` | the care line |
| `route` | `_turn` | `turn_router.route`, the echo override, talk counts, on-device learning, entity memory, the turn log's start |
| `model_routed` | `_routed` | the learned Director's step on a routed turn; model navigation; model chatter silencing |
| `ignore` / `heard` / `handoff` | `_routed` | stay silent / the `heard` decision / the client runs the navigation or grades the step answer (grader hand-off) |
| `direct` | `_direct_turn` | §3 rule 3 cancels, the floor, the referent ("give it more") |
| `readout` | `_direct_turn` | `summarize(models_client.tag(...))` (the prefetched one when the words match) |
| `ear_readout` | `_direct_turn` | the ear's names, almost-matches, quantities, clean text on the read |
| `director_step` | `_direct_turn` | the learned Director's step with the read; round-7 model navigation (decision) |
| `readback` / `readback_out` | `_direct_turn` | the radio readback (`mission/readback.py`) |
| `privacy` | `_direct_turn` | the Director's context; the privacy guard (a name given, hard PII) |
| `decide` | `_direct_turn` | **decision node**: `dm.decide_turn` -> `model_ignore` / `model_clarify` / `director` |
| `director` | `_direct_turn` | learned aliases on the read, then `director.direct()` (the handlers as a subgraph: privacy, mission nlu, ..., the local brain; then steering = `decisions_for`) |
| `fallback` | `_direct_turn` | `_gate_fallback`, the ear's confirm offer, the Director's turn result, the turn log's decision |
| `quiet` / `story` / `answer_out` / `compose` / `emit` | `_direct_turn` | the story callback, the explorer answer, the decisions, the storm look-ahead, the sim's events |

The poll graph (`POLL`, once a second per socket): `observe ─► events ─► offer`.

## Runtime features

| feature | how | test |
|---|---|---|
| Typed state | a dataclass (`TurnState`, `PollState`, `director.DirectState`); a node may also return a dict of updates | `test_graph_runtime.py` |
| Nodes | `async` or plain `fn(state, run, **args)` | ″ |
| Decision node | returns `goto(node, update={...}, **args)`: the next node, its keyword args, state updates | ″ |
| Conditional routing | `branch(node, fn(state) -> name)`, or a node returning a name / `END` | ″ |
| Parallel fan-out | `parallel(name, {branch: fn})`: asyncio, updates merged in declared order; the first error cancels the rest | ″, `test_turn_graph.py` |
| Streaming channel | `await run.emit(x)`: out through the caller's `stream` (the session's `emit`) while the run continues | ″ |
| Interrupt / resume | `run.interrupt(value)` pauses with a `Checkpoint`; `graph.run(..., resume=cp, value=v)` re-enters the node and `interrupt()` returns `v` | ″ |
| Cancellation | `graph.start()` -> `RunHandle` in its own task; `cancel()` refuses once a `commit=True` node started; `on_cancel` cleanup keeps the state consistent; a cancel from outside is cleaned up and re-raised | ″ |
| Step / depth limit | `max_steps` (64) per run -> `StepLimit`; subgraphs at most `MAX_DEPTH` (4) deep | ″ |
| Trace | per node: `n`, `ms`, `go` (a decided next node), `w` (fields rebound), `a` (arg names), `o` (the node's own small view), `par` (fan-out branch ms) | ″ |

## Behaviour: what changed and what did not

Nothing a kid or a client can see changed. `docs/CONTRACT.md` and `docs/SESSION_CONTRACT.md` are untouched: the same
decisions, in the same order, with the same fields. Two things differ inside:

1. **The perception fan-out.** A typed or Space turn with no ear safety read used to wait for Arc Tagger twice in a row
   (the safety read, then the read-out). Both calls are independent, so they now run at once; the read-out is used only
   when the turn reaches the `readout` node with the same words, and a failed prefetch is asked again there exactly as
   before. A turn that ends early (care, ignore, navigate) leaves one unused read-out call on the local model server.
   Open-mic turns are not prefetched (most are chatter the router ignores).
2. **The turn log** carries `trace` (below).

`TURN_ENGINE=legacy` runs the pre-graph code (`Session._turn_legacy`, `_routed`, `_direct_turn`, `_poll_legacy`), kept
for one release as a kill switch and as the other side of the replay diff. Delete it once a release has shipped with
the graph.

### Cancellation (barge-in)

The session can cancel a turn still being worked out when the kid barges in (`Session.barge_in` -> `RunHandle.cancel`).
A run is cancelled only **before** its first commit node (anything that changes the sim, sends the answer, or hands the
turn to the client); after that it finishes, because the world already changed. The cleanup sends the `cancel` of older
decisions the turn had already dropped and gives the learned Director its turn result (`none`).

It is **off by default** (`TURN_GRAPH_BARGE_CANCEL=1` turns it on): today a barge-in drops unplayed decisions but lets
an in-flight turn finish, and this PR changes no behaviour. Switching it on is the next, separate step.

### Mission confirmations stay as they are

The plan asked to move mission confirmations ("All power to science? Yes / No") onto interrupt / resume only if parity
holds. It does not: the pending order lives in `director.PENDING`, keyed by mission and shared by every path that can
answer it (the session's turns, `/api/ask`, the readback gate in `Session._readback`, a role hand-off to another
officer). A per-session graph checkpoint would make a "yes" typed through `/api/ask`, or by another officer's session,
stop confirming. So the runtime has interrupt / resume (tested), and mission confirms keep `PENDING` until those paths
share one owner.

## The turn log trace

Each logged turn (only while the turn log is on, `docs/DIRECTOR_LOOP.md`) gets `trace`:
`[{"n": "route", "ms": 0.31, "o": {"outcome": "question", "reason": "...", "intent": null}}, {"n": "decide", "go":
"director", ...}, {"n": "direct/glossary", "go": "steering", "o": {"handler": "glossary"}}, ...]`.
`turnlog.trace_view` keeps node names, milliseconds, the node a decision node chose and small views whose values are
numbers, booleans or code enums (`^[a-z][a-z0-9_+.:-]{0,39}$`). Words, names and free text are dropped, so a guarded
(`<private>`) turn's trace is as safe as its other fields. Retention, the size cap and "Delete what's saved" apply as
to every other field (it is part of the same line). At most 48 nodes per turn.

## Parity

`backend/tools/turn_replay.py`:

```
cd backend
# 1. every turn the test suite exercises, recorded per test (decisions, director.direct answers, turn-log lines)
TURN_ENGINE=legacy uv run pytest -q -p tools.turn_replay --turn-record /tmp/legacy.jsonl.gz
TURN_ENGINE=graph  uv run pytest -q -p tools.turn_replay --turn-record /tmp/graph.jsonl.gz
uv run python tools/turn_replay.py diff /tmp/legacy.jsonl.gz /tmp/graph.jsonl.gz
# 2. golden turns (director_model/data/gold*.json, tests/eval, the golden ear set) and 3. a family's turn log
uv run python tools/turn_replay.py replay --golden [--log turns.jsonl]
# 4. latency, old engine vs graph (offline; --model-ms simulates the model server's Arc Tagger call)
uv run python tools/turn_replay.py bench --rounds 5 [--model-ms 20]
```

A recording of the pre-graph `main` (the same command in a checkout of `main`, with this file copied in) is the
baseline for the director refactor, which both engines share. Decision ids are renumbered per test, mission ids and
latencies masked; two recordings of one engine show which tests are noisy (`--noise`).
