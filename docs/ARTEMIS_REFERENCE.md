# Artemis reference for Outpost Luna

The sourced fact base for designers, the learning designer (`feat/learning-v3`) and engineers. **Build from this file, not from memory.**
The app audit against this file is in `docs/ACCURACY_AUDIT.md`.

- **Compiled:** 2026-11-13. Every row says when its source was accessed.
- **Confidence column:**
  - **H** means read on a primary page.
  - **M** means primary or peer-reviewed but read only through a search summary or abstract, or two good sources disagree slightly.
  - **L** means secondary source only, or not confirmed. Do not show **L** rows to kids as fact.
- **Access:** "F" = fetched and read this session; "S" = seen in search-result summaries of the cited page (not opened in full). Re-verify any S row before quoting a precise number on screen.
- **Licence of NASA media:** NASA images, audio and video are generally not copyrighted in the US and may be used for education. You must not use the NASA insignia ("meatball"), logotype or seal, and must not imply NASA endorsement. Some images on nasa.gov are third-party; check the credit line. Guidelines: https://www.nasa.gov/nasa-brand-center/images-and-media/ (accessed 2026-11-13, S).

> **Headline change since the app's copy was written.**
> On **2026-02-27** NASA redefined **Artemis III** as a **crewed test flight in low Earth orbit in 2027**. It will test docking with the SpaceX and Blue Origin landers and **will not land**. The **first planned Artemis landing near the lunar south pole is now Artemis IV, NASA target early 2028.**
> Any copy saying "Artemis III, the first landing near the south pole" is now wrong. See section 3.

---

## 1. Orion crew module cockpit

Primary sources:
- NASA Orion Reference Guide pages on nasa.gov: "Crew Systems", "Crew Module" and "Avionics and Software". These are the web edition of the Orion Reference Guide and were last updated 2026-09-08.
- NASA "How to Fly NASA's Orion Spacecraft" (2025-01-28).

The PDF Orion Reference Guide was not retrievable (only a third-party copy exists). The nasa.gov reference pages are its web edition.

### 1.1 Displays and crew interaction

| Item | Value | Source | URL | Accessed | Conf. |
|---|---|---|---|---|---|
| Display units (DUs) | **3** | NASA Orion "Crew Systems" | https://www.nasa.gov/reference/crew-systems/ | 2026-11-13 F | H |
| DU placement | DU1 (left) is at the commander's eye level. DU2 (middle) is shared. DU3 (right) is in front of the pilot. | NASA "Crew Systems" | same | 2026-11-13 F | H |
| DU size | 14.1 in diagonal LCD with programmable bezel keys. This is Honeywell's "space-rated display unit", and Honeywell says it supplies "the DU for the Orion Space Capsule". NASA does not state the size. | Honeywell product page (vendor) | https://aerospace.honeywell.com/us/en/products-and-services/product/hardware-and-systems/space/space-rated-display-unit | 2026-11-13 S | M |
| What the DUs show | They are the primary crew interface. The crew gets vehicle status, commands new operations, edits data and works through electronic procedures. The procedures link to caution and warning: they flag faults and let the crew call up urgent actions. | NASA "Crew Systems"; NASA "Avionics & Software" (a display control module sits in each vehicle management computer) | https://www.nasa.gov/reference/crew-systems/ · https://www.nasa.gov/reference/avionics-and-software/ | 2026-11-13 F | H |
| Number of display formats | "60+ display formats" appears in one NASA page excerpt, but that page could not be opened (404). | NASA (unverified) | — | 2026-11-13 S | L |
| Edge keys / softkeys | Each DU frame has **edge keys** (bezel keys) **and a "twizzle" rotary knob**. Interaction is through physical keys, **not a touchscreen**. | NASA "Crew Systems" | https://www.nasa.gov/reference/crew-systems/ | 2026-11-13 F | H |
| Cursor control devices (CCDs) | **2**, on the **left side of the commander's and pilot's seats**. They let the crew drive the displays when launch or entry g-forces stop them reaching the screens. | NASA "Crew Systems"; NASA "How to Fly Orion" | https://www.nasa.gov/reference/crew-systems/ · https://www.nasa.gov/missions/artemis/orion/how-to-fly-nasas-orion-spacecraft/ | 2026-11-13 F | H |
| Switch interface panels (SIPs) | **7** panels of switches, toggles and dials next to the displays. They give a **backup way to fly** if a display or hand controller fails. | NASA "Crew Systems"; "How to Fly Orion" | same | 2026-11-13 F | H |
| Physical switch count, Orion | About **60** physical switches. This comes from astronaut Lee Morin, who worked on the design, in a NASA video quoted in 2014. Design News quoted NASA saying 56 of about 2,000 shuttle switches stayed physical. Military Embedded Systems says about 40. | Universe Today quoting a NASA video; Design News; Military Embedded Systems | https://www.universetoday.com/articles/orions-glass-cockpit-will-steer-astronauts-through-the-solar-system · https://www.designnews.com/aerospace/exclusive-a-closer-look-at-nasa-s-orion-glass-cockpit | 2026-11-13 F/S | M (say "about 60") |
| Switch count, Apollo CM | Main display console: **24 instruments, 566 switches, 40 event indicators, 71 lights**. This is a widely repeated tally, but no primary NASA page confirming it was found. A UPI report says "450-odd". The NASA Apollo 10 D&C pages describe a console about 7 ft long and 3 ft high. | Secondary tally; NASA ALSJ CSM D&C | https://www.nasa.gov/wp-content/uploads/static/history/alsj/CSM10_Displays_&_Controls_pp83-86.pdf | 2026-11-13 S | L–M (say "hundreds of switches") |
| Switch count, Space Shuttle | About 1,249 in the cockpit and about 2,000 for the whole vehicle (Lee Morin) | Design News / UPI | https://www.upi.com/Science_News/2014/12/02/NASA-video-shows-off-Orion-cockpit/8121417530521/ | 2026-11-13 S | M |
| Kid-safe framing | "Apollo had hundreds of switches. Orion has 3 big screens and about 60 switches." | derived | — | — | M |

