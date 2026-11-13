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
