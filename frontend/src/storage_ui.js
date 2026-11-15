// Settings → Storage & updates (docs/DESKTOP.md "Asset updates"): the desktop app's downloaded models and media, their
// versions and size, and their updates (downloaded in the background, swapped in on the next launch). The backend
// relays the Electron main process's state: GET /api/assets, POST /api/assets/check (backend/app/assets_api.py). In a
// dev checkout there is no desktop app ({managed: false}): the section is not shown.
const O = typeof window !== "undefined" ? (window.__outpost = window.__outpost || { stepRenderers: {} }) : { stepRenderers: {} };

const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
export const size = b => {
  const mb = (b || 0) / 1e6;
  return mb >= 1000 ? `${(mb / 1000).toFixed(1)} GB` : mb >= 10 ? `${Math.round(mb)} MB` : `${mb.toFixed(1)} MB`;
};

/** One short line for the update state. */
export function updateLine(s) {
  const u = (s && s.update) || {};
  const ready = (u.ready || []).length;
  if (ready) return `Update ready: restart Outpost Luna to use it.`;
  switch (u.state) {
    case "checking": return "Checking for updates…";
    case "available":
    case "downloading": return `Downloading an update${u.downloading ? ` (${u.downloading})` : ""}…`;
    case "paused": return "Update paused while you play.";
    case "offline": return "Offline: can't check for updates.";
    case "error": return "Couldn't check for updates. Try again later.";
    case "up_to_date": return "Up to date.";
    default: return u.checked_at ? "Up to date." : "Not checked yet.";
  }
}

/** The rows: [{name, version, size, note}] for the installed assets. */
export function rows(s) {
  return ((s && s.installed) || []).map(a => ({
    name: a.title || a.id,
    version: a.installed ? `v${a.version || "1"}` : "not downloaded",
    size: a.installed ? size(a.bytes) : "",
    note: a.update_ready ? "update ready" : "",
  }));
}

let last = null;   // the last state fetched (html() is sync: it paints what we know, bind() refreshes)
const load = () => fetch("/api/assets").then(r => r.json()).then(s => (last = s)).catch(() => null);

const section = {
  id: "storage", title: "Storage & updates", after: "videos",
  html: () => (last && last.managed === false ? "" : `<p class="set-help" data-as-line>${esc(last ? updateLine(last) : "Checking…")}</p>
    <div class="tbl"><table><thead><tr><th>Download</th><th>Version</th><th>Size</th></tr></thead>
      <tbody data-as-rows><tr><td colspan="3">…</td></tr></tbody></table></div>
    <p class="set-help" data-as-total></p>
    <button type="button" class="btn" data-as-check>Check for updates</button>
    <p class="set-help">Models, voices and media download once and stay on this computer. Updates download in the background and are used the next time Outpost Luna starts.</p>`),
  bind(el) {
    const line = el.querySelector("[data-as-line]"), body = el.querySelector("[data-as-rows]"),
      total = el.querySelector("[data-as-total]"), btn = el.querySelector("[data-as-check]");
    if (!line) return;
    const paint = s => {
      if (!s) { line.textContent = "Can't read the downloads right now."; return; }
      line.textContent = updateLine(s);
      body.innerHTML = rows(s).map(r => `<tr><td>${esc(r.name)}</td><td>${esc(r.version)}${r.note ? ` · ${esc(r.note)}` : ""}</td><td>${esc(r.size)}</td></tr>`).join("")
        || `<tr><td colspan="3">Nothing downloaded yet.</td></tr>`;
      total.textContent = `Total on this computer: ${size(s.total_bytes)}${s.app_version ? ` · app ${s.app_version}` : ""}`;
    };
    load().then(paint);
    btn.onclick = async () => {
      btn.disabled = true; line.textContent = "Checking for updates…";
      try { await fetch("/api/assets/check", { method: "POST" }); } catch (e) { /* shown below */ }
      let n = 0;
      const poll = setInterval(async () => {   // the desktop app checks within a few seconds
        const s = await load(); if (s) paint(s);
        const st = s && s.update && s.update.state;
        if (++n > 15 || (st && st !== "checking" && n > 2)) { clearInterval(poll); btn.disabled = false; }
      }, 2000);
    };
  },
};
if (typeof window !== "undefined") {
  (O.settingsSections = O.settingsSections || []).push(section);
  if (typeof fetch === "function" && typeof document !== "undefined") load();
}
export default section;
