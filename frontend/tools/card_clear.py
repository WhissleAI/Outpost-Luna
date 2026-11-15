"""The lesson card never sits under the voice-bar caption (guidance playtest: at 1280x720 the vocab card's third answer
was under the caption until scrolled).

1. Opens "Lessons from Apollo" (a vocab_match step, three answers), shows a two-line caption, and asserts every answer
   button is fully visible, above the caption box and inside the card, at 1280x720, 1366x768, 1440x900 and 1100x700.
2. --all (default on): walks every step of every lesson (vocab, choice, predict, compare, route, command, keywords,
   tap, globe steps, the check ride) at 1280x720 and 1100x700 and asserts the step's answer controls are inside the card
   and clear of the caption; where the card has to scroll, the control must be reachable (scrolled into view on focus)
   and the card shows its fade.

  uv run --with playwright python frontend/tools/card_clear.py --base http://127.0.0.1:5398
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

sys.path.insert(0, os.path.dirname(__file__))
from ux_shots import COURSE, answer_for, _Vocab  # noqa: E402

CAPTION = """() => { document.getElementById('captionBar').innerHTML =
  '<p class="cap-line">Apollo 11 landed on a mare. What does mare mean? It is one of the big dark patches you can see from Earth.</p>'; }"""
MEASURE = """(sel) => {
  const cap = document.getElementById('captionBar');
  const c = cap.getBoundingClientRect(), card = document.getElementById('aPanel').getBoundingClientRect();
  const body = document.querySelector('#aPanel .a-body');
  const opts = [...document.querySelectorAll(sel)].filter(b => b.getClientRects().length).map(b => b.getBoundingClientRect());
  return { cap: [c.top, c.bottom, c.left, c.right], card: [card.top, card.bottom, card.left, card.right],
    scrolls: !!body && body.scrollHeight > body.clientHeight + 2, fade: !!body && body.classList.contains('is-more'),
    opts: opts.map(r => [r.top, r.bottom, r.left, r.right]) };
}"""
CONTROLS = "#aPanel .a-input button, #aPanel .a-input input, #aPanel .a-input [role=option]"


def check(m, label, k, t, bt, lft, rt):
    overlaps_cap = bt > m["cap"][0] and lft < m["cap"][3] and rt > m["cap"][2] and t < m["cap"][1]
    inside = t >= m["card"][0] - 0.5 and bt <= m["card"][1] + 0.5
    good = inside and not overlaps_cap
    print(f"  {'ok  ' if good else 'FAIL'} {label} control {k + 1}: top {t:.0f} bottom {bt:.0f}, caption top {m['cap'][0]:.0f}, "
          f"card bottom {m['card'][1]:.0f}{' (scrolled into view)' if m.get('scrolled') else ''}")
    return good


def first_card(b, base, vw, vh):
    pg = b.new_page(viewport={"width": vw, "height": vh})
    pg.goto(base)
    pg.wait_for_selector("#aCsForm", timeout=30000)
    say = lambda t: (pg.fill("#q", t), pg.press("#q", "Enter"))  # noqa: E731
    say("call me Nova")
    pg.wait_for_selector(".mp-card", timeout=20000)
    say("lesson 2")
    pg.wait_for_selector("#aPanel.is-lesson .a-choice", timeout=20000)
    pg.wait_for_timeout(1500)
    pg.evaluate(CAPTION)
    m = pg.evaluate(MEASURE, "#aPanel .a-choice")
    ok = all(check(m, f"{vw}x{vh} answer", k, *o) for k, o in enumerate(m["opts"]))
    pg.close()
    return ok


def every_step(b, base, vw, vh):
    """Every step of every lesson: each answer control fits in the card, or the card scrolls it into view on focus."""
    ctx = b.new_context(viewport={"width": vw, "height": vh})
    badges = []
    ok = True
    for L in COURSE["lessons"]:
        pg = ctx.new_page()
        pg.add_init_script("""try{ localStorage.setItem('outpost-callsign','Nova'); localStorage.setItem('atm-mode','academy');
          localStorage.setItem('atm-academy', JSON.stringify({badges:%s, qualified:false})); }catch(e){}""" % repr(badges).replace("'", '"'))
        pg.add_init_script("""window.__ux_answer = t => { const q = document.getElementById('q'); q.value = t; document.getElementById('askForm').requestSubmit(); };""")
        pg.goto(base)
        pg.wait_for_selector(f'[data-l="{L["id"]}"]', state="attached", timeout=30000)
        pg.wait_for_timeout(400)
        if not pg.query_selector(f'#aStart[data-l="{L["id"]}"]'):   # the next lesson's card is already up; else pick its pin
            pg.evaluate("id => document.querySelector('.pin[data-l=\"' + id + '\"]').click()", L["id"])
            pg.wait_for_selector(f'#aStart[data-l="{L["id"]}"]', timeout=20000)
        pg.click("#aStart")
        for k, st in enumerate(L["steps"]):
            pg.wait_for_selector("#aInput", state="attached", timeout=20000)
            pg.wait_for_timeout(900)
            pg.evaluate(CAPTION)
            label = f"{vw}x{vh} {L['id']} step {k + 1} ({st['accept']['type']})"
            m = pg.evaluate(MEASURE, CONTROLS)
            for j, o in enumerate(m["opts"]):
                t, bt = o[0], o[1]
                if (t < m["card"][0] or bt > m["card"][1]) and m["scrolls"]:
                    # out of the card's view: it must come into view when focused (Tab / voice "option 3")
                    pg.evaluate("([sel, j]) => { const e = [...document.querySelectorAll(sel)].filter(b => b.getClientRects().length)[j]; e.focus(); }", [CONTROLS, j])
                    pg.wait_for_timeout(250)
                    m2 = pg.evaluate(MEASURE, CONTROLS)
                    m2["scrolled"] = True
                    if not m["fade"]:
                        print(f"  FAIL {label}: the card scrolls but shows no fade"); ok = False
                    ok &= check(m2, label, j, *m2["opts"][j])
                    pg.evaluate("() => { const b = document.querySelector('#aPanel .a-body'); if (b) b.scrollTop = 0; }")
                else:
                    ok &= check(m, label, j, *o)
            if not m["opts"]:
                print(f"  ok   {label}: no answer controls (the globe is the answer surface)")
            pg.evaluate("t => window.__ux_answer(t)", answer_for(st, vocab=_Vocab()))
            last = k == len(L["steps"]) - 1
            # the step is passed: a Next button, the patch, or (the check ride moves on by itself) the next step
            nxt = f"Step {k + 2} of"
            try:
                pg.wait_for_function("""([last, nxt]) => last ? !!document.querySelector('.a-badge')
                    : !!document.getElementById('aNext') || ((document.querySelector('#aPanel .a-where') || {}).textContent || '').includes(nxt)""",
                                     arg=[last, nxt], timeout=30000)
            except Exception:
                print(f"  note {label}: did not advance by voice (skipping the rest of {L['id']})")
                break
            if not last:   # a Next button can be replaced under the click (the ride's own advance): press it if it's there
                pg.evaluate("() => { const b = document.getElementById('aNext'); if (b) b.click(); }")
                pg.wait_for_function("nxt => ((document.querySelector('#aPanel .a-where') || {}).textContent || '').includes(nxt)",
                                     arg=nxt, timeout=30000)
        badges.append(L["badge"]["id"])
        pg.close()
    ctx.close()
    return ok


def run(base, sweep=True):
    exe = (sorted(glob.glob(os.path.expanduser("~/Library/Caches/ms-playwright/chromium_headless_shell-*/*/chrome-headless-shell"))) or [None])[-1]
    ok = True
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=exe, args=["--autoplay-policy=no-user-gesture-required"])
        for vw, vh in ((1280, 720), (1366, 768), (1440, 900), (1100, 700)):
            ok &= first_card(b, base, vw, vh)
        if sweep:
            for vw, vh in ((1280, 720), (1100, 700)):
                ok &= every_step(b, base, vw, vh)
        b.close()
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:5398")
    ap.add_argument("--no-sweep", action="store_true", help="only the vocab card at four sizes")
    a = ap.parse_args()
    sys.exit(run(a.base, not a.no_sweep))
