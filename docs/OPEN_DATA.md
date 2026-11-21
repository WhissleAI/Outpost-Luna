# Open data beyond NASA in Explore

**Question (owner, 2026-11-20):** why is Explore only enriched with NASA data? Other agencies and world organisations
publish open data. Add the right ones to Explore (the Library) for **both** courses.

**Answer.** Explore used NASA because NASA's media rules are the simplest: public domain, credit NASA. Other agencies
have open data too, but each has its own terms: CC0, public domain, an EU notice, per-file Creative Commons, or
"educational use only, no redistribution". Each one has to be checked before it can go in an offline pack. This page
lists the candidates and the terms checked at each source. Phase 2 ships the ones that are clearly licensed and small.

Tags: **[read]** = the licence was read on the source page or document · **[search]** = taken from search results, page
not opened · **[unclear]** = the terms are ambiguous or conflict.

## 1. What shipped (phase 2)

| Course | Dataset (owner) | Licence, as read at the source | In the app | Size | Explore feature |
|---|---|---|---|---|---|
| Moon | **Unified Geologic Map of the Moon, 1:5M, 2020** (USGS Astrogeology: Fortezzo, Spudis, Harrel) | "Use Constraints: CC0, but please cite authors" [read] | `courses/moon/media/moon_age.jpg`, 4096×2048. The 64 px/° unit raster recoloured by its 5 periods, with the LRO map's shading | 1.7 MB (the source zip is 37 MB) | Library → **Maps → Age**: the globe turns into an age map, with a 5-period legend (oldest first) and the credit |
| Moon | **Moon LRO LOLA Color Shaded Relief 388 m v4** (USGS Astrogeology, from NASA GSFC's LOLA DEM) | "Use Constraints: Public domain" [read] | `courses/moon/media/moon_height.jpg`, 4096×2048, from the USGS map service | 2.8 MB | Library → **Maps → Height**: low-to-high colour ramp; the far-side highlands stand out |
| Archaeology | **Copernicus Sentinel-2 L2A** (ESA / EU), scene S2A_12SYG_20240617 | EU legal notice: free reproduction, distribution and adaptation; notice "Contains modified Copernicus Sentinel data [Year]" [read, PDF] | `s2_mesa_verde_true.jpg` + `s2_mesa_verde_nir.jpg`, the park's tableland (37.12–37.36 N, 108.62–108.32 W) | 0.64 + 0.67 MB | New shelf **Sentinel-2 · ESA (Copernicus)**: true colour, then near-infrared ("living plants glow red; five big fires 1996–2003 burned more than half the park", NPS fire history [read]) |
| Archaeology | **NOAA NCEI / ITRDB CO652** (Stahle et al. 2015), already in the course for the `rings` step | No licence on the record; NCEI asks for citation; NCEI's open-data policy [read, #168] | `co652_chart.png`: the chronology as a chart, the Great Drought (1276–1299) marked | 0.12 MB | New shelf **Climate record · NOAA**: "Over 1,200 years of tree rings". Narrow rings mean dry years. The drought is "one reason among several" (Crow Canyon, NPS) |

Every picture is in its folder's `media/credits.json` (credit, licence, source_url, alt, size, sha256). The card or
the Maps panel shows that credit. Every caption is backed by a checked quote in `sources.json`. All the files are made at
build time by `scripts/open_data_build.py` (`make open-data`). The app never fetches them.

**Where it ships.**
- Moon: in the app itself (`backend/data/courses/moon/`, 4.5 MB). `desktop/scripts/build_python.py` and
  `ios/scripts/build_python.sh` keep that one `media/` folder, so there is no asset to upload.
- Archaeology: in the course pack `course_archaeology` **v3** (39.2 MB, up from 37.7 MB). It still needs uploading (§4).

**Mechanism.** `library.json` gains `layers`: whole-globe maps with a title, a line to say, a legend and a source,
checked by `backend/app/course_library.py`. The Moon's library has layers only, because its Library itself is built
from code. `frontend/src/map_layers.js` adds a **Maps** button to the Library toolbar of any course that has layers.
`globe.setBaseMap` swaps the texture and hides the polar cap and draped pictures while a layer is on. Leaving the
Library puts the photo back. A course item can carry a `label` (for example "Chart"), so a chart is never called a
"Real photo".

## 2. Candidates checked, not shipped yet

### Moon

| Dataset | Owner | Licence | Packable? | Explore feature it would enable | Verdict |
|---|---|---|---|---|---|
| Kaguya / SELENE TC mosaic, LALT DEM | JAXA | SELENE archive asks for "©JAXA/SELENE"; JAXA Virtual Planet says "redistribution over networks is prohibited"; the DARTS FAQ says no procedure is needed [search, unclear] | yes (WMS `KaguyaTC_Ortho` at USGS) | A "Japan's view" photo layer; Kaguya HDTV Earthrise | **Ask JAXA in writing** before packing. Do not ship on the current terms |
| LROC QuickMap / NAC mosaics | NASA / ASU | LROC credits "NASA/GSFC/Arizona State University" [search] | per-site crops only (NAC is metres per pixel) | Close-ups of the Apollo sites in the hardware cards | Next Moon pick. NASA-led, so it does not answer "beyond NASA" |
| Diviner temperatures | NASA / UCLA (PDS) | PDS: public [search] | yes, a global min/max map is about 2 MB | "Temperature" layer: the coldest places in the Solar System at the poles | Good next layer. The site navigator already uses Diviner polar data (`site_layers`) |
| Lunar Sample Compendium | NASA JSC | US Government, public domain [search] | text, under 1 MB | Rock cards: mass, type, story for all Apollo samples | Extend the rocks tray (the 6 Astromaterials 3D rocks ship already) |
| IAU / USGS Gazetteer of Planetary Nomenclature | IAU WGPSN, hosted by USGS | USGS, public domain [search] | yes, about 9,000 names, under 2 MB | "Names" layer: label the near side's maria and big craters | 216 names ship already (south pole, Apollo sites) |
| Smithsonian 3D (CC0): Apollo 11 Command Module *Columbia*, Armstrong's suit | Smithsonian NASM | CC0 for items marked so [search] | yes after decimation (source models are 100+ MB) | More hardware in the rocks tray | Good pick. Needs the nasa_views GLB pipeline and a per-item CC0 check |
| Chandrayaan-1/2 (TMC, OHRC, M3) | ISRO | PRADAN needs an account; redistribution terms not found [unclear] | — | — | Skip until ISRO terms are in writing |
| SMART-1 AMIE images | ESA | ESA images are © ESA, some CC BY-SA 3.0 IGO per image [search] | per image | One ESA Moon photo per card | Only items marked CC BY-SA, and keep the share-alike notice |

### Archaeology / Earth

| Dataset | Owner | Licence | Packable? | Explore feature it would enable | Verdict |
|---|---|---|---|---|---|
| USGS 3DEP lidar / The National Map | USGS | "free of charge and without use restrictions" [read, #168] | yes, as pre-rendered hillshades | Already shipped (Far View low and high sun); more interpreted areas could be added | Shipped earlier |
| NAIP aerial photos (0.6 m) | USDA FSA | US Government, public domain [search] | yes, a crop is about 0.5 MB | "Same ground, photo vs lidar" next to the hillshade pair | Next pick. Needs the hillshade's exact bounds (not recorded with the media) |
| NPS open data and IRMA (Mesa Verde) | NPS | NPS-made: public domain; some records are restricted to protect sites [search] | yes | Fire perimeters 1996–2003 over the Sentinel-2 view; vegetation | Good next pick. Use only published, non-sensitive layers (no site points) |
| Smithsonian Open Access (CC0) | Smithsonian | CC0 per item [search] | yes | Pottery and tools on a "Things people left" shelf | **Hold.** Many Mesa Verde objects in museums came from burials (Wetherill-era collecting). It needs per-object provenance and the tribal review (§3) |
| Open Context | AAI / UC Berkeley | per project, mostly CC BY [search] | per dataset | Real excavation records for the `layers` step | Later. Check each project's licence and sensitivity |
| tDAR (Digital Archaeological Record) | Digital Antiquity / ASU | user agreement; many files restricted [search] | no | — | Skip: not open redistribution |
| NOAA paleoclimate (ITRDB, Mesa Verde 1,300-year moisture reconstruction) | NOAA NCEI | NCEI open-data policy (public domain for federal data) [read, #168] | yes, text | A second chart: reconstructed rainfall | CO652 shipped as a chart; the reconstruction would add a "rain" line |
| Copernicus / Sentinel-2 | ESA / EU | EU legal notice [read] | yes | — | **Shipped** (§1) |
| Copernicus DEM GLO-30 | ESA / EU (DLR, Airbus data) | free licence with a long attribution clause [search] | yes | A global relief layer for Earth | Later. 3DEP is better for the US |
| OpenStreetMap | OSM Foundation | ODbL: attribution plus share-alike on the database [search] | vector extracts yes; the tile servers forbid bulk download | Roads and towns on the regional map | Later, from a Geofabrik extract with "© OpenStreetMap contributors" |
| Wikimedia Commons | per file | per file (PD, CC BY, CC BY-SA …) [search] | per file | Extra site photos | Use only when NPS has none; record each file's licence in credits.json |
| PRISM climate normals | Oregon State PRISM Group | free with citation; redistribution terms [unclear] | yes | Today's rainfall map of the Four Corners | Ask PRISM, or use NOAA nClimGrid (public domain) instead |
| Natural Earth | NACIS | public domain [search] | yes, about 1 MB | State lines and rivers on the Earth globe | Easy add when the globe needs borders |

## 3. Respect rules these picks follow (docs/COURSES.md §1.5)

- **Park level only.** Sentinel-2 shows the whole park tableland, the same frame as NASA's Landsat image. No site points
  and no new coordinates. Every new item names the gazetteer place `mesa_verde`.
- **No human remains, no burials, no sacred objects.** That is why Smithsonian and museum object images are on hold.
- **Descendant voices come from their own sources.** The drought caption says "one reason among several", as NPS and
  Crow Canyon do, and never "the drought made them leave".
- **Review.** A Crow Canyon educator or a tribal cultural office should review the course before a classroom pilot.
  That decision is still **open** (docs/COURSES.md §7).

## 4. What needs uploading (not done by this PR)

| Asset | File | sha256 | Size | Where |
|---|---|---|---|---|
| `course_archaeology` v3 | `outpost-luna-v2-course_archaeology-3.tar` | `00428ea521a2e06a33725dffc6b9cde66cc6911cd033a661cfdcbd35214dc712` | 39,157,760 B | Dropbox (`scripts/upload_assets.py`) + GitHub `assets-v2` mirror (`scripts/upload_assets_github.py`), then `bash scripts/publish_site.sh` |

- Until the upload, the manifest's `url` is null. The app falls back to v2, the published pack. Its library is
  self-consistent and simply lacks the new shelves.
- Rebuild it with `COURSE_PACK_VIDEOS=1 uv run --project backend python scripts/asset_pack.py --only course_archaeology --no-zip`.
  The five video copies come from the published v2 tar.
- After the upload, consider `min_version: "3"`, so that installed v2 packs fetch the new views on the next course
  switch.
- The Moon's layers need no upload. They ship in the next app build.
