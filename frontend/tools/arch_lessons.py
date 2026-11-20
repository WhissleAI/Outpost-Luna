"""Archaeology course (docs/COURSES.md P3) under the dev flag: every lesson plays to its patch in the real app, and the
new step types (layers, rings, hillshade, decide) are screenshotted at each size. Silent and headless (tools/silent.py).

  # backend: OUTPOST_DEV_COURSE=archaeology .venv/bin/uvicorn app.main:app --port <b>
  # vite:    BACKEND_URL=http://127.0.0.1:<b> npx vite --port <v> --strictPort
  python frontend/tools/arch_lessons.py --base http://localhost:<v> --out <dir> [--sizes 1440x900,1280x720] [--keys]

Answers go in as typed turns (the ask box, the same path as the ear's words), using the hands-free script's answers
(backend/tools/handsfree_run.answer_for). --keys also drives one rings and one hillshade step by keyboard only.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parents[1] / "backend")]
import silent  # noqa: E402,F401  (mute + headless, before Playwright launches)
from playwright.sync_api import sync_playwright  # noqa: E402

NEW = ("layers", "rings", "hillshade", "decide")


def answer(st: dict, got: list | None = None) -> str:
    from app.academy.arch_steps import ARCH_TYPES, answer_for as arch
    a = st["accept"]
    if a["type"] in ARCH_TYPES:
        return arch(st, got)
    if a["type"] in ("predict", "choice"):
        return next(o["label"] for o in a["options"] if o["id"] == a["answer"])
    if a["type"] == "intent":
        return {"mesa_verde": "Mesa Verde", "chimney_rock": "Chimney Rock"}.get(a["place"], a["place"])
    if a["type"] == "keywords":
        return a["any"][0][0]
    if a["type"] == "describe":
        return st["example"]
    if a["type"] == "sequence":
        return ", then ".join(i["label"].lower() for i in a["items"])
    if a["type"] == "rounds":
        r = a["rounds"][len(got or [])]
        return next(o["label"] for o in a["options"] if o["id"] == r["answer"])
    return "next"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--sizes", default="1440x900,1280x720")
    ap.add_argument("--keys", action="store_true")
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    raw = json.loads((HERE.parents[1] / "backend/data/courses/archaeology/course.json").read_text())
    pub = json.loads(urllib.request.urlopen(a.base.rstrip("/") + "/api/academy/course").read())
    assert pub.get("course") == "archaeology", "start the backend with OUTPOST_DEV_COURSE=archaeology"
    ok = True
    with sync_playwright() as p:
        import glob, os
        exe = (sorted(glob.glob(os.path.expanduser("~/Library/Caches/ms-playwright/chromium_headless_shell-*/*/chrome-headless-shell"))) or [None])[-1]
        b = p.chromium.launch(args=["--use-gl=angle", "--use-angle=swiftshader", "--mute-audio"], **({"executable_path": exe} if exe else {}))
        for size in a.sizes.split(","):
            w, h = (int(x) for x in size.split("x"))
            badges: list[str] = []
            shot_types: set[str] = set()
            for L, PL in zip(raw["lessons"], pub["lessons"]):
                lid = PL["id"]
                pg = b.new_page(viewport={"width": w, "height": h})
                pg.add_init_script("""try{ localStorage.setItem('outpost-callsign','Nova'); localStorage.setItem('atm-mode','academy');
                  localStorage.setItem('atm-academy', JSON.stringify({badges:%s, qualified:false})); }catch(e){}""" % json.dumps(badges))
                pg.add_init_script("""window.__ux_answer = t => { const q = document.getElementById('q'); q.value = t; document.getElementById('askForm').requestSubmit(); };""")
                pg.goto(a.base.rstrip("/") + "/?course=archaeology")
                pg.wait_for_selector(f'[data-l="{lid}"]', state="attached", timeout=60000)
                pg.wait_for_timeout(500)
                if not pg.query_selector(f'#aStart[data-l="{lid}"]'):
                    pg.evaluate("id => document.querySelector('.pin[data-l=\"' + id + '\"]').click()", lid)
                    pg.wait_for_selector(f'#aStart[data-l="{lid}"]', timeout=20000)
                pg.click("#aStart")
                for k, st in enumerate(L["steps"]):
                    t = st["accept"]["type"]
                    pg.wait_for_selector("#aInput", state="attached", timeout=20000)
                    pg.wait_for_timeout(1200)
                    if t in NEW and t not in shot_types:
                        f = out / f"arch_{t}-{size}.jpg"
                        pg.screenshot(path=str(f), type="jpeg", quality=82)
                        shot_types.add(t)
                        print("shot", f)
                    if a.keys and t == "rings" and size == a.sizes.split(",")[0]:
                        pg.focus(".ar-slider")
                        for _ in range(13):
                            pg.keyboard.press("ArrowLeft")
                        pg.keyboard.press("Enter")
                    elif a.keys and t == "hillshade" and size == a.sizes.split(",")[0]:
                        targets = st["accept"]["targets"][: st["accept"]["need"]]
                        for tg in targets:
                            pg.focus(".ar-hill-img")
                            # the crosshair starts at the centre (or the last tap) and moves 0.025 per arrow
                            cur = pg.evaluate("() => { const g = document.querySelector('.ar-cross'); const m = /translate\\(([\\d.]+) ([\\d.]+)\\)/.exec(g.getAttribute('transform')); return [ +m[1] / 100, +m[2] / 100 / (1000/1400) ]; }")
                            dx, dy = round((tg["x"] - cur[0]) / 0.025), round((tg["y"] - cur[1]) / 0.025)
                            for _ in range(abs(dx)):
                                pg.keyboard.press("ArrowRight" if dx > 0 else "ArrowLeft")
                            for _ in range(abs(dy)):
                                pg.keyboard.press("ArrowDown" if dy > 0 else "ArrowUp")
                            pg.keyboard.press("Enter")
                            pg.wait_for_timeout(1500)
                    elif t == "rounds":   # one round per turn: read which round the card is on
                        for _ in range(len(st["accept"]["rounds"])):
                            n = pg.evaluate("() => { const m = /(\\d+) of/.exec((document.querySelector('.f-round-n') || {}).textContent || ''); return m ? +m[1] : 1; }")
                            pg.evaluate("t => window.__ux_answer(t)", answer(st, ["x"] * (n - 1)))
                            pg.wait_for_timeout(2500)
                            if pg.query_selector("#aNext"):
                                break
                    else:
                        pg.evaluate("t => window.__ux_answer(t)", answer(st))
                    last = k == len(L["steps"]) - 1
                    nxt = f"Step {k + 2} of"
                    try:
                        pg.wait_for_function("""([last, nxt]) => last ? !!document.getElementById('aNext') || !!document.querySelector('.a-badge')
                            : !!document.getElementById('aNext') || ((document.querySelector('#aPanel .a-where') || {}).textContent || '').includes(nxt)""",
                                             arg=[last, nxt], timeout=30000)
                    except Exception:
                        fb = pg.evaluate("() => (document.getElementById('aFeedback') || {}).textContent || ''")
                        print(f"FAIL {size} {lid} step {k + 1} ({t}): did not advance. Feedback: {fb!r}")
                        pg.screenshot(path=str(out / f"fail-{L['id']}-{k + 1}-{size}.jpg"), type="jpeg", quality=70)
                        ok = False
                        break
                    if t in NEW and f"{t}:locked" not in shot_types:   # the answered card: law card, found tags, order
                        pg.wait_for_timeout(700)
                        pg.screenshot(path=str(out / f"arch_{t}_answered-{size}.jpg"), type="jpeg", quality=82)
                        shot_types.add(f"{t}:locked")
                    pg.evaluate("() => { const b = document.getElementById('aNext'); if (b) b.click(); }")
                    if last:
                        try:
                            pg.wait_for_selector(".a-badge", timeout=20000)
                            print(f"ok   {size} {lid}: patch {PL['badge']['name']}")
                            if L["id"] in ("what_is", "chimney_rock"):
                                pg.screenshot(path=str(out / f"arch_patch_{L['id']}-{size}.jpg"), type="jpeg", quality=82)
                        except Exception:
                            print(f"FAIL {size} {lid}: no patch screen"); ok = False
                    else:
                        pg.wait_for_function("nxt => ((document.querySelector('#aPanel .a-where') || {}).textContent || '').includes(nxt)", arg=nxt, timeout=30000)
                badges.append(PL["badge"]["id"])
                pg.close()
        b.close()
    print("ALL LESSONS PLAYED TO THEIR PATCH" if ok else "SOME LESSONS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
