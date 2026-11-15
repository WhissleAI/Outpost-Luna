# Accuracy audit: Outpost Luna vs `docs/ARTEMIS_REFERENCE.md`

- **Audited:** 2026-11-13, against `origin/integ/desktop-v2` @ the base of `feat/artemis-ref`.
- **Scope:**
  - `backend/data/academy/course.json`
  - `facts.json`, `glossary.json`, `places.json`, `artifacts.json`
  - `mission/` (`sites.json`, `radiation.json`, `donki_events.json`, ephemerides)
  - `backend/app/mission/sim.py` and `capcom.py`
  - `frontend/src/story.js`
  - the cabin and mission UI (`frontend/src/mission/cabin.js`, `cockpit.js`, `ui.js`, `mock.js`)
  - the About section in `frontend/index.html`
- **Verdicts:**
  - **WRONG**: false today.
  - **IMPRECISE**: true-ish but mislabelled, outdated or misleading to a kid.
  - **UNVERIFIABLE**: no primary source found.
  - **OK**: checked against a source.
- **Sources:** "Ref §n" points to the section of `ARTEMIS_REFERENCE.md` that holds the source and URL.
- **Process:** this audit lists fixes only. Owners apply them; no app code was changed here.

---

## Status (re-checked 2026-11-14, `feat/learning-v1`)

Facts re-verified on nasa.gov and the USGS Gazetteer on 2026-11-14; sources are in `backend/data/learning/concepts.json`
(`checked` fields) and listed in `docs/LEARNING_DESIGN.md` §11.

| # | Status | Where it stands now |
|---|---|---|
| 1 | **Resolved** | Artemis III = 2027 Earth-orbit test; Artemis IV = first south-pole landing, NASA: "Early 2028" (nasa.gov/mission/artemis-iv). `tests/test_learning.py::test_nothing_says_artemis_iii_lands` locks it. |
| 2 | **Resolved** (picker) / open (debrief wording) | The picker labels the yearly average ("About 86% sunlight (yearly average)") and shows the window as days. The debrief still names "JPL Horizons" next to the window days, with a "smooth ground" caveat. |
| 3 | **Resolved** | Events are keyed on DONKI SEP records (`sep_id`) and named "solar particle storm"; the G class stays only as Earth-side context. Still open: the dev-only storm mock in `mission/ui.js:74` says "G5" (owned by the mission-UI branch; handed off). |
| 4 | **Resolved** | Houston's warning says particles "within hours" (lead 12 h Cadet / 6 h Commander, a game setting). |
| 5 | **Resolved** | The `moon` lesson cites NASA's Oct 2024 list of 9 regions (Malapert Massif, de Gerlache Rim 2). |
| 6 | **Resolved** | 2.6 times the ISS cosmic-ray dose (523 µSv/day); locked by `test_dose_baseline_compares_with_the_iss_cosmic_ray_dose`. |
| 7 | **Resolved** | No "the plan is a soil shelter"; the lessons use Orion's stowage-bag shelter. |
| 8 | **Resolved** | "Pretend tech" tags on the shields and other game hardware (`story.js` PRETEND_TECH). NASA's real Moon Base plan now exists, so the credit lines add "Outpost Luna is a pretend outpost for learning. NASA's real Moon Base plans: nasa.gov/moon-base." (`PRETEND_BASE`, home, map, About). |
| 9 | **Resolved** | LCROSS: about 2,300 kg Centaur, about 155 kg of water (Colaprete 2010). |
| 10 | **Resolved** | "Built on NASA open data, plus a few science papers" (`SOURCES_LINE`); About no longer says "Every fact shows its NASA source". |

Other items closed in this pass:
- **Coldest temperature.** NASA now gives "lower than -410°F (-246°C)" (science.nasa.gov/moon/weather-on-the-moon). The
  old "near -235 C" (Paige et al. 2010, an early Diviner result) is replaced. The wording stays "the coldest spots
  measured", with NASA's Moon Base page (about -203 °C in shadowed craters, nasa.gov/reference/moonbase-about) as a
  second source.
