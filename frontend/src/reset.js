// Settings → Reset Outpost Luna (docs/RESET.md): the danger zone at the bottom of Settings.
//
//   Start over        erases progress and settings on this computer: the call sign, every cadet's lessons, patches and
//                     explorer unlocks, missions flown and debriefs, every pref (voice, theme, Mute, expressiveness, the
//                     recorded voice, gesture calibration, coach marks seen, the tour, the first-mission briefing), the
//                     opt-in turn log and the spoken-line cache. The downloaded assets stay (no re-download).
//   Reset everything  the same, plus the NASA video cache, the other caches and the first-run downloads, so the next
//                     launch starts from scratch.
//
// Safety: a confirm view that says exactly what goes, then a 3-second hold ("Hold to start over"; the grown-up gate's
// pattern). Mouse/touch, Enter or Space held, and a controller's A button held all work. Esc or Cancel always backs out.
// Voice alone never resets: "reset" only opens this view (a11y.js).
//
// Mechanics: POST /api/reset (the backend clears its per-user state and returns a one-time token), clear this page's
// storage, then in the desktop app navigate to /__outpost/reset?… (Electron stops the children, clears its storage and
// folders, relaunches: desktop/main/reset.js). In a browser it reloads.

export const HOLD_MS = 3000;
/** Everything the app keeps in the browser is under these prefixes (localStorage, sessionStorage). */
export const PREFIXES = ["outpost", "atm-", "atm:"];

export const LEVELS = {
  start: {
    title: "Start over", hold: "Hold to start over", done: "Starting over…",
    lead: "This erases on this computer:",
    erases: ["Call signs and every cadet", "Lessons, patches and unlocked places", "Missions flown and debriefs",
      "Settings: voice, theme, sound, gestures, captions", "The saved voice-guide log"],
    keeps: "Downloaded voices, crew audio, videos and models stay.",
  },
  all: {
    title: "Reset everything", hold: "Hold to reset everything", done: "Resetting…",
    lead: "This erases everything Outpost Luna saved on this computer:",
    erases: ["Everything in Start over", "Saved NASA videos and other caches", "Downloaded voices and models (they download again)"],
    keeps: "The next start is like the very first one.",
  },
};

/** The keys a reset removes from a Storage (pure; tests/reset.test.js). */
export function appKeys(storage) {
  const out = [];
  try { for (let i = 0; i < storage.length; i++) { const k = storage.key(i); if (k && PREFIXES.some(p => k.startsWith(p))) out.push(k); } } catch (e) { /* blocked */ }
  return out;
}

/** Clear this page's own storage: the app's localStorage / sessionStorage keys, and its IndexedDB databases. */
export async function clearAppStorage(w = window) {
  const removed = [];
  for (const st of [w.localStorage, w.sessionStorage]) {
    if (!st) continue;
    for (const k of appKeys(st)) { try { st.removeItem(k); removed.push(k); } catch (e) { /* */ } }
  }
  try {
    const dbs = w.indexedDB && w.indexedDB.databases ? await w.indexedDB.databases() : [];
    for (const d of dbs) if (d && d.name) { try { w.indexedDB.deleteDatabase(d.name); removed.push("idb:" + d.name); } catch (e) { /* */ } }
  } catch (e) { /* not supported */ }
  return removed;
}

export const isDesktop = (ua = typeof navigator !== "undefined" ? navigator.userAgent : "") => /Electron\//.test(ua);

/** Do it: the backend, this page's storage, then the desktop shell (or a reload). */
export async function runReset(level, { fetchFn = fetch, w = window } = {}) {
  let token = "";
  try {
    const r = await fetchFn(`/api/reset?level=${encodeURIComponent(level)}`, { method: "POST", headers: { "X-Outpost-Reset": "1" } });
    if (r.ok) token = (await r.json()).token || "";
  } catch (e) { /* the backend is down: the page's part still runs */ }
  await clearAppStorage(w);
  if (isDesktop(w.navigator && w.navigator.userAgent) && token) {
    w.location.href = `/__outpost/reset?level=${encodeURIComponent(level)}&token=${encodeURIComponent(token)}`;
    // the shell relaunches the app; if it doesn't (an older shell), come back fresh anyway
    try { setTimeout(() => w.location.replace("/"), 8000); } catch (e) { /* */ }
  } else {
    w.location.replace("/");
  }
  return { token };
}

const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

/** The danger zone's section in Settings: the two buttons. */
export function zoneHtml() {
  return `<div class="rs-zone" role="group" aria-label="Reset Outpost Luna">
      <p class="set-help">Erase what Outpost Luna saved on this computer. A grown-up should do this.</p>
      <button type="button" class="btn rs-btn" data-reset-open="start">Start over</button>
      <small class="rs-note">Progress and settings. Downloads stay.</small>
      <button type="button" class="btn rs-btn rs-all" data-reset-open="all">Reset everything</button>
      <small class="rs-note">Also downloads and saved videos.</small></div>`;
}

