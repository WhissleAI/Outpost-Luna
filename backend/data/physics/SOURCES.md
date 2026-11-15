# Physics data sources

`physics.json` is built at build time by `backend/pipeline/physics_data.py`. The app never calls NASA. Each value in
`physics.json` carries a `source` id, which matches a row below (`sources.json` holds the same list as data), and a
`where` that says where in the source it comes from.

**How sites were sampled.** Each site is sampled in a box of ±500 m around its coordinates in
`data/mission/sites.json`. The box values are reduced to a median, a 90th percentile, a minimum and a maximum.

## NASA data

| id | Source | URL | Use in the game |
|---|---|---|---|
| `diviner` | LRO Diviner seasonal polar temperatures (Williams et al. 2019, 240 m maps made by the Diviner team from PDS data) | https://luna1.diviner.ucla.edu/~jpierre/diviner/level4_polar/ | Each site's winter night minimum feeds the Heaters card ("Dark ground here drops to about −206 °C"). |
| `diviner_prp` | LRO Diviner Polar Resource Product (PDS LRO-L-DLRE-5-PRP-V2.0, doi:10.17189/1520650) | https://pds-geosciences.wustl.edu/lro/urn-nasa-pds-lro_diviner_derived1/data_derived_prp/ | Each site's annual maximum surface temperature (sunlit ground) and the shadowed floor's yearly mean, about 50 K. Also the ice-stability depth: none within 2.9 m at the rims, 0.1–0.8 m at Malapert and de Gerlache. |
| `diviner_team` | LRO Diviner team: seasonal polar data products | https://www.diviner.ucla.edu/single-post/2020/07/20/new-diviner-seasonal-polar-data-products | 110 K is cold enough to trap ice for a billion years. |
| `crater` | LRO CRaTER quiet-time cosmic rays (Schwadron et al. 2012, JGR 117) | https://prediccs.sr.unh.edu/papers/schwadron2011JE003978.pdf | Cross-check of the Chang'e 4 baseline: 11.7 cGy/yr = 0.0134 mGy/h, × Q 4.3 = 0.057 mSv/h. This matches Chang'e 4's 0.057 mSv/h, so the baseline stays. Used in the Dose card and its Engineer equation. |
| `crater_events` | LRO CRaTER team: solar particle event list | https://crater-web.sr.unh.edu/data/craterProducts/events/events.txt | Real storm peaks, e.g. January 2012 at 61.8 mGy/h, thousands of times the quiet rate. Used in the storm Dose card. The game's ×1.25–×8 storms are labelled "scaled for the game". |
| `lola_slope` | LRO LOLA slope map LDSM_85S_40M (PDS LRO-L-LOLA-4-GDR-V1.0) | http://imbrium.mit.edu/DATA/LOLA_GDR/POLAR/IMG/ | Slopes per site, shown on the Commander route choice ("Steep, about 25°") and the Rover card. Track-gap fill pixels (DN 0) are excluded. |
| `lola_illum` | LRO LOLA average illumination and Earth visibility, 60 m (PGDA product 69; Mazarico et al. 2011 method) | https://pgda.gsfc.nasa.gov/products/69 | Ground-level sunlight % per site, kept as a cross-check (see "Findings"). Not shown to kids. |
| `horizons` | JPL Horizons API | https://ssd-api.jpl.nasa.gov/doc/horizons.html | The Sun's height above each site's ridge line, which drives the Solar power card and the debrief's night and energy lines. |
| `lend` | LRO LEND polar hydrogen (NTRS 20180004020) | https://ntrs.nasa.gov/citations/20180004020 | Average polar soil is only about 0.13% water-equivalent. That is why the rover goes into the dark craters. |
| `bvad` | NASA Life Support Baseline Values and Assumptions Document (NTRS 20210024855), Table 3-31 | https://ntrs.nasa.gov/citations/20210024855 | Oxygen use is 0.9 kg per person per day (0.895 nominal; range 0.61–1.08). Used in the Life support card. |
| `sh_tcs` | Schunk et al. 2022, NASA MSFC Surface Habitat thermal and power architecture (NTRS 20210026557) | https://ntrs.nasa.gov/citations/20210026557 | Anchors the outpost model: a 10–15 kW array and 155–540 kWh to get through a night. |
| `sst_soa` / `li_ion` | NASA Small Spacecraft Technology State of the Art: Power | https://www.nasa.gov/smallsat-institute/sst-soa/power-subsystems/ | 30% multi-junction cells, which set the Engineer panel equation and the 37 m² array. Li-ion stores 150–270 Wh/kg. |
| `tsi` | NASA GSFC solar irradiance (TSIS-1) | https://earth.gsfc.nasa.gov/climate/projects/solar-irradiance/science | 1361 W/m² of sunlight, in the Engineer panel equation. |
| `sunfact` | NASA Sun Fact Sheet | https://nssdc.gsfc.nasa.gov/planetary/factsheet/sunfact.html | The Sun's disk is about 0.5° wide, which is why panels fade over half a degree as it sets. |
| `vsat` | NASA: vertical solar array technologies for the lunar surface | https://www.nasa.gov/technology/nasa-industry-to-mature-vertical-solar-array-technologies-for-lunar-surface/ | "Upright panels catch the low Sun." |
| `databook` | NASA Lunar Surface Data Book, M2M-30044 (NTRS 20250002845) | https://ntrs.nasa.gov/citations/20250002845 | The Sun is at most 7.5° up at the pole. Darkness lasts up to 150 h. LCROSS soil is "on the order of five percent" water. The coldest shadowed spots reach 18 K. |
| `dsne` | NASA DSNE, SLS-SPEC-159 Rev H (NTRS 20205007447) | https://ntrs.nasa.gov/citations/20205007447 | Regolith thermal properties (conductivity, density, heat capacity, emissivity) and reference temperatures. Held in `physics.json` for the Engineer level. |
| `fsp` | NASA Fission Surface Power | https://www.nasa.gov/exploration-systems-development-mission-directorate/fission-surface-power/ | 40 kW: context for the backup generator. |
| `viper` / `viper_ntrs` | NASA VIPER in depth; Bluethmann 2024 (NTRS 20240013903) | https://science.nasa.gov/mission/viper/in-depth/ · https://ntrs.nasa.gov/citations/20240013903 | A real polar rover: 450 kg, 450 W, a 5.4 kWh battery, built for slopes up to 15°. Used in the Rover Engineer equation. |
| `a15_report` | Apollo 15 Mission Report (NTRS 19720021182) §8.2 | https://ntrs.nasa.gov/citations/19720021182 | The Apollo rover used about 67 Wh per km (1.87 Ah/km × 36 V). |
| `donki` | NASA CCMC DONKI | https://kauai.ccmc.gsfc.nasa.gov/DONKI/ | The real storms in each mission (already in `data/mission`). |
| `regolith_shield` | NASA NTRS 19890004839 | https://ntrs.nasa.gov/citations/19890004839 | Real shielding is mass. Used in the pretend-shields card. |

