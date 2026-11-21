"""A course switch gets the course's videos in the background, end to end (app/video.py kick, course_switch.js).

The Archaeology pack (v2) carries its five NASA videos. Before, they reached the video cache only at backend startup,
so after a switch they streamed on first play (and needed the internet). Now, in a fresh browser profile:

  1. first-run pick: Archaeology downloads (the backend's local-file fallback, COURSE_PACK_SRC, the real sha256-checked
     pack), the app reloads on it, and the switch copies its five videos into the cache with no network (VIDEO_PREFETCH=0
     here: nothing may come from NASA). A course video then plays from the saved file.
  2. Course storage (For grown-ups, behind the hold) says "All 5 videos saved."
  3. while videos are on their way (the progress answer, slowed with a route): the chip keeps its name and shows a thin
     progress line + "Getting its videos… 40%" in its label; Course storage shows "2 of 5 (40%)" with a bar; then
     both go quiet once done.
  4. a video still downloading opens a calm "still downloading" card (no stream), and plays by itself once saved.
  5. the chip switches to the Moon (unchanged: no progress, nothing downloading), and back to Archaeology after the
     video cache was cleared: the chip switch copies the videos again.

    backend (port 8853): COURSE_PACK_SRC=<src> COURSE_PACKS_DIR=<packs> ACTIVE_COURSE_FILE=<f> LUNA_DATA_DIR=<data> \\
        CACHE_DIR=<cache> VIDEO_PREFETCH=0 uvicorn app.main:app --port 8853
    vite (port 5853) with BACKEND_URL=http://127.0.0.1:8853
    uv run --no-project --with playwright==1.58.0 python frontend/tests/e2e/course_switch_prefetch_e2e.py \\
        --base http://localhost:5853 --api http://127.0.0.1:8853 --packs <packs> --out <shots>
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright
_d = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [_d, os.path.join(_d, "..", "..", "tools")]
import silent  # noqa: E402,F401
from silent import LAUNCH_ARGS, silence  # noqa: E402

results: list[tuple[bool, str]] = []
VID = "arch_lidar_space"
OPEN = f"() => {{ window.__outpost.video.openVideo('{VID}', {{context: 'library'}}); }}"
ON_MAP = "() => document.body.dataset.aview === 'map'"
PICK = "() => document.body.dataset.aview === 'home' && !!document.querySelector('#aPanel .a-crs-opt')"
CHIP = "() => { const c = document.getElementById('courseChip'); return c ? {text: c.textContent, dl: c.dataset.dl ?? null, label: c.getAttribute('aria-label'), hidden: c.hidden} : null; }"


def ok(cond, what):
    results.append((bool(cond), what))
    print(("PASS " if cond else "FAIL ") + what, flush=True)
    return bool(cond)


def until(pg, js, ms=10000):
    t = time.time() + ms / 1000
    while time.time() < t:
        try:
            if pg.evaluate(js):
                return True
        except Exception:  # noqa: BLE001  (a reload in flight)
            pass
        pg.wait_for_timeout(150)
    return False


def call(api, path, method="GET", body=None):
    req = urllib.request.Request(api + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, None


def api_until(a, path, test, s=30):
    t = time.time() + s
    last = None
    while time.time() < t:
        _, last = call(a.api, path)
        if last is not None and test(last):
            return True, last
        time.sleep(0.3)
    return False, last


def shot(pg, out, name):
    if out:
        try:
            pg.screenshot(path=str(Path(out) / f"{name}.png"), timeout=60000)
        except Exception as e:  # noqa: BLE001
            print("  (screenshot failed:", str(e)[:80], ")")


def hold(pg, sel, ms=3400):
    box = pg.evaluate("s => { const q = document.querySelector(s).getBoundingClientRect(); return [q.x + q.width / 2, q.y + q.height / 2]; }", sel)
    pg.mouse.move(*box)
    pg.mouse.down()
    pg.wait_for_timeout(ms)
    pg.mouse.up()


def course_storage(pg):
    """Settings → For grown-ups (the 3-second hold) → Course storage."""
    pg.evaluate("() => dispatchEvent(new CustomEvent('outpost:course-storage'))")
    until(pg, "() => !!document.querySelector('.a11y-panel:not([hidden]) [data-gu-open], [data-crs-store]')", 5000)
    if pg.evaluate("() => !!document.querySelector('.a11y-panel:not([hidden]) [data-gu-open]')"):
        hold(pg, ".a11y-panel:not([hidden]) [data-gu-open]")
    return until(pg, "() => !!document.querySelector('[data-crs-row=archaeology]')", 6000)


def note(pg):
    return pg.evaluate("() => { const n = document.querySelector('[data-crs-row=archaeology] .crs-note'); return n ? n.textContent : ''; }")


def reset(a):
    call(a.api, "/api/courses/active", "POST", {"id": "moon"})
    call(a.api, "/api/courses/packs/archaeology/remove", "POST")
    shutil.rmtree(Path(a.packs) / "course_archaeology", ignore_errors=True)
    call(a.api, "/api/video/cache", "DELETE")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:5853")
    ap.add_argument("--api", default="http://127.0.0.1:8853")
    ap.add_argument("--packs", required=True, help="COURSE_PACKS_DIR")
    ap.add_argument("--out", default="")
    ap.add_argument("--size", default="1024x640")
    a = ap.parse_args()
    errs: list[str] = []
    if a.out:
        Path(a.out).mkdir(parents=True, exist_ok=True)
    w, h = (int(x) for x in a.size.split("x"))
    exe = (sorted(glob.glob(os.path.expanduser("~/Library/Caches/ms-playwright/chromium_headless_shell-*/*/chrome-headless-shell"))) or [None])[-1]
    reset(a)
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=exe, headless=True, args=[*LAUNCH_ARGS, "--enable-unsafe-swiftshader"])
        ctx = b.new_context(viewport={"width": w, "height": h})
        silence(ctx)
        pg = ctx.new_page()
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(a.base + "/", wait_until="domcontentloaded")

        # 1. the first-run pick downloads the pack; the switch copies its videos (no network)
        ok(until(pg, "() => !!document.querySelector('#aCsGo')", 40000), "the call sign screen")
        pg.wait_for_timeout(600)
        pg.click("#aCsGo")
        ok(until(pg, PICK, 8000), "Pick your course")
        pg.click("#aPanel .a-crs-opt[data-crs=archaeology]")
        ok(until(pg, "() => document.documentElement.dataset.course === 'archaeology'", 60000), "Archaeology downloads and opens")
        ok(until(pg, ON_MAP, 30000), "the Archaeology map")
        done, pr = api_until(a, "/api/courses/active/progress", lambda d: d["videos"]["state"] == "done", 60)
        ok(done and pr["videos"]["ready"] == 5 and pr["videos"]["total"] == 5 and not pr["busy"],
           f"the switch saved the course's 5 videos from its pack, no network ({pr and pr['videos']})")
        _, av = call(a.api, f"/api/video/{VID}/available")
        ok(av and av["status"] == "cached", f"{VID} plays from the saved file ({av})")
        pg.evaluate(OPEN)   # not awaited: openVideo settles when the dialog closes
        ok(until(pg, "() => { const d = document.getElementById('vidDlg'); return d && d.open && !!d.querySelector('video.vid-video') && !d.dataset.card; }", 8000),
           "the course video opens in our player (no card, no stream)")
        ok(until(pg, "() => { const v = document.querySelector('#vidDlg video'); return v && v.readyState >= 1 && v.src.includes('/api/video/'); }", 15000),
           "the saved file loads")
        pg.evaluate("() => { const v = document.querySelector('#vidDlg video'); if (v) v.pause(); }")   # light on a loaded machine
        shot(pg, a.out, "video_saved_plays")
        pg.keyboard.press("Escape")
        until(pg, "() => !document.getElementById('vidDlg') || !document.getElementById('vidDlg').open", 3000)
        c = pg.evaluate(CHIP)
        ok(c and c["text"] == "Archaeology" and c["dl"] is None, f"done: the chip is just its name ({c})")

        # 2. Course storage says so
        if ok(course_storage(pg), "Course storage opens (For grown-ups, the hold)"):
            ok(until(pg, "() => /All 5 videos saved\\./.test(document.querySelector('[data-crs-row=archaeology]').textContent)", 6000),
               f"Course storage: 'All 5 videos saved.' ({note(pg)!r})")
            shot(pg, a.out, "storage_videos_saved")
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(300)

        # 3. on their way (the progress answers slowed): the chip and Course storage show it, then go quiet
        state = {"busy": True}

        def progress(route):
            resp = route.fetch()
            d = resp.json()
            if state["busy"]:
                d.update(busy=True, progress=0.4)
                d["videos"].update(state="downloading", ready=2, progress=0.4)
            route.fulfill(response=resp, body=json.dumps(d))

        def packs(route):
            resp = route.fetch()
            d = resp.json()
            for pk in d.get("packs", []):
                if pk["id"] == "archaeology" and state["busy"] and pk.get("videos"):
                    pk["videos"].update(state="downloading", ready=2, progress=0.4)
            route.fulfill(response=resp, body=json.dumps(d))
        pg.route("**/api/courses/active/progress", progress)
        pg.route("**/api/courses/packs", packs)
        pg.reload(wait_until="domcontentloaded")
        ok(until(pg, ON_MAP, 40000), "reload: the Archaeology map")
        ok(until(pg, "() => (document.getElementById('courseChip').dataset.dl || '') === '40'", 8000), "the chip shows the download (40%)")
        c = pg.evaluate(CHIP)
        ok(c["text"] == "Archaeology", "the chip's name never changes")
        ok(c["label"] == "Course: Archaeology. Getting its videos… 40%", f"the chip says it ({c['label']!r})")
        ok(pg.evaluate("() => getComputedStyle(document.getElementById('courseChip'), '::after').content !== 'none'"), "a thin progress line under the name")
        pg.mouse.move(5, 5)
        shot(pg, a.out, "chip_videos_40")
        pg.screenshot(path=str(Path(a.out) / "chip_videos_40_zoom.png"), clip={"x": 0, "y": 0, "width": 520, "height": 64}) if a.out else None
        if ok(course_storage(pg), "Course storage opens while downloading"):
            ok(until(pg, "() => /Getting its videos… 2 of 5 \\(40%\\)/.test(document.querySelector('[data-crs-row=archaeology]').textContent)", 6000),
               f"Course storage: 'Getting its videos… 2 of 5 (40%)' ({note(pg)!r})")
            ok(pg.evaluate("() => document.querySelector('[data-crs-row=archaeology] .crs-bar').getAttribute('aria-valuenow') === '40'"), "with a progress bar")
            shot(pg, a.out, "storage_videos_40")
            state["busy"] = False
            ok(until(pg, "() => /All 5 videos saved\\./.test(document.querySelector('[data-crs-row=archaeology]').textContent)", 8000),
               "Course storage: done, it says so (it polled)")
        state["busy"] = False
        ok(until(pg, "() => !('dl' in document.getElementById('courseChip').dataset)", 10000), "the chip goes quiet once done")
        pg.keyboard.press("Escape")
        pg.unroute("**/api/courses/active/progress")
        pg.unroute("**/api/courses/packs")
        pg.wait_for_timeout(300)

        # 4. a video still downloading: the calm card, then it plays by itself
        n = {"i": 0}

        def avail(route):
            n["i"] += 1
            if n["i"] <= 2:
                return route.fulfill(status=200, content_type="application/json", body=json.dumps({"id": VID, "status": "downloading"}))
            route.continue_()
        pg.route(f"**/api/video/{VID}/available", avail)
        pg.evaluate(OPEN)   # not awaited: openVideo settles when the dialog closes
        ok(until(pg, "() => document.getElementById('vidDlg').dataset.card === 'downloading'", 6000), "a video on its way: the 'downloading' card")
        txt = pg.inner_text("#vidDlg")
        ok("still downloading" in txt and "plays here as soon as it's ready" in txt, "it says so calmly")
        ok(pg.evaluate("() => !document.querySelector('#vidDlg video')"), "no stream meanwhile")
        shot(pg, a.out, "video_downloading_card")
        ok(until(pg, "() => !!document.querySelector('#vidDlg video.vid-video') && !document.getElementById('vidDlg').dataset.card", 10000),
           "saved: it plays by itself")
        pg.evaluate("() => { const v = document.querySelector('#vidDlg video'); if (v) v.pause(); }")
        pg.keyboard.press("Escape")
        pg.unroute(f"**/api/video/{VID}/available")
        pg.wait_for_timeout(400)

        # 5. the chip: to the Moon (unchanged), then back after the video cache was cleared (copies again)
        def chip_switch(to):
            pg.click("#courseChip")
            if not until(pg, f"() => !!document.querySelector('.crs-item[data-course={to}]')", 4000):
                return False
            pg.click(f".crs-item[data-course={to}]")
            until(pg, "() => !!document.querySelector('[data-crs-yes]')", 3000)
            pg.click("[data-crs-yes]")
            return until(pg, f"() => (document.documentElement.dataset.course || 'moon') === '{to}'", 30000) and until(pg, ON_MAP, 40000)
        ok(chip_switch("moon"), "the chip switches to the Moon")
        _, pr = call(a.api, "/api/courses/active/progress")
        ok(pr and pr["course"] == "moon" and not pr["busy"] and pr["pack"] is None and pr["videos"]["state"] == "none", f"the Moon needs nothing ({pr})")
        c = pg.evaluate(CHIP)
        ok(c["text"] == "Moon" and c["dl"] is None and c["label"] == "Course: Moon", f"the Moon's chip is as it was ({c})")
        _, cat = call(a.api, "/api/video/catalog")
        ok(cat and not any(v.get("course") for v in cat), "the Moon's video catalog is its own")
        call(a.api, "/api/video/cache", "DELETE")
        ok(chip_switch("archaeology"), "the chip switches back to Archaeology")
        done, pr = api_until(a, "/api/courses/active/progress", lambda d: d["videos"]["state"] == "done", 60)
        ok(done and pr["videos"]["ready"] == 5, f"the chip switch saved the videos again ({pr and pr['videos']})")
        shot(pg, a.out, "arch_after_chip_switch")
        b.close()
    reset(a)
    bad_errs = [e for e in errs if "WebGL" not in e]
    ok(not bad_errs, f"no page errors ({bad_errs[:3]})")
    bad = [w for c, w in results if not c]
    print(f"\n{len(results) - len(bad)}/{len(results)} passed")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
