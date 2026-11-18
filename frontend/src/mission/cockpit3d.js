// The cabin as a 3D room (three.js), seen from the commander's seat. Inspired by Orion's cockpit design language:
// glass display units with edge keys, guarded switches, a big forward window. It is NOT a replica of Orion and our
// outpost is a surface habitat, not a spacecraft.
//
// Two layers share one camera:
//   • WebGL: the shell (walls, window frame, consoles, rails), lit by the window and the displays. The window is a real
//     hole (alpha 0), so the terrain / globe views behind the cabin show through it.
//   • CSS3D: the control panels are the cabin's real DOM (buttons, sliders, live text) placed on the console faces with
//     CSS3DRenderer. Focus, labels, screen readers and voice all keep working; nothing is drawn only on the canvas.
// Seat view shows everything; open("habitat" | "power" | "comm") dollies the camera to that panel; back() returns.
// Reduced motion: camera moves are cuts and there is no head-bob.
import * as THREE from "three";
import { CSS3DRenderer, CSS3DObject } from "three/examples/jsm/renderers/CSS3DRenderer.js";
import { RoundedBoxGeometry } from "three/examples/jsm/geometries/RoundedBoxGeometry.js";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";
import { RectAreaLightUniformsLib } from "three/examples/jsm/lights/RectAreaLightUniformsLib.js";

/** Panel placement in metres. px = the DOM panel's CSS width; the scale maps it onto `w` metres of console face.
 *  [0.4 cabin 2] The faces turn toward the seat: each one is nearly square-on to the camera (a small yaw and tilt keep
 *  the room's depth), so their text reads upright from the seat (consoleSkew ≤ MAX_SKEW°, tests/cabin_flat.test.js).
 *  The old angles (rover / comm yawed 0.6 rad and pitched 0.62, the pedestal laid back 1.0) slanted "Ice · Explore ·
 *  Home" and "Call Houston" by 13-15°, soft and hard to read. The side consoles sit 4 cm higher, so the Rover's
 *  Ice · Explore · Home row clears the CAPCOM strip at 1280×720. */
const BASE_LAYOUT = {
  window: { cx: 0, cy: 1.66, w: 2.3, h: 0.98, r: 0.16, z: -1.7 },
  // the three display units, side by side under the window (DU1 commander-side power, DU2 shared, DU3 radiation)
  displays: { pos: [0, 0.98, -1.5], rot: [-0.24, 0, 0], w: 2.0, px: 1200, pxh: 330, pedestal: true },
  // switch panels round the displays: habitat + rover on the left, radiation + comm on the right, C&W + End shift below
  habitat: { pos: [-1.25, 1.18, -1.2], rot: [-0.06, 0.18, 0], w: 0.8, px: 560, pxh: 340 },
  rover: { pos: [-1.12, 0.66, -1.02], rot: [-0.2, 0.18, 0], w: 0.8, px: 560, pxh: 300 },
  radiation: { pos: [1.25, 1.18, -1.2], rot: [-0.06, -0.18, 0], w: 0.8, px: 560, pxh: 340 },
  comm: { pos: [1.12, 0.66, -1.02], rot: [-0.2, -0.18, 0], w: 0.8, px: 560, pxh: 320 },
  pedestal: { pos: [0, 0.56, -1.12], rot: [-0.34, 0, 0], w: 1.15, px: 800, pxh: 300 },
};
/** The most a console's text may lean from the seat (degrees): its rows off horizontal, its columns off vertical. */
export const MAX_SKEW = 8;
/** [0.3.12] The check ride's layout: no Habitat or Comm, so the Rover takes the Habitat's seat (the mirror of
 *  Radiation, high and facing the seat) instead of the low console whose face ran off-screen and read slanted. */