- **Integrity and Carroll.** Still not in the IAU Gazetteer's Moon list (newest approvals Sep 21, 2026). The history
  lesson says "proposed" and "the IAU has not approved them".
- **LROC.** The site moved to lroc.im-ldi.com. About now links it and credits "NASA/GSFC/Arizona State University", and
  credits NASA's Scientific Visualization Studio for the CGI Moon Kit.
- **SPA "as wide as the USA"** and **"Mare Orientale"** are fixed in `places.json` ("more than half as wide",
  "Orientale Basin").

---

## Top 10 corrections (priority order)

| # | Where | Current claim | Verdict | Fix | Source |
|---|---|---|---|---|---|
| 1 | `story.js:10` FRAMING, `:62` MENTOR.first, `:70` SCHOOL.hero; `course.json:20` (lesson `moon` brief); `index.html:144`, `:168` (About); `places.json` shackleton aliases "artemis iii"; `sim.py:701` | "**Artemis III, the first landing near the south pole, hasn't happened yet**" / "Artemis III hasn't landed yet" | **WRONG** (since 2026-02-27) | NASA made Artemis III a **2027 crewed test in Earth orbit** (docking with the landers). The **first planned south-pole landing is Artemis IV, NASA target 2028**. Suggested copy: "Artemis II flew its crew around the Moon in April 2026. The next big step is the first landing near the south pole, planned for Artemis IV. You're training to help run Outpost Luna for the crews who come after." Hero: "Nobody has landed at the south pole yet. Train for the crew that will." Keep an "artemis iii" alias but answer correctly ("Artemis III is a 2027 practice flight in Earth orbit"). Add "artemis iv" / "artemis 4" aliases. | Ref §3 (NASA release 26-022; Nov 2026 crew release; Artemis IV page) |
| 2 | `ui.js:139-140` site picker vs `sim.py:684` debrief; `sites.json` `sunlight_pct` / `window_sunlit_pct` / `earth_visible_pct` | Picker: "☀ 86% sun". Debrief: "the Sun was up 100% of these 10 days (JPL Horizons, April 2026)". Picker also shows "🌍 Earth 45%". | **IMPRECISE (mislabelled, mixed time bases)** | **Both numbers can be right; they measure different things.** `sunlight_pct` = **long-term (about yearly) average illumination** from published studies. `window_sunlit_pct` = **our model's 10-day April 2026 window**. The picker's **Earth %** is *also* the 10-day window value, so one row mixes a yearly sun number with a 10-day Earth number. **Label them:** picker "☀ About 86% sunlight (yearly average)" and "🌍 Earth up 45% (Apr 8–18, 2026)", or compute a long-term Earth %. Debrief: "During your 10 days the Sun stayed up X% of the time **in our model**". **Do not attribute the 100% to "JPL Horizons":** Horizons gave Sun elevations of **−1.09° to −0.81°** for Shackleton rim. The 100% comes from the app's single calibrated horizon angle (−1.312°), a model choice. Add one line: "Real mountains make some hours darker or lighter." | Ref §4.1; `ephemeris_shackleton_rim.json` checked |
| 3 | `donki_events.json` (all events), `mapping.rule`; `course.json:441,988,1015`; `story.js` LESSON_BLURB.radiation; `ui.js:55` | Lunar radiation events are **geomagnetic storms (GST, G4/G5, Kp)**. "Real G5 solar storm… replayed at your outpost". Severity is set from Kp and CME speed. | **IMPRECISE → misleading** | G-scale, Kp and GST measure **Earth's magnetic field**. The Moon has none. A lunar crew's hazard is the **SEP (solar proton) event**, NOAA's **S-scale**. Re-key events on **DONKI SEP** records and, ideally, GOES ≥10 MeV proton peak / S-level. Rename to "solar particle storm". For May 2024 say: "the real May 2024 solar storm, which gave Earth huge auroras. At the Moon, what matters is the burst of fast particles." Keep Kp only as Earth-side context. | Ref §6 (DONKI types; NOAA scales) |
| 4 | `sim.py:300` | "Houston: we just saw a big flare… Particles may reach you in **about 6 hours**." It fires 6 h before a GST-dated storm. | **IMPRECISE** | Flare light arrives in about 8 min. **SEP protons arrive in tens of minutes to a few hours.** **CMEs take about 1–3 days** (15–18 h at the fastest). Either keep "particles could arrive within an hour, shelter now!", or warn 1–3 days ahead for a CME. Don't tie a geomagnetic-storm date to a 6 h particle warning. | Ref §6 |
| 5 | `course.json:23` (lesson `moon` fact 0); `sites.json:39` and `:104` notes | "NASA has named candidate landing regions… **including the rim of Shackleton crater**". Connecting Ridge is "an Artemis III candidate region". | **WRONG / outdated** | The 2022 list had "**Peak near Shackleton**" (not "the rim"), and **NASA dropped it and Connecting Ridge in Oct 2024**. Current 9 regions: Peak near Cabeus B, Haworth, **Malapert Massif**, Mons Mouton Plateau, Mons Mouton, Nobile Rim 1, Nobile Rim 2, **de Gerlache Rim 2**, Slater Plain. Fix: "NASA's 2024 list of 9 possible landing regions near the south pole includes Malapert Massif and de Gerlache Rim 2. Shackleton is one of the most-studied craters there." Sites notes: "was a candidate region in 2022; not on NASA's 2024 list". | Ref §3 (NASA 2024-10-28 release) |
| 6 | `course.json:431`; `sim.py:675`; `radiation.json` `iss_comparison` | "1369 µSv a day, **about 2.6 times more than inside the ISS**". `radiation.json` stores the ISS figure as **731** µSv/day. | **IMPRECISE** | The 2.6× in Zhang 2020 compares against the ISS **GCR-only 523 µSv/day**. 731 is the ISS total including the South Atlantic Anomaly (1369/731 ≈ 1.9). Store `iss_gcr_usv_per_day: 523` next to the 731 total and say "about 2.6 times the cosmic-ray dose inside the Space Station". `sim.py` already says that. Kid line: "One day on the Moon ≈ 14 chest X-rays". | Ref §5 (Zhang 2020, fetched) |
| 7 | `course.json:451`; `sim.py:669` ("a regolith shelter is the plan"); `capcom.py` shelter readback; `radiation.json.shielding` | "**The plan** is a shelter covered in soil." | **IMPRECISE** | No NASA Artemis surface-shelter design was found. Regolith shielding is a **studied idea** (NTRS 1989, 2011). The **real, flown plan** is in Orion: the crew **build a shelter from stowage bags** in the bays under the seats, with up to 1 h warning, for up to 24 h. Artemis I showed shielded spots get **about 4× less** dose. Fix: "Scientists have studied covering a base with Moon soil. In Orion, real crews build a shelter out of their supply bags." This also makes the game's ×0.25 shelter factor defensible (cite George et al. 2024). | Ref §1.4, §5 |
| 8 | `cabin.js` (shields knob, "Shield power %"), `ui.js:12` LOAD_HELP "shields: Blocks radiation", "greenhouse: Plants make oxygen"; `radiation.json.game.shields_note` | **Powered "radiation shields"** and a working greenhouse are shown as hardware with no in-UI label | **Invented hardware presented as real** (to a kid) | Mass shields radiation, not electricity. No flown or planned NASA powered radiation shield exists. Keep it as a game mechanic, but **label it in the UI** ("pretend tech: pumps water walls around the crew") or rename it "Water wall pumps". Tag the greenhouse "future idea". The data file already says "Game assumption"; the kid never sees that. | Ref §5 |
| 9 | `facts.json:490-491`, `artifacts.json:1107`, `course.json:566` | "**2000 kg** Centaur… dug out roughly **350 metric tons**… crater about **20 m**" | **IMPRECISE** | Centaur at impact was about **2,300 kg** (2,305 kg nominal). **350 t was the pre-impact prediction.** About 4,000–6,000 kg of debris rose into sunlight. The crater was about **25–30 m**. Add the headline result kids can use: "about **155 kg of water** in the plume, around **5–6% water** in that soil". | Ref §4.2 (Colaprete 2010; NTRS 20100026403) |
| 10 | `story.js:18,59`; `index.html:168` ("Every fact shows its NASA source") | "Everything you learn here uses **real NASA data**" | **IMPRECISE (over-claim)** | The baseline dose is from **China's Chang'e 4** (CNSA; Zhang 2020). The illumination % comes from peer-reviewed papers (Bussey/Kaguya, Gläser). Dose is **doubled** for gameplay. Shields, greenhouse, cable losses and the relay are game assumptions. Fix: "Built on real NASA open data and space-science measurements. Some game rules are made up so the game works; the Debrief shows which." CREDIT and "not endorsed by NASA" lines are good: keep them. | Ref §5 |

