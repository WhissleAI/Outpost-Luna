"""Archaeology, every workflow a first-time cadet walks, end to end (the 0.5.2 novice playtest: "the whole experience
in archaeology is a bit choppy"). tests/arch_playtest.test.js has the pure parts.

A fresh cadet picks a call sign, then Archaeology, and:
  1. the lesson map is the Four Corners region, close: every pin in view (they were spread over North America),
     Chimney Rock at its own point, the Next-up card naming the lesson's site ("Cliff Palace");
  2. lesson 1: "um, I don't know" gets a hint; a typed non-answer gets the step again (it was silence); the find step
     names no neighbour on the spot to find ("Four Corners" over Mesa Verde); a keywords step says "Say the word"
     (not "radio practice"); captions name the Field Director (not CAPCOM); the header never wraps;
  3. a reload mid-lesson picks up at the same step;
  4. My Brain: Field crew, big-idea stars, no Missions / CAPCOM; the call-sign screen is the course's own;
  5. For grown-ups: Progress without missions, Class lessons in Field School;
  6. small laptops (1280x720, 1024x640): the lesson card fits, the map keeps every pin in view;
  7. the chip switches to the Moon: its own words are back (Cadet, the Moon's hero), the Archaeology map gone.

    backend (port 8964): OUTPOST_DEV_COURSE=archaeology ACTIVE_COURSE_FILE=<f> LUNA_DATA_DIR=<d> CACHE_DIR=<c> \\
        uvicorn app.main:app --port 8964      (the course from source: its site names and big ideas)
    vite (port 5964) with BACKEND_URL=http://127.0.0.1:8964 (hmr off is fine; keep ws on: the session router)
    cd backend && uv run --with playwright==1.58.0 python ../frontend/tests/e2e/arch_workflows_e2e.py \\
        --base http://localhost:5964 [--out DIR]
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path[:0] = [os.path.dirname(os.path.abspath(__file__))]
from silent import LAUNCH_ARGS, silence  # noqa: E402

results: list[tuple[bool, str]] = []
W = "window.__outpost.academyTest.where"
MOON_WORDS = re.compile(r"\b(CAPCOM|Houston|Cadet|Commander|Missions?|outpost|Flight School|NASA's)\b")


def ok(cond, what):
    results.append((bool(cond), what))
    print(("PASS " if cond else "FAIL ") + what, flush=True)
    return bool(cond)


def until(pg, js, ms=10000):
    t = time.time() + ms / 1000
    while time.time() < t:
        try:
            v = pg.evaluate(js)
            if v:
                return v
        except Exception:  # noqa: BLE001  (a reload in flight)
            pass
        pg.wait_for_timeout(150)
    return None


def shot(pg, out, name):
    if out:
        try:
            pg.screenshot(path=str(Path(out) / f"{name}.png"), timeout=60000)
        except Exception as e:  # noqa: BLE001
            print("  (screenshot skipped:", str(e)[:80], ")")


PINS = """() => [...document.querySelectorAll('.route .pin')].map(b => { const r = b.getBoundingClientRect();
  return {l: b.dataset.l.split(':')[1], x: r.left + r.width / 2, y: r.top + r.height / 2,
          inView: r.left >= 0 && r.right <= innerWidth && r.top >= 48 && r.bottom <= innerHeight}; })"""
FB = "() => (document.getElementById('aFeedback') || {}).innerText || ''"


def type_(pg, t):
    pg.fill("#q", t)
    pg.press("#q", "Enter")


def hold(pg, sel, ms=3400):
    b = pg.query_selector(sel).bounding_box()
    pg.mouse.move(b["x"] + b["width"] / 2, b["y"] + b["height"] / 2)
    pg.mouse.down(); pg.wait_for_timeout(ms); pg.mouse.up()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:5964")
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    if a.out:
        Path(a.out).mkdir(parents=True, exist_ok=True)
    errs: list[str] = []
    exe = (sorted(glob.glob(os.path.expanduser("~/Library/Caches/ms-playwright/chromium_headless_shell-*/*/chrome-headless-shell"))) or [None])[-1]
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=exe, headless=True, args=[*LAUNCH_ARGS, "--enable-unsafe-swiftshader"])
        ctx = b.new_context(viewport={"width": 1440, "height": 900}); silence(ctx)
        ctx.add_init_script("window.__outpostTest = true;")
        pg = ctx.new_page()
        pg.on("pageerror", lambda e: errs.append(str(e)))

        # first run: call sign, then the pick -> Archaeology
        pg.goto(a.base)
        pg.wait_for_selector("#aCsIn", timeout=90000); pg.fill("#aCsIn", "Pulsar"); pg.click("#aCsGo")
        if until(pg, "() => !!document.querySelector('#aPanel .a-crs-opt[data-crs=archaeology]')", 15000):
            with pg.expect_navigation(timeout=60000):
                pg.click("#aPanel .a-crs-opt[data-crs=archaeology]")
        ok(until(pg, "() => !!document.querySelector('.apanel.is-map .mp-card')", 60000), "the Archaeology map")
        ok(pg.evaluate("() => (window.__outpost.course || {}).id") == "archaeology", "the app plays Archaeology")

        # 1. the map: the region, close; every pin in view; Chimney Rock at its own point; the site named
        pg.wait_for_timeout(3000)
        shot(pg, a.out, "aw_map")
        dist = pg.evaluate("() => window.__outpost.globe.distance")
        ok(dist < 1.3, f"the map looks at the region, close ({dist:.2f} globe radii; it was 4.2: the whole continent)")
        pins = pg.evaluate(PINS)
        ok(len(pins) == 10 and all(q["inView"] for q in pins), f"all 10 pins in view ({[q['l'] for q in pins if not q['inView']]} out)")
        mv = [q for q in pins if q["l"] != "chimney_rock"]
        cx, cy = sum(q["x"] for q in mv) / len(mv), sum(q["y"] for q in mv) / len(mv)
        ok(all(abs(q["x"] - cx) < 220 and abs(q["y"] - cy) < 220 for q in mv), "the nine Mesa Verde lessons sit together round the park")
        cr = next(q for q in pins if q["l"] == "chimney_rock")
        ok(cr["x"] - cx > 120, f"Chimney Rock sits east of the cluster, at its own point (dx {cr['x'] - cx:.0f}px)")
        ok("CLIFF PALACE" in pg.inner_text(".mp-card .eyebrow").upper(), "the Next-up card names the lesson's site (Cliff Palace)")
        pg.click('.route .pin[data-l="archaeology:dating"]'); pg.wait_for_timeout(1500)
        ok(abs(pg.evaluate("() => window.__outpost.globe.distance") - dist) < 0.05, "picking another pin keeps the view still")
        ok("LONG HOUSE" in pg.inner_text(".mp-card .eyebrow").upper(), "its card names Long House")

        # 2. lesson 1, as a hesitant typist
        pg.click('.route .pin[data-l="archaeology:what_is"]'); pg.wait_for_timeout(600); pg.click("#aStart")
        ok(until(pg, f"() => {W}.view === 'lesson'", 10000), "lesson 1 opens")
        pg.wait_for_timeout(1200)
        brief = pg.evaluate("() => document.getElementById('aBrief') ? document.getElementById('aBrief').textContent : ''")
        ok("CAPCOM" not in brief and "Houston" not in brief, "the brief has no CAPCOM / Houston")
        type_(pg, "um I don't know")
        ok(until(pg, f"() => ({FB})().trim().length > 0", 8000), f"'um, I don't know' gets a hint ({pg.evaluate(FB)!r})")
        hh = pg.evaluate("() => Math.round(document.querySelector('#aPanel .a-where').getBoundingClientRect().height)")
        ok(hh <= 20, f"the lesson header is one line ({hh}px)")
        pg.evaluate("() => window.__outpost.academyTest.step(1)"); pg.wait_for_timeout(2500)
        lab = pg.evaluate("() => { const l = document.getElementById('label'); return l && !l.hidden ? l.innerText : ''; }")
        ok("Four Corners" not in lab, f"the find step names no neighbour on the spot to find ({lab!r})")
        shot(pg, a.out, "aw_find_step")
        pg.evaluate("() => window.__outpost.academyTest.step(3)"); pg.wait_for_timeout(1500)
        body = pg.inner_text("#aPanel")
        ok("Say the word" in body and "radio" not in body.lower() and "order back" not in body, "the keywords step says 'Say the word' (not radio practice)")
        type_(pg, "dinosaur bones")
        ok(until(pg, f"() => /Name the field/.test(({FB})())", 8000), f"a typed non-answer gets the step again, not silence ({pg.evaluate(FB)!r})")
        who = until(pg, "() => (document.querySelector('#captionBar .cap-who') || {}).textContent", 8000) or ""
        ok(who in ("Field Director", "") and "CAPCOM" not in pg.inner_text("#captionBar"), f"captions name the Field Director ({who!r})")
        shot(pg, a.out, "aw_typed_nonanswer")
        type_(pg, "archaeology")
        ok(until(pg, "() => !!document.getElementById('aNext')", 8000), "the right word passes")

        # 3. a reload mid-lesson picks up at the same step
        pg.click("#aNext"); pg.wait_for_timeout(1200)
        at = pg.evaluate(W)
        pg.reload()
        until(pg, f"() => window.__outpost.academyTest && ({W}.view === 'lesson' || {W}.view === 'map')", 60000)
        pg.wait_for_timeout(2500)
        if pg.evaluate(W)["view"] == "map" and pg.query_selector("#aStart"):
            pg.click("#aStart"); pg.wait_for_timeout(1500)
        now = pg.evaluate(W)
        ok(now["view"] == "lesson" and now["lesson"] == at["lesson"] and now["step"] == at["step"], f"resume: the same step after a relaunch ({at['step']} -> {now})")

        # 6. small laptops: the lesson card fits
        for w, h in ((1280, 720), (1024, 640)):
            pg.set_viewport_size({"width": w, "height": h}); pg.wait_for_timeout(1200)
            fit = pg.evaluate("""() => { const p = document.getElementById('aPanel').getBoundingClientRect();
              return p.right <= innerWidth + 1 && p.bottom <= innerHeight + 1 && document.documentElement.scrollWidth <= innerWidth + 1; }""")
            ok(fit, f"{w}x{h}: the lesson card fits, no sideways scroll")
            shot(pg, a.out, f"aw_lesson_{w}x{h}")
        pg.click("#aBack"); pg.wait_for_timeout(2500)
        pins = pg.evaluate(PINS)
        ok(all(q["inView"] for q in pins), f"1024x640: every map pin in view ({[q['l'] for q in pins if not q['inView']]} out)")
        shot(pg, a.out, "aw_map_1024")
        pg.set_viewport_size({"width": 1440, "height": 900}); pg.wait_for_timeout(800)

        # 4. My Brain and the call-sign screen
        pg.click("#brainBtn"); pg.wait_for_timeout(1500)
        bt = pg.inner_text("#brain")
        ok("field crew" in bt.lower() and "Evidence" in bt and "Field Director" in bt, "My Brain: Field crew, big-idea stars, the Field Director")
        ok(not MOON_WORDS.search(bt), f"My Brain has no Moon words ({MOON_WORDS.findall(bt)})")
        shot(pg, a.out, "aw_brain")
        pg.click("#brain [data-bm-cs]"); pg.wait_for_timeout(1500)
        cs = pg.inner_text("#aPanel")
        ok("Mesa Verde" in cs and "Nobody's landed" not in cs and "Artemis" not in cs, "the call-sign screen is the course's own")
        shot(pg, a.out, "aw_callsign")
        pg.click("#aCsGo"); pg.wait_for_timeout(1500)

        # 5. For grown-ups
        pg.click("#a11yBtn"); pg.wait_for_timeout(800)
        pg.click(".a11y-panel:not([hidden]) button:has-text('For grown-ups')"); pg.wait_for_timeout(800)
        if pg.query_selector(".a11y-panel:not([hidden]) [data-gu-open]"):
            hold(pg, ".a11y-panel:not([hidden]) [data-gu-open]")
        until(pg, "() => /Course storage/.test(document.querySelector('.a11y-panel:not([hidden])').innerText)", 8000)
        gt = pg.inner_text(".a11y-panel:not([hidden])")
        ok("MISSIONS" not in gt.upper().split("PROGRESS", 1)[-1].split("CLASS LESSONS", 1)[0], "Progress: no missions in a course with none")
        ok("They show up in Field School next to the course's own." in gt and "next to NASA's" not in gt, "Class lessons sit in Field School")
        shot(pg, a.out, "aw_grownups")
        pg.keyboard.press("Escape"); pg.wait_for_timeout(500)

        # 7. the chip to the Moon: the Moon's own words come back
        pg.click("#courseChip")
        if until(pg, "() => !!document.querySelector('.crs-item[data-course=moon]')", 5000):
            pg.click(".crs-item[data-course=moon]"); until(pg, "() => !!document.querySelector('[data-crs-yes]')", 3000)
            pg.click("[data-crs-yes]")
            ok(until(pg, "() => (document.documentElement.dataset.course || 'moon') === 'moon' && !!document.querySelector('.apanel.is-map, #aPanel .mp-card')", 60000), "the chip switches to the Moon")
            pg.wait_for_timeout(2500)
            pg.click("#brainBtn"); pg.wait_for_timeout(1500)
            mt = pg.inner_text("#brain")
            ok("Cadet" in mt.title() and "CAPCOM" in mt, "the Moon's My Brain is as it was (Cadet, CAPCOM)")
            ok(pg.evaluate("() => window.__outpost.globe.distance") > 1.5, "the Moon's map is the whole Moon")
        else:
            ok(False, "the course chip lists the Moon")
        b.close()
    bad_errs = [e for e in errs if "WebGL" not in e]
    ok(not bad_errs, f"no page errors ({bad_errs[:3]})")
    bad = [w for c, w in results if not c]
    print(f"\n{len(results) - len(bad)}/{len(results)} passed")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
