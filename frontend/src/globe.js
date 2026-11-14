// The three.js Moon: LRO color map, place pins, ghost-hardware markers (HTML over the canvas), highlight ring, fly-to, tap-to-pick.
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";

const R = 1, MOON_KM = 1737.4;

const ll2v = (lat, lon, r = R) => {
  const phi = (90 - lat) * Math.PI / 180, th = (lon + 180) * Math.PI / 180;
  return new THREE.Vector3(-r * Math.sin(phi) * Math.cos(th), r * Math.cos(phi), r * Math.sin(phi) * Math.sin(th));
};
const v2ll = v => {
  const n = v.clone().normalize(); const lat = Math.asin(n.y) * 180 / Math.PI;
  let lon = Math.atan2(n.z, -n.x) * 180 / Math.PI - 180; if (lon < -180) lon += 360;
  return { lat, lon };
};
/** Angular distance in degrees between two {lat, lon}. */
export const angDist = (a, b) => Math.acos(Math.min(1, ll2v(a.lat, a.lon).normalize().dot(ll2v(b.lat, b.lon).normalize()))) * 180 / Math.PI;
/** A feature's angular radius in degrees. */
export const angRadius = f => (f.km / 2) / MOON_KM * 180 / Math.PI;

export function createGlobe({ stage, label, loading, places, onTap, onArtifact = () => {} }) {
  const features = places.filter(f => f.kind !== "artifact"), artifacts = places.filter(f => f.kind === "artifact");
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  stage.prepend(renderer.domElement);
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(38, 1, 0.01, 100);
  camera.position.set(0, 0, 3.6);
  const controls = new OrbitControls(camera, renderer.domElement);
  Object.assign(controls, { enablePan: false, minDistance: 1.5, maxDistance: 6, enableDamping: true, rotateSpeed: 0.6 });

  const ambient = new THREE.AmbientLight(0xffffff, 0.35 * Math.PI); scene.add(ambient);
  const sun = new THREE.DirectionalLight(0xfff4e0, 1.15 * Math.PI); scene.add(sun);
  sun.position.copy(ll2v(10, -40).multiplyScalar(5));

  const tex = new THREE.TextureLoader().load("/media/img/moon4k.jpg", () => loading.remove(), undefined,
    () => { loading.textContent = "Couldn't load the Moon map."; });
  tex.colorSpace = THREE.SRGBColorSpace; tex.anisotropy = renderer.capabilities.getMaxAnisotropy();
  const moon = new THREE.Mesh(new THREE.SphereGeometry(R, 128, 96), new THREE.MeshStandardMaterial({ map: tex, roughness: 1, metalness: 0 }));
  scene.add(moon);

  { // stars
    const g = new THREE.BufferGeometry(), n = 1400, p = new Float32Array(n * 3);
    for (let i = 0; i < n; i++) { const v = new THREE.Vector3().randomDirection().multiplyScalar(30 + Math.random() * 20); p.set([v.x, v.y, v.z], i * 3); }
    g.setAttribute("position", new THREE.BufferAttribute(p, 3));
    scene.add(new THREE.Points(g, new THREE.PointsMaterial({ color: 0xc8d0ff, size: 0.08, sizeAttenuation: true, transparent: true, opacity: .7 })));
  }

  const pins = new THREE.Group(); scene.add(pins);
  const pinMat = new THREE.MeshBasicMaterial({ color: 0xffc35a }), pinEst = new THREE.MeshBasicMaterial({ color: 0x7cc7ff });
  features.forEach(f => { const m = new THREE.Mesh(new THREE.SphereGeometry(0.009, 10, 8), f.est ? pinEst : pinMat); m.position.copy(ll2v(f.lat, f.lon, R * 1.002)); pins.add(m); });

  // Ghost hardware: one small glowing diamond per artifact, coloured by hardware kind. HTML so it can be focused,
  // hovered (name + year tooltip) and tapped; positioned every frame and hidden when it is round the back.
  const layer = document.createElement("div"); layer.className = "ghosts"; stage.append(layer);
  const ghosts = artifacts.map(a => {
    const el = document.createElement("button"); el.type = "button";
    el.className = "ghost k-" + (a.hw || "lander");
    const yr = (a.landed || "").slice(0, 4);
    const tip = document.createElement("span"); tip.className = "tip"; tip.setAttribute("aria-hidden", "true");
    tip.textContent = a.name + (yr ? " · " + yr : ""); el.append(tip);
    el.setAttribute("aria-label", `${a.name}${yr ? ", " + yr : ""}. Hear its story`);
    el.onclick = e => { e.stopPropagation(); onArtifact(a); };
    layer.append(el);
    return { a, el, p: ll2v(a.lat, a.lon, R * 1.003) };
  });

  const ringMat = new THREE.MeshBasicMaterial({ color: 0xffc35a, side: THREE.DoubleSide, transparent: true, opacity: .95 });
  let ring = null, sel = null, fly = null;

  function highlight(f) {
    if (ring) { scene.remove(ring); ring.geometry.dispose(); }
    const ang = Math.max((f.km / 2) / MOON_KM, 0.035), r = Math.sin(ang), h = Math.cos(ang);
    ring = new THREE.Mesh(new THREE.RingGeometry(r * (f.kind === "artifact" ? 0.8 : 0.92), r, 96), ringMat);
    const n = ll2v(f.lat, f.lon).normalize();
    ring.position.copy(n.clone().multiplyScalar(h * R + 0.004)); ring.lookAt(n.clone().multiplyScalar(5));
    scene.add(ring); sel = f;
    ghosts.forEach(g => g.el.classList.toggle("is-on", g.a === f));
    label.textContent = f.name;
    if (f.est) { const s = document.createElement("small"); s.textContent = "est."; label.append(s); }
    label.hidden = false;
  }

  function flyTo(lat, lon, dist) {
    const d = ll2v(Math.max(-75, Math.min(75, lat)), lon).normalize();
    const from = camera.position.clone(), r0 = from.length();
    fly = { fd: from.clone().normalize(), td: d, r0, r1: dist || Math.min(Math.max(r0, 2.4), 3.2), t0: performance.now(), dur: 1300 };
  }

  function showFeature(f, { dist } = {}) {
    highlight(f); flyTo(f.lat, f.lon, dist || (f.kind === "artifact" ? 2.3 : f.km > 800 ? 3.2 : 2.5));
    if (!mi.on) sun.position.copy(ll2v(f.lat + 15, f.lon - 40).multiplyScalar(5));
  }

  // ---------- Mission layer: outpost, Sun-driven day/night shading, Earth's direction, rover path ----------
  const mi = { on: false, site: null, group: new THREE.Group(), marks: [], earth: null, earthLine: null, rover: null, roverDot: null, path: null };
  scene.add(mi.group); mi.group.visible = false;
  const mlayer = document.createElement("div"); mlayer.className = "mmarks"; stage.append(mlayer); mlayer.hidden = true;
  function mark(cls, text) { const el = document.createElement("div"); el.className = "mmark " + cls; el.textContent = text; mlayer.append(el); const m = { el, p: new THREE.Vector3() }; mi.marks.push(m); return m; }
  const outpostMark = mark("is-outpost", "Outpost"), earthMark = mark("is-earth", "Earth"), roverMark = mark("is-rover", "Rover");
  /** Local frame at the site: up (normal), toward-Earth-side tangent, and the tangent 90° from it. */
  function frame(site) {
    const n = ll2v(site.lat, site.lon).normalize(), e0 = ll2v(0, 0).normalize();
    let t = e0.clone().sub(n.clone().multiplyScalar(n.dot(e0))); if (t.lengthSq() < 1e-6) t = new THREE.Vector3(1, 0, 0); t.normalize();
    return { n, t, b: new THREE.Vector3().crossVectors(n, t).normalize() };
  }
  const dirAt = (f, elevDeg, azDeg) => {   // az 0 = toward the Earth-facing side
    const e = elevDeg * Math.PI / 180, a = azDeg * Math.PI / 180;
    return f.t.clone().multiplyScalar(Math.cos(a)).add(f.b.clone().multiplyScalar(Math.sin(a))).multiplyScalar(Math.cos(e)).add(f.n.clone().multiplyScalar(Math.sin(e))).normalize();
  };
  const earthMat = new THREE.MeshBasicMaterial({ color: 0x6fa3db });
  mi.earth = new THREE.Mesh(new THREE.SphereGeometry(0.018, 16, 12), earthMat); mi.group.add(mi.earth);
  mi.earthLine = new THREE.Line(new THREE.BufferGeometry(), new THREE.LineDashedMaterial({ color: 0x6fa3db, dashSize: 0.012, gapSize: 0.008, transparent: true, opacity: .9 }));
  mi.group.add(mi.earthLine);
  mi.path = new THREE.Line(new THREE.BufferGeometry(), new THREE.LineBasicMaterial({ color: 0x4fc08a, transparent: true, opacity: .95 }));
  mi.group.add(mi.path);
  const outpostDot = new THREE.Mesh(new THREE.SphereGeometry(0.006, 12, 8), new THREE.MeshBasicMaterial({ color: 0xefc463 })); mi.group.add(outpostDot);
  let arc = [];
  // The real Earth in the sky (NASA Blue Marble, bundled in /terrain/earth.jpg), on its true line of sight from the Moon:
  // at 60 Moon radii with a 1-radius sphere it has its true angular size (1.9°), and the sim's Sun lights its phase.
  const earthTex = new THREE.TextureLoader().load("/terrain/earth.jpg"); earthTex.colorSpace = THREE.SRGBColorSpace;
  const farEarth = new THREE.Mesh(new THREE.SphereGeometry(1, 48, 24), new THREE.MeshStandardMaterial({ map: earthTex, roughness: .7, emissive: 0x0a1630, emissiveIntensity: .3 }));
  farEarth.rotation.y = 2.2; mi.group.add(farEarth);
  const glareTex = (() => { const c = document.createElement("canvas"); c.width = c.height = 128; const g = c.getContext("2d"), r = g.createRadialGradient(64, 64, 0, 64, 64, 64);
    r.addColorStop(0, "rgba(255,250,235,1)"); r.addColorStop(.12, "rgba(255,244,215,.85)"); r.addColorStop(.35, "rgba(255,230,190,.18)"); r.addColorStop(1, "rgba(255,220,180,0)");
    g.fillStyle = r; g.fillRect(0, 0, 128, 128); const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t; })();
  const sunGlare = new THREE.Sprite(new THREE.SpriteMaterial({ map: glareTex, blending: THREE.AdditiveBlending, depthWrite: false, transparent: true }));
  sunGlare.scale.setScalar(9); mi.group.add(sunGlare);
  /** Sub-Earth point on the equator side (lon 0) whose elevation seen from the site is `el` degrees. */
  const earthLat = el => { const n = ll2v(mi.site.lat, mi.site.lon).normalize(), s = Math.sin(el * Math.PI / 180); let lo = -15, hi = 15;
    for (let i = 0; i < 30; i++) { const m = (lo + hi) / 2; if (n.dot(ll2v(m, 0).normalize()) > s) lo = m; else hi = m; } return (lo + hi) / 2; };

  const mission = {
    enter() { mi.on = true; mi.group.visible = true; mlayer.hidden = false; ambient.intensity = 0.07 * Math.PI; pins.visible = false; layer.style.display = "none"; },
    exit() { mi.on = false; mi.group.visible = false; mlayer.hidden = true; ambient.intensity = 0.35 * Math.PI; pins.visible = true; layer.style.display = "";
      if (ring) { scene.remove(ring); ring = null; } sel = null; label.hidden = true; },
    /** Preview or place the outpost; flies there (south-pole sites are seen from 75°S, the camera's limit). */
    setSite(site, { dist = 1.75 } = {}) {
      mi.site = site; mi.f = frame(site);
      const p = ll2v(site.lat, site.lon, R * 1.004); outpostDot.position.copy(p); outpostMark.p.copy(p); outpostMark.el.textContent = site.short || "Outpost";
      flyTo(site.lat, site.lon, dist); label.hidden = true; sel = null; if (ring) { scene.remove(ring); ring = null; }
    },
    /** Day/night: aim the Sun so it stands sunElev degrees above the outpost's horizon, circling once per lunar day. */
    setSun(sunElevDeg, timeH = 0) { if (!mi.f) return; const d = dirAt(mi.f, sunElevDeg, 140 + timeH * 360 / 708.7); sun.position.copy(d).multiplyScalar(5); sunGlare.position.copy(d).multiplyScalar(80); },
    /** Earth's direction from the outpost: a dashed pointer, solid blue when Earth is above the horizon. */
    setEarth(earthElevDeg) {
      if (!mi.f) return;
      const p0 = ll2v(mi.site.lat, mi.site.lon, R * 1.004), d = dirAt(mi.f, earthElevDeg, 0), p1 = p0.clone().add(d.multiplyScalar(0.32));
      mi.earth.position.copy(p1); earthMark.p.copy(p1);
      mi.earthLine.geometry.setFromPoints([p0, p1]); mi.earthLine.computeLineDistances();
      const up = earthElevDeg > 0; mi.earthLine.material.opacity = up ? .95 : .35; earthMat.color.set(up ? 0x6fa3db : 0x51607a);
      earthMark.el.textContent = up ? `Earth ↑ ${earthElevDeg.toFixed(1)}°` : "Earth below horizon"; earthMark.el.classList.toggle("is-down", !up);
      farEarth.position.copy(ll2v(earthLat(earthElevDeg), 0).normalize().multiplyScalar(60));
    },
    /** Rover path to a target {lat, lon}; progress 0..1 moves the rover dot. null clears it. */
    setRover(target, progress = 0) {
      if (!target || !mi.site) { mi.path.visible = false; roverMark.el.hidden = true; arc = []; return; }
      const a = ll2v(mi.site.lat, mi.site.lon).normalize(), b = ll2v(target.lat, target.lon).normalize();
      arc = []; for (let i = 0; i <= 32; i++) arc.push(a.clone().lerp(b, i / 32).normalize().multiplyScalar(R * 1.004));
      mi.path.geometry.setFromPoints(arc); mi.path.visible = true;
      const k = Math.max(0, Math.min(1, progress)), at = arc[Math.round(k * 32)]; roverMark.p.copy(at); roverMark.el.hidden = false;
    },
  };
  function tickMission() {
    if (!mi.on) return;
    const w = stage.clientWidth, h = stage.clientHeight;
    mi.marks.forEach(m => {
      if (m.el.hidden || !mi.site) { m.el.style.visibility = "hidden"; return; }
      const facing = m.p.clone().normalize().dot(camera.position.clone().normalize()) > 0.05;
      m.el.style.visibility = facing ? "" : "hidden"; if (!facing) return;
      tmp.copy(m.p).project(camera);
      m.el.style.transform = `translate(${((tmp.x + 1) / 2 * w).toFixed(1)}px,${((1 - tmp.y) / 2 * h).toFixed(1)}px)`;
    });
  }

  // Viewport band: in the Mission cabin the Moon is seen through a window at the top of the stage, so the camera's
  // view is shifted (setViewOffset) to centre the globe in that band. null = the whole stage, as before.
  let band = null, paused = false;
  function resize() {
    const w = stage.clientWidth, h = stage.clientHeight; renderer.setSize(w, h, false); camera.aspect = w / h;
    if (band) { const hb = h * band; camera.setViewOffset(w, h, 0, (h - hb) / 2, w, h); } else camera.clearViewOffset();
    camera.updateProjectionMatrix();
  }
  function setViewport(frac) { band = frac || null; resize(); }
  new ResizeObserver(resize).observe(stage); resize();

  const tmp = new THREE.Vector3();
  function tick(now) {
    if (fly) {
      const t = Math.min(1, (now - fly.t0) / fly.dur), e = t < .5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
      const a = fly.fd, b = fly.td; let dir;
      if (a.dot(b) < -0.98) { const mid = new THREE.Vector3(0, 1, 0).cross(a).normalize(); dir = e < .5 ? a.clone().lerp(mid, e * 2) : mid.clone().lerp(b, (e - .5) * 2); }
      else dir = a.clone().lerp(b, e);
      camera.position.copy(dir.normalize().multiplyScalar(fly.r0 + (fly.r1 - fly.r0) * e)); camera.lookAt(0, 0, 0);
      if (t >= 1) fly = null;
    }
    controls.update();
    if (ring) ring.material.opacity = .65 + .3 * Math.sin(now / 300);
    if (layer.style.display !== "none") {
      const w = stage.clientWidth, h = stage.clientHeight;
      ghosts.forEach(g => {
        // visible only in front of the horizon (n·C > R), with a small margin so markers don't sit on the limb
        const facing = g.p.dot(camera.position) / g.p.length() > R * 1.06;
        g.el.classList.toggle("is-hidden", !facing);
        if (!facing) return;
        tmp.copy(g.p).project(camera);
        g.el.style.transform = `translate(${((tmp.x + 1) / 2 * w).toFixed(1)}px,${((1 - tmp.y) / 2 * h).toFixed(1)}px)`;
      });
    }
    if (sel) {
      const p = ll2v(sel.lat, sel.lon, R * 1.01), facing = p.clone().normalize().dot(camera.position.clone().normalize()) > 0.15;
      tmp.copy(p).project(camera);
      label.style.left = ((tmp.x + 1) / 2 * stage.clientWidth) + "px"; label.style.top = ((1 - tmp.y) / 2 * stage.clientHeight) + "px";
      label.style.opacity = facing ? 1 : 0;
    }
    tickMission();
    if (!paused) renderer.render(scene, camera); requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);

  /** Nearest named place to a point, scored by distance minus a share of its radius. */
  function nearest(p) {
    let best = null, bd = 1e9;
    features.forEach(f => { const d = angDist(p, f) - angRadius(f) * 0.6; if (d < bd) { bd = d; best = f; } });
    return { f: best, d: bd };
  }

  // tap (not drag) → lat/lon on the Moon
  const ray = new THREE.Raycaster(), ndc = new THREE.Vector2(); let down = null;
  renderer.domElement.addEventListener("pointerdown", e => { down = [e.clientX, e.clientY]; });
  renderer.domElement.addEventListener("pointerup", e => {
    if (!down) return; const moved = Math.hypot(e.clientX - down[0], e.clientY - down[1]); down = null; if (moved > 6) return;
    const r = renderer.domElement.getBoundingClientRect();
    ndc.set((e.clientX - r.left) / r.width * 2 - 1, -(e.clientY - r.top) / r.height * 2 + 1);
    ray.setFromCamera(ndc, camera); const hit = ray.intersectObject(moon)[0];
    if (hit) onTap(v2ll(hit.point));
  });

  return {
    showFeature, highlight, flyTo, nearest, mission, setViewport,
    /** Screen position (px in the stage) of a surface point, and whether it faces the camera. Used by the site pins. */
    project(lat, lon) { const p = ll2v(lat, lon, R * 1.004), v = p.clone().project(camera);
      return { x: (v.x + 1) / 2 * stage.clientWidth, y: (1 - v.y) / 2 * stage.clientHeight, facing: p.clone().normalize().dot(camera.position.clone().normalize()) > 0.05 }; },
    /** Stop drawing (the cabin window covers the globe with a surface view); the camera keeps flying. */
    pause(on) { paused = !!on; renderer.domElement.style.visibility = on ? "hidden" : ""; },
    togglePins() { pins.visible = !pins.visible; return pins.visible; },
    toggleHardware() { const on = layer.style.display === "none"; layer.style.display = on ? "" : "none"; return on; },
    get hardwareOn() { return layer.style.display !== "none"; },
  };
}