---

## Full findings by file

### `frontend/src/story.js`

| Line | Claim | Verdict | Fix / note |
|---|---|---|---|
| 8 | "Inspired by NASA's Artemis program. Uses NASA open data; not endorsed by NASA." | OK | Keep. Good disclaimer. |
| 10, 62, 70 | Artemis III = first south-pole landing; hasn't landed | **WRONG** | Top-10 #1 |
| 18, 59 | "real NASA data" | IMPRECISE | Top-10 #10 |
| 59 | "The next crews will land near the south pole" | OK | Optionally add "(planned for 2028)". |
| LESSON_BLURB.power | "Malapert's long polar night" | IMPRECISE | In the window, Malapert's dark spell is a terrain plus libration effect in our model, not a season. Say "Malapert's long dark spell". |
| LESSON_BLURB.radiation | "Ride out the real May 2024 solar storm" | IMPRECISE | Top-10 #3 |
| LESSON_STORY.comms | "Outpost Luna is 384,000 km from Houston" | OK | Mean distance is 384,400 km. |
| DEBRIEF.mars | "On Mars, Houston would answer 6 to 44 minutes later." | OK | 3–22 min each way (Ref §7). |
| CALLBACKS.comm_closed | "Earth just set, so the radio is quiet" | OK | — |

