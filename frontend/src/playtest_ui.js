// Settings → For grown-ups → "Voice log and playtest" (docs/DIRECTOR_LOOP.md §1 and §1b).
//   * Says plainly that the voice guide's text log is on (prefs.improve, on by default since 0.4.3) and what it keeps.
//   * Playtest session: a consent screen (a grown-up confirms permission), then the backend also keeps each kid turn's
//     audio as a WAV next to the turn, on this computer only (backend app/playtest.py). A small "Playtest" tag shows in
//     the top bar while it runs. "Export playtest" writes one zip (turn log + audio + app version + manifest) where the
//     grown-up chooses: the desktop shell asks with a save dialog (/__outpost/playtest-export, desktop/main/playtest.js),
//     the browser build downloads it. It turns off when stopped, when the page closes, and when the app quits.
const O = typeof window !== "undefined" ? (window.__outpost = window.__outpost || { stepRenderers: {} }) : { stepRenderers: {} };

const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

export const COPY = {
  title: "Voice log and playtest",
  logOn: "The voice log is on.",
  logOff: "The voice log is off.",
  keeps: "It keeps what the voice guide heard as text: no names, no audio.",
  where: "Saved on this computer only. Nothing is sent.",
  switchAt: "Change it in Settings → Listening.",
  saved: n => (n === 1 ? "1 turn saved." : `${n} turns saved.`),
  start: "Start playtest",
  ptLine: "A playtest also keeps each turn's audio, on this computer only.",
  consentTitle: "Before you start",
  consent: ["Each thing your child says is saved as audio.",
    "It stays on this computer. You choose where to export it.",
    "It stops when you press Stop or close the app."],
  agree: "I'm the parent or guardian, or I have their permission.",
  go: "Start playtest",
  cancel: "Cancel",
  on: n => `Playtest on · ${n === 1 ? "1 clip" : `${n} clips`}`,
  clips: n => (n === 1 ? "1 clip saved." : `${n} clips saved.`),
  stop: "Stop playtest",
  export: "Export playtest…",
  tag: "Playtest",
  tagTitle: "Playtest on: each turn's audio is saved on this computer",
  state: { saving: "Saving…", saved: "Saved.", cancelled: "", error: "Couldn't save it. Try again." },
  error: "Couldn't reach the app. Try again.",
};

export const isDesktop = (ua = typeof navigator !== "undefined" ? navigator.userAgent : "") => /Electron\//.test(ua);

/** The part's HTML (pure; tests/playtest_ui.test.js). st = GET /api/playtest, or null; view = "main" | "consent". */
export function viewHtml({ st = null, improve = true, view = "main" } = {}) {
  if (view === "consent") {
    return `<div class="pt-consent" role="group" aria-labelledby="ptConsentH">
      <p class="set-help" id="ptConsentH"><b>${esc(COPY.consentTitle)}</b></p>
      <ul class="pt-list">${COPY.consent.map(t => `<li>${esc(t)}</li>`).join("")}</ul>
      <label class="a11y-sw pt-agree"><input type="checkbox" data-pt-agree><span><b>${esc(COPY.agree)}</b></span></label>
      <span class="pt-row"><button type="button" class="btn btn-primary" data-pt-go disabled>${esc(COPY.go)}</button>
      <button type="button" class="btn" data-pt-cancel>${esc(COPY.cancel)}</button></span></div>`;
  }
  const on = !!(st && st.on), clips = (st && st.clips) || 0;
  const log = `<p class="set-help pt-status"><span class="pt-lamp${improve || on ? "" : " is-off"}" aria-hidden="true"></span>${esc(improve || on ? COPY.logOn : COPY.logOff)}${st ? ` ${esc(COPY.saved(st.turns || 0))}` : ""}</p>
    <p class="set-help">${esc(COPY.keeps)} ${esc(COPY.where)} ${esc(COPY.switchAt)}</p>`;
  const pt = on
    ? `<p class="set-help pt-status" role="status"><span class="pt-lamp is-rec" aria-hidden="true"></span>${esc(COPY.on(clips))}</p>
      <span class="pt-row"><button type="button" class="btn" data-pt-export>${esc(COPY.export)}</button>
      <button type="button" class="btn" data-pt-stop>${esc(COPY.stop)}</button></span>`
    : `<p class="set-help">${esc(COPY.ptLine)}${clips ? ` ${esc(COPY.clips(clips))}` : ""}</p>
      <span class="pt-row"><button type="button" class="btn" data-pt-start>${esc(COPY.start)}</button>
      ${clips ? `<button type="button" class="btn" data-pt-export>${esc(COPY.export)}</button>` : ""}</span>`;
  return `${log}${pt}<p class="set-help" data-pt-state role="status" aria-live="polite"></p>`;
}

