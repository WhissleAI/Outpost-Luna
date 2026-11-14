"""One tap, one spoken line (packaged-app RC bug: a tap on the Moon in "Know your Moon" sometimes said the same thing
twice, in two voices). Real mouse taps on the globe at a place's screen position; every line the floor starts playing is
recorded (floor "playback" start events, with the voice). Asserts:
  - a lesson tap step (Know your Moon: find Apollo 11's landing site): exactly one line per tap, wrong or right;
  - a lesson route step (Lessons from Apollo: Orientale, then Ohm): the leg taps say nothing, the last tap one line;
  - free explore: a tap on a named place in the Library says one line; a tap on the Flight School map says nothing;
  - no line is ever spoken twice for one tap, in any voice.

  uv run --with playwright python frontend/tools/tap_once.py --base http://127.0.0.1:5398
"""
import argparse
import glob
import os
import sys

from playwright.sync_api import sync_playwright

HOOK = """() => { const O = window.__outpost; window.__lines = [];
  O.floor.on('playback', e => { if (e.state === 'start') window.__lines.push({ voice: e.kind, text: e.text || '' }); }); }"""


def run(base):
    exe = (sorted(glob.glob(os.path.expanduser("~/Library/Caches/ms-playwright/chromium_headless_shell-*/*/chrome-headless-shell"))) or [None])[-1]
    fails, errs = [], []
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=exe, args=["--autoplay-policy=no-user-gesture-required"])
        pg = b.new_page(viewport={"width": 1280, "height": 720})
        pg.on("pageerror", lambda e: errs.append(str(e)))
        say = lambda t: (pg.fill("#q", t), pg.press("#q", "Enter"))  # noqa: E731

        def check(cond, msg):
            print(("  ok   " if cond else "  FAIL ") + msg)
            if not cond:
                fails.append(msg)

        def quiet(ms=400):
            pg.wait_for_function("!window.__outpost.floor.guideBusy", timeout=60000)
            pg.wait_for_timeout(ms)

        def tap_place(pid, settle=4500):
            """Turn the Moon to the place, then a real mouse tap on it. -> the lines spoken for that tap."""
            pg.evaluate("id => { const f = window.__outpost.placeById(id); window.__outpost.globe.showFeature(f, { dist: 2.4 }); }", pid)
            pg.wait_for_timeout(1800)
            quiet()
            xy = pg.evaluate("""id => { const O = window.__outpost, f = O.placeById(id), s = document.getElementById('stage').getBoundingClientRect();
              const q = O.globe.project(f.lat, f.lon); return [s.left + q.x, s.top + q.y, q.visible !== false]; }""", pid)
            pg.evaluate("window.__lines = []")
            pg.mouse.move(xy[0], xy[1]); pg.mouse.down(); pg.mouse.up()
            pg.wait_for_timeout(settle)
            quiet(600)
            return pg.evaluate("window.__lines")

        def once(lines, n, what):
            texts = [ln["text"] for ln in lines]
            check(len(lines) == n and len(set(texts)) == len(texts), f"{what}: {len(lines)} line(s), want {n} {lines}")

        pg.goto(base)
        pg.wait_for_selector("#aCsForm", timeout=30000)
        pg.evaluate(HOOK)
        say("call me Nova")
        pg.wait_for_selector(".mp-card", timeout=20000)
        quiet()
        once(tap_place("tycho"), 0, "Flight School map: a tap says nothing (the map card owns it)")

        say("lesson 1")                                     # Know your Moon, step 1: find where Apollo 11 landed
        pg.wait_for_selector("#aPanel.is-lesson", timeout=20000)
        quiet(800)
        once(tap_place("tycho"), 1, "lesson tap step, wrong place: one line")
        once(tap_place("tranquillitatis"), 1, "lesson tap step, right place: one line")

        say("lesson 2")                                     # Lessons from Apollo: answer by voice up to the route step
        pg.wait_for_selector("#aPanel.is-lesson", timeout=20000)
        quiet(800)
        for t in ("one", "next", "a", "next", "yes", "next"):
            say(t)
            pg.wait_for_timeout(1500)
            quiet(300)
        frame = pg.evaluate("window.__outpost.screenFrame()")
        check(frame.get("step_type") == "route", f"on the route step ({frame})")
        once(tap_place("orientale"), 0, "route step, first stop: the leg is drawn, nothing said")
        # the last stop: CAPCOM acknowledges ("Roger.") and the step's "after" crew clip tells it, never both telling it
        lines = tap_place("ohm", settle=6000)
        guide = [ln for ln in lines if ln["voice"] == "guide"]
        check(len(guide) == 1 and len(guide[0]["text"].split()) <= 3 and len(lines) <= 2,
              f"route step, last stop: one short CAPCOM ack (+ the crew clip), no paraphrase twice {lines}")

        pg.click("#libraryBtn")
        pg.wait_for_function("document.body.dataset.mode === 'cadet'", timeout=10000)
        pg.wait_for_timeout(2500)
        quiet()
        once(tap_place("tycho"), 1, "Library: a tap on a named place says one line")
        b.close()
    if errs:
        print("  page errors:", errs[:3])
    ok = not fails and not errs
    print("PASS" if ok else f"FAIL ({len(fails)})")
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:5398")
    sys.exit(run(ap.parse_args().base))
