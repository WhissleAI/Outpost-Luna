// Settings → For grown-ups → Reset Outpost Luna (docs/RESET.md): the danger zone, behind the grown-up hold.
//
//   Start over        erases settings and the rest on this computer: every pref (voice, theme, Mute, expressiveness, the
//                     recorded voice, gesture calibration, coach marks seen, the tour, the first-mission briefing),
//                     mission debriefs, the opt-in turn log and the spoken-line cache. The downloaded assets stay.
//   Reset everything  the same, plus the NASA video cache, the other caches and the first-run downloads, so the next
//                     launch starts from scratch.
//
// [0.4.1] Progress stays on both levels: Flight School / Field School progress (`atm-academy`), every cadet's call sign
// and missions flown (they open bonus lessons). Only "Erase progress too", its own 3-second hold, erases those as well.
//
// Safety: a confirm view that says exactly what goes, then a 3-second hold ("Hold to start over"; the grown-up gate's
// pattern). Mouse/touch, Enter or Space held, and a controller's A button held all work. Esc or Cancel always backs out.
// Voice alone never resets: "reset" only opens this view (a11y.js).
//
// Mechanics: POST /api/reset (the backend clears its per-user state and returns a one-time token), clear this page's
// storage (keeping progress unless erased), then in the desktop app navigate to /__outpost/reset?… (Electron stops the
// children, clears its storage and folders, relaunches: desktop/main/reset.js; Local Storage only with erase=1). In a
// browser it reloads.

export const HOLD_MS = 3000;
/** Everything the app keeps in the browser is under these prefixes (localStorage, sessionStorage). */
export const PREFIXES = ["outpost", "atm-", "atm:"];
/** Progress a reset keeps (unless "Erase progress too"): Flight School / Field School progress, the call sign, the
 *  missions flown per call sign (bonus lessons open after them). */
export const PROGRESS_KEYS = ["atm-academy", "outpost-callsign", "outpost-brain"];   // [brain] practice counts (brain_store.js)
export const PROGRESS_PREFIXES = ["outpost-missions-flown:"];
const PROFILES = "outpost-profiles";   // other cadets' saved keys (prefs.js): kept, trimmed to their progress
export const isProgressKey = k => PROGRESS_KEYS.includes(k) || PROGRESS_PREFIXES.some(p => k.startsWith(p));
/** The cadet list with each saved cadet trimmed to its progress keys (null when there is nothing to keep). Pure. */
export function trimProfiles(raw) {
  let s; try { s = JSON.parse(raw || "null"); } catch (e) { return null; }
  if (!s || !Array.isArray(s.list)) return null;
  const list = s.list.map(p => ({ ...p, data: p && p.data ? Object.fromEntries(Object.entries(p.data).filter(([k]) => isProgressKey(k))) : null }));
  return JSON.stringify({ ...s, list });
}

export const LEVELS = {
  start: {
    title: "Start over", hold: "Hold to start over", done: "Starting over…",
    lead: "This erases on this computer:",
    erases: ["Settings: voice, theme, sound, gestures, captions", "Mission debriefs and the tour", "The saved voice-guide log"],
    keeps: "Lessons, patches and call signs stay. So do downloaded voices, crew audio, videos and models.",
  },
  all: {
    title: "Reset everything", hold: "Hold to reset everything", done: "Resetting…",
    lead: "This erases everything Outpost Luna saved on this computer:",
    erases: ["Everything in Start over", "Saved NASA videos and other caches", "Downloaded voices and models (they download again)"],
    keeps: "Lessons, patches and call signs stay. Everything else starts like the very first time.",
  },
};
/** The second hold in each confirm view: progress goes too. */
export const ERASE = {
  hold: "Hold to erase progress too",
  note: "Also erases every cadet's call sign, patches and lesson progress. This can't be undone.",
};

/** The keys a reset removes from a Storage (pure; tests/reset.test.js). */
export function appKeys(storage) {
  const out = [];
  try { for (let i = 0; i < storage.length; i++) { const k = storage.key(i); if (k && PREFIXES.some(p => k.startsWith(p))) out.push(k); } } catch (e) { /* blocked */ }
  return out;
}

/** Clear this page's own storage: the app's localStorage / sessionStorage keys, and its IndexedDB databases. Progress
 *  (PROGRESS_KEYS, missions flown, the cadet list trimmed to those) stays in localStorage unless `erase`. */