/** The confirm view for a level: exactly what goes, a 3-second hold, Cancel. */
export function confirmHtml(level) {
  const L = LEVELS[level];
  return `<div class="rs-confirm" role="alertdialog" aria-labelledby="rsTitle" aria-describedby="rsWhat" data-level="${level}">
      <h4 id="rsTitle">${esc(L.title)}?</h4>
      <div id="rsWhat"><p>${esc(L.lead)}</p><ul>${L.erases.map(t => `<li>${esc(t)}</li>`).join("")}</ul><p class="rs-keep">${esc(L.keeps)}</p></div>
      <div class="rs-row"><button type="button" class="btn rs-cancel" data-reset-cancel>Cancel</button>
        <button type="button" class="btn rs-hold" data-reset-hold><i class="rs-fill" aria-hidden="true"></i><span>${esc(L.hold)}</span></button></div>
      <p class="rs-status" aria-live="assertive"></p></div>`;
}

/**
 * Wire a confirm view: the hold button resets after HOLD_MS of continuous press (pointer, Enter / Space, or a
 * controller's A while it has focus); letting go early resets the fill. onCancel(): back to the zone. doReset(level).
 */
export function bindConfirm(root, { onCancel, doReset = runReset, holdMs = HOLD_MS }) {
  const box = root.querySelector(".rs-confirm"); if (!box) return () => {};
  const level = box.dataset.level, hold = box.querySelector("[data-reset-hold]"), fill = box.querySelector(".rs-fill"), status = box.querySelector(".rs-status");
  let t0 = 0, raf = 0, timer = 0, fired = false, padRaf = 0;
  const paint = p => { fill.style.width = `${Math.round(p * 100)}%`; };
  // the fill is painted on animation frames; the 3 s itself is a timer (a busy 3D cabin can starve frames, and a
  // hold that really lasted 3 s must count even if no frame landed near the end)
  const tick = () => { if (!t0) return; paint(Math.min(1, (performance.now() - t0) / holdMs)); raf = requestAnimationFrame(tick); };
  const start = () => {
    if (fired || t0) return;
    t0 = performance.now(); hold.classList.add("is-holding"); raf = requestAnimationFrame(tick);
    timer = setTimeout(() => { if (t0) { paint(1); stop(true); fire(); } }, holdMs);
  };
  const stop = (keep = false) => {
    if (t0 && !fired && !keep && performance.now() - t0 >= holdMs) { paint(1); clearTimeout(timer); cancelAnimationFrame(raf); t0 = 0; fire(); return; }
    clearTimeout(timer); cancelAnimationFrame(raf); t0 = 0; hold.classList.remove("is-holding"); if (!keep) paint(0);
  };
  const fire = () => { if (fired) return; fired = true; status.textContent = LEVELS[level].done; hold.disabled = true; Promise.resolve(doReset(level)).catch(() => { status.textContent = "That didn't work. Try again."; fired = false; hold.disabled = false; paint(0); }); };
  hold.addEventListener("pointerdown", e => { e.preventDefault(); start(); });
  ["pointerup", "pointerleave", "pointercancel"].forEach(ev => hold.addEventListener(ev, () => { if (!fired) stop(); }));
  hold.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); e.stopPropagation(); if (!e.repeat) start(); } });
  hold.addEventListener("keyup", e => { if ((e.key === "Enter" || e.key === " ") && !fired) stop(); });
  hold.addEventListener("click", e => e.preventDefault());   // a click (or a single select from a controller) is not a hold
  // a controller: A held while the hold button has focus
  const padA = () => { try { return [...(navigator.getGamepads ? navigator.getGamepads() : [])].some(g => g && g.buttons && g.buttons[0] && g.buttons[0].pressed); } catch (e) { return false; } };
  const pollPad = () => { if (!hold.isConnected) return; if (document.activeElement === hold) { if (padA()) start(); else if (t0 && !fired) stop(); } padRaf = requestAnimationFrame(pollPad); };
  padRaf = requestAnimationFrame(pollPad);
  box.querySelector("[data-reset-cancel]").onclick = () => { stop(); onCancel && onCancel(); };
  box.addEventListener("keydown", e => { if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); stop(); onCancel && onCancel(); } });
  box.querySelector("[data-reset-cancel]").focus({ preventScroll: true });   // the safe choice has focus first
  return () => { stop(); cancelAnimationFrame(padRaf); };
}