## Papers and other sources (numbers cited only)

| id | Source | URL | Use in the game |
|---|---|---|---|
| `change4` | Zhang et al. 2020, Chang'e 4 LND (Science Advances; CC BY-NC) | https://pmc.ncbi.nlm.nih.gov/articles/PMC7518862/ | The quiet-Moon baseline, 0.057 mSv/h, and the quality factor 4.3 used to convert CRaTER's Gy to Sv. |
| `lcross` | Colaprete et al. 2010, Science 330 | https://doi.org/10.1126/science.1186986 | 5.6 ± 2.9% water by mass. Used in the Rover card and the debrief's ice line. |
| `artemis1_shelter` | DLR, Artemis I radiation findings | https://www.dlr.de/en/latest/news/2024/orion-spacecraft-radiation-protection-tested-initial-findings-from-artemis-i-moon-mission | The shelter cuts storm dose about 4×. |
| `outpost_model`, `game` | Outpost Luna game rules (docs/PHYSICS.md) | — | Game percent maps to real units. The battery is 250 kWh: the habitat's 15 kW array ÷ the sim's 6 %/h full-Sun charge. A 20% heater share counts as 100% duty. |

## Licence

- **NASA material** is generally not under copyright in the United States. Credit NASA as the source, and never imply endorsement. NASA insignia are not used.
  - Terms: https://www.nasa.gov/nasa-brand-center/images-and-media/
- **PDS data** are open NASA archives. Cite them by data-set ID or DOI, as listed above.
- **Journal papers** are cited for their numbers only. No text or figures are copied.

## Findings from the cross-checks

- **Radiation baseline:** confirmed. CRaTER's quiet-time cosmic rays, converted with Chang'e 4's measured quality factor, give the same 0.057 mSv/h as Chang'e 4. The baseline is unchanged.
- **Real storms are far bigger than the game's.** CRaTER measured peaks of 47–62 mGy/h in the January and March 2012 storms, behind thin shielding. The game multiplies the quiet rate by 1.25–8. The game keeps its multipliers, labels them as scaled, and the storm card says real storms are thousands of times the quiet rate.
- **Sunlight at ground level is lower than the picker shows.**
  - The LOLA maps give 38–42% sunlight at ground level for the sunlit sites.
  - The site picker's yearly figures (73–86%, Bussey/Gläser) are for the best-lit points, a few metres up.
  - Mazarico 2011 found that about 10 m of height "dramatically improves" sunlight.
  - Both stay labelled as they are. The power cards never quote a year figure.
- **Malapert coordinates:** sampled at `sites.json`'s (−85.98, −1.67), the same point the sim uses.
- **Not verified:** CRaTER doses for the 10 September 2017 storm (not in the event list); the full text of the LAMP frost paper; a NASA figure for lunar battery depth of discharge. None of these is used.
