"""Archaeology patches persist and show after every lesson (the owner's 0.5.1 report: "archaeology badges disappear as
I take lessons").

A fresh cadet picks Archaeology on the first-run pick (installed, or played from source with the dev flag), then plays
lessons 1..N for real: every answer is typed in the voice bar and graded by the backend (the answers come from
backend/tools/handsfree_run.py answer_for, the same script the backend's voice-flight test uses). After each lesson:

  - the progress store keeps every patch earned so far, prefixed once ("archaeology:<badge>"), and the cadet's course
    is still Archaeology; the Brain's practice counts say "course": "archaeology";
  - the patch screen shows the new patch, with no Moon-only line ("then your check ride", NASA, Flight School);
  - the map shows every earned patch as a pin in colour, on the globe and not covered by anything, and in the header
    strip; an earned pin stays where it was (Mesa Verde holds nine lessons: they used to be flung across the continent,
    somewhere else after every lesson); the map's small print is not the Moon's Artemis line;
  - after a reload (a relaunch) the same patches are there; My Brain lights one star per patch, named after its big idea.

Screenshots (--out) at 1440x900: the patch screen and the map after each lesson, My Brain at the end.

    backend (port 8531): OUTPOST_DEV_COURSE=archaeology ACTIVE_COURSE_FILE=<f> LUNA_DATA_DIR=<d> uv run uvicorn app.main:app --port 8531
        (or COURSE_PACKS_DIR=<dir with course_archaeology/> for the installed pack)
    vite (port 5531): BACKEND_URL=http://127.0.0.1:8531 npx vite --port 5531
    cd backend && uv run --with playwright==1.58.0 python ../frontend/tests/e2e/arch_patches_e2e.py --base http://localhost:5531 \\
        [--lessons 3] [--out DIR]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("OUTPOST_DEV_COURSE", "archaeology")   # this process only: the answer keys come from the source
ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "backend"), str(Path(__file__).resolve().parent)]
from playwright.sync_api import sync_playwright  # noqa: E402
from silent import LAUNCH_ARGS, silence  # noqa: E402
from app.academy import content, grade as g, vocab  # noqa: E402
from tools.handsfree_run import answer_for  # noqa: E402

results: list[bool] = []
MOON_ONLY = ("check ride", "Artemis", "Moon Base", "NASA facts", "Flight School")


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


def shot(pg, out, name):
    if out:
        try:
            pg.screenshot(path=str(Path(out) / f"{name}.png"), timeout=60000)
        except Exception as e:  # noqa: BLE001  (a loaded machine can stall one WebGL capture)
            print("  (screenshot skipped:", str(e)[:80], ")")


# every earned pin: where it is, and whether it is the thing on top at its centre (not under a card, not off the globe)
PINS = """() => { const o = {}, st = document.getElementById('stage') || document.body, sr = st.getBoundingClientRect();
  document.querySelectorAll('.route .pin.is-done').forEach(b => { const r = b.getBoundingClientRect(), cx = r.left + r.width / 2, cy = r.top + r.height / 2;
    let op = 1; for (let a = b; a; a = a.parentElement) op *= +getComputedStyle(a).opacity;
    const top = document.elementFromPoint(cx, cy);
    o[b.dataset.l] = { x: Math.round(cx), y: Math.round(cy), art: !!b.querySelector('svg.patch.is-earned'), op, hidden: getComputedStyle(b).visibility === 'hidden',
      onTop: !!top && (top === b || b.contains(top)), placed: !!b.style.transform && r.width >= 8 && cx > sr.left + 8 && cy > sr.top + 8 }; });
  return o; }"""
STRIP = "() => [...document.querySelectorAll('.mp-patchbtn')].filter(b => b.querySelector('svg.patch.is-earned')).map(b => b.dataset.l)"
WHERE = "window.__outpost.academyTest.where"


def play_lesson(pg, lessons, last):
    """Answer every step of the open lesson by typing in the voice bar; returns the badge the backend awarded."""
    got, badge = [], None
    for _ in range(80):
        w = pg.evaluate(WHERE)
        if w["view"] != "lesson":
            break
        if w["waitingNext"]:
            pg.fill("#q", "next"); pg.press("#q", "Enter"); pg.wait_for_timeout(600); got = []
            continue
        st = lessons[w["lesson"]]["steps"][w["step"]]
        last.clear()
        pg.fill("#q", answer_for(st, gaz=g.gaz(), vocab=vocab, got=got)); pg.press("#q", "Enter")
        t = time.time()
        while time.time() - t < 10 and "r" not in last:
            pg.wait_for_timeout(150)
        r = last.get("r") or {}
        if r.get("got") is not None:
            got = r["got"]
        badge = r.get("badge") or badge
        pg.wait_for_timeout(400)
    return badge


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:5531")
    ap.add_argument("--lessons", type=int, default=3)
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    if a.out:
        Path(a.out).mkdir(parents=True, exist_ok=True)
    lessons = {l["id"]: l for l in content.course()["lessons"]}
    order = list(lessons)
    exe = (sorted(glob.glob(os.path.expanduser("~/Library/Caches/ms-playwright/chromium_headless_shell-*/*/chrome-headless-shell"))) or [None])[-1]
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=exe, headless=True, args=LAUNCH_ARGS)
        ctx = b.new_context(viewport={"width": 1440, "height": 900}); silence(ctx)
        ctx.add_init_script("window.__outpostTest = true;")
        pg = ctx.new_page()
        errs, last = [], {}
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.on("console", lambda m: errs.append(m.text) if m.type == "warning" and "unknown patch" in m.text.lower() else None)

        def onresp(r):
            if "/api/academy/attempt" in r.url:
                try:
                    last["r"] = r.json()
                except Exception:  # noqa: BLE001
                    pass
        pg.on("response", onresp)

        # first run: a call sign, then the course pick -> Archaeology (the app reloads on it)
        pg.goto(a.base)
        pg.wait_for_selector("#aCsIn", timeout=60000); pg.fill("#aCsIn", "Pulsar"); pg.click("#aCsGo")
        if until(pg, "() => !!document.querySelector('#aPanel .a-crs-opt[data-crs=archaeology]')", 15000):
            with pg.expect_navigation(timeout=60000):
                pg.click("#aPanel .a-crs-opt[data-crs=archaeology]")
        pg.wait_for_selector(".apanel.is-map .mp-card", timeout=60000); pg.wait_for_timeout(2500)
        check(pg.evaluate("() => (window.__outpost.course || {}).id") == "archaeology", "the app plays Archaeology")

        earned, where = [], {}
        for n in range(a.lessons):
            lid = order[n]
            pg.click(f'#aStart[data-l="{lid}"]')   # the map card's Next up (the map is where every lesson ends here)
            until(pg, f"{WHERE}.view === 'lesson' && {WHERE}.lesson === {json.dumps(lid)}", 10000)
            badge = play_lesson(pg, lessons, last)
            check(badge and badge["id"] == lessons[lid]["badge"]["id"], f"L{n + 1} {lid}: the backend awarded {badge and badge['id']}")
            earned.append(lessons[lid]["badge"]["id"])
            check(until(pg, f"{WHERE}.view === 'badge'", 6000), f"L{n + 1}: the patch screen")
            pg.wait_for_timeout(800)
            shot(pg, a.out, f"arch_patch_L{n + 1}")
            txt = pg.evaluate("() => document.getElementById('aPanel').innerText")
            check(pg.locator("#aPanel .a-bigpatch svg.patch.is-earned").count() == 1, f"L{n + 1}: the new patch is drawn in colour")
            check(not [w for w in MOON_ONLY if w in txt], f"L{n + 1}: no Moon-only words on the patch screen ({txt.splitlines()[1:3]})")
            store = json.loads(pg.evaluate("() => localStorage.getItem('atm-academy')") or "{}")
            check([x for x in store.get("badges", []) if x.startswith("archaeology:")] == earned and len(store.get("badges", [])) == len(earned),
                  f"L{n + 1}: the store keeps every patch so far, prefixed once: {store.get('badges')}")
            check(pg.evaluate("() => localStorage.getItem('outpost-course')") == "archaeology", f"L{n + 1}: the cadet's course is still Archaeology")
            brain = json.loads(pg.evaluate("() => localStorage.getItem('outpost-brain')") or "{}")
            check(brain.get("course") == "archaeology", f"L{n + 1}: the Brain's counts say course archaeology (was stuck at moon)")

            # the map: every earned patch on the globe, in colour, on top, and where it was after the last lesson
            pg.click("#aMap"); pg.wait_for_selector(".apanel.is-map .mp-card", timeout=10000); pg.wait_for_timeout(3000)
            shot(pg, a.out, f"arch_map_L{n + 1}")
            pins, strip = pg.evaluate(PINS), pg.evaluate(STRIP)
            for k, e in enumerate(order[: n + 1]):
                pin = pins.get(e) or {}
                check(pin.get("art") and pin.get("op", 0) > .5 and not pin.get("hidden") and pin.get("placed") and pin.get("onTop"),
                      f"map after L{n + 1}: the {e} patch pin shows, in colour, on the globe, uncovered {pin}")
                if e in where and pin:
                    d = ((pin["x"] - where[e][0]) ** 2 + (pin["y"] - where[e][1]) ** 2) ** .5
                    check(d <= 60, f"map after L{n + 1}: the {e} pin stayed put (moved {d:.0f}px)")
                if pin:
                    where[e] = (pin["x"], pin["y"])
            check(strip == order[: n + 1], f"map after L{n + 1}: the header strip has every earned patch {strip}")
            mtxt = pg.evaluate("() => document.getElementById('aPanel').innerText")
            check("Artemis" not in mtxt and "Moon Base" not in mtxt, "the map's small print isn't the Moon's")
        # a relaunch keeps them; My Brain lights one star per patch, named after its big idea
        pg.reload(); pg.wait_for_selector(".apanel.is-map .mp-card", timeout=60000); pg.wait_for_timeout(3000)
        check(pg.evaluate(STRIP) == order[: len(earned)], f"after a reload: the same patches {pg.evaluate(STRIP)}")
        pg.click("#brainBtn"); pg.wait_for_timeout(2000)
        shot(pg, a.out, "arch_brain")
        btxt = pg.evaluate("() => (document.getElementById('brain') || {}).innerText || ''")
        big = json.loads((ROOT / "backend/data/courses/archaeology.json").read_text()).get("big_ideas") or {}   # [courses playtest] the big ideas
        names = [(big.get(l.split(":")[-1]) or {}).get("star") or lessons[l]["badge"]["name"] for l in order[: len(earned)]]
        check(all(nm in btxt for nm in names), f"My Brain names the stars after the big ideas {names}")
        check(f"{len(earned)} of {len(order)}" in btxt.replace("\n", " "), "My Brain: one star lit per patch")
        check("Go to Field School" in btxt or len(earned) == len(order), "My Brain's button names Field School")
        check(not errs, f"no page errors or unknown-patch warnings {errs[:3]}")
        b.close()
    print(f"{sum(results)}/{len(results)} checks")
    sys.exit(0 if results and all(results) else 1)


if __name__ == "__main__":
    main()
