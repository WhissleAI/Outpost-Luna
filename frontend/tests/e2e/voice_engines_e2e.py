"""Settings → Voice, end to end: exactly two engines; the computer's voice shows no voice list (only the recorded-guide
toggle and the OS hint); Steer TTS shows Steer's voice list with previews; switching back hides it again. Silent
(silent.py: muted, no audio output, headless).

    (backend on :8215 serving frontend/dist, its model server with Steer loaded)
    uv run --no-project --with playwright==1.58.0 python frontend/tests/e2e/voice_engines_e2e.py --base http://127.0.0.1:8215
"""
from __future__ import annotations

import argparse
import glob
import os
import sys

from playwright.sync_api import sync_playwright

_d = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [_d, os.path.join(_d, "..", "..", "tools")]
from silent import LAUNCH_ARGS, silence  # noqa: E402

FAILS: list[str] = []


def ok(cond, what):
    print(("PASS " if cond else "FAIL ") + what, flush=True)
    if not cond:
        FAILS.append(what)


def until(pg, expr, timeout=15000):
    try:
        pg.wait_for_function(expr, timeout=timeout)
        return True
    except Exception:  # noqa: BLE001
        return False


STATE = """() => { const box = document.querySelector('#setVoices'); if (!box) return null;
  return { engines: [...box.querySelectorAll('input[name=p-engine]')].map(i => ({ v: i.value, on: i.checked, dis: i.disabled })),
           osList: box.querySelectorAll('input[data-p=voice]').length,
           steerList: [...box.querySelectorAll('input[data-p=steer_voice]')].map(i => i.value),
           previews: box.querySelectorAll('[data-preview]').length,
           pack: !!box.querySelector('[data-pb=pack]'), everyone: !!box.querySelector('[data-pb=voice_all]'),
           text: box.textContent } }"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8215")
    base = ap.parse_args().base.rstrip("/")
    exe = (sorted(glob.glob(os.path.expanduser("~/Library/Caches/ms-playwright/chromium_headless_shell-*/*/chrome-headless-shell"))) or [None])[-1]
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=exe, args=[*LAUNCH_ARGS, "--enable-unsafe-swiftshader"])
        ctx = b.new_context(viewport={"width": 1280, "height": 800})
        silence(ctx)
        pg = ctx.new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(base + "/")
        until(pg, "() => window.__outpost && window.__outpost.a11y", 30000)
        pg.wait_for_timeout(1000)
        pg.mouse.click(*pg.evaluate("() => { const q = document.getElementById('a11yBtn').getBoundingClientRect(); return [q.x + q.width / 2, q.y + q.height / 2]; }"))
        pg.evaluate("() => document.querySelector('.a11y-panel [data-sec=voice]').click()")
        ok(until(pg, "() => document.querySelectorAll('#setVoices input[name=p-engine]').length === 2"), "two engine choices")
        s = pg.evaluate(STATE)
        ok([e["v"] for e in s["engines"]] == ["os", "steer"], f"engines {s['engines']}")
        ok(s["engines"][0]["on"] and not s["engines"][1]["dis"], "computer's voice selected; Steer ready (enabled)")
        ok(s["osList"] == 0 and not s["steerList"] and not s["everyone"], "computer's voice: no voice list, no 'everyone'")
        ok(s["pack"], "computer's voice: the recorded guide voice toggle")
        pg.evaluate("() => document.querySelector('#setVoices input[value=steer]').click()")
        ok(until(pg, "() => document.querySelectorAll('#setVoices input[data-p=steer_voice]').length > 0"), "Steer shows its voices")
        s = pg.evaluate(STATE)
        ok(len(s["steerList"]) == 10 and s["previews"] == 10 and "Aurora" in s["text"], f"10 Steer voices with previews ({len(s['steerList'])})")
        ok(not s["pack"] and s["osList"] == 0, "Steer: no recorded-guide toggle, no OS list")
        ok(pg.evaluate("() => window.__outpost.prefsApi.value.engine") == "steer", "pref engine = steer")
        pg.evaluate("() => document.querySelector('#setVoices input[value=os]').click()")
        ok(until(pg, "() => !document.querySelector('#setVoices input[data-p=steer_voice]')"), "back to the computer's voice: Steer list gone")
        nav = pg.evaluate("() => [...document.querySelectorAll('.a11y-panel .set-nav [data-sec]')].map(b => b.dataset.sec)")
        ok(nav[-1] == "reset" and nav[-2] == "help", f"Reset is the last sidebar item, below Help ({nav[-3:]})")
        ok(not errs, f"no page errors {errs[:2]}")
        b.close()
    print(f"{'ALL PASS' if not FAILS else f'{len(FAILS)} FAILED'}")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