export const RIDE_LAYOUT = { rover: { pos: [-1.25, 1.14, -1.2], rot: [-0.06, 0.18, 0], w: 0.8, px: 560, pxh: 300 } };
/** Zoom targets that are part of a bigger console: [object, left fraction, right fraction]. */
const SUB = { power: ["displays", 0, 1 / 3] };
const SEAT = { pos: new THREE.Vector3(0, 1.32, 0.78), look: new THREE.Vector3(0, 1.2, -1.6) };
const STRIP_PX = 84;   // the comm strip under the cabin (captions + voice), kept clear when a panel is open
export const PANELS = [["displays", "Displays"], ["power", "Power"], ["habitat", "Habitat"], ["rover", "Rover"], ["radiation", "Radiation"], ["comm", "Comm"], ["pedestal", "Shift"]];

const css = (el, name, fb) => (getComputedStyle(el).getPropertyValue(name).trim() || fb);

/** [0.3.12] The seat view's vertical field of view: the base for the free area's aspect, widened (up to FIT_MAX_FOV)
 *  until every console's face is inside the free area with `margin` px to spare. `project(fov)` returns the faces'
 *  projected x range in px for a fov. The panel row scales down instead of being clipped (the check ride's Radiation
 *  panel was cut and its Rover panel ran off the left edge beside the lesson card). */
export const FIT_MAX_FOV = 84;
export function baseFov(aspect) { return aspect < 1.5 ? 66 : aspect < 1.75 ? 60 : 56; }
export function fitFov(aspect, freeW, project, margin = 12) {
  let fov = baseFov(aspect);
  for (; fov < FIT_MAX_FOV; fov += 2) {
    const [x0, x1] = project(fov);
    if (x0 >= margin && x1 <= freeW - margin) break;
  }
  return Math.min(fov, FIT_MAX_FOV);
}

/** How far a console's text leans on screen from the seat, in degrees: the worst of its rows (top, middle, bottom) off
 *  horizontal and its columns (left, centre, right) off vertical. Pure three.js maths (no DOM): the tests run it on
 *  every layout at the seat's field of view for common window shapes. -> {id: degrees} */
export function consoleSkew(layout = null, { w = 1440, h = 900, fov = baseFov(w / h) } = {}) {
  const L = { ...BASE_LAYOUT, ...(layout || {}) }, cam = new THREE.PerspectiveCamera(fov, w / h, 0.05, 50);
  cam.position.copy(SEAT.pos); cam.lookAt(SEAT.look); cam.updateMatrixWorld(true);
  const P = v => { const p = v.project(cam); return [(p.x + 1) / 2 * w, (1 - p.y) / 2 * h]; };
  const ang = (a, b) => Math.atan2(-(b[1] - a[1]), b[0] - a[0]) * 180 / Math.PI;
  const out = {};
  Object.entries(L).forEach(([id, c]) => {
    if (!c.rot) return;
    const g = new THREE.Object3D(); g.position.set(...c.pos); g.rotation.copy(new THREE.Euler(c.rot[0], c.rot[1], c.rot[2], "YXZ")); g.updateMatrixWorld(true);
    const pw = c.w, ph = c.pxh * c.w / c.px, at = (x, y) => P(g.localToWorld(new THREE.Vector3(x, y, 0)));
    let worst = 0;
    [-0.45, 0, 0.45].forEach(f => { worst = Math.max(worst, Math.abs(ang(at(-pw / 2, f * ph), at(pw / 2, f * ph))),
      Math.abs(90 - Math.abs(ang(at(f * pw, -ph / 2), at(f * pw, ph / 2))))); });
    out[id] = +worst.toFixed(1);
  });
  return out;
}

