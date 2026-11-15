"""Global Mute, end to end (integ/v1): the top bar's Mute (Shift+M, the button, voice "mute") reaches every sound path
the merged branches added: the voice floor's <audio> (OS voices #6 and the voice pack #7 play through it), crew clips
and chimes (Web Audio master level), media-v1's own <video> player and its YouTube embed (IFrame API mute / unMute).

The page is inaudible the whole time, but this test can't use silent.py's init script: that one pins `muted` to true and
swallows the setter, so nothing could be checked. Here `muted` still reads true (so nothing ever plays out loud) while
its setter records what the app asked for (el.__asked), Web Audio stays suspended, speechSynthesis is off, and the
iframe's postMessage is captured (window.__yt). Launch flags as in silent.py.

    (backend :8196 with VIDEO_PREFETCH=0, vite :5196)
    uv run --no-project --with playwright==1.58.0 python frontend/tests/e2e/mute_e2e.py --base http://127.0.0.1:5196
"""
from __future__ import annotations

import argparse
import glob
import os
import sys

from playwright.sync_api import sync_playwright

SPY = """(()=>{const P=HTMLMediaElement.prototype;
Object.defineProperty(P,'muted',{get(){return true},set(v){this.__asked=!!v;(window.__asked=window.__asked||[]).push(!!v)}});
Object.defineProperty(P,'volume',{get(){return 0},set(){}});
const AC=window.AudioContext||window.webkitAudioContext;if(AC){AC.prototype.resume=function(){return Promise.resolve()};
const C=function(...a){const c=new AC(...a);try{c.suspend()}catch(e){};return c};C.prototype=AC.prototype;window.AudioContext=window.webkitAudioContext=C}
if(window.speechSynthesis){window.speechSynthesis.speak=()=>{};}
window.__yt=[];const d=Object.getOwnPropertyDescriptor(HTMLIFrameElement.prototype,'contentWindow');
Object.defineProperty(HTMLIFrameElement.prototype,'contentWindow',{get(){const w=d.get.call(this);
 return {postMessage:(m,o)=>{try{const j=JSON.parse(m);if(j&&j.func)window.__yt.push(j.func)}catch(e){}}, __real:w}}});
try{localStorage.setItem('outpost-callsign','Nova')}catch(e){}})()"""
LAUNCH_ARGS = ["--mute-audio", "--disable-audio-output"]

results = []


def ok(cond, label):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + label, flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:5196")
    a = ap.parse_args()
    exe = (sorted(glob.glob(os.path.expanduser("~/Library/Caches/ms-playwright/chromium_headless_shell-*/*/chrome-headless-shell"))) or [None])[-1]
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=exe, headless=True, args=LAUNCH_ARGS)
        ctx = b.new_context(viewport={"width": 1280, "height": 800})
        ctx.add_init_script(SPY)
        pg = ctx.new_page()
        js = pg.evaluate
        pg.goto(a.base + "/")
        pg.wait_for_function("() => !!document.getElementById('muteBtn') && !!(window.__outpost && window.__outpost.prefs)", timeout=30000)
        ok(js("() => document.getElementById('muteBtn').getAttribute('aria-pressed')") == "false", "starts unmuted")
        # Shift+M (keys) -> Mute
        pg.keyboard.press("Shift+M")
        pg.wait_for_timeout(300)
        ok(js("() => window.__outpost.prefs.muted === true && document.getElementById('muteBtn').getAttribute('aria-pressed') === 'true'"),
           "Shift+M: muted (prefs + the top bar button)")
        ok(js("() => window.__outpost.levels.master === 0 && window.__outpost.levels.muted === true"),
           "Web Audio master level 0 (crew clips, chimes, the radio beep, gesture ticks)")
        # the voice floor: the next line's <audio> asks to be muted (OS voice / voice pack lines play through it)
        js("() => { window.__asked = []; }")
        js("async () => { const f = await import('/src/floor.js'); try { f.speak ? f.speak('Testing one two.') : null; } catch (e) {} }")
        pg.wait_for_timeout(1500)
        ok(js("() => [...document.querySelectorAll('audio')].every(e => e.__asked !== false)") and True in js("() => window.__asked || []"),
           "the voice floor's <audio> plays muted (OS voice and voice-pack lines)")
        # media-v1's own <video> player: opens muted, follows Mute while open
        js("() => { window.__asked = []; }")
        js("async () => { const m = await import('/src/media/video.js'); window.__vp = m.openVideo('phases_loop', { context: 'mute-test' }); }")
        pg.wait_for_timeout(2500)
        vid = js("() => { const v = document.querySelector('.vid-video'); return v ? v.__asked : null; }")
        if vid is None:
            print("   (no <video> mounted: the file is not cached and the stream is offline; skipping the file-player checks)")
        else:
            ok(vid is True, "the NASA <video> opens muted")
            pg.keyboard.press("Shift+M")   # unmute while it plays
            pg.wait_for_timeout(300)
            ok(js("() => document.querySelector('.vid-video').__asked") is False, "unmute while the video plays: the <video> follows")
            pg.keyboard.press("Shift+M")
            pg.wait_for_timeout(300)
            ok(js("() => document.querySelector('.vid-video').__asked") is True, "mute again: the <video> follows")
        js("async () => { const m = await import('/src/media/video.js'); m.command && m.command('stop'); }")
        pg.wait_for_timeout(800)
        # the YouTube embed: the IFrame API's mute / unMute
        if not js("() => window.__outpost.prefs.muted"):
            pg.keyboard.press("Shift+M"); pg.wait_for_timeout(300)
        js("() => { window.__yt = []; }")
        js("async () => { const m = await import('/src/media/video.js'); window.__vp2 = m.openVideo('meet_crew', { context: 'mute-test' }); }")
        pg.wait_for_timeout(2500)
        fr = js("() => { const f = document.querySelector('iframe.vid-yt'); return f ? f.getAttribute('src') : null; }")
        if fr is None:
            print("   (no YouTube embed: offline; skipping the embed checks)")
        else:
            ok("mute=1" in fr, "the YouTube embed starts muted (mute=1)")
            pg.keyboard.press("Shift+M"); pg.wait_for_timeout(300)
            ok("unMute" in js("() => window.__yt"), "unmute while the embed plays: IFrame API unMute")
            pg.keyboard.press("Shift+M"); pg.wait_for_timeout(300)
            ok("mute" in js("() => window.__yt"), "mute again: IFrame API mute")
        js("async () => { const m = await import('/src/media/video.js'); m.command && m.command('stop'); }")
        pg.wait_for_timeout(500)
        # the voice command: "mute" / "unmute" typed in the voice bar (no session needed)
        if js("() => window.__outpost.prefs.muted"):
            pg.fill("#q", "unmute"); pg.keyboard.press("Enter"); pg.wait_for_timeout(400)
            ok(js("() => window.__outpost.prefs.muted === false"), "typed / said 'unmute': sound on")
        pg.fill("#q", "mute"); pg.keyboard.press("Enter"); pg.wait_for_timeout(400)
        ok(js("() => window.__outpost.prefs.muted === true"), "typed / said 'mute': sound off")
        b.close()
    n = len(results)
    print(f"{sum(results)}/{n} checks")
    sys.exit(0 if all(results) and n else 1)


if __name__ == "__main__":
    main()
