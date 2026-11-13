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

  scene.add(new THREE.AmbientLight(0xffffff, 0.35 * Math.PI));
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
    sun.position.copy(ll2v(f.lat + 15, f.lon - 40).multiplyScalar(5));
  }

  function resize() { const w = stage.clientWidth, h = stage.clientHeight; renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix(); }
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
    renderer.render(scene, camera); requestAnimationFrame(tick);
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
    showFeature, highlight, flyTo, nearest,
    togglePins() { pins.visible = !pins.visible; return pins.visible; },
    toggleHardware() { const on = layer.style.display === "none"; layer.style.display = on ? "" : "none"; return on; },
    get hardwareOn() { return layer.style.display !== "none"; },
  };
}
