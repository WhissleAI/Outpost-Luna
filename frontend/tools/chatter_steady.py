"""[P0] Room chatter leaves no trace (the owner's "keeps flickering badly" + "Shit. Shit." on the voice bar).

Replaces the ear socket (/ws/listen) with a fake that feeds the client a stream of room-chatter turns exactly as the ear
sends them (turn start, partial words, the Arc read, turn end): "Oh.", "um", two adults talking, a profanity with
device_directed 0.91 (what Arc said in the owner's room). On the map, a lesson, the Library and the cabin it samples
the voice bar every 100 ms for 10 s and asserts

  - 0 overheard words shown (the bar's words, the caption, the transcript, the answer card),
  - no "Thinking" and no "Hearing you",
  - at most 1 state change,

then a real directed turn ("where did Apollo 11 land?", dd 0.95) in the Library must still show its words and get
answered (the card opens).

  uv run --with playwright python frontend/tools/chatter_steady.py --base http://localhost:5311
"""
import argparse
import glob
import json
import os
import sys
import time

from playwright.sync_api import sync_playwright

CHATTER = [   # (text, device_directed, seconds before the next turn)
    ("Oh.", 0.4, 0.7),
    ("um", 0.3, 0.6),
    ("Did you call your mother about Sunday?", 0.12, 1.0),
    ("Yeah, she said three o'clock is fine.", 0.15, 0.9),
    ("Shit. Shit.", 0.91, 0.8),
    ("Can you pass me the charger", 0.2, 0.9),
    ("Oh, it's over there by the couch.", 0.18, 1.0),
    ("shit shit oh", 0.91, 0.8),
]
WORDS = sorted({w.strip(".,?'").lower() for t, _, _ in CHATTER for w in t.split() if len(w.strip(".,?'")) > 3})

SAMPLE = r"""() => {
  const bar = document.getElementById('askbar'), st = document.getElementById('listenState');
  const shown = ['is-thinking', 'is-hearing', 'is-speaking', 'is-notice', 'is-listening', 'is-idle'].find(c => bar.classList.contains(c)) || '';
  const vis = e => e && e.getClientRects().length > 0 && !e.closest('[hidden]');
  const card = document.getElementById('card');
  const tr = ((window.__outpost || {}).transcript || []).filter(e => e.who === 'kid').map(e => e.text).join(' | ');
  return {shown, label: st.textContent || getComputedStyle(st, '::before').content, words: document.getElementById('liveWords').textContent,
    caption: document.getElementById('captionBar').innerText, card: vis(card) ? card.innerText : '', transcript: tr,
    asked: vis(document.getElementById('cardAsked')) ? document.getElementById('cardAsked').innerText : '',
    speaking: !!(window.__outpost && window.__outpost.floor && window.__outpost.floor.holder && window.__outpost.floor.holder !== 'none')};
}"""


