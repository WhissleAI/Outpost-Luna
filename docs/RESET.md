# Reset Outpost Luna

Settings → **Reset** is the danger zone. It is always the last item in the Settings sidebar, below Help, after a thin
divider; it turns the warning colour only when it is hovered or selected. Cadets links to it too ("Start over with a
new cadet? Reset"). Keyboard (Alt+A, the arrows, Enter) and a controller (D-pad, A) reach it like any other section.
It erases what the app saved on this computer, at one of two levels.

| | Start over | Reset everything |
|---|---|---|
| Call signs and every cadet (profiles) | erased | erased |
| Lessons, patches, explorer unlocks, the check ride | erased | erased |
| Missions flown, debriefs, the first-mission briefing seen | erased | erased |
| Prefs: voice, theme, Mute, expressiveness, the recorded voice, captions, text size, gestures and their calibration, coach marks seen, the tour seen | erased | erased |
| The opt-in voice-guide log (turn log) | erased | erased |
| Spoken-line cache (TTS) | erased | erased |
| Live server state: missions, sessions, check rides, standing orders | erased | erased |
| Saved NASA videos, embedding vectors, `hf/` | kept | erased |
| First-run downloads (models, voice pack, crew audio) | kept | erased (a hook: today they are bundled read-only) |
| Logs, `ports.json`, `children.json` | kept | kept |

## Safety

- **A confirm view** lists exactly what goes and what stays, and Cancel has focus first.
- **The button must be held for 3 seconds**: "Hold to start over" / "Hold to reset everything". This is the grown-up
  gate's pattern. Any of these works:
  - the mouse, touch or a pen;
  - Enter or Space, held;
  - a controller's A button, held while the button has focus.

  A click, or a hold shorter than 3 s, does nothing.
- **Esc or Cancel always backs out.**
- **Voice can open it but never finish it.** "Reset", "reset the app" or "reset everything" opens the Reset panel
  with both options, and the one asked for has focus. The router sends these phrases to the client's a11y handler.
  Only the hold resets.

## How it works

1. **The page** (`frontend/src/reset.js`) calls `POST /api/reset?level=start|all` with the header `X-Outpost-Reset: 1`.
2. **The backend** (`backend/app/reset.py`) accepts the request only from our own page: its `Origin` must be this host
   or a configured dev origin, and it must carry that header. A cross-site page can't send the header without a CORS
   preflight, which we refuse. The backend then:
   - empties its per-user folders, taken from the settings, never hard-coded:
     - `turnlog`, `tts` (both levels);
     - `video`, `vectors` (`all` only);
   - clears its in-memory state;
   - calls `reset_downloaded_assets()` for `all`;
   - returns a one-time token, valid for 60 s.
3. **The page** removes every `outpost*` / `atm-*` / `atm:*` key from localStorage and sessionStorage, and deletes its
   IndexedDB databases. Then:
   - in a browser (the dev stack), it reloads;
   - in the desktop app, it navigates to `/__outpost/reset?level=…&token=…`.
4. **The desktop shell** (`desktop/main/reset.js`, wired in `main.js`'s `will-navigate`) stops that navigation, then:
   1. confirms the token with `GET /api/reset/confirm`, and does nothing unless the backend confirms the same level;
   2. stops the backend and the model server (the existing `stopAll`), so Windows can delete files a child held open;
   3. runs `session.clearStorageData` and `clearCache`;
   4. deletes the level's folders under `app.getPath("userData")`:
      - `cache/tts` and `cache/turnlog` for Start over;
      - `cache/` and `hf/` for Reset everything;
      - joined with `path.win32` / `path.posix`, using `rmSync` with retries;
   5. logs the reset in `logs/main.log` (`logs/` and `metrics/`, the local diagnostics, are kept: `docs/DIAGNOSTICS.md`);
   6. calls `app.relaunch(); app.exit(0)`.

   If the shell doesn't relaunch within 8 s (an older shell), the page reloads itself.

**Where the data lives:**
- macOS: `~/Library/Application Support/Outpost Luna/`.
- Windows: `%APPDATA%\Outpost Luna\` (Electron's `userData`). Nothing of ours is in `%LOCALAPPDATA%` except the
  installed program, which a reset never touches.

## First-run downloads

"Reset everything" deletes the first-run downloads (`<userData>/assets/`: the ear, tagger, embedder, voice pack, crew
audio, videos, the Steer voice, staged updates, rollback copies, the cached remote manifest). The next launch runs the
first-run download again (or "Import offline pack").
- `desktop/main/reset.js`: `downloadedAssetDirs()` adds `<userData>/assets` to the `all` plan, and `performReset`
  calls `clearAssets` (main.js: `assets.clearAll(store.dir)`, which also covers an `OUTPOST_ASSETS_DIR` override)
  after the children are stopped (Windows file locks).
- `backend/app/reset.py`: `reset_downloaded_assets()` reports `settings.assets_dir` but deletes nothing itself (the
  model server has those files open, and the reset can still be refused).

## Tests

- **backend:** `tests/test_reset.py`: what each level empties; the in-memory state; who may ask; the one-use token;
  voice routing.
- **desktop:** `main/reset.test.js`, on darwin and win32:
  - the folders for each level, and that logs / ports / pids are never deleted;
  - the order: confirm → stop → storage → delete → relaunch;
  - nothing happens without the backend's confirmation;
  - an EBUSY lock is retried, then reported.
- **frontend:** `tests/reset.test.js`: the keys cleared; the copy; the backend first, then the desktop hand-over;
  voice only opens the panel.
- **e2e:** `tests/e2e/reset_e2e.py`:
  - finding it: Reset is the last sidebar item below Help, with a divider and no warning colour at rest; the Cadets
    link goes there; the keyboard and a controller reach it; voice "reset" opens the panel; none of these erases;
  - make progress, then Start over: the app comes back at the call-sign screen, the spoken-line cache and turn log
    are gone, and the saved video, the vectors and the bundled media stay;
  - Reset everything: every cache is empty.
- **robustness matrix:** `reset` is the last change in every row of `robustness_e2e.py`, so a reset is tried while a
  video, a lesson, a mission and the rest are open.
