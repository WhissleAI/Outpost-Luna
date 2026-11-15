"""Silent test runs (owner rule): no sound from the browser, ever. Every e2e here imports this.

chrome-headless-shell ignores --mute-audio, so on top of the launch flags every page gets an init script that mutes
media elements, keeps every AudioContext suspended and turns speechSynthesis off, and the app's own volume is 0.
After a run, `pmset -g assertions | grep -i "playing audio"` must show nothing from it.
"""
LAUNCH_ARGS = ["--mute-audio", "--disable-audio-output"]
MUTE_JS = """(()=>{const P=HTMLMediaElement.prototype;Object.defineProperty(P,'muted',{get(){return true},set(){}});Object.defineProperty(P,'volume',{get(){return 0},set(){}});const AC=window.AudioContext||window.webkitAudioContext;if(AC){AC.prototype.resume=function(){return Promise.resolve()};const C=function(...a){const c=new AC(...a);try{c.suspend()}catch(e){};return c};C.prototype=AC.prototype;window.AudioContext=window.webkitAudioContext=C}if(window.speechSynthesis){window.speechSynthesis.speak=()=>{}}})();
try { const k = 'outpost-prefs', p = JSON.parse(localStorage.getItem(k) || '{}') || {}; if (p.volume !== 0) { p.volume = 0; p.alarms = 0; localStorage.setItem(k, JSON.stringify(p)); } } catch (e) {}"""


def silence(ctx):
    """Register the mute script on a browser context (call it after any script that clears localStorage)."""
    ctx.add_init_script(MUTE_JS)
