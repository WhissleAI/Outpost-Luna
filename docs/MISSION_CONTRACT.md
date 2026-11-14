# Mission Trainer contract (shared by the sim, command, UI and docs work)

Challenge: NASA Space Apps 2026, "Build a Junior Astronaut Mission Trainer" (ages 7–12). The kid commands a lunar
south-pole outpost by voice. Three core resources; every choice costs something; real NASA data drives events.
Cadet mode (the existing Moon explorer, hardware, crew audio) stays as training before the mission.

## Resources (0–100 bars in the UI; real units in the API)
- **power**: battery state of charge, % (from solar arrays; drops in darkness, with loads)
- **life_support**: oxygen + water reserve, % of mission need (greenhouse/ISRU raise it; consumes power)
- **dose**: crew radiation dose so far, mSv, against a mission limit (shielding/shelter lowers the rate; costs power or time)

## Loads the kid controls (power split, sums to 100)
`shields`, `life_support`, `greenhouse`, `science`, `rover`, `comms`, `heaters`

## Time
Turn-based by **mission hour blocks**: one "shift" = 6 hours; the mission = 10 days (40 shifts). The kid makes decisions,
then says "end shift" / "next" to advance. The server may also stream telemetry frames between shifts for a live feel.

## API (backend, all JSON)
- `GET  /api/mission/sites` → `{"sites":[{id,name,lat,lon,sunlight_pct,ice:bool,earth_visible_pct,notes,sources:[{title,url}]}]}`
- `POST /api/mission/start` `{site, seed?, roles?:["power","life","comms"]}` → `State`
- `GET  /api/mission/{mid}` → `State`
- `POST /api/mission/{mid}/command` `{command: Command}` → `{state: State, result: {ok, needs_confirm?:bool, say, readback, events:[Event]}}`
- `POST /api/mission/{mid}/advance` `{shifts: 1}` → `{state: State, events:[Event], say}`
- `GET  /api/mission/{mid}/debrief` → `{score, grade, timeline:[...], lessons:[{text, source}], data_used:[{name,url,how}]}`
- `WS   /ws/mission/{mid}` → telemetry frames `{"t":"telemetry","mission_time_h":…, "power":…, "life_support":…, "dose_msv":…, "dose_rate":…, "sun_elev_deg":…, "earth_elev_deg":…, "comm":"open|closed", "loads":{…}, "alerts":[…]}` every ~1 s (sim time compressed)

### State
```json
{"id":"m-…","site":{…},"day":3,"shift":2,"mission_time_h":66,"over":false,"outcome":null,
 "resources":{"power_pct":72,"life_support_pct":81,"dose_msv":14.2,"dose_limit_msv":50,"dose_rate_msv_h":0.06},
 "loads":{"shields":20,"life_support":30,"greenhouse":15,"science":15,"rover":10,"comms":5,"heaters":5},
 "env":{"sun_elev_deg":1.8,"in_sun":true,"earth_elev_deg":-0.4,"earth_visible":false,"next_comm_window_h":5,"comm_delay_s":2.6,
        "storm":{"active":true,"name":"Real solar storm, May 2024","source":"DONKI","severity":3}},
 "rover":{"busy":false,"task":null,"eta_h":0},"shelter":false,
 "alerts":["dose_rate_high"],"log":[{"t_h":60,"text":"…","kind":"event|command|houston"}],"score":340}
```

### Command (produced by the command layer from speech; consumed by the sim)
```json
{"type":"allocate","to":"shields","amount":{"kind":"percent|delta|all|half|little|none","value":20},"from":null}
{"type":"dispatch","vehicle":"rover","task":"collect_ice|repair_array|explore|return","target":"<place id or null>"}
{"type":"shelter","on":true}
{"type":"query","what":"power|oxygen|life_support|dose|storm|comms|all"}
{"type":"call_houston","text":"…"}
{"type":"end_shift"}
{"type":"confirm"} | {"type":"cancel"}
```
Destructive or risky commands (all power to one load, sending the rover into a storm, turning heaters/life support to 0)
return `needs_confirm: true` with a readback; the kid says "yes"/"confirm" (→ `confirm`) or "no" (→ `cancel`).

### Event
`{"t_h":…,"kind":"solar_storm|storm_end|sunset|sunrise|comm_open|comm_closed|low_power|dose_alert|rover_back|failure","text":"…","source":{"title","url"}|null,"real_date":"YYYY-MM-DD"|null}`

## /api/ask in mission mode
Client sends `context.mission = {"id": mid, "role": "power|life|comms|null"}` (plus `last_place`, `emotion` as before).
The Director then may return:
- `action:"command"` + `command: Command` + `say` (CAPCOM readback) + `needs_confirm`
- `action:"status"` + `say` (answer from State) + `state`
- `action:"houston"` + `say` + `delay_ms` (real round trip ~2,600 ms on the Moon; client waits before speaking)
- any existing action (fly, play, explain…) for non-mission questions