export async function clearAppStorage(w = window, { erase = false } = {}) {
  const removed = [];
  for (const st of [w.localStorage, w.sessionStorage]) {
    if (!st) continue;
    const keep = !erase && st === w.localStorage;
    for (const k of appKeys(st)) {
      if (keep && isProgressKey(k)) continue;
      if (keep && k === PROFILES) { try { const t = trimProfiles(st.getItem(k)); if (t) { st.setItem(k, t); continue; } } catch (e) { /* */ } }
      try { st.removeItem(k); removed.push(k); } catch (e) { /* */ }
    }
  }
  try {
    const dbs = w.indexedDB && w.indexedDB.databases ? await w.indexedDB.databases() : [];
    for (const d of dbs) if (d && d.name) { try { w.indexedDB.deleteDatabase(d.name); removed.push("idb:" + d.name); } catch (e) { /* */ } }
  } catch (e) { /* not supported */ }
  return removed;
}

export const isDesktop = (ua = typeof navigator !== "undefined" ? navigator.userAgent : "") => /Electron\//.test(ua);

/** Do it: the backend, this page's storage, then the desktop shell (or a reload). `erase`: progress goes too. */
export async function runReset(level, { fetchFn = fetch, w = window, erase = false } = {}) {
  let token = "";
  try {
    const r = await fetchFn(`/api/reset?level=${encodeURIComponent(level)}`, { method: "POST", headers: { "X-Outpost-Reset": "1" } });
    if (r.ok) token = (await r.json()).token || "";
  } catch (e) { /* the backend is down: the page's part still runs */ }
  await clearAppStorage(w, { erase });
  if (isDesktop(w.navigator && w.navigator.userAgent) && token) {
    w.location.href = `/__outpost/reset?level=${encodeURIComponent(level)}&token=${encodeURIComponent(token)}${erase ? "&erase=1" : ""}`;
    // the shell relaunches the app; if it doesn't (an older shell), come back fresh anyway
    try { setTimeout(() => w.location.replace("/"), 8000); } catch (e) { /* */ }
  } else {
    w.location.replace("/");
  }
  return { token };
}

const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

/** The danger zone in Settings → For grown-ups: the two buttons. */
export function zoneHtml() {
  return `<div class="rs-zone" role="group" aria-label="Reset Outpost Luna">
      <p class="set-help">Erase what Outpost Luna saved on this computer. Lessons, patches and call signs stay unless you choose to erase them too.</p>
      <button type="button" class="btn rs-btn" data-reset-open="start">Start over</button>
      <small class="rs-note">Settings and saved logs. Progress and downloads stay.</small>
      <button type="button" class="btn rs-btn rs-all" data-reset-open="all">Reset everything</button>
      <small class="rs-note">Also downloads and saved videos. Progress stays.</small></div>`;
}

/** The confirm view for a level: exactly what goes, a 3-second hold, Cancel. */
export function confirmHtml(level) {
  const L = LEVELS[level];
  return `<div class="rs-confirm" role="alertdialog" aria-labelledby="rsTitle" aria-describedby="rsWhat" data-level="${level}">
      <h4 id="rsTitle">${esc(L.title)}?</h4>
      <div id="rsWhat"><p>${esc(L.lead)}</p><ul>${L.erases.map(t => `<li>${esc(t)}</li>`).join("")}</ul><p class="rs-keep">${esc(L.keeps)}</p></div>
      <div class="rs-row"><button type="button" class="btn rs-cancel" data-reset-cancel>Cancel</button>
        ${holdButtonHtml(L.hold, "data-reset-hold")}</div>
      <div class="rs-erase">${holdButtonHtml(ERASE.hold, "data-reset-erase")}<small class="rs-note">${esc(ERASE.note)}</small></div>
      <p class="rs-status" aria-live="assertive"></p></div>`;
}

/** A hold button (the grown-up gate's pattern): the danger fill grows while it is held; a click does nothing. */
export function holdButtonHtml(label, attr = "data-hold") {
  return `<button type="button" class="btn rs-hold" ${attr}><i class="rs-fill" aria-hidden="true"></i><span>${esc(label)}</span></button>`;
}

/**
 * Wire a hold button: onFire() runs after holdMs of continuous press (pointer, Enter / Space, or a controller's A while
 * it has focus); letting go early resets the fill; a plain click never counts. Used by Reset and by Settings → Videos
 * → "Hold to clear saved videos". -> { stop, rearm, destroy }.
 */
