// Settings → For grown-ups → School network (docs/SCHOOL_IT.md). One switch: nothing connects to the internet. Missions,
// lessons, the Moon, voice and saved videos keep working; what needs the internet says so where it would be.
// The backend owns the switch (GET / POST /api/network) and every process follows it at once (app/netgate.py, the
// desktop shell's netpolicy.js). When this computer's IT admin turned it on (a machine policy), it is locked on.
// Other modules read the state from window.__outpost.network (videos: "Off on the school network"; updates; downloads).
const O = typeof window !== "undefined" ? (window.__outpost = window.__outpost || { stepRenderers: {} }) : { stepRenderers: {} };

const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

export const COPY = {
  title: "School network",
  line: "For school computers. Nothing connects to the internet.",
  sw: "School network mode",
  swHelp: "Missions, lessons, voice and saved videos still work.",
  locked: "Turned on by this computer's IT admin.",
  offTitle: "Off while it's on",
  off: { videos: "NASA videos not saved here", downloads: "New downloads: voices, videos, maps", updates: "Update checks" },
  allowed: "Your IT admin allows:",
  error: "Couldn't change it. Try again.",
};
/** Short words other screens use where the internet would be needed. */
export const SCHOOL = { label: "Off on the school network", line: "Off on the school network. Saved videos still play." };

/** Is School network mode on (from the last /api/network answer)? */
export const schoolOn = (o = O) => !!(o && o.network && o.network.school_network);

/** The section's inside for a state (pure; tests/network_ui.test.js). */
export function innerHtml(st) {
  const s = st || { school_network: false, locked: false, off: [], allow_hosts: [] };
  const on = !!s.school_network;
  const off = on && (s.off || []).length ? `<p class="set-help nw-off-h"><b>${esc(COPY.offTitle)}</b></p>
    <ul class="gu-list nw-off">${s.off.map(k => `<li>${esc(COPY.off[k] || k)}</li>`).join("")}</ul>` : "";
  const allow = on && (s.allow_hosts || []).length ? `<p class="set-help">${esc(COPY.allowed)} ${s.allow_hosts.map(esc).join(", ")}</p>` : "";
  return `<p class="set-help">${esc(COPY.line)}</p>
    <label class="a11y-sw"><input type="checkbox" data-nw-sw ${on ? "checked" : ""} ${s.locked ? "disabled" : ""}><span><b>${esc(COPY.sw)}</b><small>${esc(s.locked ? COPY.locked : COPY.swHelp)}</small></span></label>
    ${off}${allow}
    <p class="set-help" data-nw-state role="status" aria-live="polite"></p>`;
}
export const bodyHtml = st => `<div class="nw-zone" data-nw>${innerHtml(st)}</div>`;

export async function load(fetchFn = typeof fetch === "function" ? fetch : null, o = O) {
  if (!fetchFn) return null;
  try {
    const r = await fetchFn("/api/network");
    if (!r.ok) return null;
    o.network = await r.json();
    return o.network;
  } catch (e) { return null; }
}

export async function set(on, fetchFn = fetch, o = O) {
  const r = await fetchFn("/api/network", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ school_network: !!on }) });
  if (!r.ok) throw new Error(String(r.status));
  o.network = await r.json();
  try { window.dispatchEvent(new CustomEvent("outpost:network", { detail: o.network })); } catch (e) { /* tests */ }
  return o.network;
}

const section = {
  id: "network", title: COPY.title, after: "diagnostics", grownup: true,   // drawn in Settings → For grown-ups
  html: () => bodyHtml(O.network),
  bind(el) {
    const zone = el.querySelector("[data-nw]");
    if (!zone) return;
    const draw = (st, focus = false) => {
      zone.innerHTML = innerHtml(st);
      const sw = zone.querySelector("[data-nw-sw]");
      if (!sw) return;
      if (focus) sw.focus({ preventScroll: true });
      sw.onchange = async () => {
        const want = sw.checked;
        sw.disabled = true;
        try { draw(await set(want), true); }   // redraw: the list of what's off follows the switch
        catch (e) { sw.checked = !want; sw.disabled = false; const m = zone.querySelector("[data-nw-state]"); if (m) m.textContent = COPY.error; }
      };
    };
    draw(O.network);
    load().then(st => { if (st && zone.isConnected && document.activeElement !== zone.querySelector("[data-nw-sw]")) draw(st); });
  },
};
if (typeof window !== "undefined") {
  (O.settingsSections = O.settingsSections || []).push(section);
  load();
}
export default section;