export function createCockpit3D(host, { panels, hole, glass = null, reduced = () => false, onPanel = () => {}, insetRight = () => 0, layout = null } = {}) {
  const LAYOUT = { ...BASE_LAYOUT, ...(layout || {}) };
  let renderer;
  try { renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "high-performance" }); }
  catch (e) { return null; }
  if (!renderer.getContext()) return null;
  RectAreaLightUniformsLib.init();
  renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 1.5));
  renderer.setClearColor(0x000000, 0);
  renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = 1.05;
  renderer.domElement.className = "c3-gl"; renderer.domElement.setAttribute("aria-hidden", "true");
  const cssR = new CSS3DRenderer(); cssR.domElement.className = "c3-css";
  host.append(renderer.domElement, cssR.domElement);

  const scene = new THREE.Scene(), cssScene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(58, 1, 0.05, 50);
  camera.position.copy(SEAT.pos); camera.lookAt(SEAT.look);
  const pmrem = new THREE.PMREMGenerator(renderer);
  const envTex = pmrem.fromScene(new RoomEnvironment(renderer), 0.04).texture; scene.environment = envTex;

  // ---------- materials (colours from the design tokens) ----------
  const col = n => new THREE.Color(css(host, n, "#1A1D22"));
  const metal = new THREE.MeshStandardMaterial({ color: col("--color-panel"), roughness: 0.62, metalness: 0.35, envMapIntensity: 0.6 });
  const wall = new THREE.MeshStandardMaterial({ color: col("--color-panel-2"), roughness: 0.85, metalness: 0.1, envMapIntensity: 0.4 });
  const dark = new THREE.MeshStandardMaterial({ color: col("--color-space"), roughness: 0.5, metalness: 0.5 });
  const trim = new THREE.MeshStandardMaterial({ color: col("--color-on-space-2"), roughness: 0.35, metalness: 0.8, envMapIntensity: 1 });

  // ---------- shell ----------
  const W = LAYOUT.window;
  const rr = (s, x, y, w, h, r) => { s.moveTo(x + r, y); s.lineTo(x + w - r, y); s.quadraticCurveTo(x + w, y, x + w, y + r); s.lineTo(x + w, y + h - r);
    s.quadraticCurveTo(x + w, y + h, x + w - r, y + h); s.lineTo(x + r, y + h); s.quadraticCurveTo(x, y + h, x, y + h - r); s.lineTo(x, y + r); s.quadraticCurveTo(x, y, x + r, y); return s; };
  // forward bulkhead with the window hole
  const front = rr(new THREE.Shape(), -2.6, 0, 5.2, 3.0, 0.3);
  front.holes.push(rr(new THREE.Path(), W.cx - W.w / 2, W.cy - W.h / 2, W.w, W.h, W.r));
  const frontM = new THREE.Mesh(new THREE.ExtrudeGeometry(front, { depth: 0.08, bevelEnabled: false }), wall);
  frontM.position.z = W.z - 0.08; scene.add(frontM);
  // window reveal (the deep frame) + a bright trim ring
  const ringS = rr(new THREE.Shape(), W.cx - W.w / 2 - 0.09, W.cy - W.h / 2 - 0.09, W.w + 0.18, W.h + 0.18, W.r + 0.09);
  ringS.holes.push(rr(new THREE.Path(), W.cx - W.w / 2, W.cy - W.h / 2, W.w, W.h, W.r));
  const ring = new THREE.Mesh(new THREE.ExtrudeGeometry(ringS, { depth: 0.22, bevelEnabled: true, bevelThickness: 0.015, bevelSize: 0.015, bevelSegments: 3 }), metal);
  ring.position.z = W.z - 0.14; scene.add(ring);
  const lipS = rr(new THREE.Shape(), W.cx - W.w / 2 - 0.12, W.cy - W.h / 2 - 0.12, W.w + 0.24, W.h + 0.24, W.r + 0.12);
  lipS.holes.push(rr(new THREE.Path(), W.cx - W.w / 2 - 0.085, W.cy - W.h / 2 - 0.085, W.w + 0.17, W.h + 0.17, W.r + 0.085));
  const lip = new THREE.Mesh(new THREE.ExtrudeGeometry(lipS, { depth: 0.03, bevelEnabled: false }), trim); lip.position.z = W.z + 0.08; scene.add(lip);
  // bolts round the frame
  const boltG = new THREE.CylinderGeometry(0.014, 0.014, 0.012, 12); boltG.rotateX(Math.PI / 2);
  for (let i = 0; i < 18; i++) {
    const t = i / 18 * Math.PI * 2, b = new THREE.Mesh(boltG, trim);
    b.position.set(W.cx + Math.cos(t) * (W.w / 2 + 0.1) * 1.0, W.cy + Math.sin(t) * (W.h / 2 + 0.1), W.z + 0.115);
    b.position.x = Math.max(W.cx - W.w / 2 - 0.1, Math.min(W.cx + W.w / 2 + 0.1, b.position.x)); scene.add(b);
  }
  // side walls, ceiling, floor: a narrow, tapered cabin
  const sideG = new THREE.PlaneGeometry(3.2, 3.0);
  [-1, 1].forEach(s => { const m = new THREE.Mesh(sideG, wall); m.position.set(s * 2.05, 1.5, -0.3); m.rotation.y = -s * (Math.PI / 2 - 0.42); scene.add(m); });
  const ceil = new THREE.Mesh(new THREE.PlaneGeometry(5, 3.4), wall); ceil.position.set(0, 2.55, -0.2); ceil.rotation.x = Math.PI / 2 + 0.12; scene.add(ceil);
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(5, 3.4), dark); floor.position.set(0, 0.0, -0.2); floor.rotation.x = -Math.PI / 2; scene.add(floor);
  // [0.4] no visible ceiling light strip: at the wider fields of view (fitFov) its white bar showed as a thin line under
  // the cockpit's top bar. The cabin light stays (the `fill` point light below); the ceiling is plain panel.
  // grab bars either side of the window (Orion-style handholds)
  const railG = new THREE.CapsuleGeometry(0.014, 0.42, 4, 10);
  [-1, 1].forEach(sx => { const r = new THREE.Mesh(railG, trim); r.position.set(sx * (W.w / 2 + 0.26), W.cy, W.z + 0.1); scene.add(r);
    [-1, 1].forEach(sy => { const f = new THREE.Mesh(new THREE.CylinderGeometry(0.012, 0.012, 0.09, 8), trim); f.rotation.x = Math.PI / 2; f.position.set(r.position.x, W.cy + sy * 0.2, W.z + 0.06); scene.add(f); }); });

  // ---------- consoles + the DOM panels on their faces ----------
  const objs = {}, poses = {};
  const toRot = r => new THREE.Euler(r[0], r[1], r[2], "YXZ");
  Object.entries(panels).forEach(([id, el]) => {
    const L = LAYOUT[id]; if (!L || !el) return;
    const s = L.w / L.px, h = L.pxh * s;
    const g = new THREE.Group(); g.position.set(...L.pos); g.rotation.copy(toRot(L.rot)); scene.add(g);
    const body = new THREE.Mesh(new RoundedBoxGeometry(L.w + 0.12, h + 0.12, 0.42, 4, 0.04), metal); body.position.z = -0.215; g.add(body);
    const bezel = new THREE.Mesh(new THREE.BoxGeometry(L.w + 0.04, h + 0.04, 0.01), dark); bezel.position.z = -0.002; g.add(bezel);
    // a pedestal to the floor for the main console
    if (L.pedestal) { const ped = new THREE.Mesh(new RoundedBoxGeometry(L.w * 0.7, 1.0, 0.5, 3, 0.04), metal); ped.position.set(0, -0.6, -0.42); g.add(ped); }
    const o = new CSS3DObject(el); o.position.copy(g.position); o.rotation.copy(g.rotation); o.scale.setScalar(s);
    o.position.add(new THREE.Vector3(0, 0, 0.004).applyEuler(g.rotation));
    cssScene.add(o); objs[id] = { o, g, w: L.w, h, el };
    // panel glow onto the room
    const glow = new THREE.PointLight(col("--color-phosphor"), 0.35, 1.6, 2); glow.position.set(0, 0, 0.35); g.add(glow);
  });

  // ---------- light: the window is the key light; the room is dim ----------
  const hemi = new THREE.HemisphereLight(0xb9c6d8, 0x101216, 0.35); scene.add(hemi);
  const win = new THREE.RectAreaLight(0xe8eef8, 4.2, W.w, W.h); win.position.set(W.cx, W.cy, W.z); win.lookAt(W.cx, W.cy - 0.6, 1); scene.add(win);
  const fill = new THREE.PointLight(0xc8d4e6, 0.8, 5, 2); fill.position.set(0, 2.3, 0.2); scene.add(fill);
  /** [0.4 cabin 2] Storm lighting: the room (walls, frame, console bodies) goes to red alert light; the consoles' own
   *  faces are DOM and keep their colours, so every value stays readable (the old full-screen dim made them vanish). */
  let alertOn = false;
  function setAlert(on) {
    alertOn = !!on;
    hemi.color.set(alertOn ? 0xd8584c : 0xb9c6d8); hemi.intensity = alertOn ? 0.3 : 0.35;
    fill.color.set(alertOn ? 0xff4636 : 0xc8d4e6); fill.intensity = alertOn ? 1.1 : 0.8;
    win.intensity = alertOn ? 2.6 : 4.2;
  }
  /** Graphics quality: "low" drops the display glows and the environment reflections and renders at 1× pixels. */
  let quality = "high";
  function setQuality(q) {
    quality = q === "low" ? "low" : "high";
    renderer.setPixelRatio(quality === "low" ? 1 : Math.min(devicePixelRatio || 1, 1.5));
    scene.environment = quality === "low" ? null : envTex;
    scene.traverse(o => { if (o.isPointLight && o !== fill) o.visible = quality !== "low"; });
    resize();
  }

  // ---------- camera: seat, parallax, dolly ----------
  let open = null, tween = null, pointer = { x: 0, y: 0 }, size = { w: 1, h: 1, fw: 1 };
  // look-around offset (gestures: head pose / grab-drag), clamped; eased toward its target each frame
  // Bounded so the windshield and the consoles always stay in frame (the owner got stuck at ±0.55 rad yaw, the window
  // pushed off to one side). Any look input that stops (the face lost, the camera off, a hand gone) springs back to the
  // seat after LOOK_IDLE_MS; the tour's beats hold their look until the next beat (look(..., {hold: true})).
  const lookT = { x: 0, y: 0 }, lookC = { x: 0, y: 0 }, MAX_YAW = 0.2, MAX_PITCH = 0.1, LOOK_IDLE_MS = 700;
  let lookAt = 0, lookHold = false, lookLast = performance.now();
  let hl = null;
  const target = { pos: SEAT.pos.clone(), look: SEAT.look.clone() };
  host.dataset.panel = "seat";
  const cur = { pos: SEAT.pos.clone(), look: SEAT.look.clone() };
  function poseFor(id) {
    const sub = SUB[id], P = objs[sub ? sub[0] : id]; if (!P) return { pos: SEAT.pos.clone(), look: SEAT.look.clone() };
    const n = new THREE.Vector3(0, 0, 1).applyEuler(P.g.rotation), c = P.g.position.clone();
    let pw = P.w, ppx = LAYOUT[sub ? sub[0] : id].px;
    if (sub) { const right = new THREE.Vector3(1, 0, 0).applyEuler(P.g.rotation); c.addScaledVector(right, ((sub[1] + sub[2]) / 2 - .5) * P.w); pw = P.w * (sub[2] - sub[1]); ppx = ppx * (sub[2] - sub[1]); }
    const L = { ...LAYOUT[sub ? sub[0] : id], px: ppx }, vfov = camera.fov * Math.PI / 180, tv = Math.tan(vfov / 2), th = tv * camera.aspect;
    // On-screen size: about 1.15× the panel's CSS pixels (crisp text), never wider than 86% of the stage or taller than
    // the space above the comm strip.
    const free = size.h - STRIP_PX, tw = Math.min(L.px * 1.15, size.fw * 0.86), thh = Math.min(L.pxh * 1.15, free * 0.9);
    const d = Math.max(pw * size.fw / (2 * th * tw), P.h * size.h / (2 * tv * thh));
    // centre the panel in the space above the comm strip: aim a little below it
    const up = new THREE.Vector3(0, 1, 0).applyEuler(P.g.rotation), shift = (STRIP_PX / 2) * (2 * d * tv / size.h);
    const look = c.clone().addScaledVector(up, -shift);
    return { pos: look.clone().addScaledVector(n, d), look };
  }
  function go(id) {
    open = id || null; const p = open ? poseFor(open) : { pos: SEAT.pos.clone(), look: SEAT.look.clone() };
    host.dataset.panel = open || "seat";
    const home = open && SUB[open] ? SUB[open][0] : open;
    Object.entries(objs).forEach(([k, P]) => { P.el.classList.toggle("is-open", k === home); P.el.classList.toggle("is-dim", !!open && k !== home); });
    if (reduced()) { target.pos.copy(p.pos); target.look.copy(p.look); cur.pos.copy(p.pos); cur.look.copy(p.look); tween = null; }
    else { tween = { t0: performance.now(), d: 750, fromP: cur.pos.clone(), fromL: cur.look.clone(), toP: p.pos, toL: p.look }; target.pos.copy(p.pos); target.look.copy(p.look); }
    onPanel(open);
  }
  host.addEventListener("pointermove", e => { const r = host.getBoundingClientRect(); pointer.x = (e.clientX - r.left) / r.width - .5; pointer.y = (e.clientY - r.top) / r.height - .5; });
  host.addEventListener("pointerleave", () => { pointer.x = pointer.y = 0; });

  // [0.3.12] the free area: the stage minus a side card that floats over the cabin's right edge (the check ride's lesson
  // card). The cabin's walls run on behind the card; the seat view is centred and fitted in the free area.
  const faces = [];
  Object.values(objs).forEach(P => { P.g.updateMatrixWorld(true); [[-1, -1], [1, -1], [1, 1], [-1, 1]].forEach(([a, b]) => faces.push(P.g.localToWorld(new THREE.Vector3(a * (P.w + 0.12) / 2, b * (P.h + 0.12) / 2, 0)))); });
  function seatSpan(fov) {
    camera.fov = fov; camera.updateProjectionMatrix();
    camera.position.copy(SEAT.pos); camera.lookAt(SEAT.look); camera.updateMatrixWorld(true);
    let x0 = 1e9, x1 = -1e9;
    faces.forEach(v => { const p = v.clone().project(camera), x = (p.x + 1) / 2 * size.w; x0 = Math.min(x0, x); x1 = Math.max(x1, x); });
    return [x0, x1];
  }
  function resize() {
    const w = host.clientWidth, h = host.clientHeight; if (!w || !h) return;
    const inset = Math.max(0, Math.min(w * 0.6, +insetRight() || 0)), fw = w - inset;
    size = { w, h, fw };
    renderer.setSize(w, h, false); renderer.domElement.style.width = w + "px"; renderer.domElement.style.height = h + "px";
    // the DOM panels (CSS3D) render the free area only: CSS3DRenderer's own view-offset maths assumes a sub-view of a
    // bigger image, so it renders with the offset off (the WebGL room runs on behind the card with it on)
    cssR.setSize(fw, h); camera.aspect = fw / h;
    if (inset > 0) camera.setViewOffset(fw, h, 0, 0, w, h); else camera.clearViewOffset();
    // fit the seat view: the window and every panel in the free area on any aspect (wider field of view, never clipped)
    camera.fov = fitFov(fw / h, fw, seatSpan); camera.updateProjectionMatrix();
    if (open) { const p = poseFor(open); target.pos.copy(p.pos); target.look.copy(p.look); if (!tween) { cur.pos.copy(p.pos); cur.look.copy(p.look); } }
  }
  const ro = new ResizeObserver(resize); ro.observe(host); resize();

  // the window's on-screen rectangle (for the glass HUD and the globe viewport)
  const corners = [[-1, -1], [1, -1], [1, 1], [-1, 1]].map(([a, b]) => new THREE.Vector3(W.cx + a * W.w / 2, W.cy + b * W.h / 2, W.z + 0.08));
  function placeHole() {
    if (!hole) return;
    let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
    corners.forEach(c => { const p = c.clone().project(camera), x = (p.x + 1) / 2 * size.w, y = (1 - p.y) / 2 * size.h; x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y); });
    hole.style.left = x0.toFixed(1) + "px"; hole.style.top = y0.toFixed(1) + "px"; hole.style.width = (x1 - x0).toFixed(1) + "px"; hole.style.height = (y1 - y0).toFixed(1) + "px";
    return [x0, y0, x1, y1];
  }
  /** The window views (terrain / globe glass) render into a box just larger than the window, so the horizon sits in
   *  the window. Moved only when the camera comes to rest (a canvas resize per frame would stall). */
  let glassKey = "";
  function fitGlass(r) {
    if (!glass || !r) return; const m = 90, k = r.map(v => Math.round(v / 24)).join(",");
    if (k === glassKey) return; glassKey = k;
    Object.assign(glass.style, { left: (r[0] - m) + "px", top: (r[1] - m) + "px", width: (r[2] - r[0] + 2 * m) + "px", height: (r[3] - r[1] + 2 * m) + "px", right: "auto", bottom: "auto" });
  }

  let raf = 0, last = performance.now(), frames = 0, fpsT = performance.now(), fps = 0, running = true;
  const ease = t => t < .5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
  function frame(now) {
    if (!running) return;
    raf = requestAnimationFrame(frame);
    const dt = Math.min(0.05, (now - last) / 1000); last = now;
    if (tween) {
      const k = Math.min(1, (now - tween.t0) / tween.d), e = ease(k);
      cur.pos.lerpVectors(tween.fromP, tween.toP, e); cur.look.lerpVectors(tween.fromL, tween.toL, e);
      if (k >= 1) tween = null;
    }
    const red = reduced(), bob = red ? 0 : Math.sin(now / 1900) * 0.004;
    const par = red || open ? 0 : 1;
    if (!lookHold && (lookT.x || lookT.y) && now - lookAt > LOOK_IDLE_MS) { lookT.x = 0; lookT.y = 0; }   // input ended: back to the seat
    // time-based, not per frame: a slow frame (a busy machine, a software renderer) must not stretch the spring-back
    const lookDt = Math.min(0.5, Math.max(0, (now - lookLast) / 1000)); lookLast = now;
    const kk = red ? 1 : 1 - Math.exp(-lookDt * 8); lookC.x += (lookT.x - lookC.x) * kk; lookC.y += (lookT.y - lookC.y) * kk;
    if (Math.abs(lookC.x) < 1e-4 && Math.abs(lookC.y) < 1e-4 && !lookT.x && !lookT.y) { lookC.x = 0; lookC.y = 0; }
    camera.position.set(cur.pos.x + pointer.x * 0.07 * par, cur.pos.y + bob - pointer.y * 0.035 * par, cur.pos.z);
    camera.lookAt(cur.look.x + pointer.x * 0.03 * par, cur.look.y - pointer.y * 0.02 * par, cur.look.z);
    if (lookC.x || lookC.y) { camera.rotateY(-lookC.x); camera.rotateX(-lookC.y); }
    renderer.render(scene, camera);
    if (camera.view && camera.view.enabled) { camera.view.enabled = false; cssR.render(cssScene, camera); camera.view.enabled = true; } else cssR.render(cssScene, camera);
    const r = placeHole();
    if (!tween && (open === null)) fitGlass(r);
    frames++; if (now - fpsT > 1000) { fps = Math.round(frames * 1000 / (now - fpsT)); frames = 0; fpsT = now; }
    void dt;
  }
  raf = requestAnimationFrame(frame);

  const api = {
    open: id => go(id), back: () => go(null), alert: on => setAlert(on), get alerting() { return alertOn; }, get panel() { return open; }, get fps() { return fps; }, setQuality, get quality() { return quality; },
    /** Look around from where the camera is: dx, dy in -1..1 (yaw, pitch), clamped to ±MAX_YAW / ±MAX_PITCH. look(0, 0)
     *  recentres; with no new look input for LOOK_IDLE_MS it springs back by itself (opts.hold: the tour's beats). */
    look(dx, dy, { hold = false } = {}) { lookT.x = Math.max(-1, Math.min(1, +dx || 0)) * MAX_YAW; lookT.y = Math.max(-1, Math.min(1, +dy || 0)) * MAX_PITCH;
      lookAt = performance.now(); lookHold = !!hold && !!(lookT.x || lookT.y); },
    /** Center view: the seat pose, now (any panel closes, any look offset goes). */
    recenter() { lookT.x = lookT.y = 0; lookHold = false; if (open) go(null); },
    /** The camera as the tests see it: the look offset (rad), the open panel, a dolly in flight. */
    get fov() { return camera.fov; },
    /** Each console's top edge on screen from the current camera, in degrees off horizontal (the tests: text never
     *  reads slanted; [0.3.12] the ride's low Rover console read about 15°). */
    get slant() { camera.updateMatrixWorld(true); const out = {};
      Object.entries(objs).forEach(([id, P]) => { const a = P.g.localToWorld(new THREE.Vector3(-P.w / 2, P.h / 2, 0)).project(camera), b = P.g.localToWorld(new THREE.Vector3(P.w / 2, P.h / 2, 0)).project(camera);
        out[id] = +(Math.atan2((b.y - a.y) * size.h, (b.x - a.x) * size.w) * 180 / Math.PI).toFixed(1); });
      return out; },
    /** [0.4 cabin 2] Each console's text lean from the current camera (rows off horizontal, columns off vertical), in
     *  degrees: tools/mission_ui.py fails the seat view over MAX_SKEW. */
    get skew() { camera.updateMatrixWorld(true); const out = {}, P = v => { const p = v.project(camera); return [(p.x + 1) / 2 * size.w, (1 - p.y) / 2 * size.h]; };
      const ang = (a, b) => Math.atan2(-(b[1] - a[1]), b[0] - a[0]) * 180 / Math.PI;
      Object.entries(objs).forEach(([id, Q]) => { const at = (x, y) => P(Q.g.localToWorld(new THREE.Vector3(x, y, 0))); let worst = 0;
        [-0.45, 0, 0.45].forEach(f => { worst = Math.max(worst, Math.abs(ang(at(-Q.w / 2, f * Q.h), at(Q.w / 2, f * Q.h))), Math.abs(90 - Math.abs(ang(at(f * Q.w, -Q.h / 2), at(f * Q.w, Q.h / 2))))); });
        out[id] = +worst.toFixed(1); });
      return out; },
    /** The seat view's faces in px (the tests: every panel inside the free area). */
    get seatSpan() { const f = camera.fov, r = seatSpan(f); return { x0: r[0], x1: r[1], w: size.w, fw: size.fw, fov: f }; },
    get pose() { return { yaw: lookC.x, pitch: lookC.y, targetYaw: lookT.x, targetPitch: lookT.y, panel: open, moving: !!tween, maxYaw: MAX_YAW, maxPitch: MAX_PITCH }; },
    /** Mark a panel as the one a lean-in would open (null clears). */
    highlight(id) { hl = id || null; Object.entries(objs).forEach(([k, P]) => P.el.classList.toggle("is-hl", k === hl)); },
    get highlighted() { return hl; },
    resize, dispose() {
      running = false; cancelAnimationFrame(raf); ro.disconnect();
      // [qa] free the GPU side too: geometries, materials, their textures, the environment map and the context itself
      scene.traverse(o => { if (o.geometry) o.geometry.dispose(); [].concat(o.material || []).forEach(m => { Object.values(m).forEach(v => { if (v && v.isTexture) v.dispose(); }); m.dispose(); }); });
      envTex.dispose(); pmrem.dispose(); renderer.dispose(); renderer.forceContextLoss();
      renderer.domElement.remove(); cssR.domElement.remove(); delete host.__c3;
    },
  };
  host.__c3 = api;   // the layout checks read the seat view's fit and slant from the .c3 element
  return api;
}