def run(base):
    exe = (sorted(glob.glob(os.path.expanduser("~/Library/Caches/ms-playwright/chromium_headless_shell-*/*/chrome-headless-shell"))) or [None])[-1]
    fails, report = [], []
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=exe, args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
                                                        "--autoplay-policy=no-user-gesture-required"])   # the real GPU: the cabin is heavy
        ctx = b.new_context(viewport={"width": 1280, "height": 720})
        six = ["scout", "history", "radio", "sun", "storm", "ice", "commander"]
        ctx.add_init_script("""try{if(!sessionStorage.getItem('cs')){sessionStorage.setItem('cs','1');localStorage.clear();
          localStorage.setItem('outpost-callsign','Nova');localStorage.setItem('outpost-tour-done:Nova','1');
          localStorage.setItem('atm-academy', JSON.stringify({badges:%s, qualified:true}));}}catch(e){}""" % json.dumps(six))
        # The fake ear: a stand-in WebSocket for /ws/listen only (page.route_web_socket stalls the other sockets in
        # headless Chromium, so the session never connected). Audio frames are swallowed; window.__ear(m) delivers m.
        ctx.add_init_script("""(() => { const Real = window.WebSocket;
          class FakeEar { constructor(url) { this.url = url; this.readyState = 0; this.binaryType = 'arraybuffer';
              window.__earSock = this; setTimeout(() => { this.readyState = 1; this.onopen && this.onopen({});
                this.onmessage && this.onmessage({data: JSON.stringify({t: 'ready'})}); }, 30); }
            send() {} close() { this.readyState = 3; } }
          window.WebSocket = function (url, p) { return /\\/ws\\/listen/.test(url) ? new FakeEar(url) : new Real(url, p); };
          Object.assign(window.WebSocket, {CONNECTING: 0, OPEN: 1, CLOSING: 2, CLOSED: 3});
          window.__ear = m => { const s = window.__earSock; if (s && s.onmessage) s.onmessage({data: JSON.stringify(m)}); }; })();""")
        pg = ctx.new_page(); pg.set_default_timeout(30000)
        pg.on("pageerror", lambda e: fails.append(f"page error: {e}"))
        heard = []   # the router's verdicts (the session's `heard` decisions), for the report

        def on_sock(ws):
            if "/ws/session" not in ws.url:
                return

            def rx(payload):
                try:
                    m = json.loads(payload)
                except Exception:
                    return
                for d in (m.get("decisions") if isinstance(m, dict) and "decisions" in m else [m]):
                    if isinstance(d, dict) and d.get("t") == "heard":
                        heard.append((d.get("outcome"), d.get("reason"), d.get("text")))
            ws.on("framereceived", rx)
        pg.on("websocket", on_sock)
        send = lambda m: pg.evaluate("m => window.__ear(m)", m)  # noqa: E731

        def say_turn(text, dd):
            send({"t": "turn", "state": "start", "text": ""})
            words = text.split()
            for k in range(1, len(words) + 1):
                send({"t": "words", "text": " ".join(words[:k]), "final": False}); pg.wait_for_timeout(60)
            send({"t": "arc", "device_directed": dd})
            send({"t": "words", "text": text, "final": True})
            send({"t": "turn", "state": "end", "text": text})

        def quiet(max_s=25):
            t0 = time.time()
            while time.time() - t0 < max_s:
                s = pg.evaluate(SAMPLE)
                if not s["speaking"] and s["shown"] in ("is-listening",):
                    pg.wait_for_timeout(1200)
                    s = pg.evaluate(SAMPLE)
                    if not s["speaking"] and s["shown"] == "is-listening":
                        return True
                pg.wait_for_timeout(300)
            return False

        def check(where):
            if not quiet():
                fails.append(f"{where}: the app never went quiet (still speaking)"); return
            tr0 = pg.evaluate(SAMPLE)["transcript"]
            samples, t0, k, nxt = [], time.time(), 0, 0.0
            while time.time() - t0 < 10:
                el = time.time() - t0
                if k < len(CHATTER) and el >= nxt:
                    text, dd, gap = CHATTER[k]; say_turn(text, dd); nxt = el + gap + 0.1 * len(text.split()); k += 1
                samples.append(pg.evaluate(SAMPLE)); pg.wait_for_timeout(100)
            states = [s["shown"] for s in samples]
            changes = sum(1 for i in range(1, len(states)) if states[i] != states[i - 1])
            leaked = set()
            for s in samples:
                # kid text can show in the bar's words, the card's "you asked" line and the transcript (the caption
                # and the card's body are the app's own lines)
                blob = " ".join([s["words"], s["asked"], s["transcript"][len(tr0):]]).lower()
                leaked |= {w for w in WORDS if w in blob}
            bad = [s for s in states if s in ("is-thinking", "is-hearing")]
            row = {"where": where, "samples": len(samples), "changes": changes, "thinking_or_hearing": len(bad), "leaked": sorted(leaked),
                   "states": sorted(set(states))}
            row["router"] = heard[:]; heard.clear()
            report.append(row); print(json.dumps(row), flush=True)
            if leaked: fails.append(f"{where}: overheard words shown: {sorted(leaked)}")
            if bad: fails.append(f"{where}: Thinking/Hearing shown {len(bad)} samples")
            if changes > 1: fails.append(f"{where}: {changes} state changes")

        pg.goto(base); pg.wait_for_selector("#modeAcademy", timeout=30000); pg.wait_for_timeout(2500)
        pg.mouse.click(1200, 400)   # the first gesture opens the (fake) mic
        pg.wait_for_timeout(1500)
        # map
        pg.click("#modeAcademy"); pg.wait_for_selector(".mp-card", timeout=20000); check("map")
        # a lesson (a choice step: words that are not an option must not grade)
        pg.evaluate("document.querySelector('.pin[data-l=\"history\"]').click()"); pg.wait_for_timeout(800)
        pg.click("#aStart"); pg.wait_for_selector(".apanel.is-lesson", timeout=20000); check("lesson")
        misses = pg.evaluate("document.querySelectorAll('.a-choice.is-wrong').length")
        if misses: fails.append(f"lesson: chatter graded as {misses} wrong answers")
        # Library
        pg.click("#libraryBtn"); pg.wait_for_timeout(2500); check("library")
        # a real directed turn still works (Library)
        quiet()
        say_turn("where did Apollo 11 land", 0.95)
        seen_words, t0 = "", time.time()
        while time.time() - t0 < 8:
            s = pg.evaluate(SAMPLE)
            if "apollo" in s["words"].lower(): seen_words = s["words"]
            if s["card"] and seen_words: break
            pg.wait_for_timeout(100)
        print(json.dumps({"directed": {"words": seen_words, "card": pg.evaluate(SAMPLE)["card"][:80], "router": heard[-3:]}}))
        if not seen_words: fails.append("directed turn: its words never showed")
        if not pg.evaluate(SAMPLE)["card"]: fails.append("directed turn: no answer card")
        # cabin (last: the 3D cabin is the heaviest screen)
        pg.click("#modeMission"); pg.wait_for_timeout(3000)
        if pg.query_selector("#mStart"):
            pg.click("#mStart"); pg.wait_for_timeout(6000)
            for _ in range(14):   # a tour still up (cadet): skip it
                if pg.query_selector("text=Skip tour"): pg.click("text=Skip tour"); break
                pg.wait_for_timeout(300)
            check("cabin")
        else:
            fails.append("cabin: no Take command on the picker")
        b.close()
    return fails, report


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--base", default="http://localhost:5311")
    fails, report = run(ap.parse_args().base)
    print("PASS" if not fails else "FAIL")
    for f in fails: print("  ", f)
    sys.exit(1 if fails else 0)
