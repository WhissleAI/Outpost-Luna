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

## NASA views (`nasa_views` asset)

0.4 "Real NASA views": an optional asset (`NASA_VIEWS_DIR`, ~14 MB) built at **build time** by
`scripts/nasa_views_build.py` (`make nasa-views`), which fetches, converts and decimates, then deletes the raw downloads.
The app never fetches these; without the asset it keeps its own visuals. `index.json` lists every file with its title,
credit and source; `NOTICE` carries the credit line *"Uses NASA open data and 3D models (NASA 3D Resources;
NASA/Astromaterials 3D, CC0; USGS Astrogeology); not endorsed by NASA."* and one line per item.

| Part | Source | What we did |
|---|---|---|
| `sky/starmap_4k.jpg` | NASA/GSFC SVS [4851, Deep Star Maps 2020](https://svs.gsfc.nasa.gov/4851): `starmap_2020_4k.exr` (Hipparcos-2, Tycho-2, Gaia DR2 + Milky Way) | Linear EXR → gamma 2.2 (SVS's own print tone), JPG q88, 4096 × 2048. Plate carrée, celestial ICRF/J2000; RA 0h at the centre (`ra0_u` 0.5), RA increasing to the left. svs.gsfc.nasa.gov sends no intermediate certificate: fetched with `backend/data/video/intermediates.pem` |
| `models/*.glb` | [NASA 3D Resources](https://science.nasa.gov/3d-resources/): Apollo Lunar Module, Habitat Demonstration Unit (parts 1 + 2, merged), RASSOR, JSC Mission Control Room, Lunar Reconnaissance Orbiter (B), LADEE | `scripts/nasa_views_glb.mjs` (gltf-transform 4.5): merge, base at y = 0, weld, simplify (RASSOR 12 %: 6.3 → 1.4 MB), textures ≤ 1024 px WebP, `EXT_meshopt_compression`. Scaled to metres where the source is not (HDU cm; LADEE to its 2.37 m height, NSSDCA 2013-047A) |
| `rocks/*.glb` | [Astromaterials 3D](https://ares.jsc.nasa.gov/astromaterials3d/) (NASA JSC ARES; public domain, credit NASA): 15016, 60025, 76535, 70017, 79115, 65035, web-resolution photogrammetry OBJ + texture (`<sample>_A3D_EXPLORER_metadata.json` names the files) | Simplified to 20 % (40 k triangles), smooth normals, texture 1024 px WebP, meshopt; centred, metres. Name, story: condensed by hand from each sample's own story in `lunar_sample_metadata.json`; type, mission, site and mass (only where the story states it) from that JSON |
| `images/*.jpg` | [NASA Image and Video Library](https://images.nasa.gov/): AS08-14-2383 (Earthrise), art002e009284 (Earthset), art002e014211, jsc2026e405549, jsc2024e055124 | `~orig.jpg` → ≤ 2048 px, JPG q85, EXIF dropped. Ids checked through images-api.nasa.gov; Axiom (`com-axiom`, `axemu-axiom`) ids are refused by the builder |
| `sdo/*.jpg` | [SDO](https://sdo.gsfc.nasa.gov/) AIA 131 browse frames of 2024-05-14 (`assets/img/browse/2024/05/14/`) | 18 frames at 1024 px: 15 spread over the day plus 16:25 / 16:40 / 16:55 / 17:10 round the X8.7 flare from AR 13664 (peak 16:51 UTC); the peak frame is `"flare": true` |
| `names/moon_names.json` | [Gazetteer of Planetary Nomenclature](https://planetarynames.wr.usgs.gov/) (IAU WGPSN / USGS Astrogeology), `MOON_nomenclature_center_pts.zip` | IAU-adopted features at or south of 75° S plus those within 1.5° of an Apollo landing site (216, 33 KB): name, lat, lon (−180..180), km, type, short origin. A curated subset (the south-pole craters) is copied into `places.json` / `facts.json` / the entity registry (docs/LEARNING_DESIGN.md §12.5); the pack itself stays optional |