### 1.2 Flight controls

| Item | Value | Source | URL | Accessed | Conf. |
|---|---|---|---|---|---|
| Rotational hand controller (RHC) | **2**, one each for the **commander and pilot**, held in the **right hand**. It controls **attitude**, meaning pitch, roll and yaw of the nose. Twisting it left turns the nose left. | NASA "Crew Systems"; "How to Fly Orion" | https://www.nasa.gov/reference/crew-systems/ · https://www.nasa.gov/missions/artemis/orion/how-to-fly-nasas-orion-spacecraft/ | 2026-11-13 F | H |
| Translational hand controller (THC) | **2**, to the right or left of the screens. They **translate** the craft: push in to go forward, pull out to go back, and move up, down, left or right. | same | same | 2026-11-13 F | H |
| What fires | The flight software (built by Lockheed Martin) fires some of the **24 reaction control system thrusters** on the ESA-built European Service Module. | "How to Fly Orion" | same | 2026-11-13 F | H |
| First manual flying | Artemis II, about **3 h** after launch. In the proximity-operations demonstration, Wiseman and Glover flew Orion toward and away from the spent ICPS upper stage. | "How to Fly Orion" | same | 2026-11-13 F | H |
| Flight computers | 2 vehicle management computers × 2 flight computer modules = **4 FCMs**. If one disagrees, it "fails silent", resets and rejoins within **22 s**. | NASA "Avionics & Software" | https://www.nasa.gov/reference/avionics-and-software/ | 2026-11-13 F | H |

### 1.3 Seats, cabin, windows, hatches

| Item | Value | Source | URL | Accessed | Conf. |
|---|---|---|---|---|---|
| Seats | **4**. As seen from the side hatch, the **commander and pilot are on the left** and the **mission specialists on the right**. | NASA "Crew Systems" | https://www.nasa.gov/reference/crew-systems/ | 2026-11-13 F | H |
| Posture | On their backs for launch and entry, with knees bent 90° and feet on foot pans (the pilot's and commander's pans are removable in orbit) | same | same | F | H |
| Seat fit and safety | Fits people from 4 ft 10 in / 94 lb to 6 ft 5 in / 243 lb. 5-point harness. Each seat strokes **6 in** to absorb landing impact (landing only). | same | same | F | H |
| Artemis II seating | Wiseman (CDR) and Glover (PLT) sat at the controls. Koch and Hansen (MS) were on the right. | NASA crew roles (section 2) | — | — | H |
| Habitable volume | **330 ft³** (about 9.3 m³), "about two minivans". Supports 4 crew for up to 21 days undocked. | NASA "Crew Module" | https://www.nasa.gov/reference/crew-module/ | 2026-11-13 F | H |
| Windows | **4 windows in the crew-module cone, each with 3 panes** (the innermost is acrylic). The **side hatch** and **docking hatch** each have a window, and so does the launch-abort-system hatch. | NASA "Orion Windows Provide New Outlook…" (2015); NASA "Crew Module" | https://www.nasa.gov/missions/artemis/orion/orion-windows-provide-new-outlook-for-spacecrafts-future/ · https://www.nasa.gov/reference/crew-module/ | 2026-11-13 F | H (count of 4) |
| Window roles | 2 forward-facing (docking) windows and 2 side "horizon" windows | Spaceflight101 (secondary) | https://spaceflight101.com/spacecraft/?p=760 | 2026-11-13 S | L |
| Hatches | 3: side hatch (the main way in and out), docking hatch (through the nose tunnel) and LAS hatch | NASA "Crew Module" | same | F | H |
| Heat shield | 16.5 ft across, 186 Avcoat blocks, sees about 5,000 °F at entry | NASA "Crew Module" | same | F | H |
| Parachutes | 11 in all. The 3 mains are 116 ft across. They slow the capsule from about 325 mph to 20 mph or less. | NASA "Crew Module" | same | F | H |
| Sleep | 4 sleeping bags hung like hammocks. On Artemis II all 4 crew slept 8 h at the same time. | NASA "Crew Systems" | https://www.nasa.gov/reference/crew-systems/ | F | H |
| Exercise | A flywheel rowing-type device about the size of an extra-large shoebox. Loads up to 400–500 lb. About 30 min a day on Artemis II. | same | same | F | H |
| Toilet (UWMS) | About 5 ft³, 60% smaller than the shuttle toilet. Urine is vented overboard daily. | same | same | F | H |

