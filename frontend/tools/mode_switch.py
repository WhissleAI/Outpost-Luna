"""Switching mode never leaks a screen (packaged-app RC bug: a Flight School lesson card stayed on top of the Mission
site picker, while the voice context was already Mission). For every mode pair, by tab and by voice: start a lesson
step (and answer one, as the owner had), switch away, assert no academy card is visible and the router's screen frame
is the new screen ("brief" = the Mission site picker, "library"); switch back and assert the same step is restored.

  uv run --with playwright python frontend/tools/mode_switch.py --base http://127.0.0.1:5398
"""
import argparse
import glob
import os
import sys

from playwright.sync_api import sync_playwright
import os as _os, sys as _sys  # noqa: E401
_d = _os.path.dirname(_os.path.abspath(__file__))
_sys.path[:0] = [_d, _os.path.join(_d, "..", "..", "tools")]
import silent  # noqa: E402,F401  (owner rule: every browser run is muted and headless; frontend/tools/silent.py)

VISIBLE = """sel => [...document.querySelectorAll(sel)].filter(e => e.getClientRects().length &&
  getComputedStyle(e).display !== 'none' && getComputedStyle(e).visibility !== 'hidden').length"""
ACADEMY_CARDS = "#aPanel, #aPanel.is-lesson, .apanel.is-lesson, .a-feedback, .a-choices, #aRideCabin"
MISSION_CARDS = "#mPanel, #mDebrief, #mBanner"
FRAME = {"academy": "lesson", "mission": "brief", "cadet": "library"}
TAB = {"academy": "#modeAcademy", "mission": "#modeMission", "cadet": "#libraryBtn"}
VOICE = {"academy": "go to the academy", "mission": "go to mission", "cadet": "open the library"}


def run(base):
    exe = (sorted(glob.glob(os.path.expanduser("~/Library/Caches/ms-playwright/chromium_headless_shell-*/*/chrome-headless-shell"))) or [None])[-1]
    fails, errs = [], []
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=exe, args=["--autoplay-policy=no-user-gesture-required"])
        pg = b.new_page(viewport={"width": 1280, "height": 720})
        pg.on("pageerror", lambda e: errs.append(str(e)))
        say = lambda t: (pg.fill("#q", t), pg.press("#q", "Enter"))  # noqa: E731
        frame = lambda: pg.evaluate("window.__outpost.screenFrame()") or {}  # noqa: E731
        vis = lambda sel: pg.evaluate(VISIBLE, sel)  # noqa: E731
        mode = lambda: pg.evaluate("document.body.dataset.mode")  # noqa: E731

        def check(cond, msg):
            print(("  ok   " if cond else "  FAIL ") + msg)
            if not cond:
                fails.append(msg)

        pg.goto(base)
        pg.wait_for_selector("#aCsForm", timeout=30000)
        say("call me Nova")
        pg.wait_for_selector(".mp-card", timeout=20000)
        # QA-19: Mission, then straight back to Flight School before the sites have loaded: no picker leaks over it
        pg.evaluate("document.getElementById('modeMission').click(); document.getElementById('modeAcademy').click()")
        pg.wait_for_timeout(3000)
        check(mode() == "academy" and vis(MISSION_CARDS) == 0, "QA-19: Mission -> Flight School while sites load: no picker")
        say("lesson 2")
        pg.wait_for_selector("#aPanel.is-lesson", timeout=20000)
        pg.click(".a-choice[data-c]")                      # answer step 1 by tap (right or wrong: feedback shows)
        pg.wait_for_timeout(800)
        say("next")                                        # if it passed, on to step 2
        pg.wait_for_timeout(800)
        want = {k: frame().get(k) for k in ("screen", "lesson_id", "step")}
        print("  lesson open:", want)
        check(want["screen"] == "lesson" and want["lesson_id"] == "history", "a lesson step is open")

        for how in ("tab", "voice"):
            for other in ("mission", "cadet"):
                # academy -> other
                (pg.click(TAB[other]) if how == "tab" else say(VOICE[other]))
                pg.wait_for_function(f"document.body.dataset.mode === '{other}'", timeout=10000)
                pg.wait_for_timeout(900)
                f = frame()
                check(vis(ACADEMY_CARDS) == 0, f"{how}: academy -> {other}: no lesson / academy card visible")
                check(f.get("screen") == FRAME[other], f"{how}: academy -> {other}: screen frame is {FRAME[other]!r} "
                                                       f"(got {f.get('screen')!r})")
                if other == "cadet":
                    check(vis(MISSION_CARDS) == 0, f"{how}: library shows no mission card")
                # other -> the third mode -> back, for the remaining pairs (mission <-> library)
                third = "cadet" if other == "mission" else "mission"
                (pg.click(TAB[third]) if how == "tab" else say(VOICE[third]))
                pg.wait_for_function(f"document.body.dataset.mode === '{third}'", timeout=10000)
                pg.wait_for_timeout(900)
                check(vis(ACADEMY_CARDS) == 0 and frame().get("screen") == FRAME[third],
                      f"{how}: {other} -> {third}: no academy card, frame {FRAME[third]!r}")
                if third == "cadet":
                    check(vis(MISSION_CARDS) == 0, f"{how}: {other} -> library: no mission card")
                # back to Flight School: the same step, restored
                (pg.click(TAB["academy"]) if how == "tab" else say(VOICE["academy"]))
                pg.wait_for_function("document.body.dataset.mode === 'academy'", timeout=10000)
                pg.wait_for_timeout(900)
                f = {k: frame().get(k) for k in ("screen", "lesson_id", "step")}
                check(f == want, f"{how}: {third} -> academy: the lesson step is restored ({f})")
                check(vis("#aPanel.is-lesson") == 1 and vis(MISSION_CARDS) == 0,
                      f"{how}: back in Flight School: the lesson card shows, no mission card")
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
