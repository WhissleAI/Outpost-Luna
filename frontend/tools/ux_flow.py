"""End-to-end functional pass for the Flight School flows, two ways: by voice (typing into #q, which takes the same
session path as a spoken turn) and by click. Fails on any console error (except the known /api/voices 404 while that
endpoint isn't built) and on any step that doesn't advance.

  uv run --with playwright python frontend/tools/ux_flow.py --base http://localhost:5240
"""
import argparse
import glob
import os
import sys
import time

from playwright.sync_api import sync_playwright
import os as _os, sys as _sys  # noqa: E401
_d = _os.path.dirname(_os.path.abspath(__file__))
_sys.path[:0] = [_d, _os.path.join(_d, "..", "..", "tools")]
import silent  # noqa: E402,F401  (owner rule: every browser run is muted and headless; frontend/tools/silent.py)

sys.path.insert(0, os.path.dirname(__file__))
from ux_shots import COURSE, answer_for, _Vocab  # noqa: E402

IGNORE = ("favicon", "/api/voices", "404 (Not Found)")


def run(base, size=(1280, 720)):
    exe = (sorted(glob.glob(os.path.expanduser("~/Library/Caches/ms-playwright/chromium_headless_shell-*/*/chrome-headless-shell"))) or [None])[-1]
    errs, log = [], []
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=exe, args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream", "--autoplay-policy=no-user-gesture-required"])
        pg = b.new_page(viewport={"width": size[0], "height": size[1]})
        pg.on("console", lambda m: m.type == "error" and not any(x in m.text for x in IGNORE) and errs.append(m.text))
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.on("requestfailed", lambda r: print("  requestfailed:", r.url[:160], r.failure))
        say = lambda t: (pg.fill("#q", t), pg.press("#q", "Enter"))
        step = lambda msg: (log.append(msg), print("  ok ", msg))

        # ---- first launch: home → call sign by voice → the Moon map ----
        pg.goto(base); pg.wait_for_selector("#aCsForm", timeout=20000)
        step("home shows the call-sign form and one Start")
        assert pg.locator(".apanel.is-home .btn-primary").count() == 1
        say("call me Nova"); pg.wait_for_selector(".mp-card", timeout=20000)
        step("voice: 'call me Nova' → Moon map with the Next-up card")
        assert pg.evaluate("localStorage.getItem('outpost-callsign')") == "Nova"

        # ---- lesson 1 entirely by voice (typed turns go through the hands-free router) ----
        say("next"); pg.wait_for_selector(".apanel.is-lesson", timeout=20000)
        step("voice: 'next' → lesson 1 opens")
        L = next(l for l in COURSE["lessons"] if l["id"] == "moon")
        for k, st in enumerate(L["steps"]):
            pg.wait_for_timeout(700)
            say(answer_for(st, vocab=_Vocab()))
            last = k == len(L["steps"]) - 1
            pg.wait_for_selector("#aNext", timeout=25000)   # the last step's answer stays up: "Get your patch"
            step(f"voice: lesson 1 step {k + 1} ({st['accept']['type']}) answered")
            say("next")
            if last:
                pg.wait_for_selector(".a-badge", timeout=20000)
                pg.wait_for_timeout(1200)   # the session drops the same words twice within 1 s (session._dup)
            else:
                pg.wait_for_timeout(900)
        step("patch earned card")
        say("next"); pg.wait_for_selector(".apanel.is-lesson", timeout=20000)
        step("voice: 'next' on the patch → lesson 2")

        # ---- lesson 2 by click where the step has buttons, typing where it asks for a read-back ----
        L = COURSE["lessons"][1]   # the second stop on the route (course.json is in map order)
        for k, st in enumerate(L["steps"]):
            pg.wait_for_timeout(700)
            a = st["accept"]
            if a["type"] in ("choice", "predict"):
                pg.click(f'.a-choice[data-c="{a["answer"]}"]')
            else:
                say(answer_for(st, vocab=_Vocab()))
            last = k == len(L["steps"]) - 1
            pg.wait_for_selector("#aNext", timeout=25000)
            step(f"click/type: lesson 2 step {k + 1} ({a['type']})")
            pg.click("#aNext")
            if last:
                pg.wait_for_selector(".a-badge", timeout=20000)
            else:
                pg.wait_for_timeout(500)
        pg.click("#aMap"); pg.wait_for_selector(".mp-card", timeout=15000)
        step("click: patch → Map")
        assert pg.evaluate("JSON.parse(localStorage.getItem('atm-academy')).badges.length") == 2

        # ---- map: tap a pin, the card switches, Replay opens it, Map goes back ----
        pg.evaluate("document.querySelector('.pin[data-l=\"moon\"]').click()")
        pg.wait_for_selector('#aStart[data-l="moon"]', timeout=10000)
        step("click: a done pin → the card offers Replay")
        pg.click("#aStart"); pg.wait_for_selector(".apanel.is-lesson", timeout=15000)
        pg.click("#aBack"); pg.wait_for_selector(".mp-card", timeout=15000)
        step("click: Replay → lesson; Map → back")

        # ---- voice bar: typed command, keyboard nudge, reset ----
        say("move the voice bar to the top right"); pg.wait_for_timeout(700)
        assert pg.evaluate("document.getElementById('askbar').dataset.anchor") == "tr"
        say("reset the voice bar"); pg.wait_for_timeout(700)
        assert pg.evaluate("document.getElementById('askbar').dataset.anchor") == "bc"
        step("voice bar: move + reset by command")

        # ---- settings: open, switch section, change a pref, Esc closes ----
        pg.click("#a11yBtn"); pg.wait_for_selector(".a11y-panel:not([hidden])")
        pg.click('.set-nav [data-sec="listen"]'); pg.click('input[data-p="filter"][value="strict"]')
        assert pg.evaluate("JSON.parse(localStorage.getItem('outpost-prefs')).filter") == "strict"
        pg.keyboard.press("Escape"); pg.wait_for_selector(".a11y-panel[hidden]", state="attached")
        step("settings: listening filter saved; Esc closes")

        # ---- library and back ----
        pg.click("#libraryBtn"); pg.wait_for_timeout(1200)
        assert pg.evaluate("document.body.dataset.mode") == "cadet"
        say("where did Apollo 11 land?"); pg.wait_for_selector("#card:not([hidden])", timeout=25000)
        step("library: a question opens the answer card")
        pg.click("#modeAcademy"); pg.wait_for_selector(".mp-card", timeout=15000)
        step("back to Flight School")
        b.close()
    return errs, log


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--base", default="http://localhost:5240")
    ap.add_argument("--size", default="1280x720", help="the window, WxH (the owner checks 1280x720 and 1440x900)")
    a = ap.parse_args()
    t0 = time.time(); errs, log = run(a.base, tuple(map(int, a.size.split("x"))))
    print(f"{len(log)} checks in {time.time() - t0:.0f}s; console errors: {len(errs)}")
    for e in errs: print("  ERR", e[:300])
    sys.exit(1 if errs else 0)
