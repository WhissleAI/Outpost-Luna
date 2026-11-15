"""Silent browser runs for every Playwright tool (owner rule: testing makes no sound and never steals focus).

`import silent` (before launching) patches Playwright for the whole process:
  * every launch gets --mute-audio --disable-audio-output (chrome-headless-shell ignores --mute-audio alone);
  * every page / context gets SILENT_INIT before the page's own scripts: media elements are always muted at volume 0,
    Web Audio contexts stay suspended, speechSynthesis.speak does nothing;
  * the app's own global Mute pref (prefs.muted) is set and kept set, even when a tool clears or rewrites
    localStorage['outpost-prefs'] in its own seed.
Headless only; nothing is brought to the front. Check with `pmset -g assertions | grep -i "playing audio"`.
"""
from __future__ import annotations

from playwright.sync_api import Browser, BrowserContext, BrowserType

SILENT_ARGS = ["--mute-audio", "--disable-audio-output"]
SILENT_INIT = """(()=>{const P=HTMLMediaElement.prototype;Object.defineProperty(P,'muted',{get(){return true},set(){}});
Object.defineProperty(P,'volume',{get(){return 0},set(){}});
const AC=window.AudioContext||window.webkitAudioContext;if(AC){AC.prototype.resume=function(){return Promise.resolve()};
const C=function(...a){const c=new AC(...a);try{c.suspend()}catch(e){};return c};C.prototype=AC.prototype;window.AudioContext=window.webkitAudioContext=C}
if(window.speechSynthesis){window.speechSynthesis.speak=()=>{}}
try{const S=Storage.prototype,set=S.setItem,clear=S.clear,K='outpost-prefs';
const muted=v=>{let o={};try{o=JSON.parse(v||'{}')||{}}catch(e){};o.muted=true;return JSON.stringify(o)};
S.setItem=function(k,v){return set.call(this,k,k===K?muted(v):v)};
S.clear=function(){const r=clear.call(this);set.call(this,K,muted('{}'));return r};
set.call(localStorage,K,muted(localStorage.getItem(K)))}catch(e){}})()"""

_launch, _new_page, _new_context = BrowserType.launch, Browser.new_page, Browser.new_context


def _silent_launch(self, *a, **k):
    args = list(k.get("args") or [])
    k["args"] = args + [x for x in SILENT_ARGS if x not in args]
    k.setdefault("headless", True)
    return _launch(self, *a, **k)


def _silent_page(self, *a, **k):
    page = _new_page(self, *a, **k)
    page.add_init_script(SILENT_INIT)
    return page


def _silent_context(self, *a, **k):
    ctx = _new_context(self, *a, **k)
    ctx.add_init_script(SILENT_INIT)
    return ctx


BrowserType.launch = _silent_launch
Browser.new_page = _silent_page
Browser.new_context = _silent_context