### 1.4 Storm shelter, caution and warning, comms, lighting

| Item | Value | Source | URL | Accessed | Conf. |
|---|---|---|---|---|---|
| **Storm shelter (real procedure)** | The HERA radiation sensor warns the crew, who have **up to 1 h** to get ready. They shelter in the **two large stowage bays under the central seats, two astronauts per bay**, with **stowage bags repositioned as a barrier**. They can stay **up to 24 h** with food, water, medical kit, air lines and computers. | NASA "Crew Systems" | https://www.nasa.gov/reference/crew-systems/ | 2026-11-13 F | H |
| Radiation instruments | HERA (Hybrid Electronic Radiation Assessor), plus **5 ESA active dosimeters** around the cabin. Crew also carried Crew Active Dosimeters (Mirion). | NASA "Crew Systems"; Mirion | same · https://www.mirion.com/discover/knowledge-hub/articles/stories/from-ram-to-cad-the-evolution-of-astronaut-radiation-monitoring-through-artemis-ii | F / S | H / M |
| Caution and warning | Shown on the DUs and tied to electronic procedures that flag faults and give urgent actions. **No public NASA description of a separate MASTER ALARM lamp panel was found.** | NASA "Crew Systems" | same | F | H (DU-based C&W); unknown for a physical panel |
| Comms (vehicle) | 4 phased-array antennas on the crew module and 2 on the service module. The crew module must be upright after splashdown for its comms to work. Audio panel layout is **not public**. | NASA "Avionics & Software", "Crew Module" | https://www.nasa.gov/reference/avionics-and-software/ | F | H / unknown |
| Cabin lighting | **Not found in public NASA sources.** Treat any lighting design as notional. | — | — | — | — |

### 1.5 Public NASA images to reference

These are NASA media under NASA's media guidelines: describe them or link to them, and credit "NASA". Check each image's credit line before reusing it.

| Image | ID / page | What it shows | Accessed |
|---|---|---|---|
| Earthset from Artemis II, 2026-04-06 17:41 CDT | art002e009287, on https://www.nasa.gov/centers-and-facilities/johnson/artemis-ii-mission-milestones-an-image-and-video-recap/ | Earth setting behind the lunar limb | 2026-11-13 F |
| Moon during the solar eclipse seen from Orion, 2026-04-06 | art002e009571 (same page) | The Moon backlit by the Sun | F |
| Crew using eclipse viewers inside Orion | art002e009302 (same page) | **Interior of the cabin with crew**: good cockpit reference | F |
| Earth after TLI, 2026-04-02 | art002e000192 (same page) | Earth from a window | F |
| Solar-array camera inspection, 2026-04-07 | art002e012476 (same page) | ESM array | F |
| Orion suited-crew testing in the cockpit mockup | https://www.nasa.gov/image-article/orion-suited-crew-testing-2 | Suited crew in seats, using the CCD and hand controllers | 2026-11-13 S |
| Artemis II splashdown and recovery gallery | https://www.nasa.gov/gallery/artemis-ii-splashdown-and-recovery/ | Recovery | S |

---

## 2. Artemis II (flew 2026-04-01 to 2026-04-10)