// ---- the top bar's "Playtest" tag ----
let tagTimer = 0;
export function setTag(on, doc = typeof document !== "undefined" ? document : null) {
  if (!doc) return;
  let t = doc.getElementById("ptTag");
  if (on && !t) {
    t = doc.createElement("span");
    t.id = "ptTag"; t.className = "pt-tag"; t.setAttribute("role", "status"); t.title = COPY.tagTitle;
    t.innerHTML = `<span class="pt-lamp is-rec" aria-hidden="true"></span>${esc(COPY.tag)}`;
    const nav = doc.querySelector(".topnav");
    if (nav) nav.prepend(t); else doc.body.append(t);
  } else if (!on && t) t.remove();
  if (typeof window !== "undefined") {
    clearTimeout(tagTimer);
    if (on) tagTimer = setTimeout(refresh, 30000);   // the backend turns a forgotten playtest off after 3 hours
  }
}

const get = (fetchFn = fetch) => fetchFn("/api/playtest").then(r => (r.ok ? r.json() : null)).catch(() => null);
const post = (path, body, fetchFn = fetch) => fetchFn(path, { method: "POST",
  headers: { "Content-Type": "application/json", "X-Outpost-Reset": "1" }, body: JSON.stringify(body || {}) });
export async function refresh(fetchFn = typeof fetch === "function" ? fetch : null) {
  if (!fetchFn) return null;
  const st = await get(fetchFn);
  setTag(!!(st && st.on));
  return st;
}

/** Desktop: hand over to the shell (a save dialog). Browser: fetch the zip and let the browser save it. */
export async function exportZip({ w = window, fetchFn = fetch, onState = () => {} } = {}) {
  if (isDesktop(w.navigator && w.navigator.userAgent)) {
    w.__lunaPlaytest = d => onState(d && d.state);
    w.location.href = "/__outpost/playtest-export";
    return "desktop";
  }
  onState("saving");
  try {
    const r = await post("/api/playtest/export", {}, fetchFn);
    if (!r.ok) throw new Error(String(r.status));
    const url = URL.createObjectURL(await r.blob());
    const a = w.document.createElement("a");
    a.href = url; a.download = `outpost-luna-playtest-${new Date().toISOString().slice(0, 10)}.zip`;
    w.document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
    onState("saved");
    return "browser";
  } catch (e) { onState("error"); return "error"; }
}

let view = "main";
const section = {
  id: "playtest", title: COPY.title, after: "learning", grownup: true,   // in Settings → For grown-ups
  html: () => `<div class="pt-zone" data-pt-zone>${viewHtml({ st: null, improve: !!(O.prefs && O.prefs.improve !== false), view })}</div>`,
  bind(el, { fetchFn = typeof fetch === "function" ? fetch : null } = {}) {
    const zone = el.querySelector("[data-pt-zone]");
    if (!zone || !fetchFn) return;
    let st = null;
    const improve = () => !!(O.prefs && O.prefs.improve !== false);
    const draw = (focus) => {
      zone.innerHTML = viewHtml({ st, improve: improve(), view });
      wire();
      const f = focus && zone.querySelector(focus);
      if (f) f.focus({ preventScroll: true });
    };
    const say = t => { const s = zone.querySelector("[data-pt-state]"); if (s) s.textContent = t; };
    const load = async (focus) => { st = await get(fetchFn); setTag(!!(st && st.on)); draw(focus); };
    function wire() {
      const q = s => zone.querySelector(s);
      if (q("[data-pt-start]")) q("[data-pt-start]").onclick = () => { view = "consent"; draw("[data-pt-agree]"); };
      if (q("[data-pt-cancel]")) q("[data-pt-cancel]").onclick = () => { view = "main"; draw("[data-pt-start]"); };
      if (q("[data-pt-agree]")) q("[data-pt-agree]").onchange = e => { q("[data-pt-go]").disabled = !e.target.checked; };
      if (q("[data-pt-go]")) q("[data-pt-go]").onclick = async () => {
        if (!q("[data-pt-agree]").checked) return;
        const r = await post("/api/playtest/start", { consent: true }, fetchFn).catch(() => null);
        view = "main";
        if (!r || !r.ok) { draw(); say(COPY.error); return; }
        await load("[data-pt-stop]");
      };
      if (q("[data-pt-stop]")) q("[data-pt-stop]").onclick = async () => {
        const r = await post("/api/playtest/stop", {}, fetchFn).catch(() => null);
        if (!r || !r.ok) { say(COPY.error); return; }
        await load("[data-pt-start]");
      };
      if (q("[data-pt-export]")) q("[data-pt-export]").onclick = e => {
        const b = e.currentTarget; b.disabled = true;
        exportZip({ fetchFn, onState: s => { say(COPY.state[s] ?? ""); if (s !== "saving") b.disabled = false; } });
      };
    }
    load();
  },
};
if (typeof window !== "undefined") {
  (O.settingsSections = O.settingsSections || []).push(section);
  if (typeof document !== "undefined" && typeof fetch === "function") {
    refresh();
    // the playtest ends with the page (a reload, a profile switch, closing the app): the backend stops keeping audio
    addEventListener("pagehide", () => { try { if (document.getElementById("ptTag") && navigator.sendBeacon) navigator.sendBeacon("/api/playtest/stop", new Blob(["{}"], { type: "application/json" })); } catch (e) { /* closing */ } });
  }
}
export default section;
