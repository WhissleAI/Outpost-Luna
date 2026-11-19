// Settings → App version (desktop/main/appupdate.js, docs/DESKTOP.md "App updates"): the installed version and
// "Check for updates". The page is locked to its own origin, so the shell does the asking: the page navigates to
// /__outpost/update?do=check (Electron stops that), the main process asks GitHub for the latest release and calls
// window.__lunaUpdate with the result. "Download" navigates to /__outpost/update?do=open&what=download: the shell opens
// the installer it found in the system browser (the page never names a URL). Nothing installs by itself.
// Opt-in "Check for updates automatically" (prefs.update_check, off by default): when the page loads, the shell asks
// window.__lunaUpdate whether it is on; if so it checks at most once a day and stays silent unless there is an update,
// which shows as a small notice with the same Download. In a browser (make dev) the section is not shown.
const O = typeof window !== "undefined" ? (window.__outpost = window.__outpost || { stepRenderers: {} }) : { stepRenderers: {} };

const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

export const SITE = "whissleai.github.io/Outpost-Luna";
export const COPY = {
  line: "Asks GitHub for a newer version. Nothing installs by itself.",
  check: "Check for updates",
  auto: "Check for updates automatically",
  autoHelp: "Once a day, when Outpost Luna starts.",
};
export const isDesktop = (ua = typeof navigator !== "undefined" ? navigator.userAgent : "") => /Electron\//.test(ua);
const bundled = () => (typeof __APP_VERSION__ !== "undefined" ? __APP_VERSION__ : "");

const list = xs => (xs.length < 2 ? xs.join("") : `${xs.slice(0, -1).join(", ")} and ${xs[xs.length - 1]}`);

/** A result from the shell -> what the row shows: {line, notes, action: {what, label} | null, busy}. Pure. */
export function view(s) {
  const st = (s && s.state) || "idle";
  switch (st) {
    case "checking": return { line: "Checking…", notes: "", action: null, busy: true };
    case "up_to_date": return { line: `You're up to date (${s.current})`, notes: "", action: null };
    case "available":
      if (s.download) return { line: `Outpost Luna ${s.latest} is available`, notes: s.notes || "", action: { what: "download", label: "Download" } };
      return { line: `${s.latest} is out${s.others && s.others.length ? ` for ${list(s.others)}` : ""}; ${s.platform && s.platform !== "this computer" ? `the ${s.platform} installer` : "an installer for this computer"} is coming`,
        notes: s.notes || "", action: { what: "release", label: "Open the release page" } };
    case "error":
      if (s.reason === "school") return { line: "Update checks are off on the school network.", notes: "", action: null };   // docs/SCHOOL_IT.md
      return { line: `Couldn't check right now. You can also download from ${SITE}`, notes: "", action: { what: "site", label: "Open the site" } };
    default: return { line: "", notes: "", action: null };
  }
}

/** Is the opt-in on? (prefs.update_check; read straight from storage before prefs.js is up.) */
export function autoOn(o = O, ls = (() => { try { return window.localStorage; } catch (e) { return null; } })()) {
  const P = o && o.prefsApi && o.prefsApi.value;
  if (P) return P.update_check === true;
  try { return JSON.parse((ls && ls.getItem("outpost-prefs")) || "null").update_check === true; } catch (e) { return false; }
}

let last = null, mounted = null;
const go = (w, q) => { w.location.href = `/__outpost/update?${q}`; };
export const check = (w = window) => go(w, "do=check");
export const open = (what, w = window) => go(w, `do=open&what=${encodeURIComponent(what)}`);

const notesHtml = n => (n ? `<p class="au-notes">${n.split("\n").map(esc).join("<br>")}</p>` : "");
const actionHtml = (a, cls) => (a ? `<button type="button" class="${cls}" data-au-open="${esc(a.what)}">${esc(a.label)}</button>` : "");

function paint() {
  if (!mounted || mounted.isConnected === false) return;
  const v = view(last);
  const ver = mounted.querySelector("[data-au-ver]"), st = mounted.querySelector("[data-au-state]"), btn = mounted.querySelector("[data-au-check]");
  if (ver) ver.textContent = (last && last.current) || bundled();
  if (btn) btn.disabled = !!v.busy;
  if (st) {
    st.dataset.state = (last && last.state) || "idle";
    st.innerHTML = v.line ? `<p class="au-line">${esc(v.line)}</p>${notesHtml(v.notes)}${actionHtml(v.action, v.action && v.action.what === "download" ? "btn-primary" : "btn-quiet")}` : "";
  }
}

/** The small non-blocking notice the opt-in check shows when there is an update. */
export function showNotice(s, doc = typeof document !== "undefined" ? document : null) {
  if (!doc || !doc.body) return null;
  const v = view(s);
  if (!v.action) return null;
  let n = doc.getElementById("auNotice");
  if (!n) { n = doc.createElement("div"); n.id = "auNotice"; n.className = "au-notice"; n.setAttribute("role", "status"); doc.body.appendChild(n); }
  n.innerHTML = `<p class="au-line">${esc(v.line)}</p>${actionHtml(v.action, "btn")}<button type="button" class="btn-icon" data-au-close aria-label="Dismiss">&times;</button>`;
  n.onclick = e => {
    const t = e.target.closest ? e.target.closest("button") : null;
    if (!t) return;
    if (t.dataset.auOpen) open(t.dataset.auOpen);
    n.remove();
  };
  return n;
}

/** The shell's only way in: a result (or {state: "idle", current} on load). Answers whether the opt-in is on. */
export function receive(s) {
  if (s && typeof s === "object") {
    last = s;
    paint();
    if (s.auto && s.state === "available") showNotice(s);
  }
  return { auto: autoOn() };
}

const section = {
  id: "appupdate", title: "App version", after: "diagnostics",
  html: () => (!isDesktop() ? "" : `<div class="au-zone">
    <p class="au-ver">Outpost Luna <span data-au-ver>${esc((last && last.current) || bundled())}</span></p>
    <p class="set-help">${esc(COPY.line)}</p>
    <button type="button" class="btn" data-au-check>${esc(COPY.check)}</button>
    <div class="au-state" data-au-state role="status" aria-live="polite"></div>
    <label class="a11y-sw"><input type="checkbox" data-pb="update_check" ${autoOn() ? "checked" : ""}><span><b>${esc(COPY.auto)}</b><small>${esc(COPY.autoHelp)}</small></span></label></div>`),
  bind(el) {
    mounted = el;
    const btn = el.querySelector("[data-au-check]");
    if (!btn) return;
    btn.onclick = () => { last = { ...(last || {}), state: "checking" }; paint(); check(); };
    el.querySelector("[data-au-state]").onclick = e => { const t = e.target.closest("[data-au-open]"); if (t) open(t.dataset.auOpen); };
    paint();
  },
};
if (typeof window !== "undefined") {
  (O.settingsSections = O.settingsSections || []).push(section);
  window.__lunaUpdate = receive;
}
export default section;
