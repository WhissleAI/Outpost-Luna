"""[arch QA 0.5.2] The Archaeology flow defects, end to end in the real UI (typed only, silent, headless).

  1. a typed wrong word on a keywords / intent step is a miss with a hint ("Not the word I need…"), never a silent
     "Didn't catch that"; the ladder climbs (rung 2: the words on the card) and the answer is shown after 3 misses;
     typed filler ("um") is still ignored;
  2. the two describe steps show the picture they ask about;
  3. no Moon words on a keywords step ("radio practice", "Say the order back") or in the lesson hello ("cadet");
  4. the map lands on the course's region (not the continent), with Mesa Verde's nine pins fanned out round it, and
     zoomed far out they fold into one count pin;
  7. Moonrise at Chimney Rock opens on the Moon, then Earth, then flies to Chimney Rock;
  8. a wrong guess is acknowledged ("You guessed: …"); a decide step's other call offers Try again; the tree-ring
     reveal slides the beam to the year.

    backend (port 8531): OUTPOST_DEV_COURSE=archaeology ACTIVE_COURSE_FILE=<f> LUNA_DATA_DIR=<d> uv run uvicorn app.main:app --port 8531
    vite (port 5531): BACKEND_URL=http://127.0.0.1:8531 npx vite --port 5531
    cd backend && uv run --with playwright==1.58.0 python ../frontend/tests/e2e/arch_qa_e2e.py --base http://localhost:5531 [--out DIR]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent)]
from playwright.sync_api import sync_playwright  # noqa: E402
from silent import LAUNCH_ARGS, silence  # noqa: E402

results: list[bool] = []
WHERE = "window.__outpost.academyTest.where"


def check(ok, msg):
    results.append(bool(ok)); print(("  ok  " if ok else "  FAIL ") + msg, flush=True)
    return bool(ok)


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


def panel(pg):
    return pg.evaluate("""() => { const p = document.getElementById('aPanel'); const g = s => [...p.querySelectorAll(s)].map(e => e.innerText.trim()).filter(Boolean).join(' / ');
      return { fb: g('#aFeedback'), how: g('.a-how'), intro: g('.a-intro'), phrase: g('.a-phrase'), prompt: g('.a-prompt'),
               text: p.innerText, img: [...p.querySelectorAll('.a-step .a-photo img')].map(i => ({ src: i.getAttribute('src'), ok: i.complete && i.naturalWidth > 0 })),
               next: !!document.getElementById('aNext'), retry: !!document.getElementById('aRetry') }; }""")


def typed(pg, t, wait=1600):
    pg.fill("#q", t); pg.press("#q", "Enter"); pg.wait_for_timeout(wait)


def open_lesson(pg, lid, step=None):
    if until(pg, f"{WHERE}.view === 'lesson'", 300):
        pg.click("#aBack"); until(pg, "() => !!document.querySelector('.apanel.is-map .mp-card')", 8000)
    pg.locator(f'.route .pin[data-l="{lid}"]').first.click(); pg.wait_for_timeout(700)
    if not until(pg, f"{WHERE}.view === 'lesson'", 300):   # the selected pin opens on its first tap; another selects
        pg.click(f'#aStart[data-l="{lid}"]')
    until(pg, f"{WHERE}.view === 'lesson' && {WHERE}.lesson === {json.dumps(lid)}", 10000)
    if step is not None:
        pg.evaluate(f"() => window.__outpost.academyTest.step({step})"); pg.wait_for_timeout(900)


def shot(pg, out, name):
    if out:
        pg.screenshot(path=str(Path(out) / f"{name}.png"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:5531")
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    if a.out:
        os.makedirs(a.out, exist_ok=True)
    exe = sorted(glob.glob(str(Path.home() / "Library/Caches/ms-playwright/chromium_headless_shell-*/chrome-*/chrome-headless-shell")))
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=exe[-1] if exe else None, headless=True, args=LAUNCH_ARGS)
        ctx = b.new_context(viewport={"width": 1440, "height": 900}); silence(ctx)
        ctx.add_init_script("window.__outpostTest = true;")
        # every caption line the app shows (it speaks each one): the "cadet" check reads these
        ctx.add_init_script("""window.__caps = []; addEventListener('DOMContentLoaded', () => { const b = document.getElementById('captionBar');
          if (b) new MutationObserver(() => { const t = b.innerText.trim(); if (t && window.__caps[window.__caps.length - 1] !== t) window.__caps.push(t); })
            .observe(b, { childList: true, subtree: true, characterData: true }); });""")
        pg = ctx.new_page()
        errs, said = [], []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.on("request", lambda r: said.append(json.loads(r.post_data or "{}").get("text", "")) if "/api/tts" in r.url and r.method == "POST" else None)
        pg.goto(a.base)
        pg.wait_for_selector("#aCsIn", timeout=60000); pg.fill("#aCsIn", "Zed"); pg.click("#aCsGo")
        if until(pg, "() => !!document.querySelector('#aPanel .a-crs-opt[data-crs=archaeology]')", 15000):
            with pg.expect_navigation(timeout=60000):
                pg.click("#aPanel .a-crs-opt[data-crs=archaeology]")
        pg.wait_for_selector(".apanel.is-map .mp-card", timeout=60000)

        # 4. the map: the region, a fan round Mesa Verde; far out, one count pin
        pg.wait_for_timeout(2600)
        m = pg.evaluate("""() => { const g = window.__outpost.globe, pins = [...document.querySelectorAll('.route .pin')].filter(e => getComputedStyle(e).visibility !== 'hidden');
          const pr = g.project(37.18, -108.49); const d = pins.map(e => { const r = e.getBoundingClientRect(), s = document.getElementById('stage').getBoundingClientRect();
            return Math.hypot(r.left + r.width / 2 - s.left - pr.x, r.top + r.height / 2 - s.top - pr.y); });
          return { dist: g.distance, collapsed: g.route.collapsed.length, shown: pins.length, far: Math.max(...d) }; }""")
        shot(pg, a.out, "qa_map_region")
        check(m["dist"] < 2 and m["collapsed"] == 0 and m["shown"] == 10, f"#4 the map lands on the region with every pin fanned out {m}")
        check(m["far"] < 220, f"#4 every pin within ~200 px of Mesa Verde (was flung to Mexico) {round(m['far'])}px")
        pg.evaluate("() => window.__outpost.globe.flyTo(37.18, -108.49, 4.2)"); pg.wait_for_timeout(2200)
        c = pg.evaluate("() => ({ c: window.__outpost.globe.route.collapsed, btn: !!document.querySelector('.route .route-cluster:not([hidden])') })")
        shot(pg, a.out, "qa_map_far")
        check(c["c"] and c["c"][0]["n"] == 9 and c["btn"], f"#4 zoomed out: one count pin for Mesa Verde's nine lessons (Chimney Rock keeps its own pin) {c}")
        pg.click(".route .route-cluster:not([hidden])"); pg.wait_for_timeout(2200)
        check(pg.evaluate("() => window.__outpost.globe.distance") < 2, "#4 the count pin zooms back in to the region")

        # 1. keywords step: typed wrong words are misses with hints, filler is ignored, then the answer is shown
        open_lesson(pg, "archaeology:layers", 3)
        f0 = panel(pg)
        check(not any(w in (f0["how"] + f0["intro"]).lower() for w in ("radio", "order back")), f"#3 the keywords step's line is not the Moon's radio drill: {f0['how'] or f0['intro']!r}")
        t0 = time.time()
        typed(pg, "um")
        fu = panel(pg)["fb"]   # never a miss: at most the step again (the playtest round's typed nudge), never "Not the word"
        check("Not the word" not in fu and "card" not in fu.lower(), f"#1 typed filler ('um') is not a miss: {fu!r}")
        typed(pg, "history")
        f1 = panel(pg)
        check("Not the word" in f1["fb"] or "Not quite" in f1["fb"], f"#1 typed 'history' is a miss with a hint: {f1['fb']!r}")
        typed(pg, "geology")
        f2 = panel(pg)
        check(f2["fb"] and "card" in f2["fb"].lower() and f2["phrase"], f"#1 a second miss climbs the ladder (the words on the card): {f2['fb']!r} {f2['phrase']!r}")
        pg.wait_for_timeout(max(0, int((21 - (time.time() - t0)) * 1000)))
        typed(pg, "geology", 2000)
        f3 = panel(pg)
        shot(pg, a.out, "qa_keywords_shown")
        check(f3["fb"].startswith("Here it is.") and "Right." not in f3["fb"] and f3["next"], f"#1/#8 the third miss shows the answer, without 'Right.': {f3['fb']!r}")

        # 1. intent step: "Colorado" / "show me Denver" are tries
        open_lesson(pg, "archaeology:what_is", 1)
        typed(pg, "Colorado")
        f = panel(pg)
        check(f["fb"] and "catch" not in f["fb"].lower(), f"#1 typed 'Colorado' on the find step gets a hint: {f['fb']!r}")

        # 8. a wrong guess is acknowledged; 3. no "cadet" in the hello
        open_lesson(pg, "archaeology:what_is", 0)
        pg.click('#aInput [data-c="treasure"]'); pg.wait_for_timeout(1500)
        f = panel(pg)
        check(f["fb"].startswith("You guessed: Treasure"), f"#8 a wrong guess is acknowledged: {f['fb']!r}")
        caps = pg.evaluate("() => window.__caps || []")
        check(any("Here we go." in c for c in caps) and not [c for c in caps if "cadet" in c.lower()],
              f"#3 the lesson hello says 'Here we go.', never 'cadet' ({[c for c in caps if 'here we go' in c.lower()][:2]})")

        # 8. decide: the other call keeps its reason and offers Try again
        open_lesson(pg, "archaeology:what_is", 4)
        pg.click('#aInput [data-c="take"]'); pg.wait_for_timeout(1500)
        f = panel(pg)
        shot(pg, a.out, "qa_decide_retry")
        check(f["retry"] and f["next"] and "loses its place" in f["fb"], f"#8 decide's other call: reason + Try again + Next {f['fb']!r}")
        pg.click("#aRetry"); pg.wait_for_timeout(800)
        check(not panel(pg)["next"] and until(pg, f"{WHERE}.step === 4 && !{WHERE}.waitingNext", 2000), "#8 Try again reopens the same step")

        # 2. the describe steps show their picture
        for lid, name in (("archaeology:survey", "reservoir"), ("archaeology:stuff", "walls")):
            open_lesson(pg, lid, 4)
            pg.wait_for_timeout(1200)
            f = panel(pg)
            shot(pg, a.out, f"qa_describe_{name}")
            check(f["img"] and all(i["ok"] for i in f["img"]), f"#2 {lid} describe step shows its picture {f['img']} ({f['prompt']!r})")

        # 8. the tree-ring reveal moves the beam to the year
        open_lesson(pg, "archaeology:dating", 1)
        t0 = time.time()
        for k in range(2):
            pg.click("#aInput .ar-lock"); pg.wait_for_timeout(1300)
        pg.wait_for_timeout(max(0, int((21 - (time.time() - t0)) * 1000)))
        pg.click("#aInput .ar-lock"); pg.wait_for_timeout(1500)
        yr = pg.evaluate("() => (document.querySelector('#aInput .ar-year b') || {}).textContent")
        shot(pg, a.out, "qa_rings_shown")
        check(yr == "1275", f"#8 the ring reveal slides the beam to 1275 (it shows {yr})")

        # 7. the Moon -> Earth bridge
        open_lesson(pg, "archaeology:chimney_rock")
        pg.wait_for_timeout(600)
        br = pg.evaluate("() => window.__outpost.globe.bridging")
        shot(pg, a.out, "qa_bridge_moon")
        check(br == "moon", f"#7 Chimney Rock opens on the Moon ({br!r})")
        ok = until(pg, "() => !window.__outpost.globe.bridging && window.__outpost.globe.distance < 2", 8000)
        pg.wait_for_timeout(1500)
        shot(pg, a.out, "qa_bridge_earth")
        check(ok, "#7 … then Earth, flying in to Chimney Rock")

        check(not errs, f"no page errors {errs[:3]}")
        b.close()
    print(f"{sum(results)}/{len(results)} checks")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
