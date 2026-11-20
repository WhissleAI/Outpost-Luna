// Spatial (D-pad) focus: the arrow keys move focus to the nearest control in that direction, like a TV remote
// (docs/KEYBOARD.md). It sits on top of the normal Tab order (Tab still works) and on the one intent bus: keys and the
// gamepad emit `move {dir}`, input/keys.js calls engine.move(dir).
//
// The top half is pure (geometry, scopes, memory) and unit-tested in tests/spatial.test.js. The bottom half,
// createSpatial(), is the DOM engine:
//   - scopes: a modal, a sheet, an open cabin panel or a lesson card traps arrow focus; otherwise focus moves inside the
//     current region first (top bar, stage card, voice bar…) and only then to the nearest control in another region
//   - memory: the last focused control per screen, restored when the kid comes back (or when a re-render drops it)
//   - the Moon: one focusable reticle at the globe's centre; arrows hop between places (the globe flies there),
//     Shift+arrows turn the Moon, Enter taps what is under the reticle; past the last place in a direction, the arrow
//     leaves the Moon like any other control
//   - the 3D cabin seat view: arrows move across the console panels (habitat, rover, displays, radiation, comm, the
//     pedestal), which lights the panel; Enter opens it; inside an open panel arrows move between its controls

// ---------------------------------------------------------------- pure ----------------------------------------------

export const DIRS = Object.freeze({ left: [-1, 0], right: [1, 0], up: [0, -1], down: [0, 1] });
export const KEY_DIR = Object.freeze({ ArrowLeft: "left", ArrowRight: "right", ArrowUp: "up", ArrowDown: "down" });

const cx = r => r.left + r.width / 2, cy = r => r.top + r.height / 2;
/** A plain rect {left, top, width, height} (+ right / bottom). */
export function rect(left, top, width, height) { return { left, top, width, height, right: left + width, bottom: top + height }; }

/**
 * How far `to` is from `from` going `dir`, or Infinity when it is not that way. The TV rule: the candidate's centre must
 * be past the source's centre on the main axis; then main-axis gap + 2 × the off-axis gap (0 when they overlap on the
 * other axis), plus a small pull toward the source's centre line so a row reads straight.
 */
export function score(from, to, dir) {
  const [dx, dy] = DIRS[dir] || [0, 0];
  if (!dx && !dy) return Infinity;
  const along = (cx(to) - cx(from)) * dx + (cy(to) - cy(from)) * dy;
  if (along <= 1) return Infinity;
  let gap, off, centreOff;
  if (dx) {
    gap = dx > 0 ? to.left - from.right : from.left - to.right;
    off = Math.max(0, Math.max(from.top, to.top) - Math.min(from.bottom, to.bottom));
    centreOff = Math.abs(cy(to) - cy(from));
  } else {
    gap = dy > 0 ? to.top - from.bottom : from.top - to.bottom;
    off = Math.max(0, Math.max(from.left, to.left) - Math.min(from.right, to.right));
    centreOff = Math.abs(cx(to) - cx(from));
  }
  return Math.max(0, gap) + 2 * off + 0.1 * centreOff + (gap < 0 ? 0.25 * -gap : 0);
}

/** Overlap on the other axis: the candidate is "in the beam" (straight ahead). */
export function inBeam(from, to, dir) {
  const [dx] = DIRS[dir] || [0];
  return dx ? Math.min(from.bottom, to.bottom) > Math.max(from.top, to.top) : Math.min(from.right, to.right) > Math.max(from.left, to.left);
}
/**
 * The index of the best candidate ({rect}) from `from` going `dir`, or -1. Straight ahead first: when anything is in the
 * beam, only those count (a row reads as a row, like a TV focus engine). opts.cone (Moon hops, points not boxes): the
 * candidate must lie within a cone round the direction (along ≥ cone × sideways), so "down" never picks a place to the right.
 */
export function pickBest(from, cands, dir, { cone = 0 } = {}) {
  const [dx, dy] = DIRS[dir] || [0, 0];
  const ok = cands.map(c => {
    const s = score(from, c.rect, dir); if (s === Infinity) return Infinity;
    if (cone) { const ax = cx(c.rect) - cx(from), ay = cy(c.rect) - cy(from), along = ax * dx + ay * dy, side = Math.abs(ax * dy - ay * dx); if (along < cone * side) return Infinity; }
    return s;
  });
  const bestOf = idx => idx.reduce((b, i) => (ok[i] < Infinity && (b < 0 || ok[i] < ok[b]) ? i : b), -1);
  const all = ok.map((_, i) => i);
  if (cone) return bestOf(all);
  const beam = bestOf(all.filter(i => inBeam(from, cands[i].rect, dir))), off = bestOf(all.filter(i => !inBeam(from, cands[i].rect, dir)));
  if (beam < 0 || off < 0) return beam < 0 ? off : beam;
  // the Android TV rule: the straight-ahead one wins when it is nearer than the far edge of the nearest off-axis one
  if (major(from, cands[beam].rect, dir) < majorFar(from, cands[off].rect, dir)) return beam;
  return ok[beam] <= ok[off] ? beam : off;
}
const major = (f, t, dir) => Math.max(0, { right: t.left - f.right, left: f.left - t.right, down: t.top - f.bottom, up: f.top - t.bottom }[dir]);
const majorFar = (f, t, dir) => Math.max(1, { right: t.right - f.right, left: f.left - t.left, down: t.bottom - f.bottom, up: f.top - t.top }[dir]);

