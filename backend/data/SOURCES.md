# Sources: the landing-site navigator's NASA data

Every number in `sites_physics.json` names its source (`places[].<field>.source` → `sources.<key>`), and every map layer
carries its credit line (`layers.json`). This file explains each source, what we computed from it, and its limits.
All data is fetched at **build time** by `backend/pipeline/site_physics.py` (`make site-physics`, `make site-layers`);
the app never fetches it. Not endorsed by NASA.

## Products used

| Key | Product | Where | What we take from it |
|---|---|---|---|
| `illum` | LRO LOLA **average solar illumination**, south pole, `AVGVISIB_85S_060M_201608` (60 m/px, to ~85° S) and `AVGVISIB_75S_120M_201608` (120 m/px, to 75° S). Mazarico et al. 2011 method, hourly over an 18.6-year lunar nutation cycle, "any part of the Sun's disc" counts | [PGDA product 69](https://pgda.gsfc.nasa.gov/products/69) → [PDS LOLA node, EXTRAS/ILLUMINATION](http://imbrium.mit.edu/EXTRAS/ILLUMINATION/); paper [doi:10.1016/j.icarus.2010.10.030](https://doi.org/10.1016/j.icarus.2010.10.030) | Yearly sunlight % at the outpost spot, the range around it; the Sunlight layer |
| `earth` | LRO LOLA **average Earth visibility**, `AVGVISIB_*_201608_EARTH` (same grids) | same | Earth in view %; the Earth view layer |
| `psr` | LRO LOLA **permanently shadowed regions**, `LPSR_*_201608` | same | Distance to the nearest never-sunlit ground; the blue of the Ice layer |
| `slope` | LRO LOLA **gridded slope**, `LDSM_85S_40M` (40 m baseline) and `LDSM_75S_120M` | [PDS LOLA GDR polar](http://imbrium.mit.edu/DATA/LOLA_GDR/POLAR/IMG/) | Slope at the pad (mean within 250 m), the range over the area, the slope along the ice drive; the Slope layer. DN 0 is a data gap, never read as 45° |
| `dem` | LRO LOLA **gridded topography**, `LDEM_75S_120M` | same | The terrain horizon (720 azimuths, out to 220 km, with the Moon's curvature, from 2 m above the ground); the shaded-relief base map |
| `diviner` | LRO **Diviner South Polar Resource Product** (Paige et al. 2010): yearly average and maximum surface temperature and the depth where water ice is stable (1 kg/m² per billion years), on 2.88 million mesh triangles to 80° S | [PDS Geosciences, LRO-L-DLRE-5-PRP-V2.0](https://pds-geosciences.wustl.edu/lro/urn-nasa-pds-lro_diviner_derived1/data_derived_prp/); paper [doi:10.1126/science.1187726](https://doi.org/10.1126/science.1187726) | Temperature range (average to warmest); distance to ground where ice can last **at the surface** (the ice-run target) and **under at most 1 m**; the white of the Ice layer |
| `horizons` | **JPL Horizons** topocentric Sun and Earth azimuth/elevation, hourly, all of 2026 and the mission's 10 days | [Horizons API](https://ssd-api.jpl.nasa.gov/doc/horizons.html) | Against the LOLA horizon: the **longest darkness** in 2026, a 2026 cross-check of the 18.6-year averages, and the mission engine's hourly Sun and Earth (below) |
| `artemis2024` | NASA, *Provides Update on Artemis III Moon Landing Regions* (Oct 2024) | [nasa.gov](https://www.nasa.gov/news-release/nasa-provides-update-on-artemis-iii-moon-landing-regions/) | The 9 regions and the "On NASA's 2024 list" tag |
| `artemis2022` | NASA, *Identifies Candidate Regions…* (Aug 2022) | [nasa.gov](https://www.nasa.gov/news-release/nasa-identifies-candidate-regions-for-landing-next-americans-on-moon/) | "Studied, dropped (NASA's 2022 list)": Peak Near Shackleton, Connecting Ridge |
| `criteria` | George et al., *Artemis III site selection update: downselection from thirteen to nine candidate regions* (NASA NTRS 20250011660, LPSC 2026) | [ntrs.nasa.gov](https://ntrs.nasa.gov/citations/20250011660) | NASA's criteria the score weighs: illumination, Direct-to-Earth comms, terrain safety (slope), science (PSR access) |
| `lroc` | LROC NAC low-Sun controlled mosaics of the candidate regions (Henriksen et al. 2023) | [LROC RDR](https://data.lroc.im-ldi.com/lroc/rdr_product_select) | Region centres from the product names: Peak near Cabeus B `P836S2912`, Malapert `P860S0003`, Mons Mouton Plateau `P843S0306`, Nobile Rim 2 `P839S0587`, de Gerlache Rim `P885S2933` |
| `regionmap` | NASA's map of the 9 regions (NTRS 20250011660, Image 1) | same | Haworth, Mons Mouton, Nobile Rim 1 and Slater Plain have no published centre: read off NASA's map, georeferenced on the pole + 5 LROC centres (residual ≈ 4 km), shown as "about ±5 km" |
| `viper` | NASA VIPER mission overview: top speed 0.72 km/h (0.45 mph); drives on slopes up to 15° | [NTRS 20230011558](https://ntrs.nasa.gov/api/citations/20230011558/downloads/VIPER%20Mission%20Overview%20Presentation-%20CATIE%20Expo.pdf), [VIPER lunar operations](https://science.nasa.gov/mission/viper/lunar-operations/) | The ice-run hours (a game rule on real distances, flagged) |

Not used, and why: LEND / LAMP / Mini-RF have no open polar grid at site scale that we could sample consistently;
the Moon Trek WMTS layers (e.g. `WAC_POLE_ILL_PCT_SOUTH_100M`, verified via its GetCapabilities: PNG tiles, zoom 0–5,
±61 km) are colourised tiles, not values, and do not reach Malapert, so we use the PDS products they are made from.

## How each number is made

* **The outpost spot.** A site's published point is a few hundred metres from its best ground. The navigator measures
  at the best-lit spot **flatter than 10°** within 1 km of the site (within 7.5 km for a 15 km region), choosing the
  99th-percentile illumination so one noisy pixel never wins. `spot` and `offset_km` are in the JSON. The crater floor
  is measured where it is.
* **Ranges** are the 10th to 90th percentile (sunlight: 10th percentile to the spot) over the 1 km disk or the region.
* **Ice.** `ice_km` is the straight-line distance to the nearest Diviner triangle where ice is stable at the surface
  (`ice_depth` 0; `-1`, which occurs only where the yearly maximum stays under ~100 K, is read as the same colder case);
  its range starts at the nearest ice buried under at most 1 m. This is where ice **can last**, not a detection.
* **Longest dark** is the longest run of 2026 hours with no part of the Sun above the LOLA skyline.
* **Cross-checks** (`check` in the JSON): the 2026 sunlight % from Horizons + LOLA horizon agrees with the 18.6-year LOLA
  average within a few points at most sites (e.g. Shackleton rim 89 vs 87, Connecting Ridge 61 vs 60); Earth visibility
  differs where the 120 m horizon cannot resolve a peak's last metres (Malapert spot 73 vs 64). The LOLA Shackleton-rim
  peak (87 %) matches Bussey et al. 2010's 86 %.

## Into the mission engine (no fork: the existing site parameters)

* `ephemeris_<site>.json` gains `sun_terrain_deg` / `earth_terrain_deg`: each hour, the LOLA skyline at the Sun's and
  Earth's azimuth (minus the disc's radius). `sim.env_at` compares the Horizons elevation with it; a site without them
  keeps the old single calibrated horizon angle.
* `sites.json`: `sunlight_pct` = the LOLA average at the spot (was Bussey 2010), `window_sunlit_pct` /
  `earth_visible_pct` recomputed on the real skyline, `rover_to_ice_h` from the ice distance at VIPER's speed (slower on
  slopes) and `rover_slope_power`, the extra battery a steep ice drive costs (mean drive slope / 5, in %).
* `academy/course.json` lesson facts quote these numbers (`tools/build_course.py` reads them).

## Map layers (`site_layers` asset)

South polar stereographic, lon 0 up, ±210 km, 2048 × 2048 PNG each: `relief` (LOLA shaded relief, 2.5× vertical
exaggeration), `sunlight`, `slope`, `ice` (PSR + surface-stable ice), `earth`, plus `layers.json` (legend, unit, ramp,
credit) and `NOTICE`. NASA data are not subject to copyright in the United States.
