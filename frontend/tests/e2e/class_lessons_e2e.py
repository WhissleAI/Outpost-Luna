"""Class lessons (docs/CURRICULUM.md): import a teacher's pack in Settings → For grown-ups → Class lessons, see it in
Flight School as its own row and pin, and play its lesson to the patch, like a NASA lesson. Also: a bad file is refused
with a clear line and changes nothing; the editor opens, Check marks a bad field; Progress lists the Class patch apart
from NASA's. Screenshots (--out) at 1440x900 and 1280x720.

    (backend with CLASS_DIR pointed at an empty scratch folder, Vite in front of it)
    uv run --no-project --with playwright==1.58.0 python frontend/tests/e2e/class_lessons_e2e.py --base http://localhost:5474 [--out DIR]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright
sys.path.insert(0, str(Path(__file__).resolve().parent))
from silent import LAUNCH_ARGS, silence  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
SAMPLE = ROOT / "docs" / "class_packs" / "sample_room12.json"
LID = "c-room-12-craters"
results: list[bool] = []


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


def open_class_part(pg):
    pg.evaluate("() => document.getElementById('a11yBtn').click()")
    until(pg, "() => !!document.querySelector('.a11y-panel:not([hidden]) [data-sec=grownups]')", 5000)
    pg.evaluate("() => document.querySelector('.a11y-panel [data-sec=grownups]').click()")
    until(pg, "() => !!document.querySelector('[data-gu-open], .gu-part')", 3000)
    if pg.evaluate("() => !!document.querySelector('[data-gu-open]')"):
        hold(pg, "[data-gu-open]", 3400)
    return until(pg, "() => !!document.querySelector('.gu-part[data-gu=class] .ce-zone')", 5000)


def shot(pg, out, name):
    if out:
        pg.screenshot(path=str(Path(out) / f"{name}.png"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:5474")
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    if a.out:
        Path(a.out).mkdir(parents=True, exist_ok=True)
    exe = (sorted(glob.glob(os.path.expanduser("~/Library/Caches/ms-playwright/chromium_headless_shell-*/*/chrome-headless-shell"))) or [None])[-1]
    bad = Path(tempfile.mkdtemp()) / "not_a_pack.json"
    bad.write_text('{"lessons": [{"title": "x"}], "format": "outpost-luna-class-pack", "version": 1, "id": "x", "title": "X"}')
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=exe, headless=True, args=LAUNCH_ARGS)
        for vw, vh in ((1440, 900), (1280, 720)):
            tag = f"{vw}x{vh}"
            print(f"-- {tag}")
            ctx = b.new_context(viewport={"width": vw, "height": vh}); silence(ctx)
            ctx.add_init_script("""try { if (!sessionStorage.getItem('cl-e2e')) { sessionStorage.setItem('cl-e2e', '1');
              localStorage.setItem('outpost-callsign', 'Nova'); localStorage.setItem('atm-mode', 'academy');
              localStorage.setItem('atm-academy', JSON.stringify({badges: ['scout', 'radio'], qualified: false})); } } catch (e) {}""")
            pg = ctx.new_page()
            errors = []
            pg.on("pageerror", lambda e: errors.append(str(e)))
            pg.goto(a.base, wait_until="domcontentloaded")
            check(until(pg, "() => !!document.querySelector('#aPanel .mp-top')", 30000), "Flight School map up")
            # clean slate: no pack from an earlier run
            pg.evaluate("""() => fetch('/api/class/packs/room-12', {method: 'DELETE', headers: {'X-Outpost-Class': '1'}}).catch(() => {})""")
            check(open_class_part(pg), "Settings → For grown-ups → Class lessons opens behind the hold")
            pg.evaluate("() => { const g = document.querySelector('.gu-part[data-gu=class]'); g.scrollIntoView({block: 'start'}); }")
            # a bad file: refused, says why, nothing saved
            pg.set_input_files("[data-ce-file]", str(bad))
            check(until(pg, "() => /isn't a lesson pack/.test(document.querySelector('.gu-part[data-gu=class] .ce-status').textContent)", 5000),
                  "a bad pack is refused with a plain line")
            n0 = pg.evaluate("() => fetch('/api/class/packs').then(r => r.json()).then(j => j.packs.length)")
            check(n0 == 0, "nothing saved from the bad file")
            # the sample pack: imported
            pg.set_input_files("[data-ce-file]", str(SAMPLE))
            check(until(pg, "() => /Imported Room 12 Moon unit: 1 lesson/.test(document.querySelector('.gu-part[data-gu=class] .ce-status').textContent)", 5000),
                  "import says what came in")
            check(pg.evaluate("() => !!document.querySelector('.ce-lessons [data-ce=edit]')"), "the lesson is listed with Edit")
            pg.evaluate("() => document.querySelector('.gu-part[data-gu=class]').scrollIntoView({block: 'start'})")
            pg.wait_for_timeout(300); shot(pg, a.out, f"class_list_{tag}")
            # the editor: opens on the title; Check marks a broken field
            pg.click(".ce-lessons [data-ce=edit]")
            check(until(pg, "() => document.activeElement && document.activeElement.dataset.at === 'lessons[0].title'", 3000), "Edit lands on the title field")
            pg.wait_for_timeout(200); shot(pg, a.out, f"class_editor_{tag}")
            pg.fill('[data-at="lessons[0].steps[0].prompt"]', " ".join(["word"] * 22))
            check(pg.evaluate("() => document.querySelector('[data-count=\"lessons[0].steps[0].prompt\"]').classList.contains('is-over')"), "the live budget turns red past 20 words")
            pg.click("[data-ce=check]")
            check(until(pg, "() => document.querySelector('[data-at=\"lessons[0].steps[0].prompt\"]').getAttribute('aria-invalid') === 'true'", 5000),
                  "Check marks the question that is too long")
            pg.wait_for_timeout(200); shot(pg, a.out, f"class_check_{tag}")
            pg.click("[data-ce=back]")
            pg.keyboard.press("Escape")
            until(pg, "() => document.querySelector('.a11y-panel').hidden", 3000)
            # Flight School: the class row and pin
            check(until(pg, f"() => !!document.querySelector('[data-class-pack=\"room-12\"]') && !!document.querySelector('.route .pin[data-l=\"{LID}\"]')", 8000),
                  "the map shows the Class row and its pin")
            core = pg.evaluate("() => document.querySelector('.mp-count').textContent")
            check(core.strip().startswith("2"), f"the core count is unchanged ({core.strip()})")
            pg.click("[data-class-pack=\"room-12\"]")
            check(until(pg, "() => /Class lesson · Room 12 Moon unit/.test(document.querySelector('.mp-card .eyebrow').textContent)", 4000), "its card says Class lesson · the pack")
            pg.wait_for_timeout(1500); shot(pg, a.out, f"class_map_{tag}")
            pg.click("#aStart")
            check(until(pg, "() => /Craters up close/.test(document.querySelector('#aPanel .m-title').textContent)", 6000), "the lesson opens on the lesson card")
            # play it: predict (A), find Copernicus (typed), choice Shackleton (A), say ejecta (typed)
            def answered():
                return until(pg, "() => !!document.querySelector('#aNext')", 8000)

            pg.click(".a-choice[data-c=a]"); check(answered(), "step 1 (predict) passes")
            pg.wait_for_timeout(300); shot(pg, a.out, f"class_lesson_{tag}")
            pg.click("#aNext")
            until(pg, "() => /Copernicus/.test(document.querySelector('#aPanel .a-step').textContent)", 4000)
            for step, text in ((2, "copernicus"), (3, None), (4, "ejecta")):
                if text is None:
                    pg.click(".a-choice[data-c=a]")
                else:
                    pg.fill("#q", text); pg.press("#q", "Enter")
                ok = answered()
                check(ok, f"step {step} passes")
                if not ok:
                    break
                pg.click("#aNext")
                pg.wait_for_timeout(400)
            check(until(pg, "() => !!document.querySelector('.a-badge') && /Crater Spotter/.test(document.querySelector('.a-badge').textContent)", 6000),
                  "the patch screen names the Class patch")
            check(pg.evaluate("() => !!document.querySelector('.a-badge svg.patch-class.is-earned')"), "with the Class letter patch")
            pg.wait_for_timeout(500); shot(pg, a.out, f"class_patch_{tag}")
            saved = pg.evaluate("() => JSON.parse(localStorage.getItem('atm-academy')).badges")
            check("c-room-12-craters" in saved, "the patch is saved with the cadet's progress")
            check(not errors, f"no page errors {errors[:2]}")
            ctx.close()
        b.close()
    print(f"{sum(results)}/{len(results)} ok")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
