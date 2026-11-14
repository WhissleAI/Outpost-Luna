"""The lesson card never sits under the voice-bar caption (guidance playtest: at 1280x720 the vocab card's third answer
was under the caption until scrolled). Opens "Lessons from Apollo" (a vocab_match step, three answers), shows a
two-line caption, and asserts every answer button is fully visible, above the caption box and inside the card.

  uv run --with playwright python frontend/tools/card_clear.py --base http://127.0.0.1:5398
"""
import argparse
import glob
import os
import sys

from playwright.sync_api import sync_playwright

MEASURE = """() => {
  const cap = document.getElementById('captionBar');
  cap.innerHTML = '<p class="cap-line">Apollo 11 landed on a mare. What does mare mean? It is one of the big dark patches you can see from Earth.</p>';
  const c = cap.getBoundingClientRect(), card = document.getElementById('aPanel').getBoundingClientRect();
  const opts = [...document.querySelectorAll('#aPanel .a-choice')].map(b => b.getBoundingClientRect());
  return { cap: [c.top, c.bottom, c.left, c.right], card: [card.top, card.bottom], opts: opts.map(r => [r.top, r.bottom, r.left, r.right]) };
}"""


def run(base):
    exe = (sorted(glob.glob(os.path.expanduser("~/Library/Caches/ms-playwright/chromium_headless_shell-*/*/chrome-headless-shell"))) or [None])[-1]
    ok = True
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=exe, args=["--autoplay-policy=no-user-gesture-required"])
        for vw, vh in ((1280, 720), (1366, 768), (1440, 900)):
            pg = b.new_page(viewport={"width": vw, "height": vh})
            pg.goto(base)
            pg.wait_for_selector("#aCsForm", timeout=30000)
            say = lambda t: (pg.fill("#q", t), pg.press("#q", "Enter"))  # noqa: E731
            say("call me Nova")
            pg.wait_for_selector(".mp-card", timeout=20000)
            say("lesson 2")
            pg.wait_for_selector("#aPanel.is-lesson .a-choice", timeout=20000)
            pg.wait_for_timeout(1500)
            m = pg.evaluate(MEASURE)
            cap_top, card_bottom = m["cap"][0], m["card"][1]
            for k, (t, bt, lft, rt) in enumerate(m["opts"]):
                overlaps_cap = bt > cap_top and lft < m["cap"][3] and rt > m["cap"][2]
                inside = t >= m["card"][0] - 0.5 and bt <= card_bottom + 0.5
                good = inside and not overlaps_cap
                ok &= good
                print(f"  {'ok  ' if good else 'FAIL'} {vw}x{vh} answer {k + 1}: bottom {bt:.0f}, caption top {cap_top:.0f}, card bottom {card_bottom:.0f}")
            pg.close()
        b.close()
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:5398")
    sys.exit(run(ap.parse_args().base))