| Item | Value | Source | URL | Accessed | Conf. |
|---|---|---|---|---|---|
| Crew and roles | **Reid Wiseman** (NASA), commander. **Victor Glover** (NASA), pilot. **Christina Koch** (NASA), mission specialist. **Jeremy Hansen** (CSA), mission specialist. | NASA splashdown gallery captions | https://www.nasa.gov/gallery/artemis-ii-splashdown-and-recovery/ | 2026-11-13 S | H |
| Spacecraft name | Orion "Integrity" | NASA record release (crater-name story) | https://www.nasa.gov/news-release/nasas-artemis-ii-crew-eclipses-record-for-farthest-human-spaceflight/ | F | H |
| Launch | **2026-04-01, 6:35 p.m. EDT** (22:35 UTC), LC-39B, Kennedy Space Center, on SLS Block 1 | NASA milestones recap (date); launch time from news reports of the NASA broadcast | https://www.nasa.gov/centers-and-facilities/johnson/artemis-ii-mission-milestones-an-image-and-video-recap/ · https://www.nasa.gov/blogs/missions/2026/04/01/live-artemis-ii-launch-day-updates | F (date) / S (time) | H date / M time |
| Prox-ops demo | About 3 h after launch: manual flying near the ICPS | "How to Fly Orion" | https://www.nasa.gov/missions/artemis/orion/how-to-fly-nasas-orion-spacecraft/ | F | H |
| Trans-lunar injection | 2026-04-02 | NASA milestones (image art002e000192) | as above | F | H |
| Trajectory | A **free-return** lunar flyby. Orion passes behind the far side and gravity bends it home with no lunar-orbit insertion. | NASA trajectory visualization; NASA Artemis II press kit | https://svs.gsfc.nasa.gov/5632 · https://www.nasa.gov/artemis-ii-press-kit/ | S | H |
| Record broken | Passed Apollo 13's **248,655 mi** record at **12:56 p.m. CDT, 2026-04-06** (flight day 6) | NASA release | https://www.nasa.gov/news-release/nasas-artemis-ii-crew-eclipses-record-for-farthest-human-spaceflight/ | F | H |
| Farthest from Earth | **252,756 mi (about 406,771 km)**. Pre-flight prediction was 252,760 mi. | NASA release / post-flight NASA | same | F | H |
| Closest approach to the Moon | **4,067 mi (about 6,545 km) above the surface**. Pre-flight figure was 4,070 mi. | same | same | F | H |
| Total distance | 694,481 mi (post-flight). Pre-flight was 695,081 mi. | NASA post-flight (search summary) | https://www.nasa.gov/missions/nasa-answers-your-most-pressing-artemis-ii-questions/ | S | M |
| **Comm blackout behind the Moon** | About **40 minutes** with no signal while the Moon blocked Earth | NASA release | https://www.nasa.gov/news-release/nasas-artemis-ii-crew-eclipses-record-for-farthest-human-spaceflight/ | F | H |
| Earthset / Earthrise | Earthset photographed at 17:41 CDT on 2026-04-06. Earthrise followed as Orion came out from behind the Moon. | NASA milestones | as above | F | H |
| Solar eclipse | On 2026-04-06 the crew saw the Moon pass in front of the Sun and used eclipse viewers | NASA milestones / release | as above | F | H |
| Crater names | The crew **proposed** "**Integrity**" (after the spacecraft) and "**Carroll**" (after Reid Wiseman's late wife, Carroll). Both were **submitted to the IAU**. **No IAU approval was found as of 2026-11-13.** | NASA release; AP coverage | same; https://wtop.com/national/2026/04/artemis-ii-astronauts-follow-apollo-tradition-of-naming-lunar-features-after-loved-ones/ | F / S | H (proposed) / M (status) |
| Re-entry | About 24,660 mph at entry interface | AP coverage | https://www.ksl.com/article/51481765/artemis-ii-returns-from-moon-with-splashdown-to-close-out-record-breaking-lunar-voyage | S | M |
| Splashdown | **2026-04-10, 8:07 p.m. EDT (5:07 p.m. PDT)**, Pacific Ocean off San Diego. Recovered by USS John P. Murtha. | NASA FD10 blog / gallery | https://www.nasa.gov/blogs/missions/2026/04/10/artemis-ii-flight-day-10-re-entry-live-updates/ | S | H |
| Mission length | About 9 days 1.5 h (launch to splashdown). NASA calls it "about 10 days" and counts 10 flight days. | derived | — | — | H |
| **Radiation results** | **No crew dose numbers published as of 2026-11-13.** Data were collected for a month after flight and will be archived in NASA's Life Sciences Data Archive. Onboard: HERA units, crew active dosimeters, 5 ESA dosimeters, the DLR M-42 EXT. | Fierce Sensors; NASA "Crew Systems" | https://www.fiercesensors.com/sensors/artemis-crew-back-home-nasa-studies-radiation-future-flights | S | M |
| Storm-shelter training | The Artemis II crew was trained to rebuild the cabin into a shelter. SRAG advises Mission Control. | Space.com | https://www.space.com/space-exploration/artemis/how-the-artemis-2-astronauts-could-weather-a-solar-storm-during-their-moon-mission | S | M |

### 2.1 Artemis II moments ↔ our clips (`backend/data/clips_manifest.json`)

All clips are NASA Artemis audio on nasa.gov. Times are from the NASA pages cited above.

| Moment (date, 2026) | Clip ids |
|---|---|
| Launch go/no-go poll and liftoff (04-01) | `go-no-go`, `liftoff`, `full-send` |
| First voice contact | `loud-and-clear` |
| Burns, TLI (04-02) | `good-burn`, `tli` |
| Apollo 13 record broken (04-06 12:56 CDT) | `apollo13-record` |
| Far-side flyby observations (04-06): Orientale, Hertzsprung, Vavilov, Ohm, Glushko, Aristarchus, Reiner Gamma, terminator, limb | `aristarchus`, `mare`, `orientale*`, `hertz`, `hertzsprung-basin-inner-ring`, `vavilov-*`, `ohm-*`, `glushko-*`, `reiner-gamma-swirl-shape`, `search-swirls-reiner-gamma`, `features-along-terminator`, `terminator-craters-elevation`, `ruminations-terminator`, `limb-imaging-craters-ridges`, `lunar-limb-mountains-mare`, `surveying-moons-far-side`, `far-side-albedo-mare`, `crew-choice-*`, `comparing-*`, `color-*`, `texture-albedo-across-mare`, `whole-moon-imaging-orientale`, `lunar-mosaic-imaging-multi`, `using-geology-terms-describe` |
| Earthset (04-06 17:41 CDT) | `earthset-limb-observations-moons`, `observing-earthset`, `earth-light-mirror-moon` |
| Loss of signal (about 40 min) then **Earthrise** on reacquisition | `earthrise`, `crew-reacts-joyfully-earth`, `watching-earthrise`, `earth-limb-hertzsprung-observation` |
| Solar eclipse from the Moon (04-06) | `solar-eclipse-beginning-observing`, `solar-eclipse-end-observing`, `moon-during-eclipse-rare`, `observing-pulsating-streamers-suns`, `impact-flashes-observing-moons`, `searching-impact-flashes-lofted`, `stars-depth-brightness-perception` |
| Crater naming: Integrity, Carroll | `naming` |
| Splashdown (04-10) | `splashdown` |
| Messages from Apollo astronauts | `lovell` (Apollo 8, Apollo 13), `duke` (Apollo 16) |
| Crew portraits (pre-flight) | `wiseman`, `glover`, `koch`, `hansen` |

---

## 3. Artemis III / IV: status as of 2026-11-13

| Item | Value | Source | URL | Accessed | Conf. |
|---|---|---|---|---|---|
| **Artemis III redefined** | On **2026-02-27** NASA moved Artemis III to **2027** and made it a **crewed test flight in low Earth orbit** to test rendezvous and docking with one or both commercial landers, plus life support, comms, propulsion and xEVA suits. **It does not land on the Moon.** | NASA release 26-022 | https://www.nasa.gov/news-release/nasa-adds-mission-to-artemis-lunar-program-updates-architecture/ | 2026-11-13 F | H |
| Artemis III crew (named Nov 2026) | Randy Bresnik (NASA), CDR. Luca Parmitano (ESA), PLT. Andre Douglas (NASA), MS. Frank Rubio (NASA), MS. Backup: Bob Hines. The flight lasts about 2 weeks. Orion docks with Blue Origin's lander pathfinder (about 2 days) and then SpaceX's Starship pathfinder (about 1 day). | NASA release | https://www.nasa.gov/news-release/nasa-marches-toward-artemis-iii-mission-in-2027-names-crew-members/ | 2026-11-13 F | H |
| **First planned landing** | **Artemis IV, NASA target early 2028**, described as "the first planned crewed mission to the lunar South Pole". Artemis V is a second landing attempt later in 2028. After that NASA plans "at least one surface landing every year". | NASA Artemis IV page (updated 2026-03-16); NASA releases | https://www.nasa.gov/mission/artemis-iv/ | 2026-11-13 F | H (target dates may slip) |
| Surface time (Artemis IV) | **2 of the 4 crew** land and spend **"approximately a week"** near the south pole, with "several" moonwalks. Two stay in Orion in lunar orbit. | NASA Artemis IV page | same | F | H |
| EVA budget | No more than about 32 h of total EVA time (Planetary Society). Not confirmed on a NASA page. | Planetary Society | https://www.planetary.org/articles/what-could-the-artemis-iv-astronauts-discover-on-the-moon | S | L |
| HLS | **SpaceX Starship HLS** and **Blue Origin Blue Moon (crewed version)**. NASA will choose which lander flies Artemis IV after the Artemis III tests. Landing accuracy for Starship was quoted as within a 100 m radius (2024). | NASA releases (2026-11; 2024-10) | as above; https://www.nasa.gov/news-release/nasa-provides-update-on-artemis-iii-moon-landing-regions/ | F | H |
| **Candidate landing regions (latest NASA list)** | **9 regions, 2024-10-28** (no priority order): **Peak near Cabeus B, Haworth, Malapert Massif, Mons Mouton Plateau, Mons Mouton, Nobile Rim 1, Nobile Rim 2, de Gerlache Rim 2, Slater Plain**. They were chosen for science, launch-window availability, terrain, **Earth communication** and **lighting**. Specific sites come after launch dates are set. **No newer NASA list was found.** It was issued for "Artemis III" and NASA has not re-issued it for Artemis IV. | NASA release 24-136 | https://www.nasa.gov/news-release/nasa-provides-update-on-artemis-iii-moon-landing-regions/ | 2026-11-13 F | H |
| Earlier list (superseded) | **13 regions, 2022-08-19**: Faustini Rim A, Peak near Shackleton, Connecting Ridge, Connecting Ridge Extension, de Gerlache Rim 1, de Gerlache Rim 2, de Gerlache-Kocher Massif, Haworth, Malapert Massif, Leibnitz Beta Plateau, Nobile Rim 1, Nobile Rim 2, Amundsen Rim. **Peak near Shackleton and Connecting Ridge were dropped in 2024.** | NASA release (2022) | https://www.nasa.gov/news-release/nasa-identifies-candidate-regions-for-landing-next-americans-on-moon/ | M (list from memory of the release; re-check) | M |
| Gateway | On **2026-03-24** ("Ignition") NASA said it intends to **pause Gateway in its current form** and redirect effort to surface infrastructure, the **"Moon Base"**. | NASA Ignition / Moon Base pages | https://www.nasa.gov/reference/moonbase-about/ · https://www.nasa.gov/gallery/ignition-nasas-plan-for-the-moon/ | S | M |
| Why the south pole | **Permanently shadowed regions (PSRs)** are cold traps that can hold **water ice**, a resource for water, oxygen and propellant. Nearby rims and peaks get **long periods of sunlight** for power and warmth. There is science value in old, undisturbed terrain and in volatiles. | NASA 2024 release; Ice-confirmed release | https://www.nasa.gov/news-release/nasa-provides-update-on-artemis-iii-moon-landing-regions/ | F | H |

**Name note for designers:** NASA's surface programme is now literally called **"Moon Base"** (2026). "Outpost Luna" is fine as a fictional name. Do not call it NASA's base.

---

## 4. Lunar south pole environment

### 4.1 Illumination: what "sun %" means

There are **two different quantities**. Always label which one you show.

1. **Long-term average illumination fraction.** This is the % of time the Sun (usually its centre, or some part of the disc) is above the *local topographic horizon*. It is averaged over a year or over the 18.6-year nutation cycle and computed from LOLA or Kaguya terrain, usually at a stated height above the ground (0 m, 2 m or 10 m). **This is what the papers publish.**
2. **Window fraction.** This is the % of a specific short window (for example our 10 days in April 2026) that a site is sunlit. It can be 0% or 100% at the same site, depending on season and libration.

| Site (app id) | Published long-term illumination | Source | URL | Accessed | Conf. |
|---|---|---|---|---|---|
| Shackleton rim (`shackleton_rim`) | **85.5%** at a rim location. Kaguya-based results for the most-illuminated region near the pole are 86% (high-res) and 89% (low-res). | Gläser et al. 2018, *Planet. Space Sci.* (via summary); Bussey et al. 2010 *Icarus* 208:558; Quick et al. AGU 2010 | https://doi.org/10.1016/j.pss.2017.07.006 · https://ui.adsabs.harvard.edu/abs/2010Icar..208..558B · https://ui.adsabs.harvard.edu/abs/2010AGUFM.P51C1447Q | 2026-11-13 S | M (say "about 86%, averaged over a year") |
| Connecting Ridge (`connecting_ridge`) | Best spots: **92.3% at 2 m and 95.7% at 10 m** above ground. Longest darkness is typically only 3–5 days. Gläser 2018 gives a ridge location at 92.1%. Two ridge points 8 km apart are lit together about 94% of the time (Speyerer 2013). | Gläser et al. 2014, *Icarus* 243:78 | https://ui.adsabs.harvard.edu/abs/2014Icar..243...78G | S | M |
| de Gerlache rim (`de_gerlache_rim`) | High-illumination rim. A single published % for our coordinates was not found. Barker et al. 2023 (LOLA) has site-level maps ("Site 11"). | NASA PGDA product 78 | https://pgda.gsfc.nasa.gov/products/78 | S | L for any exact % |
| Malapert Massif (`malapert_massif`) | About **74%** (two points, for the lunar year 2020, Kaguya-based) | Bussey et al. 2010 via a secondary table; NASA LRO page says only "high illumination" | https://ui.adsabs.harvard.edu/abs/2010Icar..208..558B | S | L–M |
| Shackleton floor (`shackleton_floor`) | **0%** (permanently shadowed; some secondary light from the walls) | Mazarico et al. 2011, *Icarus* 211:1066 (LOLA, 18.6-yr, hourly) | https://doi.org/10.1016/j.icarus.2010.10.030 | S | H |
| Sun elevation at the pole | It never climbs more than about **1.5°** above the ideal horizon (the Moon's spin axis is tilted 1.54° to the ecliptic) | standard geometry; JPL Horizons | https://ssd-api.jpl.nasa.gov/doc/horizons.html | — | H |
| Datasets to cite | NASA PGDA "Lunar Polar Illumination" (Mazarico); LROC WAC time-weighted south pole illumination map | NASA GSFC PGDA; LROC | https://pgda.gsfc.nasa.gov/products/69 · https://data.lroc.im-ldi.com/lroc/view_rdr/WAC_POLE_ILL_TWI_SOUTH | S | H |

**Recommended labels:**
- **Site picker:** "☀ About 86% sunlight (yearly average)".
- **Debrief:** "During your 10 days (April 2026) the Sun was up X% of the time *in our model*."

Never put the two numbers next to each other unlabelled.

### 4.2 Earth visibility, temperature, ice

| Item | Value | Source | URL | Accessed | Conf. |
|---|---|---|---|---|---|
| Earth visibility at the pole | Earth hangs near the horizon and bobs above and below it over a roughly monthly libration cycle, so direct-to-Earth contact comes and goes. Sites on the Earth-facing side and on high ground (for example Malapert) see Earth far more often. Without relays, landing options at the pole are "significantly limited". | NASA LCRNS award context; NASA 2024 criteria | https://www.nasa.gov/news-release/nasa-selects-lunar-relay-contractor-for-near-space-network-services | S | H (qualitative) |
| PSR temperatures | Diviner measured PSR floors as cold as about **35–40 K (about −238 to −233 °C)**. The average for the Cabeus impact site is about 37–38 K. Haworth's maximum temperature never exceeds about 40 K. | Paige et al. 2010, *Science* 330:479 | https://doi.org/10.1126/science.1187726 | S | H |
| Kid framing | "The darkest crater floors get colder than −230 °C, about as cold as Pluto's surface." "Colder than −170 °C" is true but undersells it. | derived (Pluto's surface is about 40 K) | — | — | M |
| LCROSS (2009-10-09) | The Centaur stage, about **2,300 kg** (2,305 kg nominal), hit Cabeus. The debris plume held about **155 kg of water vapour and ice**, about **5.6 ± 2.9% water by mass** in the regolith. The crater was about 25–30 m wide. About 4,000–6,000 kg of debris rose into sunlight. The "350 t" figure was a **pre-impact prediction**. | Colaprete et al. 2010, *Science* 330:463; NASA NTRS 20100026403 | https://doi.org/10.1126/science.1186986 · https://ntrs.nasa.gov/citations/20100026403 | S | H (water %) / M (ejecta) |
| Chandrayaan-1 M3 (2018) | First direct spectral detection of **surface water ice**, in PSRs at both poles. The south-pole ice is clustered in craters. | Li et al. 2018, *PNAS*; NASA release | https://www.nasa.gov/news-release/ice-confirmed-at-the-moons-poles/ | S | H |
| LRO LAMP | Far-UV signs of frost in PSRs (Gladstone et al. 2012; Hayne et al. 2015) | JGR / Icarus | https://doi.org/10.1029/2011JE003913 | S | M |
| LRO Diviner | Temperatures cold enough to trap ice (Paige 2010, above) | — | — | — | H |
| Shackleton crater | About **21 km** diameter (IAU). About **4.2 km** deep (LOLA, Zuber et al. 2012). The south pole sits almost on its rim. | IAU Gazetteer; Zuber 2012 *Nature* 486:378 | https://planetarynames.wr.usgs.gov/Feature/5450 | S | H |

---

## 5. Radiation

| Item | Value | Source | URL | Accessed | Conf. |
|---|---|---|---|---|---|
| Lunar surface dose, quiet Sun | Chang'e 4 LND (Jan–Feb 2019, solar minimum): **13.2 ± 1 µGy/h absorbed (Si)**. Dose equivalent **1,369 µSv/day ≈ 57 µSv/h ≈ 1.4 mSv/day**. ⟨Q⟩ = 4.3. **No SPE** occurred during the measurements. | Zhang et al. 2020, *Sci. Adv.* 6:eaaz1334 | https://pmc.ncbi.nlm.nih.gov/articles/PMC7518862/ | 2026-11-13 F | H |
| ISS comparison | The ISS dose equivalent over the same period was **731 µSv/day total**, of which **523 µSv/day is GCR-only** (the other ~208 comes from the South Atlantic Anomaly). The paper's "**about 2.6×**" compares the Moon with the **GCR-only** 523. Against the ISS total the ratio is about 1.9×. | same | same | F | H |
| Artemis I MARE (Helga and Zohar phantoms, 2022) | A **4× difference** in dose rate between the most and least shielded spots in Orion. Peak during the Van Allen belt pass for a 1989-type reference event: 414 µGy/min in the crew area vs **95 µGy/min in the storm shelter**. Using the shelter, a large SPE can be held to **≤ 150 mSv**. A **90° attitude change** during the belt pass cut the dose about **50%**. Interplanetary GCR dose-equivalent rates were up to 60% lower than earlier observations. **Results of the AstroRad vest (worn by Zohar) were not yet published.** | George et al. 2024, *Nature* (lead author S. P. George); DLR release 2024-09-18 | https://www.osti.gov/pages/servlets/purl/2447574 · https://www.dlr.de/en/latest/news/2024/orion-spacecraft-radiation-protection-tested-initial-findings-from-artemis-i-moon-mission | F (DLR) / S (paper) | H |
| Orion shelter procedure | See 1.4: build from stowage under the central seats, 1 h warning, up to 24 h | NASA "Crew Systems" | https://www.nasa.gov/reference/crew-systems/ | F | H |
| Surface shelter | No current NASA Artemis surface shelter design was found. Regolith-shielding studies exist (NTRS 19890004839, 20110012713). **Call it an idea studied by NASA, not "the plan".** | NTRS | https://ntrs.nasa.gov/citations/19890004839 | S | M |
| SPE dose ranges | Behind thin shielding an SPE can raise dose **by orders of magnitude** (Zhang 2020). Historic big events (Aug 1972, Oct 1989) could have given **hundreds of mSv to over 1 Sv** to a lightly shielded crew. Orion's shelter targets ≤ 150 mSv. **Specific historic numbers vary by model and shielding: show a range, not one number.** | Zhang 2020; DLR 2024 | above | F | M |
| Limits | NASA career limit **600 mSv** effective dose (NASA-STD-3001, 2022 update) | NTRS 20230012405 | https://ntrs.nasa.gov/citations/20230012405 | S | H |
| Everyday comparisons | Chest X-ray about **0.1 mSv**, so 1 mSv ≈ 10 chest X-rays. US average background is about 6 mSv a year in total, about 3 mSv of it natural. | NASA "Why Space Radiation Matters" | https://www.nasa.gov/missions/analog-field-testing/why-space-radiation-matters/ | S | M |
| Units for kids | Show **mSv** (millisievert), the dose that counts for the body. Use **mSv per day** for steady GCR (Moon ≈ 1.4 mSv/day) and **mSv per hour** only during storms. Do not mix µGy and mSv on one screen. | — | — | — | — |
| Kid-friendly framings (true) | "One day on the Moon's surface is like about 14 chest X-rays." "The Moon has no magnetic bubble and no thick air, so solar particles hit the surface." "Hiding behind lots of stuff (water, food bags, Moon soil) is the best shield." | derived from rows above | — | — | H |

---

## 6. Space weather

| Item | Value | Source | URL | Accessed | Conf. |
|---|---|---|---|---|---|
| DONKI | NASA CCMC's Space Weather Database Of Notifications, Knowledge, Information. Its API on api.nasa.gov has event types: **FLR** (solar flare), **SEP** (solar energetic particle event), **CME** (+ CME analysis), **GST** (geomagnetic storm), **IPS** (interplanetary shock), **MPC** (magnetopause crossing), **RBE** (radiation belt enhancement), **HSS** (high-speed stream), **WSA-Enlil** simulations, and notifications. | NASA api.nasa.gov / CCMC | https://api.nasa.gov/ · https://kauai.ccmc.gsfc.nasa.gov/DONKI/ | 2026-11-13 S | H |
| **GST ≠ radiation on the Moon** | GST, the Kp index and NOAA's **G-scale** describe **Earth's magnetic field** being shaken. The Moon has no global magnetic field. The hazard to a lunar crew is **SEP** (proton flux, NOAA's **S-scale**, measured as ≥10 MeV protons from GOES). A G5 storm can come with only a minor S-level radiation storm, and the other way round. | NOAA SWPC scales | https://www.swpc.noaa.gov/noaa-scales-explanation | S | H |
| Flare light | Reaches Earth or the Moon in about **8 min** (light speed). There is no warning: it is seen when it happens. | physics | — | — | H |
| SEP arrival | **Tens of minutes to hours** after the flare or CME onset. Example: in July 2000 (X5.7) the ≥10 MeV protons rose 32 min after flare start. | SWPC / SpaceWeatherLive example | https://www.swpc.noaa.gov/phenomena/coronal-mass-ejections | S | M |
| CME transit | Typically **1–3 days**. The fastest take **15–18 h**. | NOAA SWPC | https://www.swpc.noaa.gov/phenomena/coronal-mass-ejections | S | H |
| Arrival-forecast error | Often ± 6–7 h | CCMC CME Scoreboard | https://webtools.ccmc.gsfc.nasa.gov/CMEscoreboard/ | S | M |
| SRAG (Space Radiation Analysis Group, JSC) | Gives Mission Control radiation console support, **24 h a day** during crewed Artemis missions. It works with NOAA SWPC on SEP forecasts, monitors HERA and dosimeters, and recommends when the crew should shelter or avoid lower-shielded areas. | NTRS briefing (Whitman 2023); Scienceline; SpaceNews | https://ntrs.nasa.gov/api/citations/20230004380/downloads/BIRA2023_Whitman_v3.pdf | S | M |
| Kid framing | "When the Sun flares, the fast particles can arrive in less than an hour, so the crew has to move quickly. The slower cloud (a CME) takes a day or more." | derived | — | — | H |

---

## 7. Communications

| Item | Value | Source | URL | Accessed | Conf. |
|---|---|---|---|---|---|
| DSN | NASA Deep Space Network: 3 complexes about 120° apart, at **Goldstone (California), Madrid (Spain) and Canberra (Australia)**. Artemis II also used the Near Space Network. | NASA SCaN / JPL DSN | https://www.nasa.gov/directorates/somd/space-communications-navigation-program/ | — | H |
| Earth–Moon light time | **About 1.28 s one way** at the mean distance of 384,400 km. The range is 1.19–1.35 s (perigee to apogee). Round trip is about 2.6 s. | physics (distance ÷ c) | — | — | H |
| Earth–Mars light time | About **3–22 min one way** (some sources say 4–24), so up to about **44 min round trip** | NTRS (ASCEND paper) | https://ntrs.nasa.gov/api/citations/20220013418/downloads/ASCEND-Communication%20Delays%2C%20Disruptions%2C%20and%20Blackouts%20for%20Crewed%20Mars%20Missions.pdf | S | H |
| Behind the Moon | No direct link at all, about **40 min** on Artemis II (section 2) | NASA | above | F | H |
| Pole: Earth-visibility constraint | South-pole sites lose direct-to-Earth line of sight for days at a time over the libration cycle. Earth communication was a selection criterion in 2024. | NASA | above | F/S | H |
| Relay plans (**PLANS, not hardware**) | **LCRNS / Near Space Network lunar relay:** NASA's 2024 award to Intuitive Machines (up to $4.82 B) for a **5-satellite** relay and navigation constellation. The first satellite rides on IM-3 and two more on IM-4. Users would include HLS, the LTV and CLPS. **LunaNet** is the interoperability standard. **Gateway** was to provide relay and is now "paused" (2026-03). | NASA release (2024-09) | https://www.nasa.gov/news-release/nasa-selects-lunar-relay-contractor-for-near-space-network-services | S | M (status in late 2026 not confirmed) |

---

## 8. What is still uncertain

- Orion DU size (vendor-stated only), number of display formats, cabin lighting, audio panel layout, exact SIP positions, any physical master-alarm panel.
- Apollo CM switch count (the 566 tally is not primary-confirmed).
- Artemis II crew dose numbers (not published yet).
- Illumination % for our exact de Gerlache and Malapert coordinates. Published values are for nearby "best" points.
- IAU status of "Integrity" and "Carroll".
- Artemis IV/V dates (2028 targets) and the exact Gateway status.
