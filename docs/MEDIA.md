# NASA video (media v1)

Short NASA videos in lessons, the briefing and the debrief. NASA files play offline from a local cache in our own
player. NASA-channel YouTube uploads play as a youtube-nocookie embed when the computer is online. Every video gets a
predict → watch (or skip) → reveal step, and media never blocks a lesson.

## The catalog: `backend/data/video/catalog.json`

A list of entries:

| field | |
|---|---|
| `id` | lower_snake_case, unique |
| `title`, `concept`, `age` | what it is and who it's for |
| `source` | `nasa_file` (downloaded once, played offline) or `youtube` (stream only, never cached; YouTube policy III.E.1) |
| `youtube_id` | youtube only |
| `file_url`, `captions_url`, `poster_url` | nasa_file only. https on a NASA host. `.srt` is converted to WebVTT once. A missing `captions_url` means the video has no captions (or NASA's file is empty) |
| `bytes`, `sha256` | the download check (`prefetch` items must have `bytes`) |
| `duration_s` | sets the button label ("Watch (2 min)") and the watched threshold |
| `credit` | starts with "NASA". Shown under the player and in About → Videos |
| `music_credit` | the NASA source credits third-party music. Such a video plays from YouTube, never as a cached file |
| `prefetch` | pinned: downloaded on first online launch and never evicted |
| `fallback` | optional, a `nasa_file` id. The offline card offers it in place of this video |

`GET /api/video/catalog` serves it, and each entry also gets `cached`, `play_url`, `captions_src` and `poster_src`.
`app/video.py validate()` checks the contract, and the tests run it. To recheck every URL and refresh the sizes and
hashes, run `uv run python tools/video_catalog.py [--pin]` from `backend/`.

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
- Any other NASA file streams through the backend on its first play and is cached at the same time.
- Settings → Videos shows "X MB saved" and a Clear button (`GET`/`DELETE /api/video/cache`).
- `VIDEO_PREFETCH=0` turns off the background download (the tests do this). `VIDEO_OFFLINE=1` makes the backend act
  offline.

## Desktop (Electron)

- `permissions.js` allows only the youtube-nocookie `/embed/` frame and its player traffic:
  - `www.youtube.com`, `s.ytimg.com` and `i.ytimg.com`;
  - `*.googlevideo.com`;
  - the player's art by path on `www.gstatic.com/youtube/`, `fonts.gstatic.com` and `yt3.ggpht.com`.
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

