# NASA video (media v1)

Short NASA videos in lessons, the briefing and the debrief. **Every NASA video plays from a local file** in our own
player: the desktop's video pack (a first-run asset) carries all of them, and the backend keeps them in its cache, so
they play without internet ("videos offline", 2026-11-17: YouTube refuses its embeds on some networks with "Sign in to
confirm you're not a bot", even in real Chrome). The only YouTube embeds left are two hand-picked, third-party
Mission prep extras. Every video gets a predict → watch (or skip) → reveal step, and media never blocks a lesson.

## The catalog: `backend/data/video/catalog.json`

A list of entries:

| field | |
|---|---|
| `id` | lower_snake_case, unique |
| `title`, `concept`, `age` | what it is and who it's for |
| `source` | `nasa_file` (a NASA file, downloaded once or copied from the video pack, played offline), `pack_file` (only the video pack carries it; the app never downloads it: below) or `youtube` (stream only, never cached; YouTube policy III.E.1) |
| `youtube_id` | youtube only |
| `file_url`, `captions_url`, `poster_url` | nasa_file only. https on a NASA host. `.srt` is converted to WebVTT once. A missing `captions_url` means the video has no captions (or NASA's file is empty) |
| `origin_url`, `origin_sha256`, `derive` | a NASA pack_file: its NASA original (https on a NASA host, `www.jpl.nasa.gov` included) and the ffmpeg arguments of the re-encode the pack carries |
| `captions`, `poster` | pack_file only, true/false: the pack also carries `<id>.vtt` / `<id>.jpg` |
| `permission` | a third-party pack_file only: the record of the owner's written permission (who, when) |
| `bytes`, `sha256` | the download / pack check (`prefetch` items must have `bytes`; a pack_file must have `sha256`) |
| `pack` | a pinned nasa_file only: `{derive, bytes, sha256}`, the video pack's lighter copy of it (video pack v3, below). `tools/video_catalog.py --pack` makes it from the NASA file with the ffmpeg arguments in `derive` and pins its bytes + sha256; the backend accepts either the NASA file or this copy from the installed pack (`video.pack_copy_ok`). Streaming and the dev cache still use the NASA file |
| `duration_s` | sets the button label ("Watch (2 min)") and the watched threshold |
| `credit` | starts with "NASA" (a non-NASA video: its channel and "not from NASA", or "used with permission" for a pack_file). Shown under the player and in About → Videos |
| `nasa`, `channel` | optional; `nasa: false` marks one of the few hand-picked non-NASA videos (below) |
| `prep` | optional, a Mission prep task id (course.json `lesson.prep.id`): the video is that task's "Watch how" |
| `music_credit` | the NASA source credits third-party music. Such a video plays from YouTube, never as a cached file. **None is in the catalog now**: see "Where each video comes from" |
| `prefetch` | pinned: in the video pack, copied (or downloaded) on first launch and never evicted. Every NASA video is pinned |
| `fallback` | optional, a `nasa_file` / `pack_file` id. The offline / won't-play card offers it in place of this video |
| `source_page`, `nasa_id`, `note` | where a maintainer finds it again; why this rendition |

### Where each video comes from (checked 2026-11-17)

The 8 original NASA files are unchanged. The 11 YouTube entries were each looked up on NASA's own hosts
(svs.gsfc.nasa.gov, images.nasa.gov, jpl.nasa.gov), including their music credits:

| id | was (YouTube) | now | rendition |
|---|---|---|---|
| `far_side_view` | jdkMHkF7BaA, NASA Goddard | the same video, SVS 4253 ("A View From The Other Side", G2015-013) | 960×540 H.264 `.m4v`, 45.4 MB, captions |
| `south_pole_shadows` | 0GCTOHu4OrQ, NASA Goddard | the same visualization, **silent** (SVS 4893 `moon_spzoom_720p30.mp4`): the narrated cut credits Universal Production Music | 720p, 20.7 MB |
| `ltv` | zTHJ9zb8J2s, NASA | the same trailer, images.nasa.gov `jsc2024m000100…(Official NASA Trailer)` | 720p `~medium`, 24.7 MB, captions |
| `meet_crew` | lPyl6d2FJGw, NASA | **replaced**: NASA hosts that video nowhere as a file; "Artemis II Crew Talks About the Moon" (images.nasa.gov `jsc2026m000054…`, the four crew) | 1080×608 `~medium`, 39.4 MB, captions |
| `moon_phases_2025` | RROlja1ob_4, NASA Goddard | the same visualization, **silent** (SVS 5415 `phases_2025_fancy_720p30.mp4`): the YouTube cut credits Universal Production Music | 720p, 75.6 MB |
| `solar_eruptions` | bX0hv0EFKnI | **dropped**: SVS 14988 credits Universal Production Music, and NASA hosts only 137 MB vertical files. The debrief's dose-limit Learn more plays `moon_weather` |  |
| `artemis_south_pole` | AQAaAJW-uC0 | **dropped**: SVS 14886 credits Universal Production Music; no lesson used it |  |
| `impact_flashes` | B9MoWCnmuqw | **dropped**: SVS 15103 credits Universal Production Music (and is 4K only, 137 MB); no lesson used it |  |
| `solar_eclipse_sp` | hyf5JF_VxwM, NASA Space Place | **dropped**: Space Place hosts no file (YouTube only); no lesson used it. NASA's "The Moon's Role in a Solar Eclipse" (images.nasa.gov `GSFC_20170721_LRO_m12648_SolarEclipse`, 47 MB) could take its place |  |
| `diy_crater`, `diy_oreo_phases` | third-party (below) | **not downloaded**: no permission. Optional YouTube extras |  |

New: `diy_crater_nasa`, NASA/JPL Education's "DIY Space: How to Make a Crater" (Ota Lutz; flour, sprinkles, cocoa,
rocks; 2:43), the crater_drop task's NASA Watch how. JPL hosts it only as a 293 MB 720p `.mov`, so it is a
**pack_file**: `tools/video_catalog.py --derive` downloads the original (`origin_url`, checked against
`origin_sha256`), re-encodes it with the entry's `derive` arguments (720p H.264 CRF 27 + AAC, 19.3 MB), grabs a poster,
and pins `bytes` and `sha256`. NASA hosts no Oreo-phases video (Space Place's Oreo activity is a printable page only),
so `oreo_phases` keeps `moon_phases_2025` as its NASA Watch how.

**The video pack**: 8 videos, 199.4 MB before; 14 videos, 424.9 MB in v2 (38 files with captions, posters and the
NOTICE; the largest file 75.6 MB).

**Video pack v3 (0.4.3): the same 14 videos, lighter.** The 12 pinned NASA files are carried as `pack` copies: H.264
High (level 4.0, yuv420p), `-preset slow -crf 23 -maxrate 1100k -bufsize 2200k`, AAC-LC 96 kbps, faststart, at the
NASA file's own resolution and frame rate (`derive` in the catalog). `ltv`, `moon_weather` and `phases_loop` missed the
bar at 1.1 Mbps and use `-maxrate 1600k -bufsize 3200k`. H.264 High + AAC in MP4 is what every player the app has
decodes (Chromium in Electron on Mac and Windows, WKWebView on the iPad); HEVC / AV1 were not used (decode is not
certain on every Windows PC and older iPad). Captions, posters, `hammer_feather` and the `pack_file` `diy_crater_nasa`
are byte-identical. The 12 files: **399.7 MB -> 182.3 MB**. The bar (fixed before encoding), every frame compared at
the source resolution with libvmaf `vmaf_v0.6.1` + SSIM: VMAF mean >= 90 and 5th-percentile frame >= 75, SSIM (Y) >= 0.95,
duration within 0.1 s, same resolution / frame rate / audio channels. Per file (MB before -> after, VMAF mean / p5,
SSIM Y): far_side_view 45.4 -> 11.0 (93.6 / 88.7, 0.981), ltv 24.7 -> 15.9 (92.9 / 79.8, 0.985), lunar_dust 46.1 ->
20.0 (94.1 / 89.9, 0.988), lunar_eclipse 35.6 -> 12.7 (95.5 / 92.4, 0.990), meet_crew 39.4 -> 14.4 (93.2 / 85.7,
0.986), moon_base_6mo 19.7 -> 9.7 (91.2 / 80.7, 0.974), moon_phases_2025 75.6 -> 39.8 (95.4 / 94.1, 0.989),
moon_weather 26.4 -> 14.3 (93.0 / 85.0, 0.978), phases_loop 3.8 -> 3.0 (91.5 / 88.2, 0.984), psr 32.9 -> 17.1 (92.1 /
82.6, 0.972), south_pole_shadows 20.7 -> 10.9 (94.4 / 90.4, 0.990), water_extraction 29.4 -> 13.4 (95.0 / 91.4, 0.984).
The app accepts either the NASA file or the pack copy (`video.pack_copy_ok`); online streaming still plays NASA's file.

### "Watch how" videos for Mission prep (hand-picked, some not from NASA)

A hands-on Mission prep task (the flour-and-cocoa crater, Oreo Moon phases) shows a **Watch how** button for each catalog
video whose `prep` is that task, NASA first, each only when it can play now (no dead buttons): the NASA ones play from
the video pack offline; a YouTube extra shows only while online. The lesson has them too: in its Brief from the start,
and under the first step once the first answer is in (0.3.12: predict before watch; 0.3.11 showed them before the
guess). On a core lesson only the NASA ones show there; third-party extras stay on the Try at home card, which stays optional
(map card after the patch, or the patch screen). Voice: "show me how", "watch the video" (the router's `prep_watch`;
never a bare "watch", which is room talk during the task). Links out still go through the grown-up gate.

Non-NASA YouTube videos are allowed **by video id only**, never by channel: `app/video.py NON_NASA_YOUTUBE` maps each
id to its channel, and `validate()` requires `nasa: false`, the matching `channel`, "not from NASA" in the credit and a
`prep` task. Each one was checked (title and channel via YouTube oEmbed, embeddable, landscape, under 10 min, on topic).
They are third-party copyrighted and not CC-licensed, so they are **never downloaded or bundled** without the owner's
written permission.

| id | video | channel | NASA | source | prep task |
|---|---|---|---|---|---|
| `diy_crater_nasa` | DIY Space: How to Make a Crater (2:43) | NASA JPL Education | yes | pack_file | `crater_drop` |
| `diy_crater` | Moon Crater Making @ Home (osdOQhRhVJg, 2:06) | Astronomy in Action | no | youtube | `crater_drop` |
| `diy_oreo_phases` | Oreo Moon Phases Activity (XeBmuY2i2fg, 0:56) | I Play With My Kids | no | youtube | `oreo_phases` |
| `moon_phases_2025` | 2025 Moon Phases, Northern Hemisphere (SVS 5415, silent, 4:52) | NASA Goddard | yes | nasa_file | `oreo_phases` |

#### When an owner gives permission: the local drop-in

1. Put their file at `backend/data/video/local/<id>.mp4` (720p H.264 MP4; not in git), and optionally `<id>.jpg`
   (poster) and `<id>.vtt` (captions).
2. Change the catalog entry to `"source": "pack_file"`, drop `youtube_id`, add `"permission": "<who, how, when>"`,
   make the credit say so (`"Astronomy in Action · used with permission"`), set `poster` / `captions` to match the
   files, `"prefetch": true`, and remove its id from `NON_NASA_YOUTUBE`.
3. `uv run python tools/video_catalog.py --pin` (from `backend/`) records `bytes` and `sha256`; `validate()` requires
   the permission record, "used with permission" in the credit, the `channel` and a `prep` task.
4. Rebuild and upload the video asset (`make asset-pack`, `scripts/upload_assets.py`). The pack's NOTICE names the
   video and its permission, and About → Videos shows the credit with "used with permission".

`GET /api/video/catalog` serves it, and each entry also gets `cached`, `play_url`, `captions_src` and `poster_src`.
`app/video.py validate()` checks the contract, and the tests run it. To recheck every URL and refresh the sizes and
hashes, run `uv run python tools/video_catalog.py [--pin] [--derive]` from `backend/` (downloads go to the dev cache,
`CACHE_DIR/video`).

## For screens: `frontend/src/media/video.js`

```js
import { openVideo, isAvailable } from "./media/video.js";
await isAvailable("psr");                       // "cached" | "online" | "offline"
const { watched, seconds } = await openVideo("psr", { context: "debrief" });   // resolves when the overlay closes
```

- `watched` means the kid reached the end or saw at least 70% of the video. `seconds` is time actually played.
- `offline: true` means it could not play. `skipped: true` means the kid said or tapped skip. `fallback: id` means the
  kid watched the NASA alternative.
- Use `watchLabel(v)` for the button text, or `"Needs internet"` when `isAvailable` says `offline`.
- `failed: true` means the player failed while we were online (a YouTube error such as 101/150/153, or an unknown id).
  The overlay then shows **"This video won't play here."**, never "Needs internet": `diagnose(id)` checks
  `navigator.onLine` and asks the backend once (4 s) before calling anything offline. An embed that never answers is
  checked after 15 s. The backend's own probe (`video.online()`) retries a timeout once with a longer wait, counts any
  HTTP answer as online, and remembers a failure for 5 s only.
- **Stuck embed watchdog** (0.3.11): YouTube can answer (onReady) and then sit on a card of its own, such as "Sign in
  to confirm you're not a bot", with no IFrame API error. Every play request must reach "playing" within 12 s
  (`commands.js stallWatch`, `YT_STALL_MS`), or the overlay shows "This video won't play here." with the catalog's
  `fallback` NASA file as **Watch NASA's … video instead** (offered when it is saved, or, since we are online, when it
  can stream). A pause before it plays disarms the watch; playing once ends it.
- **Watch on YouTube** (videos offline): a YouTube video that won't play here (the bot card, an embed error) and has no
  NASA `fallback` gets a "Watch on YouTube" button on that card. It opens the plain `https://www.youtube.com/watch?v=<id>`
  page with `window.open`; the desktop's `setWindowOpenHandler` classifies it as "youtube" (`gate.js classifyOpen`), so
  it opens in the system browser only after the grown-up gate's 3-second hold. A signed-in browser usually passes the
  bot check the embed fails. Offline there is no button (it would need internet anyway).
- A NASA file that errors before it has played gets one quiet retry 1.5 s later (its first play is being cached).
- The overlay ignores a `<dialog>` "close" event that arrives while the dialog is open again: `close()` queues that
  event, so closing one video and opening the next a few ms later used to close the new one at once (videos offline).
- The card always renders inside the overlay (`.vid-stage` / `.vid-bar`) with a Close button. Esc, the Close button,
  voice "stop" and a thumbs down close it; an open palm pauses. Opening the overlay closes Settings and stops a gestures
  calibration (`outpost:modal-open`), and Settings opened by voice closes the video, so no sheet is ever left inert
  under the video's `<dialog>`.

## NASA views (0.4): `frontend/src/media/nasa_views.js`

The optional `nasa_views` asset (built by `scripts/nasa_views_build.py`, packed by `scripts/asset_pack.py`; sources and
credits in `backend/data/SOURCES.md` "NASA views") holds the real star sky, NASA 3D models, six Apollo Moon rocks,
Earthrise / Earthset and Artemis geology-training photos, SDO frames of the 14 May 2024 storm and IAU names near the
south pole. The desktop app downloads it in the background after the UI is up (`fetchOptional`, never on the first-run
screen); the backend serves it (`GET /api/views`, `GET /api/views/file/<folder>/<name>`, `POST /api/views/want`;
`backend/app/nasa_views.py`, `NASA_VIEWS_DIR`). Without it every screen keeps today's visuals.

```js
import { onViews, image, images, sdoFrames, sdoInfo, rocks, model, loadModel } from "./media/nasa_views.js";
onViews(v => {                                   // called once the pack is installed (never without it)
  const er = image("earthrise");                 // {url, title, caption, credit, nasa_id, source, w, h, tags}
  const sun = sdoFrames();                       // [{url, time}] — sdoInfo() has the title, region and credit
});
const lm = await loadModel(model("apollo_lm").url);   // a THREE.Group (meshopt GLB), cached per url, cloned per call
```

`window.__outpost.views` is the same API. Used today (not the cabin):

- **Globe** (`globe.js`, wired by `views_wire.js`): `setSky` (SVS Deep Star Maps 2020 on a sky sphere, the random
  points stay until it has loaded), `setHardwareModels` (the Apollo LM at the six Apollo LM markers; the HTML marker keeps
  focus, hover and tap), `setOrbiters` (LRO polar, LADEE "2013–14"; Library only, frozen with Less motion),
  `setPolarCap` (below).
- **Library**: a "Moon rocks" button in the toolbar opens the tray (`media/rocks_tray.js`): the six samples and the NASA
  hardware models in a drag-to-turn viewer, with name, mission, type, a short story and the credit link.
- **Cabin** (0.4 part 2, `mission/cabin_views.js`, the only cabin module that reads the pack):
  - **Earth view, Earth below the horizon**: a small inset with the real photo (Apollo 8's Earthrise `AS08-14-2383` while
    Earth is on its way up; Artemis II's Earthset once it is setting or won't rise again this mission), "Earth rises
    Day N" (the sim's `next_comm_window_h`, JPL Horizons) and an arrow with the elevation and its trend. With Earth up,
    the window's long lens shows the Blue Marble Earth as before. Without the pack: the plain note.
  - **Storms** (missions and the check ride): the alert strip shows the SDO frames of 14 May 2024 as a small looping
    Sun with "The actual Sun, 14 May 2024 · NASA/SDO"; the Radiation console has a bigger Sun monitor (150 px, a ring on
    AR 13664, "X8.7 flare" on the flare frame) while a storm is on or forecast. Less motion holds the flare frame
    (16:55 UTC). Without the pack: the storm icon. Each AIA 131 frame is cropped to the whole disc, contrast-stretched to
    its lit pixels and drawn on a gold ramp (`cabin_views.js toneSun`): AIA colours are false colours, and the native
    teal read as a dark blob at cabin sizes. The loop starts on the flare frame; frames are toned when the pack loads.
  - **Site view**: NASA's Habitat Demonstration Unit (`hdu.glb`, fitted to 13 m, `terrain.js fitHabitat`) replaces the
    cylinder modules (`terrain.habitat` says which is showing); the solar arrays read lit from either side (a faint
    self-lit cell grid, a light substrate), never as black slabs.
    The Site camera orbits the middle of the outpost (`terrain.js SITE_FRAME`), close enough that the habitat reads at a
    glance.
- **IAU names** (`names/moon_names.json`, 216 features south of 75°S and near the Apollo sites): shipped with the pack.
  A curated subset (the south-pole craters) is copied into the versioned `places.json`, `facts.json` and the entity
  registry, so the ear, the gazetteer and the Director know them without the pack (docs/LEARNING_DESIGN.md §12.5).

**Sharp south pole** (UX_ROUNDS round-3 queue: the picker's blurry, over-zoomed pole): `setPolarCap` drapes the site
navigator's LOLA shaded relief (`site_layers` asset, `relief.png`, south polar stereographic ±210 km, the same projection
as the navigator's map) over the globe's polar texels, tone-matched to the colour map and faded at its edge. It needs
only `site_layers` (not `nasa_views`), and is on for every screen that shows the globe. The Mission hub and briefing
(0.4 part 2) look straight down on it: `mission.setSite(site, { clamp: false })` and `flyTo(-89, 0, 1.3, { clamp: false })`
(`ui.js PICK_VIEW`), with the view's centre shifted into the free area left of the side panel
(`globe.setViewport(band, xFrac)`) and the site's name on its dot.

## Open data beyond NASA (0.5.3)

Explore used to show only US-agency media (NASA, USGS, NPS). It now also takes open datasets from other publishers, for
both courses, under one rule: **the app may be sold, so only public domain, CC0, CC BY, or CC BY-SA shipped unmodified.**
Nothing NC, nothing ND, no ODbL, nothing that needs permission.

**The licence gate.** Every course media file is credited in `media/credits.json` with `credit`, `licence`, an https
`source_url`, `alt` and a **`licence_class`**: `pd` | `cc0` | `by` | `by-sa` (by-sa also needs `modified: false`).
`app/course_library.py licence_problem` rejects anything else: nc, nd, `unknown`, a missing class, or a licence text that
names a non-commercial or no-derivatives term. It runs when the library is served (a bad entry means no library) and
when the pack is built (`scripts/asset_pack.py src_course` stops). New entries also carry `licence_evidence` (where the
licence was read) and, for data, `data_url` and `citation`. The moon_views pack applies the same classes per index entry
(`scripts/moon_views_build.py validate_index`; `app/moon_views.py` drops anything else).

**New library item kinds** (`docs/COURSES.md` §4.11; `frontend/src/field_library.js`, `frontend/src/media/chart.js`):

| kind | file in `media/` | what the screen does |
|---|---|---|
| `chart` | an `outpost-luna-chart` JSON (`{format, series: [{label, points: [[x, y]…], faint?}], x_format, zero}`) or a CSV (x, then one column per series) | an inline SVG line or bar chart (no chart library): `<title>` + `<desc>` from the item's required `summary`, annotated `bands` (`[{from, to, label}]`), a legend and direct end labels for 2+ series, a hover read-out, and a "Show the numbers" table. Colours: blue, orange, aqua, yellow (validated on the dark glass: CVD ΔE ≥ 8.4, contrast ≥ 3:1); a `faint` context series is grey |
| `model` | a `.glb` | the Moon rocks turntable (`media/turntable.js`), in a viewer beside the card |
| `layer` | a transparent equirectangular `.png` | draped on the globe between `bounds` (`globe.setOverlay({lift, opacity})`), switched from its card, with its `legend` (`[{color: "#rrggbb", label}]`) |

Course media names are one flat segment with one dot (`app/courses.py MEDIA_NAME`, `field_library.js safeDataUrl`):
`.jpg .png` for pictures, `.json .csv` only for a chart and `.glb` only for a model, always from the course's own
`/api/courses/<id>/media/`. Nothing is hot-linked.

### Archaeology sources (`scripts/arch_open_data_build.py`, `make arch-open-data`)

Each download is pinned by sha256 in `scripts/arch_open_data.pins.json` (a changed upstream file stops the build until
its licence is re-read and `--repin`). Raw files go to `.cache/arch_open_data_raw` and are only parsed, never run.

| Item | Source | Licence (class) | URL | Size in the pack | Sensitivity |
|---|---|---|---|---|---|
| Drought timeline AD 722–2011 (`drought_mesa_verde.json`) | NOAA NCEI study 19059, Stahle et al. 2015, cool-season P-PE reconstruction, each year + 10-year spline; Great Drought band 1276–1299 | No licence on the NCEI record; access constraints none; use constraint "cite" (`by`) | https://www.ncei.noaa.gov/access/paleo-search/study/19059 | 34 KB | Copy says people **moved / migrated**; drought was one of several reasons |
| Four tree-ring records AD 1200–1320 (`tree_rings_1200_1320.json`) | ITRDB CO652 (rings/, computed) + NM597 Gobernador (archaeological + modern), NM589 Chuska Mountains, CO067 Dolores (from 1270) `.crn` chronologies | NCEI terms as above (`by`) | https://www.ncei.noaa.gov/products/paleoclimatology/tree-ring | 6 KB | — |
| Radiocarbon dates near here (`radiocarbon_four_corners.json`) | p3k14c 2025.07 (Bird et al. 2022), records in 36–38 N, 110–107 W, counted per century of 1950 − ¹⁴C age (uncalibrated) | Data CC0 1.0 (`cc0`) | https://github.com/people3k/p3k14c | 1 KB | **Counts only**: no coordinates, site names or lab ids. A materials whitelist (charcoal, wood, seeds, sediment); bone, collagen, teeth, hair, coprolites, *Homo sapiens* and perishables that may be grave goods (textile, leather, basketry, sandals) excluded first: 792 kept, 180 excluded |
| Mesa Verde from Sentinel-2 (`s2_mesa_verde.jpg`) | Copernicus Sentinel-2 L2A `S2B_12SYG_20250925_0_L2A` true colour, one window via the AWS Open Data COGs | Copernicus Sentinel data terms; credit "Contains modified Copernicus Sentinel data 2025" (`by`) | https://registry.opendata.aws/sentinel-2-l2a-cogs/ | 1.2 MB | — |
| Rivers and state lines (`layer_rivers_states.png`) | Natural Earth 10m state lines + rivers (and the North America supplement: Animas, Dolores, Chaco) | Public domain (`pd`) | https://www.naturalearthdata.com/ | 153 KB | The Mancos is not in Natural Earth |

The pack grows from 37.7 MB (v2) to 39.1 MB (v3).

**Considered and left out:** museum objects for a "Things people made" shelf. The Art Institute of Chicago (CC0
images) has Ancestral Pueblo vessels (bowls 205, 213, 223, 239, ladle 201 from an 1880s collector; jars 51144, 51185,
bowl 51139 from a 1976 dealer; ollas 52784, 52794, 187545, bowl 52127, pitchers 52119, 59999 with no provenance; the
Mesa Verde-style mug 108753, a private collection by 1980) and the Cleveland Museum of Art (CC0) has water jar 151830
and jar 155114. None documents where it was found: whole vessels of this period very often come from burials, and some
carry sacred imagery (the horned serpent on 187545). The kachina 191727 is a sacred object. Per the course's respect
rules (docs/COURSES.md §1.5): when in doubt, leave it out. No Smithsonian or Met object was added for the same reason.

### Moon views (`moon_views`, `scripts/moon_views_build.py`, `make moon-views`)

An optional asset with the same shape as `nasa_views` and its own NOTICE (`backend/app/moon_views.py`: `GET
/api/moon-views`, `POST /api/moon-views/want`, `GET /api/moon-views/file/<folder>/<name>`; `MOON_VIEWS_DIR`;
`frontend/src/media/moon_views.js`). min_app 0.5.3; pinned by sha256 in `scripts/moon_views.pins.json`.

| Item | Source | Licence (class) | Where in the app | Size |
|---|---|---|---|---|
| One surface photo per Apollo landing (AS11-40-5903, AS12-48-7133, AS14-66-9306, AS15-86-11603, AS16-113-18339, AS17-140-21496) | NASA Image and Video Library | Public domain (`pd`) | "Real photo here" on every hardware card at that landing site (not the S-IVB impacts) | 2.4 MB |
| Rock ages (`layers/rock_ages.png`, 2048×1024) | USGS Unified Geologic Map of the Moon 1:5M, 2020 (Fortezzo, Spudis, Harrel), the 64 ppd numerical raster, units grouped by period (two-period units take the younger) | CC0, "please cite authors" (`cc0`) | the Library toolbar's **Rock ages** switch, with its key (`views_wire.js wireLayer`) | 125 KB |
| Apollo 11 Command Module Columbia (`models/columbia.glb`) | Smithsonian NASM 3D package, exterior 150k/4096, simplified by `scripts/nasa_views_glb.mjs` (50 % triangles, WebP ≤ 1024 px, meshopt, metres) | CC0 (Open Access API + object page) (`cc0`) | the Moon rocks tray, NASA hardware group | 1.8 MB |
| Sample facts for 15016, 60025, 76535, 70017, 65035 | Lunar Sample Compendium (C. Meyer, NASA JSC); no entry was found for 79115 | Public domain (`pd`) | the Moon rocks tray, under each rock's story | text |

Total 4.3 MB. **Skipped:** LROC NAC crops of the Apollo sites. The PDS RDR mosaics (`NAC_ROI_APOLLO11*`) are 0.2–2 GB
`.IMG` files at 0.4 m/px (the 5 m/px versions are too coarse to see hardware); cutting crops from them by byte range was
not practical in this round (QuickMap / website JPGs are not used: not the PDS). Also skipped for licence reasons: JAXA,
ISRO, CNSA, the UNESCO feed, GVP, Seshat, OSM.

**Checks.** `backend/tests/test_open_data.py` (the gate, chart parsing, the new kinds, the route, the Archaeology data
and its wording), `backend/tests/test_moon_views.py` (API, paths, licences, manifest), `frontend/tests/open_data.test.js`
and `moon_views.test.js`. Render check without the app: `node frontend/tests/fixtures/render_open_data.mjs <out.html>`
writes the real charts into a static page for a headless screenshot.

## Lesson step (course.json)

```json
{"type": "video", "media": "hammer_feather", "say": "Hammer or feather: which lands first?", "reveal": "Both at once. No air to slow the feather."}
```

1. CAPCOM says `say`.
2. The kid gets one big "Watch (N min)" button and a "Skip" button. Voice works too: "watch" or "skip".
3. The video plays.
4. The attempt (`input.video = {watched, seconds, skipped?, offline?}`) always passes, and the reply says `reveal`.
5. Next.

`content.check()` makes sure `media` is in the catalog and that `say` and `reveal` exist and are at most 20 words
each. Text that is neither watch nor skip is ignored, never counted as a miss.

## Cache (backend, dev and desktop alike)

- The backend downloads; the renderer only ever talks to our origin.
- The cache lives in `CACHE_DIR/video`, which is the per-user app data folder on the desktop and
  `backend/data/video_cache` in a dev checkout.
- Downloads resume from a `.part` file, are checked for size (and sha256), and are renamed into place atomically.
- The cap is `VIDEO_CACHE_MB` (default 1024). When it is reached, the least recently played file goes first. Pinned
  files are never evicted.
- On first online launch the pinned files download in the background: one at a time, slowly, and paused while a
  mission clock ticks or a video streams. If the computer is offline, the backend tries again every 5 minutes.
- Any other NASA file streams through the backend on its first play and is cached at the same time. A file the
  desktop's video pack (`VIDEO_PACK_DIR`) already has is copied from it and served at once, never streamed; when the
  stream fails but the background copy has landed, that copy is served. `available` says "cached" for a video the
  pack has, even before it is copied, so it plays offline from the first launch.
- A `pack_file` comes only from the video pack: without the pack it is "offline" (its Watch how button stays hidden),
  `/file` answers 503, and it does not count in Settings → Videos ("X of N lesson videos ready").
- TLS: the backend checks NASA hosts against certifi's roots plus Let's Encrypt's intermediates
  (`backend/data/video/intermediates.pem`, `video.tls()`), because `svs.gsfc.nasa.gov` has sent its leaf certificate
  without the intermediate since 2026-11-16. Browsers fetch the missing one; Python does not, so `phases_loop` failed
  to download and stream (HTTP 502) until this.
- Settings → Videos shows "X MB saved" and "Hold to clear saved videos" (`GET`/`DELETE /api/video/cache`): a 3-second
  hold like Reset and the grown-up gate (`bindHold` in `frontend/src/reset.js`); a click does nothing. The copies come
  back from the installed video pack when needed.
- `VIDEO_PREFETCH=0` turns off the background download (the tests do this). `VIDEO_OFFLINE=1` makes the backend act
  offline.

## Desktop (Electron)

- `permissions.js` allows only the youtube-nocookie `/embed/` frame and its player traffic:
  - `www.youtube.com`, `s.ytimg.com` and `i.ytimg.com`;
  - `*.googlevideo.com`;
  - the player's art by path on `www.gstatic.com/youtube/`, `ssl.gstatic.com/docs/picker/images/youtube_`,
    `fonts.gstatic.com` and `yt3.ggpht.com`;
  - YouTube's BotGuard attestation (0.3.11): the script `www.google.com/js/th/*.js` (as a script only) and its Web
    Anti-Abuse call `jnn-pa.googleapis.com/$rpc/google.internal.waa.v1.Waa/*` (xhr / fetch only). Blocked, the embed
    shows "Sign in to confirm you're not a bot" every time. Allowed, it can still show that card when YouTube distrusts
    the network (measured 2026-11-17 on a home connection: real Chrome too); the watchdog above handles that case.
- A YouTube page never loads as the window or as a frame.
- NASA hosts are not allowed in the renderer.
- Mic and camera stay with our origin.
- Links out of the player go through the grown-up gate (`gate.js`): the page shows a 3-second hold button, and only
  that opens the system browser.
- Referer: the embed plays from `http://127.0.0.1:<port>` as it is (measured in Electron 44.10). The
  `Referer: https://ai.whissle.outpostluna/` fallback is behind `OUTPOST_YT_REFERER=1`.
- `OUTPOST_MUTE_AUDIO=1` mutes the app for silent runs.

## Voice

While a video plays it joins the floor's crew channel, so the ear is gated and ducked as it is for crew clips. Only
"pause", "play", "skip" and "stop" work. The client (`media/commands.js`) handles them, and so does the router's
`video` screen (`turn_router.VIDEO_CMDS`). Other voice intents and session `say` / `play` / `answer` decisions are
dropped until the overlay closes. On a keyboard or remote, Esc or B closes the overlay; K or the controller's Back
button pauses and plays.

## Mute (integ/v1)

The top bar's Mute (`frontend/src/mute.js`: the button, Shift+M, voice "mute" / "unmute") covers the player too:
our `<video>` opens muted while the app is muted and follows `outpost:mute` while it plays; the YouTube embed opens
with `mute=1` and gets the IFrame API's `mute` / `unMute` on `outpost:mute`. `frontend/tests/e2e/mute_e2e.py` checks
it, with the voice floor and Web Audio.