### `backend/data/academy/course.json`

| Lesson / item | Claim | Verdict | Fix / source |
|---|---|---|---|
| moon.brief | Artemis III first south-pole landing | **WRONG** | #1 |
| moon.facts[0] | Shackleton rim is an Artemis III candidate | **WRONG** | #5 |
| moon.facts[1] | "far side… never faces Earth" | OK (simplified) | Libration shows us about 59% over time. Fine for ages 7–12. |
| moon.facts[2] | Shackleton ~21 km wide, ~4 km deep, "right at the south pole" | OK | Depth is about 4.2 km (Zuber 2012). The pole sits almost on its rim. Optionally say "the south pole is on its edge". |
| moon.facts[3] | Floor never sunlit, "colder than −170 °C", ice | IMPRECISE | True but undersold, and the cited source (M3 ice release) doesn't give temperature. Diviner: PSRs reach about −235 °C (35–40 K). Cite Paige 2010. (Ref §4.2) |
| moon.steps[0].success | "See how the Sun barely rises there?" | OK | At most about 1.5° above the ideal horizon. |
| power.facts[0] | Shackleton Rim ~86%, Malapert ~73% (Bussey 2010) | IMPRECISE | Label it a **yearly average**. The 86% is in the Kaguya results (Bussey/Quick 2010); Gläser 2018 gives 85.5%. Malapert is about 74% (2020). The abstract of Bussey 2010 doesn't print these, so cite Gläser 2018 / PGDA. (Ref §4.1) |
| power.facts[1-2] | Malapert sunlit 35% of the window; longest night 157 h | OK **as model output** | Add "in our model". The numbers come from the calibrated-horizon model, not raw Horizons. |
| radiation.brief / steps[0] | 1 mSv ≈ 10 chest X-rays | OK | Chest X-ray ≈ 0.1 mSv. |
| radiation.facts[0] | 1369 µSv/day, 2.6× ISS | IMPRECISE | #6 |
| radiation.facts[1] | "real G5 solar storm with solar particles and a CME at 1561 km/s" | IMPRECISE | #3: G5 is an Earth magnetic-storm level. Name the SEP part for the Moon. |
| radiation.facts[2] | "the plan is a shelter covered in soil" | IMPRECISE | #7 |
| life.facts[0] | 2000 kg Centaur, 350 t | IMPRECISE | #9 |
| life.facts[1] | LCROSS flew through the cloud and found water | OK | Add "about 155 kg of water". |
| history.facts[0] | Surveyor 3: 6,326 pictures; Apollo 12 took about 10 kg of parts incl. the TV camera | OK | NSSDCA |
| history.facts[1] | Lovell commanded Apollo 13, flew around the Moon on Apollo 8 | OK | Apollo 8 was the first crewed lunar orbit. |
| history.facts[2] | Apollo 16 rover 26.7 km | OK | NSSDCA LRV |
| history.facts[3] | Artemis II flew around the Moon in April 2026; the crew audio is theirs | OK | Ref §2 |
| words.facts[*] | Crew said "albedo"/"regolith"; cheered at Earthrise | OK | Matches clips `aristarchus`, `ohm-crater-ray-systems`, `crew-reacts-joyfully-earth`. |
| checkride.facts[0] / steps[1] | "real G5 storm of 2024-05-10 … hitting the outpost" | IMPRECISE | #3 |
| checkride.steps[0] | "Give the radiation shields more power" | Invented hardware | #8 |

