"""The first-run course pick, end to end (docs/COURSES.md §4.10, frontend/src/course_pick.js).

A new cadet picks a call sign, then "Pick your course": the Moon (built in, starts now) and Archaeology (its line,
grades 9-12, its size). Each path, in a fresh browser profile:

  1. keys: focus starts on the Moon; Down reaches Archaeology; Enter downloads it (the backend's local-file fallback,
     COURSE_PACK_SRC, the real sha256-checked pack), the app reloads on Archaeology with the welcome, the chip names it.
  2. voice: "the moon" (typed in the voice bar, routed like speech) starts the Moon; "skip" does too.
  3. offline: said plainly, "get it later in For grown-ups → Course storage", Enter starts the Moon.
  4. School network mode (the user switch, <LUNA_DATA_DIR>/network.json): the same, with the school line.
  5. failed download (no source file): the same, with "didn't download".
  6. a second call sign later gets the same pick; a cadet who picked is never asked again.
  7. after first run with only the Moon installed, the course chip shows and its "Get more courses" opens For grown-ups
     (the hold) at Course storage.

Screenshots at 1440x900 and 1280x720 (the pick, the progress, a failure, the Archaeology welcome).

    backend (port 8487): COURSE_PACK_SRC=<src> COURSE_PACKS_DIR=<packs> ACTIVE_COURSE_FILE=<f> LUNA_DATA_DIR=<data> uvicorn …
    vite (port 5487) with BACKEND_URL=http://127.0.0.1:8487
    uv run --no-project --with playwright==1.58.0 python frontend/tests/e2e/course_pick_e2e.py --base http://localhost:5487 \\
        --api http://127.0.0.1:8487 --src <src> --packs <packs> --data <data> --out <shots>
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
# the tar the backend looks for in COURSE_PACK_SRC: the manifest entry's file name (a new version is a new name)
TAR = next(x["file"] for x in json.loads((Path(_d).parents[2] / "desktop/assets.manifest.json").read_text())["assets"]
           if x["id"] == "course_archaeology")


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


def post(api, path, body=None):
    req = urllib.request.Request(api + path, data=json.dumps(body or {}).encode(), method="POST", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def shot(pg, out, name):
    if not out:
        return
    for _ in range(2):
        try:
            pg.screenshot(path=str(Path(out) / f"{name}.png"), timeout=60000)
            return
        except Exception as e:  # noqa: BLE001
            print("  (screenshot retry:", str(e)[:80], ")")


PICK = "() => document.body.dataset.aview === 'home' && !!document.querySelector('#aPanel .a-crs-opt')"
FAIL = "() => !!document.querySelector('#aCrpMoon')"
ON_MAP = "() => document.body.dataset.aview === 'map'"
ACTIVE = "() => document.activeElement && (document.activeElement.dataset.crs || document.activeElement.id || '')"
STORED = "() => localStorage.getItem('outpost-course')"


def reset_backend(a):
    post(a.api, "/api/courses/packs/archaeology/remove")
    post(a.api, "/api/courses/active", {"id": "moon"})
    shutil.rmtree(Path(a.packs) / "course_archaeology", ignore_errors=True)


def new_page(b, a, w, h, offline=False):
    ctx = b.new_context(viewport={"width": w, "height": h})
    silence(ctx)
    if offline:   # the computer is offline (the backend on loopback still answers): navigator.onLine says so
        ctx.add_init_script("Object.defineProperty(Navigator.prototype, 'onLine', { get: () => false });")
    pg = ctx.new_page()
    pg.on("pageerror", lambda e: a.errs.append(str(e)))
    pg.goto(a.base + "/", wait_until="domcontentloaded")
    return ctx, pg


def to_pick(pg, a, label):
    """The call sign screen -> Start -> the course pick."""
    if not ok(until(pg, "() => !!document.querySelector('#aCsGo')", 40000), f"{label}: the call sign screen"):
        return False
    pg.wait_for_timeout(600)
    pg.click("#aCsGo")
    return ok(until(pg, PICK, 8000), f"{label}: Start opens 'Pick your course'")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:5487")
    ap.add_argument("--api", default="http://127.0.0.1:8487")
    ap.add_argument("--src", required=True, help="COURSE_PACK_SRC (holds the Archaeology tar)")
    ap.add_argument("--packs", required=True, help="COURSE_PACKS_DIR")
    ap.add_argument("--data", required=True, help="LUNA_DATA_DIR (School network mode's user switch)")
    ap.add_argument("--out", default="")
    ap.add_argument("--sizes", default="1440x900,1280x720")
    a = ap.parse_args()
    a.errs = []
    if a.out:
        Path(a.out).mkdir(parents=True, exist_ok=True)
    tar, hidden = Path(a.src) / TAR, Path(a.src) / (TAR + ".away")
    netf = Path(a.data) / "network.json"
    exe = (sorted(glob.glob(os.path.expanduser("~/Library/Caches/ms-playwright/chromium_headless_shell-*/*/chrome-headless-shell"))) or [None])[-1]
    sizes = [tuple(int(x) for x in s.split("x")) for s in a.sizes.split(",")]
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=exe, headless=True, args=[*LAUNCH_ARGS, "--enable-unsafe-swiftshader"])
        for w, h in sizes:
            first = (w, h) == sizes[0]
            print(f"-- {w}x{h}")
            reset_backend(a)
            # 1. the pick, then keys: Down to Archaeology, Enter: it downloads and the app reloads on it
            ctx, pg = new_page(b, a, w, h)
            if to_pick(pg, a, "keys"):
                txt = pg.inner_text("#aPanel")
                for s in ("Pick your course", "The Moon", "Junior Astronaut Academy", "grades 3-8 · Built in · starts now",
                          "Archaeology", "Field Archaeology: the Mesa Verde region", "grades 9-12 · 4.6 MB", "Skip"):
                    ok(s in txt, f"the pick shows: {s}")
                ok(until(pg, f"() => ({ACTIVE})() === 'moon'", 3000), "keys: focus starts on the Moon (Enter / A starts it)")
                ok(pg.evaluate("() => document.documentElement.scrollWidth <= innerWidth + 1"), "no sideways scroll")
                ok(pg.evaluate("""() => { const r = [...document.querySelectorAll('#aPanel .a-crs-opt, #aCrpSkip')].map(e => e.getBoundingClientRect());
                    return r.every(x => x.bottom <= innerHeight && x.right <= innerWidth && x.width > 0); }"""), "every option is on screen")
                pg.mouse.move(5, 5)
                shot(pg, a.out, f"pick_{w}x{h}")
                pg.keyboard.press("ArrowDown")
                if not until(pg, f"() => ({ACTIVE})() === 'archaeology'", 1500):
                    pg.keyboard.press("Tab")
                ok(until(pg, f"() => ({ACTIVE})() === 'archaeology'", 2000), "keys: Down (or Tab) reaches Archaeology")
                pg.keyboard.press("Enter")
                ok(until(pg, "() => document.documentElement.dataset.course === 'archaeology'", 30000), "Enter: Archaeology downloads and the app opens on it")
                ok(until(pg, ON_MAP, 30000), "the Archaeology map (no second call sign screen)")
                ok(pg.evaluate(STORED) == "archaeology", "the choice is stored for this call sign (outpost-course)")
                chip = pg.evaluate("() => { const c = document.getElementById('courseChip'); return c && !c.hidden ? c.textContent : ''; }")
                ok(chip == "Archaeology", f"the course chip names it ({chip!r})")
                ok(until(pg, "() => /Field School/.test(document.getElementById('modeAcademy').textContent)", 5000), "the tab says Field School")
                pg.wait_for_timeout(2500)
                shot(pg, a.out, f"pick_arch_welcome_{w}x{h}")
                # a reload never asks again
                pg.reload(wait_until="domcontentloaded")
                ok(until(pg, ON_MAP, 40000) and not pg.evaluate(PICK), "a cadet who picked is never asked again")
            ctx.close()
            reset_backend(a)

            # the progress view (a slow download: the poll shows it); shot only
            if a.out:
                ctx, pg = new_page(b, a, w, h)
                pg.route("**/api/courses/packs/archaeology/get", lambda r: r.fulfill(status=200, content_type="application/json", body='{"state":"queued"}'))
                n = {"i": 0}

                def slow(route):
                    n["i"] += 1
                    resp = route.fetch()
                    d = resp.json()
                    for pk in d.get("packs", []):
                        if pk["id"] == "archaeology" and n["i"] > 1:
                            pk.update(state="downloading", progress=0.42)
                    route.fulfill(response=resp, body=json.dumps(d))
                pg.route("**/api/courses/packs", slow)
                if to_pick(pg, a, "progress"):
                    pg.click("#aPanel .a-crs-opt[data-crs=archaeology]")
                    ok(until(pg, "() => /42%/.test(document.querySelector('#aPanel').innerText)", 8000), "the download shows real progress (42%)")
                    ok(until(pg, f"() => ({ACTIVE})() === 'aCrpCancel'", 2000), "keys: 'Start on the Moon instead' has focus")
                    pg.mouse.move(5, 5)
                    shot(pg, a.out, f"pick_progress_{w}x{h}")
                    pg.keyboard.press("Enter")
                    ok(until(pg, ON_MAP, 8000) and pg.evaluate(STORED) == "moon", "Enter on it: the Moon starts")
                ctx.close()

            if not first:
                continue
            # 2. voice: "the moon"; then "skip" for a second fresh cadet
            for said in ("the moon", "skip"):
                ctx, pg = new_page(b, a, w, h)
                if to_pick(pg, a, f"voice '{said}'"):
                    pg.fill("#q", said)
                    pg.press("#q", "Enter")
                    ok(until(pg, ON_MAP, 10000), f"voice '{said}': the Moon map")
                    ok(pg.evaluate(STORED) == "moon", f"voice '{said}': the Moon is stored for this call sign")
                    ok(pg.evaluate("() => document.documentElement.dataset.course || 'moon'") == "moon", "no switch, no reload")
                if said == "skip":
                    # 6. a second call sign later gets the same pick
                    pg.evaluate("() => window.__outpost.prefsApi.addProfile()")
                    pg.wait_for_load_state("domcontentloaded")
                    ok(to_pick(pg, a, "a second call sign"), "a second call sign gets the same pick")
                    pg.click("#aCrpSkip")
                    ok(until(pg, ON_MAP, 8000), "Skip: the Moon map")
                    # 7. after first run, Moon only: the chip shows, Get more courses opens For grown-ups
                    ok(until(pg, "() => { const c = document.getElementById('courseChip'); return c && !c.hidden && c.textContent === 'Moon'; }", 6000),
                       "after first run with only the Moon: the course chip shows")
                    pg.click("#courseChip")
                    ok(until(pg, "() => !!document.querySelector('.crs-card [data-crs-more]')", 3000), "the chip's list offers 'Get more courses'")
                    ok(until(pg, f"() => document.activeElement && document.activeElement.hasAttribute('data-crs-more')", 2000), "keys: focus on 'Get more courses'")
                    shot(pg, a.out, f"chip_moon_only_{w}x{h}")
                    pg.keyboard.press("Enter")
                    ok(until(pg, "() => !!document.querySelector('.a11y-panel:not([hidden]) [data-gu-open], .a11y-panel:not([hidden]) [data-crs-store]')", 5000),
                       "Get more courses opens For grown-ups (behind the hold)")
                    shot(pg, a.out, f"chip_get_more_{w}x{h}")
                ctx.close()

            # 3-5. offline, School network mode, a failed download: said plainly, then the Moon
            for why, line in (("offline", "You're offline, so Archaeology can't download. Starting on the Moon."),
                              ("school", "School network mode is on, so Archaeology can't download here. Starting on the Moon."),
                              ("failed", "Archaeology didn't download. Starting on the Moon.")):
                if why == "school":
                    netf.parent.mkdir(parents=True, exist_ok=True)
                    netf.write_text(json.dumps({"school_network": True}))
                    time.sleep(1.2)
                if why == "failed" and tar.exists():
                    tar.rename(hidden)
                try:
                    ctx, pg = new_page(b, a, w, h, offline=why == "offline")
                    if to_pick(pg, a, why):
                        pg.click("#aPanel .a-crs-opt[data-crs=archaeology]")
                        ok(until(pg, FAIL, 10000), f"{why}: the failure view")
                        txt = pg.inner_text("#aPanel")
                        ok(line in txt, f"{why}: says '{line}'")
                        ok("You can get it later in For grown-ups → Course storage." in txt, f"{why}: says where to get it later")
                        ok(until(pg, f"() => ({ACTIVE})() === 'aCrpMoon'", 2000), f"{why}: 'Start on the Moon' has focus")
                        pg.mouse.move(5, 5)
                        shot(pg, a.out, f"pick_{why}_{w}x{h}")
                        pg.keyboard.press("Enter")
                        ok(until(pg, ON_MAP, 8000), f"{why}: Enter starts the Moon")
                        ok(pg.evaluate(STORED) == "moon", f"{why}: the Moon is stored")
                        ok(not (Path(a.packs) / "course_archaeology").exists(), f"{why}: nothing was installed")
                    ctx.close()
                finally:
                    if why == "school":
                        netf.unlink(missing_ok=True)
                    if hidden.exists():
                        hidden.rename(tar)
            reset_backend(a)
        b.close()
    errs = [e for e in a.errs if "WebGL" not in e]
    ok(not errs, f"no page errors ({errs[:3]})")
    bad = [w for c, w in results if not c]
    print(f"\n{len(results) - len(bad)}/{len(results)} passed")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
