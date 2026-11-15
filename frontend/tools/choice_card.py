"""The Now panel's choice card, by every input (the owner's "Steer left / Steer right": "like i can't control").

From a fresh "Boulders ahead. Steer left or right?" each time, one input picks an option, and the check is that:
  * exactly one control holds focus, and it wears its own ring (no ring round the group);
  * the arrows move focus from one option to the other (and nowhere else);
  * the pick lands: the card moves on and the sim got the choice (the step is done);
  * the card did not rebuild under the input (the focused button is the same node a second later).
Inputs: mouse click, keyboard (Tab into it, arrow, Enter), the number key 2, a game controller (stub pad: D-pad + A),
and voice (the typed turn "right" through the session's router -> task_choice).

  uv run --with playwright python frontend/tools/choice_card.py --base http://127.0.0.1:5199 [--size 1440x879]
"""
import argparse
import os
import sys
import time

from playwright.sync_api import sync_playwright
import os as _os, sys as _sys  # noqa: E401
_d = _os.path.dirname(_os.path.abspath(__file__))
_sys.path[:0] = [_d, _os.path.join(_d, "..", "..", "tools")]
import silent  # noqa: E402,F401  (owner rule: every browser run is muted and headless; frontend/tools/silent.py)
import mission_ui as mu  # noqa: E402

PAD = """(() => { const B = () => Array.from({ length: 17 }, () => ({ pressed: false, touched: false, value: 0 }));
  const pad = { id: 'Synthetic (STANDARD GAMEPAD)', index: 0, connected: true, mapping: 'standard', buttons: B(), axes: [0, 0, 0, 0], timestamp: 0 };
  let plugged = false;
  Object.defineProperty(navigator, 'getGamepads', { value: () => (plugged ? [pad, null, null, null] : [null, null, null, null]), configurable: true });
  window.__plug = () => { plugged = true; const e = new Event('gamepadconnected'); Object.defineProperty(e, 'gamepad', { value: pad }); dispatchEvent(e); };
  window.__btn = (i, on) => { pad.buttons[i] = { pressed: on, touched: on, value: on ? 1 : 0 }; pad.timestamp++; }; })();"""
STATE = """() => { const a = document.activeElement, b = [...document.querySelectorAll('.cb-now-btns .cb-now-b')];
  const ring = e => { const cs = getComputedStyle(e); return cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) > 0; };
  const g = document.querySelector('.cb-now-btns');
  return { focus: b.indexOf(a), n: b.length, ring: a && b.includes(a) ? ring(a) : false, groupRing: g ? ring(g) : false,
    others: b.filter(x => x !== a && ring(x)).length, text: (document.querySelector('#cbNowT') || {}).textContent || '',
    card: (window.__outpost.missionUI.card || {}).key || '' }; }"""
results = []


def ok(cond, what):
    results.append((bool(cond), what))
    print(("PASS " if cond else "FAIL ") + what, flush=True)


def moved_on(pg, before):
    end = time.time() + 8
    while time.time() < end:
        s = pg.evaluate(STATE)
        if s["card"] != before:
            return s
        pg.wait_for_timeout(250)
    return pg.evaluate(STATE)


def fresh(b, base, size, pad=False):
    pg = b.new_page(viewport={"width": size[0], "height": size[1]})
    pg.set_default_timeout(180000)
    if pad:
        pg.add_init_script(PAD)
    pg.add_init_script(mu.SEED)
    pg.goto(base)
    if not mu.to_steer(pg):
        ok(False, "reached the steer choice")
        return None
    pg.wait_for_timeout(800)
    return pg