### `backend/data/mission/sites.json` (+ ephemerides) and `frontend/src/mission/mock.js`

| Site / field | Claim | Verdict | Fix |
|---|---|---|---|
| all: `sunlight_pct` | Long-term illumination % | IMPRECISE (label) | #2. Add `"sunlight_basis": "long-term average, published studies"` and `"window_basis": "model, 2026-04-08..18"`. |
| shackleton_rim: 86 | | OK as a long-term average | Gläser 2018: 85.5%. |
| shackleton_rim: `ice: false`, notes "Ice is a short drive down into the crater" | Picker shows "No ice nearby" while the notes say ice is a short drive away | IMPRECISE (self-contradiction) | Picker copy: "Ice: 6 h drive". |
| shackleton_rim notes | "'Peak Near Shackleton' was an Artemis III candidate region in 2022" | OK but incomplete | Add "dropped from NASA's 2024 list". |
| connecting_ridge: 82 | | IMPRECISE (low) | The best Connecting Ridge points are about 92% at 2 m (Gläser 2014). 82% is defensible for a ground-level point. Cite the basis. |
| connecting_ridge notes | "an Artemis III candidate region in 2022" | OK but incomplete | Add "not on the 2024 list". |
| de_gerlache_rim: 81 | | UNVERIFIABLE | No published % found for these coordinates. Cite PGDA product 78, or label "estimate". |
| de_gerlache_rim notes | "'de Gerlache Rim 2' is an Artemis III candidate region" | OK | It's on the 2024 list. Change "Artemis III" to "NASA's 2024 landing-region list". |
| malapert_massif: 73 | | OK-ish (about 74% for 2020) | |
| malapert notes | "5 km-tall mountain … Earth above the horizon much more often" | OK | Window value: Earth up 93%. |
| shackleton_floor: 0, ice true, "colder than −170 C" | | OK / IMPRECISE | Temperature as in course moon.facts[3]. The power-cable and relay rows are labelled game assumptions: good. |
| Horizon model (`horizon_deg`) | One effective horizon angle per site | OK **if disclosed** | The ephemeris notes already disclose it. The debrief must not attribute the result to Horizons alone (#2). |
| `window.why` | "the month Artemis II flew" | OK | Artemis II flew Apr 1–10. The window (Apr 8–18) overlaps its last 3 days. |
| `mock.js` SITES | Connecting Ridge named "(Shackleton rim)", sun 86, ice true. Malapert 63%. de Gerlache 74% / Earth 68%. Sources say "Artemis III candidate regions" (2022 URL). | **IMPRECISE / inconsistent with real data** | Generate the mock from `sites.json` values so "Sample data" never teaches different numbers. |

### `backend/data/mission/radiation.json`, `donki_events.json`, `backend/app/mission/sim.py`, `capcom.py`

| Item | Claim | Verdict | Fix |
|---|---|---|---|
| baseline 1369 µSv/d, 0.057 mSv/h | Chang'e 4 LND | OK | Zhang 2020 (fetched) |
| iss_comparison 731 | used against "2.6×" | IMPRECISE | #6 |
| limits.career_msv 600 | NASA career limit | OK | NASA-STD-3001 (2022) |
| game ×2 dose, 50 mSv mission limit | Disclosed game numbers | OK | Disclosed in the debrief: good. |
| shelter ×0.25 (storm), ×0.7 (GCR) | Game assumption | OK-ish | ×0.25 matches Artemis I's about-4× shelter difference (George 2024). Cite it. ×0.7 for GCR is plausible; keep it labelled. |
| shields up to −50% at 30% power | Game assumption | Invented hardware | #8 |
| donki mapping rule (Kp, CME speed → dose ×1.5/×3/×6) | | IMPRECISE | #3. Use DONKI SEP plus proton flux. A real large SEP can be **10–1000×** the background behind thin shielding, so ×6 understates big events. That is fine for gameplay if labelled "scaled for the game". |
| event names "Real G4/G5 solar storm" | | IMPRECISE | "Real solar storm of 2024-05-10 (Earth: G5 geomagnetic storm; Moon: solar particle event)". |
| sim.py:300 "Particles … in about 6 hours" | | IMPRECISE | #4 |
| sim.py:669 "On the Moon there is no magnetic field or thick air to stop solar particles" | | OK | — |
| sim.py:669 "a regolith shelter is the plan" | | IMPRECISE | #7 |
| sim.py:675 2.6× | | OK wording | It says "cosmic-ray dose", so it matches 523. Fix the stored 731 (#6). |
| sim.py:684 "Sun was up X% of these 10 days (JPL Horizons…)" | | IMPRECISE | #2 |
| sim.py:684 "at the pole the Sun skims the horizon" | | OK | — |
| sim.py:20 / capcom.py:11 COMM_DELAY 2.6 s round trip, 1.28 s one way | | OK | Range 1.19–1.35 s. |
| capcom.py:15 Mars 3–22 min each way, 6–44 min round trip | | OK | NTRS ASCEND |
| capcom "Calling Houston" / "Houston here" | Role-play | OK | Optionally note once in About: "CAPCOM and Houston are played by the game." |
| sim BACKUP_GEN as a stand-in for Fission Surface Power | | OK | Labelled; NASA FSP is real (a project, not yet flown). |

### `backend/data/places.json`, `facts.json`, `glossary.json`, `artifacts.json`

| Item | Claim | Verdict | Fix |
|---|---|---|---|
| places.spa | "about 2,500 km across, **almost as wide as the USA**" | **WRONG** | The contiguous USA is about 4,500 km wide. Say "**more than half as wide as the USA**" or "about as far as New York to Denver" (about 2,600 km). |
| places/facts.aristarchus | Name "Aristarchus Plateau", 200 km, fact "brightest crater on the side we can see" | IMPRECISE | The brightest feature is the **crater** Aristarchus (about 40 km), on the plateau. `facts.json` gets this right; fix the `places.json` fact. |
| places.orientale | "Mare Orientale … 930 km bullseye" | IMPRECISE | 930 km is the **Orientale basin** (outer ring). Mare Orientale (the dark centre) is only about 300 km. Rename "Orientale Basin". |
| places/facts.integrity, carroll | Crew-proposed names, estimated positions | OK | Still **pending at the IAU** (no approval found). Keep "proposed". Optionally add "waiting for official approval". |
| places.carroll | "in memory of someone from their astronaut family" | OK | NASA: named for Carroll Wiseman, Reid Wiseman's late wife. The current gentle wording is fine for kids. |
| places/facts.shackleton | "Artemis astronauts plan to land in this region" | OK | Region = south pole. Remove the "artemis iii" alias mapping to "land next" (#1). |
| places.reiner | "Scientists think a magnetic field keeps it from darkening" | OK | Leading hypothesis; "think" is right. |
| facts.tycho / copernicus / imbrium / crisium / tranquillitatis | sizes, ages, missions | OK | Spot-checked; consistent with IAU / NSSDCA. |
| facts.orientale "formed about 3.8 billion years ago" | | OK | |
| facts LM / LRV / LRRR / ALSEP / S-IVB / Ranger / Surveyor / GRAIL / LADEE / Luna 2 / Lunokhod / Chang'e 3 / Yutu | Apollo sample masses, EVA times, rover distances, impact speeds | OK (spot-checked) | Source NSSDCA. "Surveyor 1 … one of America's first safe Moon landings" is more precisely "**America's first** soft landing" (Luna 9 was first overall). |
| facts/artifacts lcross_centaur | 2000 kg, 350 t, 20 m | IMPRECISE | #9 |
| glossary | All 25 terms | OK | "far side: always faces away from Earth" is fine. |

### Cabin and mission UI (`cabin.js`, `cockpit.js`, `ui.js`, `index.html`)

| Item | Claim / depiction | Verdict | Fix |
|---|---|---|---|
| Cabin concept | A **surface outpost** cabin with 3 "glass display units" (DU1–3) and softkeys | OK as fiction | It echoes Orion (3 DUs with edge keys) but is not Orion. Don't label it "Orion". If the 3D cabin claims to be Orion, follow Ref §1 exactly: 3 DUs, **edge keys + twizzle knob (no touch)**, 7 SIPs, RHC right hand, THC, CCDs on the **left** armrests, 4 seats, 4 cone windows plus hatch windows. |
| MASTER ALARM pushbutton, C&W lamp matrix, guarded levers | Hab hardware | OK as fiction / UNVERIFIABLE for Orion | No public NASA spec for a physical Orion master-alarm panel. Fine for the outpost; don't call it Orion's. |
| "Shield power %", "Blocks radiation" | Powered radiation shields | Invented hardware | #8 |
| Window "SUN −0.9°" while the Sun is "up" | Readout shows a negative elevation while the outpost counts as sunlit | IMPRECISE (confusing) | Show elevation relative to the **local horizon** (sun − horizon_deg), or show "Sun just above the ridge line". |
| `ui.js:20` Surveyor 3 camera "after 2½ years" | | OK | April 1967 to November 1969. |
| `ui.js:22` Apollo 15 rover "27.8 km … within 5 km" | | OK | NSSDCA (5.0 km max). |
| `ui.js:17` Cabeus target (−84.68, −48.7) | LCROSS impact point | OK | |
| Storm banner "SOURCE NASA" | DONKI is NASA CCMC | OK | |
| `index.html:144,168` | Artemis III framing | **WRONG** | #1 |
| `index.html:168` "Every fact shows its NASA source" | | IMPRECISE | #10: "Every fact shows its source". |
| `index.html` data table: "LRO LOLA: how much sunlight each site gets" | Sites actually cite Bussey (Kaguya), Mazarico (LOLA) | IMPRECISE | "LRO LOLA and Kaguya illumination studies". |
| `index.html:195` NASA media disclaimer | | OK | Keep. Make sure no NASA insignia or logotype appears anywhere (none found). |

---

## NASA endorsement, invented hardware, dates: checklist

- **Endorsement:** "not endorsed by NASA" appears in `story.js` CREDIT, the terrain credit and the About footer. **No NASA insignia found.** "CAPCOM"/"Houston" role-play is fine; add a one-line "played by the game" note.
- **Invented hardware shown as real:**
  - powered radiation shields (#8)
  - greenhouse
  - cable power from the rim to the floor
  - the rim relay
  - the hab C&W panel

  The cable and relay are labelled in data, but **none are labelled in the kid-facing UI**. Add a small "pretend tech" tag.
- **Dates:**
  - Artemis I 2022: OK.
  - Artemis II April 1–10, 2026: OK everywhere it appears.
  - **Artemis III: wrong framing (#1).**
  - No copy should give an Artemis IV date without "planned".
- **Oversimplifications that could mislead a kid:**
  - #2 (sun %: 86 vs 100)
  - #3 (Earth's magnetic storms ≠ Moon radiation)
  - #7 ("the plan")
  - SPA "as wide as the USA"
  - a negative Sun elevation shown while it's "day"