/** Same region first (the top bar, the card, the voice bar…); only when nothing is that way there, any region. */
export function pickInRegion(from, fromRegion, cands, dir) {
  const same = cands.map((c, i) => ({ ...c, i })).filter(c => c.region === fromRegion);
  const k = pickBest(from, same, dir), g = pickBest(from, cands, dir);
  if (k < 0) return g;
  // a region can be split across the screen (the map's header and its card): when something in another region is
  // much nearer (under half the distance), it wins; otherwise the region keeps focus
  if (g >= 0 && cands[g].region !== fromRegion && score(from, cands[g].rect, dir) * 2 < score(from, same[k].rect, dir)) return g;
  return same[k].i;
}

/** The scope that traps arrow focus: the first open layer, top-most first ([{id, open}]); null = the whole screen. */
export function topScope(layers) { return (layers || []).find(l => l && l.open) || null; }

/** A stable identity for a control across re-renders: its id, else its first identifying data attribute. */
const ID_ATTRS = ["l", "c", "site", "sec", "view", "task", "sw", "guard", "du", "p", "k", "intent", "say", "cs", "panel", "prof-switch"];
export function keyOf(el) {
  if (!el) return "";
  if (el.id) return "#" + el.id;
  const ds = el.dataset || {};
  for (const a of ID_ATTRS) {
    const k = a.replace(/-(\w)/g, (_, c) => c.toUpperCase());
    if (ds[k] != null && ds[k] !== "") {
      const v = String(ds[k]).replace(/["\\]/g, "\\$&");
      const extra = a === "p" && el.value != null ? `[value="${String(el.value).replace(/["\\]/g, "\\$&")}"]` : "";
      return `${(el.tagName || "").toLowerCase()}[data-${a}="${v}"]${extra}`;
    }
  }
  const cls = String(el.className || "").split(/\s+/).filter(c => c && !/^is-/.test(c))[0];
  return cls ? `${(el.tagName || "").toLowerCase()}.${cls}` : "";
}

/**
 * The last focused control per screen. alive(el) says whether a remembered element can still take focus (connected,
 * visible); when it can't, recall() hands back its identity key so the caller can find its re-rendered twin.
 */
export function createFocusMemory({ alive = el => !!(el && el.isConnected !== false), max = 40 } = {}) {
  const m = new Map();
  return {
    remember(screen, el) { if (!screen || !el) return; m.delete(screen); m.set(screen, { el, key: keyOf(el) }); if (m.size > max) m.delete(m.keys().next().value); },
    /** {el} when it is still alive, {key} when only its identity is left, null when nothing was remembered. */
    recall(screen) { const e = m.get(screen); if (!e) return null; return alive(e.el) ? { el: e.el, key: e.key } : { el: null, key: e.key }; },
    forget(screen) { m.delete(screen); },
    get size() { return m.size; },
  };
}

/** Key repeat: the shortest gap between two moves while a key is held, per Settings speed. */
export const REPEAT_MS = Object.freeze({ slow: 260, normal: 150, fast: 80 });
/** A throttle for auto-repeat: true when a move may run now. */
export function createRepeatGate(now = () => Date.now()) {
  let last = -1e9;
  return { ok(repeat, ms) { const t = now(); if (repeat && t - last < ms) return false; last = t; return true; }, reset() { last = -1e9; } };
}

/** Which controls take Left/Right as a value (1-D controls): they adjust; Up/Down leave. */
export function valueControl(el) {
  if (!el || !el.tagName) return null;
  const tag = el.tagName.toLowerCase(), type = String(el.type || "").toLowerCase(), role = el.getAttribute ? el.getAttribute("role") : null;
  if (tag === "input" && type === "range") return "range";
  if (tag === "input" && type === "radio") return "radio";
  if (tag === "select") return "select";
  if (role === "slider") return "slider";
  return null;
}
/** Text fields: letters type, arrows move the caret, only Esc (and Tab) leave. */
export function isTextField(el) {
  if (!el || !el.tagName) return false;
  if (el.isContentEditable) return true;
  const tag = el.tagName.toLowerCase();
  if (tag === "textarea") return true;
  if (tag !== "input") return false;
  return ["text", "search", "email", "number", "password", "url", "tel", ""].includes(String(el.type || "text").toLowerCase());
}

// ---------------------------------------------------------------- DOM engine ----------------------------------------

const FOCUSABLE = "button, a[href], input:not([type=hidden]), select, textarea, summary, [tabindex]";
/** Never a spatial target (Tab still reaches them): the voice bar grip (its arrows move the bar), the skip link, the
 *  hardware ghosts, the picker's leader-line labels (the Moon reticle and the site rows cover them) and the site
 *  picker's NASA source links (Up from Take command goes straight to the site rows; Tab and a click still open a source). */
const SKIP = ".vs-grip, .skip-link, .ghost, .mx-pin, .gx-grip, .sr-only, .key-hint, .key-legend, .nv-detail a, .nv-crit a";
const REGIONS = [".topbar", "#keysHelp", ".set-nav", ".set-sec", ".a11y-panel", "dialog", ".hl-card", "#card", "#missionCard", ".route", "#aPanel", "#mPanel", "#mDebrief",
  ".hud", ".nowplaying", "#askbar", ".cb-sys", "#mCabin", ".moon-focus", ".gx-ui"];
/** The cabin's console panels, in reading order (the head-look layout of docs/GESTURES.md). */
export const SEAT_PANELS = ["habitat", "rover", "displays", "radiation", "comm", "pedestal"];
const PANEL_NAME = { habitat: "Habitat", rover: "Rover", displays: "Displays and power", radiation: "Radiation", comm: "Comm", pedestal: "Caution and warning, End shift" };
/** Lesson steps whose answer is a tap on the Moon (academy/ui.js + academy/globe_steps.js). */
export const MOON_STEPS = new Set(["tap", "intent", "terminator", "route", "compare", "globe_side"]);

export function createSpatial({ globe = null, places = [], mission = null, inCabin = () => false, cabinPanel = () => null, onMove = () => {}, describe = () => {} } = {}) {
  const doc = document, html = doc.documentElement;
  /** The 3D cabin is up (the flat fallback, without WebGL, is an ordinary screen). */
  const in3d = () => inCabin() && !!doc.querySelector("#mCabin .c3-panel");
  const memory = createFocusMemory({ alive: el => !!(el && el.isConnected && visible(el)) });

  // ---- visibility + candidates ----
  function visible(el) {
    if (!el || !el.isConnected || el.closest("[hidden], [inert]")) return false;
    const r = el.getBoundingClientRect(); if (r.width < 1 || r.height < 1) return false;
    if (r.right < 0 || r.bottom < 0 || r.left > innerWidth || r.top > innerHeight) return false;
    const cs = getComputedStyle(el); if (cs.visibility === "hidden" || cs.display === "none") return false;
    if (+cs.opacity < 0.05 && !(el.tagName === "INPUT" && el.closest("label"))) return false;   // a styled radio / switch: its label shows it
    return true;
  }
  // text fields are not arrow targets: focus there means typing, and only Esc leaves (the / key, Tab or a click get in)
  const focusable = el => !el.disabled && el.tabIndex >= 0 && !el.matches(SKIP) && !isTextField(el) && visible(el);
  const within = (el, roots) => roots.some(r => r && (r === el || r.contains(el)));
  function candidates(roots) {
    const out = [];
    roots.filter(Boolean).forEach(r => {
      if (r.matches && r.matches(FOCUSABLE) && focusable(r)) out.push(r);
      r.querySelectorAll(FOCUSABLE).forEach(el => { if (focusable(el)) out.push(el); });
    });
    return [...new Set(out)];
  }
  const regionOf = el => { for (const s of REGIONS) { const r = el.closest && el.closest(s); if (r) return s; } return "stage"; };

  // ---- the Moon reticle ----
  const moonEl = doc.createElement("button");
  moonEl.type = "button"; moonEl.className = "moon-focus"; moonEl.id = "moonFocus"; moonEl.hidden = true;
  moonEl.setAttribute("aria-label", "The Moon. Arrows move between places, Shift and arrows turn it, Enter picks");
  moonEl.innerHTML = `<span class="mf-ring" aria-hidden="true"></span><span class="mf-name" aria-hidden="true"></span>`;
  (doc.getElementById("stage") || doc.body).append(moonEl);
  const moon = { target: null };
  /** The step on screen, when it is a lesson step. */
  function lessonStep() {
    const ap = doc.getElementById("aPanel"); if (!ap || ap.hidden || doc.body.dataset.aview !== "lesson") return null;
    return { locked: !!ap.querySelector(".a-input.is-locked"), input: ap.querySelector("#aInput"), type: ap.dataset.step || "" };
  }
  function moonActive() {
    if (!globe || doc.body.dataset.ride === "1" || doc.body.dataset.cabin === "1") return false;
    const mode = doc.body.dataset.mode;
    if (mode === "cadet") return true;
    if (mode !== "academy") return false;
    const st = lessonStep(); if (!st || st.locked) return false;
    return MOON_STEPS.has(st.type);
  }
  function placeMoon() {
    const on = moonActive();
    if (moonEl.hidden === on) moonEl.hidden = !on;
    if (!on) { moon.target = null; return; }
    let x = innerWidth / 2, y = innerHeight / 2;
    const st = doc.getElementById("stage"), sr = st ? st.getBoundingClientRect() : { left: 0, top: 0 };
    if (globe.centerLatLon && globe.project) { const c = globe.centerLatLon(), p = globe.project(c.lat, c.lon); x = sr.left + p.x; y = sr.top + p.y; }
    moonEl.style.transform = `translate(${(x - sr.left).toFixed(0)}px,${(y - sr.top).toFixed(0)}px)`;
  }
  const moonPoints = () => {
    const st = doc.getElementById("stage"), sr = st ? st.getBoundingClientRect() : { left: 0, top: 0 };
    const hw = doc.body.dataset.mode === "cadet" && globe.hardwareOn;
    return places.filter(p => p && p.name && p.lat != null && (p.kind !== "artifact" || hw)).map(p => {
      const q = globe.project(p.lat, p.lon); return { p, facing: q.facing, rect: rect(sr.left + q.x - 4, sr.top + q.y - 4, 8, 8) };
    }).filter(o => o.facing && o.rect.left > sr.left && o.rect.top > sr.top && o.rect.right < innerWidth && o.rect.bottom < innerHeight);
  };
  /** An arrow on the Moon: hop to the nearest place that way (true), or false at the edge (the arrow leaves the Moon). */
  function moonHop(dir) {
    const r = moonEl.getBoundingClientRect(), from = rect(cx(r) - 4, cy(r) - 4, 8, 8);
    // only the neighbourhood (30 % of the stage's short side): past it the arrow leaves the Moon for the controls round
    // it (the Library toolbar, the lesson card); Shift+arrows turn the Moon to bring far places near
    const st = doc.getElementById("stage"), reach = 0.3 * Math.min(st ? st.clientWidth : innerWidth, st ? st.clientHeight : innerHeight);
    const pts = moonPoints().filter(o => (!moon.target || o.p.id !== moon.target.id) && Math.hypot(cx(o.rect) - cx(from), cy(o.rect) - cy(from)) <= reach);
    // a place within ~50° of the arrow; else within ~75°; only with nothing that way does the arrow leave the Moon
    let k = pickBest(from, pts, dir, { cone: 0.8 }); if (k < 0) k = pickBest(from, pts, dir, { cone: 0.27 }); if (k < 0) return false;
    const f = pts[k].p; moon.target = f;
    const dist = globe.distance || 3;
    globe.flyTo(f.lat, f.lon, Math.min(dist, f.kind === "artifact" ? 2.6 : dist), Math.abs(f.lat) > 74 ? { clamp: false } : 75);
    if (globe.highlight) globe.highlight(f);
    moonEl.querySelector(".mf-name").textContent = f.name;
    moonEl.setAttribute("aria-label", `The Moon: ${f.name}. Enter picks it`);
    describe(f.name);
    onMove();
    return true;
  }
  function moonTurn(dir) {
    const [dx, dy] = DIRS[dir]; moon.target = null; moonEl.querySelector(".mf-name").textContent = "";
    if (globe.rotateBy) globe.rotateBy(dx * 0.04, dy * 0.04);
  }
  function moonTap() {
    const f = moon.target;
    if (f && f.kind === "artifact" && globe.tapArtifact) globe.tapArtifact(f.id);
    else if (f && globe.tap) globe.tap(f.lat, f.lon);
    else if (globe.tap && globe.centerLatLon) { const c = globe.centerLatLon(); globe.tap(c.lat, c.lon); }
  }

  // ---- the cabin seat: a proxy control that stands for the lit panel ----
  const seatEl = doc.createElement("button");
  seatEl.type = "button"; seatEl.className = "seat-focus"; seatEl.id = "seatFocus"; seatEl.hidden = true; seatEl.tabIndex = -1;
  doc.body.append(seatEl);
  let seatPanel = null;
  const atSeat = () => in3d() && (cabinPanel() || "seat") === "seat";
  const panelEls = () => [...doc.querySelectorAll("#mCabin .c3-panel")].filter(e => !e.hidden && e.dataset.panel && e.getBoundingClientRect().width > 4);
  const panelEl = id => doc.querySelector(`#mCabin .c3-panel[data-panel="${id}"]`);
  function placeSeat() {
    const el = seatPanel && panelEl(seatPanel);
    if (!el || !atSeat()) { if (!seatEl.hidden && doc.activeElement !== seatEl) seatEl.hidden = true; return; }
    const r = el.getBoundingClientRect();
    Object.assign(seatEl.style, { left: r.left + "px", top: r.top + "px", width: r.width + "px", height: r.height + "px" });
  }
  function focusSeat(id) {
    const pointed = doc.querySelector("#mCabin .c3-panel .is-point, #mCabin .c3-panel.is-point");
    const nowPanel = pointed && pointed.closest(".c3-panel") ? pointed.closest(".c3-panel").dataset.panel : null;
    seatPanel = id || seatPanel || nowPanel || (mission && mission.highlighted) || "displays";
    if (!panelEl(seatPanel)) seatPanel = (panelEls()[0] || {}).dataset ? panelEls()[0].dataset.panel : null;
    if (!seatPanel) return false;
    seatEl.hidden = false; seatEl.dataset.panel = seatPanel; placeSeat();
    seatEl.setAttribute("aria-label", `${PANEL_NAME[seatPanel] || seatPanel} panel. Enter opens it`);
    if (mission && mission.intent) mission.intent("highlight_panel", seatPanel);
    seatEl.focus({ preventScroll: true });
    return true;
  }

  // ---- scopes ----
  const shown = sel => [...doc.querySelectorAll(sel)].find(e => !e.hidden && e.getClientRects().length) || null;
  function scope() {
    const help = shown("#keysHelp"); if (help) return { id: "help", roots: [help] };
    // [robustness] what is on top wins: the gestures calibration opens over Settings (from its Camera section), and a
    // native <dialog> sits in the top layer above everything; Settings was checked first, so a key press (Shift+M)
    // pulled focus down into the sheet underneath the calibration
    const cal = shown(".gx-calib"); if (cal) return { id: "modal", roots: [cal] };
    const dlg = [...doc.querySelectorAll("dialog[open]")].pop(); if (dlg) return { id: "dialog", roots: [dlg] };
    const set = shown(".a11y-panel"); if (set) return { id: "settings", roots: [set] };
    const modal = shown(".gx-calib, [role=dialog][aria-modal=true]"); if (modal) return { id: "modal", roots: [modal] };
    const gl = shown(".hl-card"); if (gl && gl.contains(doc.activeElement)) return { id: "glossary", roots: [gl] };
    // the cockpit's patch card (mission/patches.js): it sits over the cabin, outside the open Habitat console, so it
    // holds focus while focus is in it (else the open panel's scope pulled focus straight back to a switch)
    const pc = shown(".cb-patchpop"); if (pc && pc.contains(doc.activeElement)) return { id: "patches", roots: [pc] };
    // the first-mission cabin tour (mission/tour.js): its card holds focus (Next, Skip tour) until it ends
    const tour = shown(".m-tour"); if (tour) return { id: "tour", roots: [tour] };
    // the cabin's Systems drawer (mission/systems.js): its panel, the Now card and the window keys (the Systems key);
    // Esc / B closes it and focus goes back to the Systems key
    const sys = in3d() && shown("#cbSys"); if (sys) return { id: "systems", roots: [sys, shown("#mCabin .cb-now"), shown("#mCabin .cb-viewbar"), shown("#mCabin .cb-why")] };
    if (in3d()) {
      const p = cabinPanel() || "seat";
      if (p !== "seat") { const open = doc.querySelector("#mCabin .c3-panel.is-open"); if (open) return { id: "panel:" + p, roots: [open, shown(".c3-back")] }; }
      return { id: "seat", roots: [doc.getElementById("mCabin"), doc.querySelector(".topbar")], seat: true };
    }
    const st = lessonStep();
    if (st || doc.body.dataset.ride === "1") {
      const ap = doc.getElementById("aPanel");
      return { id: "lesson", roots: [ap, moonActive() ? moonEl : null, shown(".route"), shown("#card")] };
    }
    return { id: "screen", roots: [doc.body], open: true };
  }
  function screenKey() {
    const b = doc.body.dataset, ms = mission && mission.screen ? (mission.screen() || {}).screen || "" : "";
    return [b.mode || "", b.aview || "", ms, inCabin() ? cabinPanel() || "seat" : "", scope().id].join("|");
  }

  // ---- what to focus when nothing is (a new screen, a re-render) ----
  const PRIMARY = ["#keysHelp [data-close]", ".m-tour .t-next", "#cbSys .is-point", "#cbSys .sys-body button:not(.sys-why):not(:disabled)", "#cbSys .sys-tab[aria-selected=true]", ".a11y-panel .set-nav [aria-current=page]", "dialog[open] .x", "#aNext", ".a-choice:not([disabled])", ".a-order", ".v-opt",
    "#aRetry", "#aGoMission", "#aNextLesson", "#aStart", "#aCsGo", "#aPanel .a-crs-opt.is-default", "#aCrpMoon", "#aCrpCancel", "#mStart", "#mBriefGo", "#mDebrief[data-primary=next] #mNext", "#mAgain", ".cb-offer button", "#card .card-actions button", "#cardClose"];
  function primary(sc = scope()) {
    if (sc.seat) return null;
    const cands = candidates(sc.roots);
    if (sc.id.startsWith("panel:")) { const pt = cands.find(c => c.matches(".is-point, .is-point *")); if (pt) return pt; }
    if (sc.id === "lesson") {
      const inp = doc.querySelector("#aInput");
      // [playtest 12] a question with several answers (the check ride's orders, a choice): the question takes focus,
      // never the first answer, so the Enter that pressed Next can't also send "Heaters up" into a storm
      const answers = inp ? cands.filter(c => inp.contains(c) && c.matches(".a-choice, .a-order, .v-opt")) : [];
      const ask = answers.length > 1 && doc.querySelector("#aPanel .a-prompt");
      if (ask && visible(ask)) { if (!ask.hasAttribute("tabindex")) ask.tabIndex = -1; return ask; }
      const own = inp && cands.find(c => inp.contains(c) && c.matches("button"));
      if (own) return own;
      const nx = cands.find(c => c.id === "aNext"); if (nx) return nx;
      if (moonActive()) return moonEl;
      const more = cands.find(c => c.matches(".a-clip, #aBriefBtn, #aRetry")); if (more) return more;   // a typed answer: "/" opens the text box
    }
    for (const s of PRIMARY) { const el = cands.find(c => c.matches(s)); if (el) return el; }
    return cands[0] || null;
  }
  function focusEl(el) {
    if (!el) return false;
    if (el === moonEl) placeMoon();
    el.focus({ preventScroll: true });
    if (el.closest && el.closest(".route") && el.dataset.lat != null && globe) {   // a map pin: the globe flies to it
      const lat = +el.dataset.lat, lon = +el.dataset.lon, d = globe.distance || 3;
      globe.flyTo(lat, lon, d, Math.abs(lat) > 70 ? 88 : 75);
    }
    return doc.activeElement === el;
  }
  /** Focus the remembered control for this screen, its re-rendered twin, or the screen's primary action. */
  function restore() {
    const sc = scope();
    if (sc.seat) return focusSeat();
    const m = memory.recall(screenKey());
    if (m && m.el && within(m.el, sc.roots.filter(Boolean)) && focusable(m.el)) return focusEl(m.el);
    if (m && m.key) { const twin = candidates(sc.roots).find(c => keyOf(c) === m.key); if (twin) return focusEl(twin); }
    if (lastKey) { const twin = candidates(sc.roots).find(c => keyOf(c) === lastKey); if (twin) return focusEl(twin); }
    const p = primary(sc); auto = { el: p, t: Date.now() };
    return focusEl(p);
  }

  // ---- moving ----
  /** One arrow press. opts.shift: on the Moon, turn it instead of hopping. True when focus (or the Moon) moved. */
  function move(dir, opts = {}) {
    if (!DIRS[dir]) return false;
    const a = doc.activeElement, sc = scope();
    const roots = sc.roots.filter(Boolean);
    if (a === moonEl && !moonEl.hidden) {
      if (opts.shift) { moonTurn(dir); return true; }
      if (moonHop(dir)) return true;
    }
    const lost = !a || a === doc.body || (!within(a, roots) && a !== seatEl) || !visible(a);
    if (sc.seat) return seatMove(dir, lost ? null : a);
    if (lost) return restore();
    const from = a.getBoundingClientRect(), cands = candidates(roots).filter(c => c !== a);
    if (moonActive() && !cands.includes(moonEl) && within(moonEl, roots)) cands.push(moonEl);
    const items = cands.map(el => ({ el, rect: el.getBoundingClientRect(), region: regionOf(el) }));
    // the top bar is the screen's edge: it is reached only when nothing on the stage lies that way (Up from the map
    // card goes to the pins above it, not to the Library button that happens to be in line)
    let k = -1;
    if (sc.id === "screen") {
      const mine = regionOf(a), stage = items.map((it, i) => ({ ...it, i })).filter(it => it.region !== ".topbar" || mine === ".topbar");
      const j = pickInRegion(from, mine, stage, dir);
      k = j >= 0 ? stage[j].i : pickInRegion(from, mine, items, dir);
    } else k = pickInRegion(from, regionOf(a), items, dir);   // inside a sheet too: its section list, then its body
    if (k < 0) return scrollOn(a, roots, dir);
    focusEl(items[k].el); onMove();
    return true;
  }
  /** Nothing that way: a long sheet (About, Settings, the debrief) scrolls instead, so what is below comes into reach. */
  function scrollOn(a, roots, dir) {
    const dy = DIRS[dir][1]; if (!dy) return false;
    const can = el => { if (!el || el.nodeType !== 1) return false; const o = getComputedStyle(el).overflowY; return /(auto|scroll)/.test(o) && el.scrollHeight > el.clientHeight + 4; };
    let el = a; while (el && el !== doc.body && !can(el)) el = el.parentElement;
    if (!can(el)) el = roots.flatMap(r => [r, ...r.querySelectorAll("div, section, ul, ol, article, form")]).find(can);
    if (!can(el)) return false;
    const before = el.scrollTop; el.scrollBy({ top: dy * el.clientHeight * 0.6 });
    if (el.scrollTop === before && !(el.scrollBy.length === 0)) return false;
    return true;
  }
  function seatMove(dir, a) {
    const cab = doc.getElementById("mCabin"); if (!cab) return false;
    // a choice on the Now panel (Steer left / Steer right): the arrows / D-pad step between its options first, and leave
    // the group only past its ends (keys and controller both arrive here as `move`)
    const grp = a && a.closest && a.closest(".cb-now-btns");
    if (grp) { const bs = [...grp.querySelectorAll("button")].filter(visible), i = bs.indexOf(a), n = bs[i + (dir === "right" || dir === "down" ? 1 : -1)];
      if (i >= 0 && n) { focusEl(n); onMove(); return true; } }
    // [polish 3] a decision on the Now card (a storm, CAPCOM's yes / no): Up from the seat goes to its first button
    // ("Crew into the shelter"); the alert strip above the window only says what is happening
    if (a === seatEl && dir === "up") { const hot = cab.querySelector(".cb-now.is-takeover:not([hidden]) .cb-now-b");
      if (hot && visible(hot)) { seatEl.hidden = true; focusEl(hot); onMove(); return true; } }
    const fromEl = a === seatEl ? panelEl(seatPanel) : a;
    if (!fromEl) return focusSeat();
    const from = fromEl.getBoundingClientRect();
    // [polish 4] Up from the cabin's own controls (the view bar, the deck, the Now card) never drops back onto a 3D
    // console: a lit console turns the camera, and its projected box could reach above the view bar, so Up from Orbit
    // went back to the seat and Up from the seat to Orbit (a trap: the top bar was out of reach)
    const hudUp = dir === "up" && a !== seatEl && !!(a && a.closest && a.closest(".cb-viewbar, .cb-deck, .cb-now, .cb-alert, .cb-why, .cb-mlog"));
    const items = [
      ...(hudUp ? [] : panelEls()).filter(p => p.dataset.panel !== (a === seatEl ? seatPanel : "")).map(p => ({ panel: p.dataset.panel, rect: p.getBoundingClientRect() })),
      // the cabin's own controls (window views, the alert strip, the comm row) and the top bar (sections, Settings)
      ...candidates([cab, doc.querySelector(".topbar")]).filter(c => c !== a && !c.closest(".c3-panel")).map(el => ({ el, rect: el.getBoundingClientRect() })),
    ];
    // the top bar is the edge here too: reached only when nothing in the cabin lies that way
    // except sideways along the cockpit's bar (body[data-cockpit]): the header keys share its row, so Left from the bar's
    // Log key reaches Library (it used to drop to the window keys, and Library was out of reach from the gear)
    const deckRow = (dir === "left" || dir === "right") && doc.body.dataset.cockpit === "1" && !!(a && a.closest && a.closest(".cb-deck"));
    const inCab = items.map((it, i) => ({ ...it, i })).filter(it => !(it.el && it.el.closest(".topbar")) || deckRow || (a && a.closest && a.closest(".topbar")));
    // sideways from a control (the alert strip, the deck, the Now panel): a control in the same row wins over a 3D console,
    // whose projected box can reach up into that row (Left from "Set shields" used to jump to a console, not "Shelter")
    const row = a !== seatEl && (dir === "left" || dir === "right") ? inCab.filter(it => it.el && inBeam(from, it.rect, dir)) : [];
    const r = row.length ? pickBest(from, row, dir) : -1;
    let j = r >= 0 ? -1 : pickBest(from, inCab, dir), k = r >= 0 ? row[r].i : j >= 0 ? inCab[j].i : pickBest(from, items, dir);
    // [0.4] the header is folded into the cockpit's bar (body[data-cockpit]): its keys share the bar's row, so Up from the
    // bar finds nothing above it; it goes to the nearest header key instead (the screen's top edge, as before)
    if (k < 0 && dir === "up" && a && a.closest && a.closest(".cb-deck") && doc.body.dataset.cockpit === "1") {
      const cx = from.left + from.width / 2;
      k = items.reduce((best, it, i) => (it.el && it.el.closest(".topbar") ? (best < 0 || Math.abs(it.rect.left + it.rect.width / 2 - cx) < Math.abs(items[best].rect.left + items[best].rect.width / 2 - cx) ? i : best) : best), -1);
    }
    if (k < 0) return false;
    if (items[k].panel) focusSeat(items[k].panel); else { seatEl.hidden = true; focusEl(items[k].el); }
    onMove();
    return true;
  }
  /** Enter / Space-tap / A: what "select" means for the focused thing. True when something ran. */
  function activate() {
    const a = doc.activeElement;
    if (a === moonEl) { moonTap(); return true; }
    if (a === seatEl) { if (mission && mission.intent) mission.intent("panel_open", seatEl.dataset.panel || seatPanel); return true; }
    if (!a || a === doc.body) { restore(); return true; }
    if (valueControl(a) === "range" || valueControl(a) === "slider" || isTextField(a)) return false;
    if (a.tagName === "SELECT") return false;
    a.click();
    return true;
  }

  // ---- watching: remember focus per screen; refocus when a re-render or a new screen drops it ----
  let lastKey = "", lastPanel = "seat", auto = { el: null, t: 0 }, was3d = false;
  doc.addEventListener("focusin", e => {
    const t = e.target; if (!t || t === doc.body) return;
    if (t !== moonEl && t !== seatEl) lastKey = keyOf(t);
    memory.remember(screenKey(), t);
    if (t !== seatEl && !seatEl.hidden) seatEl.hidden = true;
  });
  const keysMode = () => html.dataset.input === "keys" || html.dataset.input === "pad";
  function watch() {
    placeMoon(); placeSeat();
    if (!keysMode()) return;
    const sc = scope(), a = doc.activeElement;
    // the cabin camera moved (a panel opened by voice, a click, Esc): follow it
    if (in3d() && !(sc.seat || sc.id.startsWith("panel:") || sc.id === "systems")) { was3d = true; lastPanel = cabinPanel() || "seat"; }   // a sheet or the tour is up: leave its focus alone
    else if (sc.id === "systems") { was3d = true; lastPanel = cabinPanel() || "seat"; }   // the drawer: its focus is checked below
    else if (in3d()) {
      // the cabin just appeared (or keys just started in it): the seat, unless focus already sits on a cabin control
      // (a kid who clicked "Steer left" and then pressed an arrow keeps that button)
      if (!was3d) { was3d = true; lastPanel = cabinPanel() || "seat"; const cab = doc.getElementById("mCabin");
        if (lastPanel === "seat" && !(a && a !== doc.body && a !== seatEl && cab && cab.contains(a) && visible(a))) { focusSeat(); return; } }
      const p = cabinPanel() || "seat";
      if (p !== lastPanel) { const was = lastPanel; lastPanel = p;
        if (p === "seat") {
          // a cabin control the kid already moved to (the view bar, the deck, the Now card) keeps focus when the camera
          // settles back at the seat; only focus inside a console (or none) goes back to the seat
          const cab = doc.getElementById("mCabin");
          if (a && a !== seatEl && a !== doc.body && cab && cab.contains(a) && !a.closest(".c3-panel, .c3-back") && visible(a)) return;
          focusSeat(was !== "seat" ? (was === "power" ? "displays" : was) : null); return; }
        restore(); return; }
    } else { lastPanel = "seat"; was3d = false; }
    const roots = sc.roots.filter(Boolean);
    const ok = a === seatEl ? atSeat() && !seatEl.hidden && sc.id !== "systems"
      : !!(a && a !== doc.body && a.isConnected && visible(a) && (sc.id === "screen" || within(a, roots) || (isTextField(a) && !sc.id.match(/^(help|settings|dialog|modal)$/))));
    if (!ok) { restore(); return; }
    // a screen that was still loading when focus was restored (the picker's "Loading…"): once its primary action
    // appears, the auto-picked fallback moves to it (only within 4 s, and only if the kid hasn't moved since)
    if (auto.el && a === auto.el && Date.now() - auto.t < 4000) {
      if (sc.seat) { auto = { el: null, t: 0 }; focusSeat(); return; }   // the 3D cabin finished building after the restore
      const p = primary(sc);
      if (p && p !== a && PRIMARY.some(sel => p.matches(sel))) { auto = { el: p, t: auto.t }; focusEl(p); }
    }
  }
  const timer = setInterval(watch, 160);
  addEventListener("resize", () => { placeMoon(); placeSeat(); });
  (function raf() { if (doc.activeElement === seatEl) placeSeat(); if (doc.activeElement === moonEl) placeMoon(); requestAnimationFrame(raf); })();

  return {
    move, activate, restore, scope, screenKey, primary, focusSeat, moonActive,
    zoom: f => { if (doc.activeElement === moonEl && globe && globe.zoomBy) { globe.zoomBy(f); return true; } return false; },
    get moonEl() { return moonEl; }, get seatEl() { return seatEl; }, get seatPanel() { return seatEl.hidden ? null : seatPanel; },
    stop: () => clearInterval(timer),
  };
}