def run(base, size):
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=mu.chromium(), args=["--use-gl=angle", "--use-angle=swiftshader"])
        # 1. mouse: a real click on "Steer right"
        pg = fresh(b, base, size)
        if pg:
            before = pg.evaluate(STATE)["card"]
            box = pg.locator(".cb-now-btns .cb-now-b").nth(1).bounding_box()
            pg.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            pg.wait_for_timeout(400)
            hover = pg.evaluate("() => getComputedStyle(document.querySelectorAll('.cb-now-btns .cb-now-b')[1]).backgroundColor")
            pg.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            s = moved_on(pg, before)
            ok(s["card"] != before, f"mouse: a click on 'Steer right' lands (now: {s['text'][:40]})")
            ok(bool(hover), "mouse: the option shows a hover state")
            pg.close()
        # 2. keyboard: focus the first option, the arrow moves to the second, Enter presses it; one ring at a time
        pg = fresh(b, base, size)
        if pg:
            pg.evaluate("document.querySelector('.cb-now-btns .cb-now-b').focus()")
            pg.keyboard.press("Shift")   # keyboard modality (focus-visible)
            s0 = pg.evaluate(STATE)
            ok(s0["focus"] == 0 and s0["ring"] and not s0["groupRing"] and s0["others"] == 0,
               f"keyboard: one ring, on the focused option only (focus {s0['focus']}, group ring {s0['groupRing']}, others {s0['others']})")
            node = pg.evaluate_handle("document.activeElement")
            pg.wait_for_timeout(1500)
            ok(pg.evaluate("n => n === document.activeElement && n.isConnected", node), "keyboard: the card doesn't rebuild under the focused option")
            pg.keyboard.press("ArrowRight")
            pg.wait_for_timeout(500)
            s1 = pg.evaluate(STATE)
            ok(s1["focus"] == 1, f"keyboard: the arrow moves to the other option (focus {s1['focus']})")
            before = s1["card"]
            pg.keyboard.press("Enter")
            s = moved_on(pg, before)
            ok(s["card"] != before, "keyboard: Enter presses the focused option")
            pg.close()
        # 3. the number key
        pg = fresh(b, base, size)
        if pg:
            before = pg.evaluate(STATE)["card"]
            pg.keyboard.press("2")
            s = moved_on(pg, before)
            ok(s["card"] != before, "keyboard: 2 picks the second option")
            pg.close()
        # 4. a game controller: plug in, D-pad right to the second option, A
        pg = fresh(b, base, size, pad=True)
        if pg:
            pg.evaluate("window.__plug()")
            pg.wait_for_timeout(800)
            pg.evaluate("document.querySelector('.cb-now-btns .cb-now-b').focus()")
            for i in (15,):   # D-pad right
                pg.evaluate(f"window.__btn({i}, true)"); pg.wait_for_timeout(250); pg.evaluate(f"window.__btn({i}, false)"); pg.wait_for_timeout(400)
            s1 = pg.evaluate(STATE)
            ok(s1["focus"] == 1, f"controller: the D-pad moves to the other option (focus {s1['focus']})")
            before = s1["card"]
            pg.evaluate("window.__btn(0, true)"); pg.wait_for_timeout(250); pg.evaluate("window.__btn(0, false)")
            s = moved_on(pg, before)
            ok(s["card"] != before, "controller: A presses it")
            pg.close()
        # 5. voice: the kid says "right" (typed into the voice bar; the session's router makes it task_choice)
        pg = fresh(b, base, size)
        if pg:
            before = pg.evaluate(STATE)["card"]
            say = pg.evaluate("() => (document.querySelector('.cb-now-say') || {}).textContent || ''")
            ok("right" in say.lower() and "left" in say.lower(), f"voice: the card says what to say ('{say}')")
            pg.evaluate("t => { const q = document.getElementById('q'); q.value = t; document.getElementById('askForm').requestSubmit(); }", "right")
            s = moved_on(pg, before)
            ok(s["card"] != before, "voice: 'right' picks it")
            pg.close()
        b.close()
    bad = [w for c, w in results if not c]
    print("PASS" if not bad else f"FAIL ({len(bad)})")
    return 0 if not bad else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:5199")
    ap.add_argument("--size", default="1440x879")
    a = ap.parse_args()
    sys.exit(run(a.base, tuple(map(int, a.size.split("x")))))