## Additive fields (sim agent, feat/mission-sim)
Nothing above was changed; these were only added:
- **State**: `seed`, `science:{collected, sent_home}` (science only scores fully once sent home over a comm window), `pending` (the command awaiting confirm, or null), `site.window_sunlit_pct` (sunlit % in the actual 10-day window). `env.storm`, when active, is `{active, name, source, url, severity, real_date}`. `outcome` is `null | "survived" | "life_support_out" | "power_out" | "dose_limit"`.
- **Alerts**: `low_power`, `life_support_low`, `dose_rate_high`, `dose_near_limit`, `solar_storm`, `array_damaged`.
- **Event kinds**: `mission_complete` (sent on a win), plus the contract kinds. `failure` also covers the seeded solar-array damage.
- **Command result**: `call_houston` adds `delay_ms` (2600). The command type `rule` is accepted as a no-op; the voice layer owns rules.
- **Allocate amounts**: `percent` sets the new absolute share; `delta` is a signed change in points; `little` is ±5 (the sign comes from `value`); `half`, `all` and `none` set the share to 50, 100 and 0. The other loads rebalance in proportion, or take the whole difference from `from` when it is given. Total stays 100.
- **Telemetry frames**: `forecast:true` when the frame is a preview into the current shift (a 6-hour shift plays out over ~30 s, then holds), plus `over`.
- **Debrief**: `outcome`, `why` (one sentence), `lose_reason`, `site`, `seed`, `final{...}`, and `log` (the event/command text log). `timeline` has one entry per shift: `{t_h, power, life_support, dose_msv, events:[kind]}`.
- **Python** (Director): `app.mission.registry.get(mid)` returns a Mission with `.apply(cmd)` returning `{state, result}` and `.state()`. `registry.apply(mid, cmd)` returns the same shape.

## Additive fields (learning design v3, feat/learning-v3; docs/LEARNING_DESIGN.md §6)
Nothing above was removed. Added:
- **Start**: `POST /api/mission/start` takes `level: "cadet" | "commander"` (default `cadet`; Settings `prefs.level`). It is the one level: the session passes `prefs.level` to the mission (`sim.set_level`): before the first shift the whole band applies; after that the storm schedule stays and warnings, the relay and grading follow the level. Cadet: 2 storms, both with solar particles, 12 h warnings delivered even when Earth is down (a relay satellite, labelled as future), no array failure; surviving is the success and goals add stars. Commander: 2–3 storms, some without particles (honest near misses), 6 h warnings only when Earth is up, one array failure.
- **Command** `{"type": "power_save", "on": bool}`: night mode. Draw ×0.35; science stops; the greenhouse runs at half. Voice: "night mode on/off", "hibernate", "power save", "wake up the outpost". Role: power. No confirm.
- **Shelter**: Orion-style. Draw ×0.8 (not a hibernate); greenhouse at half. After 24 h in a row (and no storm on) the crew comes out (`shelter_limit` event) and can't re-enter for 12 h unless a storm is on (the command returns `ok:false` with the wait).
- **Events**: `storm_warning` `{confidence: "likely"|"possible", lead_h, by: "houston"|"relay"|"sensor"}` is separate from `solar_storm` (the hit, which adds `sep: bool`). `shelter_limit`. Houston's call says "likely/possible in the next two days", never an exact hour.
- **Storms**: keyed on DONKI SEP records (`donki_events.json` `id` is the SEP id when there is one; `gst_id`/`gst_link`/`class` keep the Earth storm as context). Dose ×8 (SEP + CME ≥ 1500 km/s, 24 h), ×4 (SEP, 18 h), ×1.25 (no SEP, 12 h).
- **State**: `power_save`, `shelter_hours`, `shelter_ready_in_h`, `difficulty`, `objectives {science:{goal,got,met}, ice:{goal,got,met}, met}`, `good_calls` (count), `pretend_tech` (labels for the UI), `env.next_sun_change_h` (Sun strip), `env.relay`, `env.warning {confidence, eta_h, by, real_date} | null`, `env.storm.sep`; `site.window_sun_days`, `site.window_earth_days`, `site.status` (`nasa_2024` | `studied`), `site.status_label`.
- **Alerts**: `storm_warning` (a warning heard, storm not yet here).
- **Score/grade**: 300 survival + up to 300 goals (science sent home ≤ 200, 50 per ice run ≤ 2) + 40 per good call (≤ 6) − 6 per game-mSv above 15. A ≥ 700, B ≥ 560, C ≥ 420, D ≥ 280. Commander: a survivor who missed a goal is capped at C. Cadet: survived = B, both goals = A.
- **Debrief**: `difficulty`, `objectives`, `stars` (0–3), `good_calls [{t_h, kind, text}]`, `try` (one line for next time).
