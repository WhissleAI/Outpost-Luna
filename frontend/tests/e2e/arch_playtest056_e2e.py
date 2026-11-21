"""[0.5.6] The owner's playtest of 0.5.5 (the Archaeology course), end to end in the real UI (typed only, silent, headless).

  1. The NPS rack card ("What If I Find an Artifact?") opens IN the app: the Lesson 1 source link is marked as a
     document kept with the course and its click opens both pages in the picture viewer (no web request, no popup);
     every other link in every lesson is marked as a web link (an arrow, "Opens in your web browser").
  2. An earned patch stays on the Earth map: at rest on its pin, and zoomed out (or while the map flies in) on the
     count pin that gathers Mesa Verde's nine lessons; and in the header strip.
  3. Pictures enlarge: the lesson photo opens big (zoom with +, Esc closes, focus comes back); the Lesson 2 lidar map's
     Enlarge opens the step itself, bigger, where taps count, the found rings show and Low sun works, also zoomed in.
  4. Lesson 1 names Mesa Verde once on the globe (it showed "Mesa Verde National Park" twice, above and below the ring).

    backend (port 8531): OUTPOST_DEV_COURSE=archaeology ACTIVE_COURSE_FILE=<f> LUNA_DATA_DIR=<d> uv run uvicorn app.main:app --port 8531
    vite (port 5531): BACKEND_URL=http://127.0.0.1:8531 npx vite --port 5531
    cd backend && uv run --with playwright==1.58.0 python ../frontend/tests/e2e/arch_playtest056_e2e.py --base http://localhost:5531 \\
        [--size 1280x720] [--out DIR]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("OUTPOST_DEV_COURSE", "archaeology")
ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "backend"), str(Path(__file__).resolve().parent)]
from playwright.sync_api import sync_playwright  # noqa: E402
from silent import LAUNCH_ARGS, silence  # noqa: E402
from app.academy import content, grade as g, vocab  # noqa: E402
from tools.handsfree_run import answer_for  # noqa: E402

results: list[bool] = []
WHERE = "window.__outpost.academyTest.where"
RACK = "https://www.nps.gov/subjects/archeology/upload/RackArtifactsVisitors_508.pdf"
LB = "window.__outpost.lightbox.state"
# visible labels on the globe that name Mesa Verde (the highlight label, guide marks, course markers)
MV_LABELS = """() => [...document.querySelectorAll('#label, .gd-label, .cm-label')].filter(e => /Mesa Verde/.test(e.textContent)).filter(e => {
  if (e.closest('[hidden], .is-hidden, .no-label')) return false; const s = getComputedStyle(e), r = e.getBoundingClientRect();
  return s.visibility !== 'hidden' && s.display !== 'none' && +s.opacity > 0.05 && r.width > 0; }).map(e => e.id || e.className)"""
PATCH_ON_GLOBE = """() => [...document.querySelectorAll('.route .pin.is-done, .route .route-cluster:not([hidden])')].some(e =>
  getComputedStyle(e).visibility !== 'hidden' && (e.style.opacity === '' || +e.style.opacity > 0.5) && !!e.querySelector('svg.patch.is-earned'))"""


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
        except Exception:  # noqa: BLE001
            pass
        pg.wait_for_timeout(150)
    return None


def shot(pg, out, name, size):
    if out:
        try:
            pg.screenshot(path=str(Path(out) / f"{name}_{size}.png"), timeout=60000)
        except Exception as e:  # noqa: BLE001
            print("  (screenshot skipped:", str(e)[:80], ")")


def to_map(pg):
    if until(pg, f"{WHERE}.view === 'lesson'", 300):
        pg.click("#aBack")
    pg.wait_for_selector(".apanel.is-map .mp-card", timeout=10000)


def open_lesson(pg, lid, step=None):
    to_map(pg)
    pg.evaluate(f"() => window.__outpost.academyTest.open({json.dumps(lid)})")
    until(pg, f"{WHERE}.view === 'lesson' && {WHERE}.lesson === {json.dumps(lid)}", 10000)
    if step is not None:
        pg.evaluate(f"() => window.__outpost.academyTest.step({step})"); pg.wait_for_timeout(900)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:5531")
    ap.add_argument("--size", default="1280x720")
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    W, H = (int(x) for x in a.size.split("x"))
    if a.out:
        Path(a.out).mkdir(parents=True, exist_ok=True)
    lessons = {l["id"]: l for l in content.course()["lessons"]}
    order = list(lessons)
    L1, L2 = order[0], order[1]
    exe = (sorted(glob.glob(os.path.expanduser("~/Library/Caches/ms-playwright/chromium_headless_shell-*/*/chrome-headless-shell"))) or [None])[-1]
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=exe, headless=True, args=LAUNCH_ARGS)
        ctx = b.new_context(viewport={"width": W, "height": H}); silence(ctx)
        ctx.add_init_script("window.__outpostTest = true;")
        pg = ctx.new_page()
        errs, offsite, popups, last = [], [], [], {}
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.on("popup", lambda x: popups.append(x.url))
        pg.on("request", lambda r: offsite.append(r.url) if "nps.gov" in r.url else None)
        pg.on("response", lambda r: last.__setitem__("r", r.json()) if "/api/academy/attempt" in r.url else None)
        pg.goto(a.base)
        pg.wait_for_selector("#aCsIn", timeout=60000); pg.fill("#aCsIn", "Pulsar"); pg.click("#aCsGo")
        if until(pg, "() => !!document.querySelector('#aPanel .a-crs-opt[data-crs=archaeology]')", 15000):
            with pg.expect_navigation(timeout=60000):
                pg.click("#aPanel .a-crs-opt[data-crs=archaeology]")
        pg.wait_for_selector(".apanel.is-map .mp-card", timeout=60000)
        check(until(pg, "() => window.__outpost.links && window.__outpost.links.docs.length > 0", 15000), "the course's documents are known (library docs)")

        # ---- 4. Lesson 1, step 2 (find Mesa Verde): answered, the place is named once ----
        pg.click(f'#aStart[data-l="{L1}"]'); until(pg, f"{WHERE}.view === 'lesson'", 10000)
        got = []
        for _ in range(12):
            w = pg.evaluate(WHERE)
            if w["step"] >= 1 and w["waitingNext"]:
                break
            if w["waitingNext"]:
                pg.fill("#q", "next"); pg.press("#q", "Enter"); pg.wait_for_timeout(700); continue
            last.clear(); pg.fill("#q", answer_for(lessons[L1]["steps"][w["step"]], gaz=g.gaz(), vocab=vocab, got=got)); pg.press("#q", "Enter")
            until(pg, "() => true", 300); t = time.time()
            while time.time() - t < 10 and "r" not in last:
                pg.wait_for_timeout(150)
            pg.wait_for_timeout(500)
        pg.wait_for_timeout(1800)
        labels = pg.evaluate(MV_LABELS)
        shot(pg, a.out, "e2e_L1_label", a.size)
        check(len(labels) == 1, f"#4 Lesson 1: Mesa Verde is named once on the globe {labels}")

        # ---- 3a. the lesson photo opens big ----
        open_lesson(pg, L1, 0)
        fig = pg.locator("#aPanel figure.a-photo.zoomable").first
        check(fig.count() == 1 and pg.locator("#aPanel .zoom-btn").first.is_visible(), "#3 the lesson photo has an Enlarge button")
        small = pg.evaluate("() => document.querySelector('#aPanel figure.a-photo img').getBoundingClientRect().width")
        pg.locator("#aPanel figure.a-photo img").first.click()
        st = until(pg, f"() => {LB}", 4000) or {}
        pg.wait_for_timeout(600); st = pg.evaluate(f"() => {LB}") or {}
        check(st.get("open") and st["content"][0] > small * 1.6, f"#3 ... tapping it opens the viewer, much bigger ({round(small)} -> {st.get('content')})")
        pg.keyboard.press("+"); pg.keyboard.press("+"); pg.wait_for_timeout(300)
        check((pg.evaluate(f"() => {LB}") or {}).get("scale", 1) > 2, "#3 ... + zooms in")
        shot(pg, a.out, "e2e_photo_enlarged", a.size)
        check(pg.locator(".lbx-close").is_visible(), "#3 ... a visible Close button")
        pg.keyboard.press("Escape"); pg.wait_for_timeout(300)
        check(not pg.evaluate(f"() => {LB}") and pg.evaluate("() => !!document.activeElement.closest('#aPanel')"), "#3 ... Esc closes it and focus comes back to the card")
        # the Enlarge button by keyboard
        pg.locator("#aPanel .zoom-btn").first.focus(); pg.keyboard.press("Enter"); pg.wait_for_timeout(400)
        check((pg.evaluate(f"() => {LB}") or {}).get("open"), "#3 ... the Enlarge button opens it from the keyboard")
        pg.click(".lbx-close"); pg.wait_for_timeout(300)
        check(not pg.evaluate(f"() => {LB}"), "#3 ... the Close button closes it")

        # ---- 1. the NPS rack card opens in the app ----
        pg.click("#aBriefBtn"); pg.wait_for_timeout(200)
        pg.evaluate("() => { const d = document.querySelector('#aBrief details.a-facts'); if (d) d.open = true; }")
        link = pg.locator(f'#aPanel a[href="{RACK}"]').first
        check(link.count() == 1, "#1 Lesson 1 cites the NPS rack card")
        check("is-local-doc" in (link.get_attribute("class") or "") and "Opens here" in (link.get_attribute("title") or ""),
              "#1 ... marked as kept with the course (opens here)")
        link.click(); pg.wait_for_timeout(900)
        st = pg.evaluate(f"() => {LB}") or {}
        ok_img = pg.evaluate("() => { const i = document.querySelector('.lbx-canvas img'); return !!i && i.complete && i.naturalWidth > 0; }")
        check(st.get("open") and st.get("pages") == 2 and ok_img and "/api/courses/archaeology/media/nps_rack_artifacts_p1.jpg" in (st.get("src") or ""),
              f"#1 ... its click opens both pages in the app viewer {st}")
        shot(pg, a.out, "e2e_nps_rack_card_p1", a.size)
        pg.keyboard.press("PageDown"); pg.wait_for_timeout(500)
        check("nps_rack_artifacts_p2" in ((pg.evaluate(f"() => {LB}") or {}).get("src") or ""), "#1 ... Page Down turns to page 2")
        shot(pg, a.out, "e2e_nps_rack_card_p2", a.size)
        pg.keyboard.press("Escape"); pg.wait_for_timeout(300)
        check(not popups and not offsite, f"#1 ... with no web request and no popup ({popups[:1]} {offsite[:1]})")

        # ---- 1b. every link in every lesson: a document here, or marked as a web link ----
        unmarked = []
        for lid, les in lessons.items():
            open_lesson(pg, lid)
            for k in range(len(les["steps"])):
                pg.evaluate(f"() => window.__outpost.academyTest.step({k})"); pg.wait_for_timeout(250)
                pg.evaluate("() => { const b = document.getElementById('aBrief'); if (b) b.hidden = false; document.querySelectorAll('#aPanel details').forEach(d => d.open = true); }")
                unmarked += pg.evaluate("""() => [...document.querySelectorAll('#aPanel a[href]')].filter(a => /^https?:/.test(a.href) && !a.href.startsWith(location.origin))
                    .filter(a => !(a.classList.contains('is-local-doc') || (a.classList.contains('is-web') && /browser/.test(a.title) && a.target === '_blank'))).map(a => a.href)""")
        check(not unmarked, f"#1 every lesson link opens here or is marked as a web link {unmarked[:3]}")

        # ---- 3b. Lesson 2, the lidar map: Enlarge opens the live step ----
        open_lesson(pg, L2, 2)
        acc = lessons[L2]["steps"][2]["accept"]
        small = pg.evaluate("() => document.querySelector('#aPanel .ar-hill-img').getBoundingClientRect().width")
        check(pg.locator("#aPanel [data-enlarge=step]").is_visible(), "#3 the lidar map has an Enlarge button")
        shot(pg, a.out, "e2e_lidar_card", a.size)
        pg.click("#aPanel [data-enlarge=step]"); pg.wait_for_timeout(800)
        st = pg.evaluate(f"() => {LB}") or {}
        big = pg.evaluate("() => document.querySelector('.lbx .ar-hill-img').getBoundingClientRect().width")
        check(st.get("live") and big > small * 1.5, f"#3 ... it opens the map itself, bigger ({round(small)} -> {round(big)} px)")

        def tap(t):
            r = pg.evaluate("() => { const b = document.querySelector('.lbx .ar-hill-img').getBoundingClientRect(); return [b.left, b.top, b.width, b.height]; }")
            last.clear(); pg.mouse.click(r[0] + t["x"] * r[2], r[1] + t["y"] * r[3]); tt = time.time()
            while time.time() - tt < 10 and "r" not in last:
                pg.wait_for_timeout(150)
            pg.wait_for_timeout(700)

        sun0 = pg.evaluate("() => document.querySelector('.lbx .ar-hill-img img').getAttribute('src')")
        pg.click(".lbx .ar-sun"); pg.wait_for_timeout(500)
        sun1 = pg.evaluate("() => document.querySelector('.lbx .ar-hill-img img').getAttribute('src')")
        check(sun0 != sun1 and "high" in sun1, f"#3 ... Low sun works there ({sun0.rsplit('/', 1)[-1]} -> {sun1.rsplit('/', 1)[-1]})")
        pg.click(".lbx .ar-sun"); pg.wait_for_timeout(400)
        tap(acc["targets"][0])
        txt = pg.evaluate("() => document.querySelector('.lbx .f-count').textContent")
        rings = pg.evaluate("() => document.querySelectorAll('.lbx .ar-found').length")
        check(txt.startswith("1 of") and rings == 1, f"#3 ... a tap there counts and its ring shows ({txt!r}, {rings} ring)")
        pg.keyboard.press("+"); pg.keyboard.press("+"); pg.wait_for_timeout(400)
        check((pg.evaluate(f"() => {LB}") or {}).get("scale", 1) > 2, "#3 ... + zooms the map")
        tap(acc["targets"][1])
        txt = pg.evaluate("() => document.querySelector('.lbx .f-count').textContent")
        check(txt.startswith("2 of"), f"#3 ... and taps still count zoomed in ({txt!r})")
        shot(pg, a.out, "e2e_lidar_enlarged_zoomed", a.size)
        pg.keyboard.press("0"); pg.wait_for_timeout(300)
        tap(acc["targets"][3])
        rings = pg.evaluate("() => document.querySelectorAll('.lbx .ar-found').length")
        check(pg.evaluate(f"{WHERE}.waitingNext") and rings >= 3, f"#3 ... the third site finishes the step; the found rings show ({rings}: the fourth is shown once done)")
        shot(pg, a.out, "e2e_lidar_enlarged_done", a.size)
        pg.keyboard.press("Escape"); pg.wait_for_timeout(500)
        check(not pg.evaluate(f"() => {LB}") and pg.evaluate("() => document.querySelectorAll('#aPanel .ar-found').length") >= 3,
              "#3 ... Esc closes it; the card shows the found sites too")

        # ---- 2. the earned patch stays on the Earth map ----
        pg.evaluate("""() => { const s = JSON.parse(localStorage.getItem('atm-academy')); if (!s.badges.includes('archaeology:field_scout')) s.badges.push('archaeology:field_scout'); localStorage.setItem('atm-academy', JSON.stringify(s)); }""")
        pg.reload(); until(pg, f"() => {WHERE}.view === 'lesson' || !!document.querySelector('.apanel.is-map .mp-card')", 60000)
        if until(pg, f"{WHERE}.view === 'lesson'", 1500):   # the half-done Lesson 2 reopens: back to the map
            pg.click("#aBack")
        seen = []
        for _ in range(8):   # while the map flies in (Mesa Verde's pins gathered into one count pin)
            seen.append(pg.evaluate(PATCH_ON_GLOBE)); pg.wait_for_timeout(200)
        pg.wait_for_timeout(2500)
        check(all(seen), f"#2 the earned patch is on the globe while the map flies in {seen}")
        check(pg.evaluate(PATCH_ON_GLOBE) and pg.evaluate("() => [...document.querySelectorAll('.mp-patchbtn')].map(b => b.dataset.l)") == [L1],
              "#2 ... at rest on its pin, and in the header strip")
        shot(pg, a.out, "e2e_map_patch_rest", a.size)
        for d in (1.8, 3.0):
            pg.evaluate(f"() => window.__outpost.globe.flyTo(37.18, -108.49, {d})"); pg.wait_for_timeout(2000)
            col = pg.evaluate("() => window.__outpost.globe.route.collapsed.length")
            check(pg.evaluate(PATCH_ON_GLOBE), f"#2 ... zoomed out ({d} radii, {col} count pin): still on the globe")
            shot(pg, a.out, f"e2e_map_patch_zoom{d}", a.size)
        lbl = pg.evaluate("() => (document.querySelector('.route .route-cluster:not([hidden])') || {}).ariaLabel || ''")
        check("patch earned" in (lbl or ""), f"#2 ... the count pin says so ({lbl!r})")

        check(not errs, f"no page errors {errs[:3]}")
        b.close()
    print(f"{sum(results)}/{len(results)} checks")
    sys.exit(0 if results and all(results) else 1)


if __name__ == "__main__":
    main()
