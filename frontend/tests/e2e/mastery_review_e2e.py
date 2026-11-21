"""Concept mastery and spaced review in the real app (D5, docs/BRAIN.md §11). Silent.

Checks:
  - the course's concepts come from the backend (GET /api/academy/concepts) and a graded step's reply names its concept;
  - a graded step lands in the cadet's concept counts with its next review day (ids and counts only);
  - My Brain shows "Quick review" for a concept that is due, in kid words, and its Review button opens Flight School
    at the step that practises it (radiation, step 3 of 5);
  - the mission debrief's hook (window.__outpost.dueReview({mission: true})) offers a mission concept;
  - the grown-ups' Progress shows the concept table: outcomes and the next review, never a grade.

    uv run --no-project --with playwright==1.58.0 python frontend/tests/e2e/mastery_review_e2e.py --base http://localhost:5480
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright
sys.path.insert(0, str(Path(__file__).resolve().parent))
from silent import LAUNCH_ARGS, silence  # noqa: E402

results: list[bool] = []
SEED = """(() => { window.__outpostTest = true; try { if (sessionStorage.getItem('mr-e2e')) return; sessionStorage.setItem('mr-e2e', '1'); localStorage.clear();
  localStorage.setItem('outpost-callsign', 'Nova');
  localStorage.setItem('atm-academy', JSON.stringify({ badges: ['scout', 'watcher', 'sun', 'radio', 'storm'], qualified: false, steps: {}, current: null }));
  const d = new Date(), day = n => { const t = new Date(d); t.setDate(t.getDate() + n); return t.getFullYear() + '-' + String(t.getMonth() + 1).padStart(2, '0') + '-' + String(t.getDate()).padStart(2, '0'); };
  localStorage.setItem('outpost-brain', JSON.stringify({ v: 1, lessons: {}, days: [], concepts: {
    storm_shelter: { first: 1, helped: 1, shown: 0, box: 1, due: day(-2) },
    regolith: { first: 2, helped: 0, shown: 0, box: 3, due: day(5) } } }));
} catch (e) {} })();"""


def no_hmr_socket(ctx):
    """server.ws:false still injects Vite's HMR client; its socket never opens and Chrome queues the app's own behind it."""
    ctx.route_web_socket(re.compile(r"^wss?://[^/]+/(\?.*)?$"), lambda ws: None)


def check(ok, msg):
    results.append(bool(ok)); print(("  ok  " if ok else "  FAIL ") + msg)


def until(pg, js, ms=8000):
    for _ in range(ms // 100):
        try:
            if pg.evaluate(js):
                return True
        except Exception:
            pass
        pg.wait_for_timeout(100)
    return False


def hold(pg, sel, ms):
    box = pg.evaluate("s => { const q = document.querySelector(s).getBoundingClientRect(); return [q.x + q.width / 2, q.y + q.height / 2]; }", sel)
    pg.mouse.move(*box); pg.mouse.down(); pg.wait_for_timeout(ms); pg.mouse.up()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:5480")
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    if a.out:
        Path(a.out).mkdir(parents=True, exist_ok=True)
    exe = (sorted(glob.glob(os.path.expanduser("~/Library/Caches/ms-playwright/chromium_headless_shell-*/*/chrome-headless-shell"))) or [None])[-1]
    errs: list[str] = []
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=exe, headless=True, args=[*LAUNCH_ARGS, "--enable-unsafe-swiftshader"])
        ctx = b.new_context(viewport={"width": 1280, "height": 800})
        ctx.add_init_script(SEED)
        silence(ctx)
        no_hmr_socket(ctx)
        pg = ctx.new_page()
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.on("console", lambda m: m.type == "error" and "favicon" not in m.text and "WebSocket" not in m.text and errs.append(m.text))
        pg.goto(a.base + "/", wait_until="domcontentloaded")
        check(until(pg, "() => !!window.__outpost && !!window.__outpost.brain && !!window.__outpost.review", 30000), "the app loads with the review hook")
        pg.wait_for_timeout(1500)

        print("-- the backend's concepts")
        meta = pg.evaluate("() => fetch('/api/academy/concepts').then(r => r.json())")
        check(meta.get("course") == "moon" and meta["concepts"]["storm_shelter"]["lesson"] == "radiation" and meta["concepts"]["storm_shelter"]["step"] == 2,
              "GET /api/academy/concepts: labels and where each review opens")
        r = pg.evaluate("""() => fetch('/api/academy/attempt', { method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ lesson_id: 'comms', step: 0, input: { choice: 'understood' } }) }).then(r => r.json())""")
        check(r.get("concept") == "radio_words", "a graded step's reply names its concept")

        print("-- a graded step lands in the concept counts")
        pg.evaluate("""() => dispatchEvent(new CustomEvent('outpost:lesson-result', { detail: { status: 'passed', step_type: 'choice', lesson: 'comms',
            shown: false, misses: 0, helped: false, step_s: 9, reply: { status: 'passed', concept: 'radio_words' }, text: 'copy that', callsign: 'Nova' } }))""")
        saved = json.loads(pg.evaluate("() => localStorage.getItem('outpost-brain')"))
        rw = (saved.get("concepts") or {}).get("radio_words") or {}
        check(rw.get("first") == 1 and rw.get("box") == 1 and isinstance(rw.get("due"), str), "radio_words: first try, box 1, a review day")
        raw = json.dumps(saved)
        check("copy that" not in raw and "Nova" not in raw, "ids and counts only, never words or the call sign")

        print("-- My Brain: Quick review, and Review opens the step")
        pg.click("#brainBtn")
        check(until(pg, "() => !!document.querySelector('#brain [data-bm-review]')", 8000), "My Brain shows Quick review for a due idea")
        txt = pg.evaluate("() => document.getElementById('brain').innerText")
        check("The outpost brings back ideas you haven't seen in a while." in txt and "Shelter from a solar storm" in txt, "in kid words, by the idea's name")
        check("Regolith" not in txt.split("Quick review")[1].split("How the outpost")[0], "an idea not yet due is not offered")
        if a.out:
            pg.evaluate("() => document.querySelector('#brain .bm-review').scrollIntoView({ block: 'center' })")
            pg.screenshot(path=str(Path(a.out) / "quick_review_1280x800.png"))
        pg.click("#brain [data-bm-review=storm_shelter]")
        check(until(pg, "() => { const w = window.__outpost.academyTest && window.__outpost.academyTest.where; return w && w.view === 'lesson' && w.lesson === 'radiation' && w.step === 2; }", 15000),
              "Review opens the radiation lesson at its step 3")

        print("-- the mission debrief's offer")
        rv = pg.evaluate("() => window.__outpost.dueReview({ mission: true })")
        check(rv and rv.get("id") == "storm_shelter" and rv.get("mission") is True, "dueReview offers a mission idea for the debrief")

        print("-- the grown-ups' concept table")
        pg.evaluate("() => document.getElementById('a11yBtn').click()")
        until(pg, "() => !!document.querySelector('.a11y-panel:not([hidden]) [data-sec=grownups]')", 5000)
        pg.evaluate("() => document.querySelector('.a11y-panel [data-sec=grownups]').click()")
        until(pg, "() => !!document.querySelector('[data-gu-open]')", 3000)
        hold(pg, "[data-gu-open]", 3400)
        check(until(pg, "() => !!document.querySelector('.pg-concepts')", 10000), "Progress shows Ideas, step by step")
        g = pg.evaluate("() => document.querySelector('.pg-concepts').innerText")
        check("Remembered after a week or more: 1 of 3 ideas practised." in g and "Due for a quick review now: 1." in g, "outcomes: remembered and due")
        check(not re.search(r"\b(score|level|mastered|weak)\b", g, re.I), "never a grade or a trait")
        if a.out:
            pg.evaluate("() => document.querySelector('.pg-concepts').scrollIntoView({ block: 'start' })")
            pg.screenshot(path=str(Path(a.out) / "concepts_grownup_1280x800.png"))
        ctx.close()
        b.close()
    errs = [e for e in errs if "Failed to load resource" not in e]
    print(f"{sum(results)}/{len(results)} checks; page errors: {len(errs)}")
    for e in errs[:10]:
        print("  ERR", e[:300])
    sys.exit(0 if all(results) and not errs else 1)


if __name__ == "__main__":
    main()
