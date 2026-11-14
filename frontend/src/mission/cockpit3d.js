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

/** Panel placement in metres. px = the DOM panel's CSS width; the scale maps it onto `w` metres of console face. */
const LAYOUT = {
  window: { cx: 0, cy: 1.66, w: 2.3, h: 0.98, r: 0.16, z: -1.7 },
  power: { pos: [0, 0.98, -1.5], rot: [-0.42, 0, 0], w: 2.0, px: 1200, pxh: 330 },
  habitat: { pos: [-1.22, 0.92, -1.18], rot: [-0.34, 0.6, 0], w: 0.86, px: 640, pxh: 470 },
  comm: { pos: [1.22, 0.92, -1.18], rot: [-0.34, -0.6, 0], w: 0.86, px: 640, pxh: 470 },
};
const SEAT = { pos: new THREE.Vector3(0, 1.32, 0.78), look: new THREE.Vector3(0, 1.2, -1.6) };
const STRIP_PX = 84;   // the comm strip under the cabin (captions + voice), kept clear when a panel is open
export const PANELS = [["power", "Power displays"], ["habitat", "Habitat panel"], ["comm", "Comm panel"]];

const css = (el, name, fb) => (getComputedStyle(el).getPropertyValue(name).trim() || fb);

export function createCockpit3D(host, { panels, hole, glass = null, reduced = () => false, onPanel = () => {} } = {}) {
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
  scene.environment = pmrem.fromScene(new RoomEnvironment(renderer), 0.04).texture;

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
  // ceiling light strip + hand rails over the window (Orion-style grab bars)
  const strip = new THREE.Mesh(new THREE.BoxGeometry(1.6, 0.02, 0.08), new THREE.MeshStandardMaterial({ color: 0xffffff, emissive: col("--color-on-space"), emissiveIntensity: 0.6 }));
  strip.position.set(0, 2.42, -0.6); scene.add(strip);
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
    if (id === "power") { const ped = new THREE.Mesh(new RoundedBoxGeometry(L.w * 0.7, 1.0, 0.5, 3, 0.04), metal); ped.position.set(0, -0.6, -0.42); g.add(ped); }
    const o = new CSS3DObject(el); o.position.copy(g.position); o.rotation.copy(g.rotation); o.scale.setScalar(s);
    o.position.add(new THREE.Vector3(0, 0, 0.004).applyEuler(g.rotation));
    cssScene.add(o); objs[id] = { o, g, w: L.w, h, el };
    // panel glow onto the room
    const glow = new THREE.PointLight(col("--color-phosphor"), 0.35, 1.6, 2); glow.position.set(0, 0, 0.35); g.add(glow);
  });

  // ---------- light: the window is the key light; the room is dim ----------
  scene.add(new THREE.HemisphereLight(0xb9c6d8, 0x101216, 0.35));
  const win = new THREE.RectAreaLight(0xe8eef8, 4.2, W.w, W.h); win.position.set(W.cx, W.cy, W.z); win.lookAt(W.cx, W.cy - 0.6, 1); scene.add(win);
  const fill = new THREE.PointLight(0xc8d4e6, 0.8, 5, 2); fill.position.set(0, 2.3, 0.2); scene.add(fill);

  // ---------- camera: seat, parallax, dolly ----------
  let open = null, tween = null, pointer = { x: 0, y: 0 }, size = { w: 1, h: 1 };
  const target = { pos: SEAT.pos.clone(), look: SEAT.look.clone() };
  const cur = { pos: SEAT.pos.clone(), look: SEAT.look.clone() };
  function poseFor(id) {
    const P = objs[id]; if (!P) return { pos: SEAT.pos.clone(), look: SEAT.look.clone() };
    const n = new THREE.Vector3(0, 0, 1).applyEuler(P.g.rotation), c = P.g.position.clone();
    const L = LAYOUT[id], vfov = camera.fov * Math.PI / 180, tv = Math.tan(vfov / 2), th = tv * camera.aspect;
    // On-screen size: about 1.15× the panel's CSS pixels (crisp text), never wider than 86% of the stage or taller than
    // the space above the comm strip.
    const free = size.h - STRIP_PX, tw = Math.min(L.px * 1.15, size.w * 0.86), thh = Math.min(L.pxh * 1.15, free * 0.9);
    const d = Math.max(P.w * size.w / (2 * th * tw), P.h * size.h / (2 * tv * thh));
    // centre the panel in the space above the comm strip: aim a little below it
    const up = new THREE.Vector3(0, 1, 0).applyEuler(P.g.rotation), shift = (STRIP_PX / 2) * (2 * d * tv / size.h);
    const look = c.clone().addScaledVector(up, -shift);
    return { pos: look.clone().addScaledVector(n, d), look };
  }
  function go(id) {
    open = id || null; const p = open ? poseFor(open) : { pos: SEAT.pos.clone(), look: SEAT.look.clone() };
    host.dataset.panel = open || "seat";
    Object.entries(objs).forEach(([k, P]) => { P.el.classList.toggle("is-open", k === open); P.el.classList.toggle("is-dim", !!open && k !== open); });
    if (reduced()) { target.pos.copy(p.pos); target.look.copy(p.look); cur.pos.copy(p.pos); cur.look.copy(p.look); tween = null; }
    else { tween = { t0: performance.now(), d: 750, fromP: cur.pos.clone(), fromL: cur.look.clone(), toP: p.pos, toL: p.look }; target.pos.copy(p.pos); target.look.copy(p.look); }
    onPanel(open);
  }
  host.addEventListener("pointermove", e => { const r = host.getBoundingClientRect(); pointer.x = (e.clientX - r.left) / r.width - .5; pointer.y = (e.clientY - r.top) / r.height - .5; });
  host.addEventListener("pointerleave", () => { pointer.x = pointer.y = 0; });

  function resize() {
    const w = host.clientWidth, h = host.clientHeight; if (!w || !h) return; size = { w, h };
    renderer.setSize(w, h, false); renderer.domElement.style.width = w + "px"; renderer.domElement.style.height = h + "px";
    cssR.setSize(w, h); camera.aspect = w / h;
    // fit the seat view: the window and all three panels in frame on any aspect
    camera.fov = w / h < 1.5 ? 66 : w / h < 1.75 ? 60 : 56; camera.updateProjectionMatrix();
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
    camera.position.set(cur.pos.x + pointer.x * 0.07 * par, cur.pos.y + bob - pointer.y * 0.035 * par, cur.pos.z);
    camera.lookAt(cur.look.x + pointer.x * 0.03 * par, cur.look.y - pointer.y * 0.02 * par, cur.look.z);
    renderer.render(scene, camera); cssR.render(cssScene, camera); const r = placeHole();
    if (!tween && (open === null)) fitGlass(r);
    frames++; if (now - fpsT > 1000) { fps = Math.round(frames * 1000 / (now - fpsT)); frames = 0; fpsT = now; }
    void dt;
  }
  raf = requestAnimationFrame(frame);

  return {
    open: id => go(id), back: () => go(null), get panel() { return open; }, get fps() { return fps; },
    resize, dispose() { running = false; cancelAnimationFrame(raf); ro.disconnect(); renderer.dispose(); pmrem.dispose(); renderer.domElement.remove(); cssR.domElement.remove(); },
  };
}