export function bindHold(hold, { onFire, holdMs = HOLD_MS } = {}) {
  const fill = hold.querySelector(".rs-fill");
  const now = () => (typeof performance !== "undefined" ? performance.now() : Date.now());
  const raf = f => (typeof requestAnimationFrame === "function" ? requestAnimationFrame(f) : 0);
  const caf = id => (typeof cancelAnimationFrame === "function" ? cancelAnimationFrame(id) : undefined);
  let t0 = 0, rafId = 0, timer = 0, fired = false, padRaf = 0, by = "";   // by: what started the hold (pointer / key / pad)
  const paint = p => { if (fill) fill.style.width = `${Math.round(p * 100)}%`; };
  // the fill is painted on animation frames; the 3 s itself is a timer (a busy 3D cabin can starve frames, and a
  // hold that really lasted 3 s must count even if no frame landed near the end)
  const tick = () => { if (!t0) return; paint(Math.min(1, (now() - t0) / holdMs)); rafId = raf(tick); };
  const start = (src = "pointer") => {
    if (fired || t0 || hold.disabled) return;
    t0 = now(); by = src; hold.classList.add("is-holding"); rafId = raf(tick);
    timer = setTimeout(() => { if (t0) { paint(1); stop(true); fire(); } }, holdMs);
  };
  const stop = (keep = false) => {
    if (t0 && !fired && !keep && now() - t0 >= holdMs) { paint(1); clearTimeout(timer); caf(rafId); t0 = 0; fire(); return; }
    clearTimeout(timer); caf(rafId); t0 = 0; hold.classList.remove("is-holding"); if (!keep) paint(0);
  };
  const rearm = () => { fired = false; hold.disabled = false; hold.classList.remove("is-holding"); paint(0); };
  const fire = () => {
    if (fired) return;
    fired = true; hold.disabled = true;
    Promise.resolve().then(() => onFire && onFire()).catch(rearm);
  };
  hold.addEventListener("pointerdown", e => { e.preventDefault(); start(); });
  ["pointerup", "pointerleave", "pointercancel"].forEach(ev => hold.addEventListener(ev, () => { if (!fired) stop(); }));
  hold.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); e.stopPropagation(); if (!e.repeat) start("key"); } });
  hold.addEventListener("keyup", e => { if ((e.key === "Enter" || e.key === " ") && !fired) stop(); });
  hold.addEventListener("click", e => e.preventDefault());   // a click (or a single select from a controller) is not a hold
  // a controller: A held while the hold button has focus
  const padA = () => { try { return [...(navigator.getGamepads ? navigator.getGamepads() : [])].some(g => g && g.buttons && g.buttons[0] && g.buttons[0].pressed); } catch (e) { return false; } };
  // [0.4.1] the poll lets go only of a hold the controller started: it used to stop a held Enter / Space (or the mouse)
  // on the very next frame, so a keyboard hold never got past 0%
  const pollPad = () => { if (!hold.isConnected) return; if (document.activeElement === hold) { if (padA()) start("pad"); else if (t0 && !fired && by === "pad") stop(); } padRaf = raf(pollPad); };
  padRaf = raf(pollPad);
  return { stop, rearm, destroy: () => { stop(); caf(padRaf); } };
}

/**
 * Wire a confirm view: the hold button resets after HOLD_MS of continuous press (bindHold). onCancel(): back to the
 * zone. doReset(level).
 */
export function bindConfirm(root, { onCancel, doReset = runReset, holdMs = HOLD_MS }) {
  const box = root.querySelector(".rs-confirm"); if (!box) return () => {};
  const level = box.dataset.level, status = box.querySelector(".rs-status");
  const holds = [];
  // two holds: the level (progress stays) and "Erase progress too"; once one fires the other is off
  for (const [sel, erase] of [["[data-reset-hold]", false], ["[data-reset-erase]", true]]) {
    const btn = box.querySelector(sel); if (!btn) continue;
    const h = bindHold(btn, { holdMs, onFire: () => {
      holds.forEach(o => { if (o.btn !== btn) { o.h.stop(); o.btn.disabled = true; } });
      status.textContent = LEVELS[level].done;
      return Promise.resolve(doReset(level, { erase })).catch((e) => {
        status.textContent = "That didn't work. Try again."; holds.forEach(o => { if (o.btn !== btn) o.btn.disabled = false; }); throw e;
      });
    } });
    holds.push({ btn, h });
  }
  const stopAll = () => holds.forEach(o => o.h.stop());
  box.querySelector("[data-reset-cancel]").onclick = () => { stopAll(); onCancel && onCancel(); };
  box.addEventListener("keydown", e => { if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); stopAll(); onCancel && onCancel(); } });
  box.querySelector("[data-reset-cancel]").focus({ preventScroll: true });   // the safe choice has focus first
  return () => holds.forEach(o => o.h.destroy());
}
