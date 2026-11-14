"""The floating voice bar must never move on its own (packaged-app RC bug: it "shakes strangely" on the Moon map and
the lesson screens). Samples the bar's rect every 50 ms for 5 s while captions come and go, the state word and the dots
change, words are heard and the lesson card re-renders, on the Moon map and on a lesson step, and asserts it never moves
or resizes. Then a window resize may move it (once), and it settles.

  uv run --with playwright python frontend/tools/voicebar_steady.py --base http://127.0.0.1:5398
"""
import argparse
import glob
import json
import os
import sys

from playwright.sync_api import sync_playwright

CHURN = """
async () => {
  const bar = document.getElementById('askbar'), cap = document.getElementById('captionBar');
  const st = document.getElementById('listenState'), words = document.getElementById('liveWords');
  const panel = document.getElementById('aPanel');
  const rect = () => { const r = bar.getBoundingClientRect(); return [r.left, r.top, r.width, r.height].map(v => Math.round(v * 10) / 10); };
  const lines = ['Every crew learns from the crews before.',
    'Apollo 11 landed on a mare. What does mare mean? It is one of the big dark patches you can see from Earth on a clear night.',
    'OK.', ''];
  const states = ['is-listening', 'is-speaking', 'is-thinking', 'is-hearing', 'is-idle'];
  const labels = ['', 'Didn\\'t catch that', 'Starting voice…', '', 'Hearing you'];
  const samples = []; const t0 = performance.now(); let k = 0;
  while (performance.now() - t0 < 5000) {
    if (k % 4 === 0) { const l = lines[(k / 4) % lines.length]; cap.innerHTML = l ? `<p class="cap-line">${l}</p>` : ''; }
    if (k % 3 === 0) { bar.classList.remove(...states); bar.classList.add(states[k % states.length]); st.textContent = labels[k % labels.length]; bar.classList.toggle('is-notice', k % 5 === 0); }
    if (k % 5 === 0) words.textContent = k % 10 ? 'oh it s' : '';
    if (panel && k % 2 === 0) { const d = document.createElement('i'); panel.append(d); setTimeout(() => d.remove(), 30); }
    samples.push(rect()); k++;
    await new Promise(r => setTimeout(r, 50));
  }
  cap.innerHTML = '';
  return samples;
}
"""


def steady(pg, where):
    s = pg.evaluate(CHURN)
    xs = {(a[0], a[1]) for a in s}
    sizes = {(a[2], a[3]) for a in s}
    print(f"  {where}: {len(s)} samples, positions={len(xs)} sizes={len(sizes)} first={s[0]}")
    return s, len(xs) == 1 and len(sizes) == 1


def run(base):
    exe = (sorted(glob.glob(os.path.expanduser("~/Library/Caches/ms-playwright/chromium_headless_shell-*/*/chrome-headless-shell"))) or [None])[-1]
    ok = True
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=exe, args=["--autoplay-policy=no-user-gesture-required"])
        pg = b.new_page(viewport={"width": 1280, "height": 720})
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(base)
        pg.wait_for_selector("#aCsForm", timeout=30000)
        say = lambda t: (pg.fill("#q", t), pg.press("#q", "Enter"))  # noqa: E731
        say("call me Nova")
        pg.wait_for_selector(".mp-card", timeout=20000)
        pg.wait_for_timeout(1200)
        s, good = steady(pg, "moon map")
        ok &= good
        say("lesson 2")
        pg.wait_for_selector("#aPanel.is-lesson", timeout=20000)
        pg.wait_for_timeout(1200)
        s, good = steady(pg, "lesson step")
        ok &= good
        before = pg.evaluate("(() => { const r = document.getElementById('askbar').getBoundingClientRect(); return [r.left, r.top]; })()")
        pg.set_viewport_size({"width": 1100, "height": 700})
        pg.wait_for_timeout(800)
        after = pg.evaluate("(() => { const r = document.getElementById('askbar').getBoundingClientRect(); return [r.left, r.top]; })()")
        print(f"  resize: {before} -> {after}")
        s, good = steady(pg, "lesson step after resize")
        ok &= good
        ok &= not errs
        if errs:
            print("  page errors:", errs[:3])
        b.close()
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:5398")
    sys.exit(run(ap.parse_args().base))
