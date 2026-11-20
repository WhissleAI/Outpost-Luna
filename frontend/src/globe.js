// The three.js Moon: LRO color map, place pins, ghost-hardware markers (HTML over the canvas), highlight ring, fly-to, tap-to-pick.
// [courses] createGlobe's optional `body` ({map, km, name}) swaps the sphere's map and size for another course's globe
// (docs/COURSES.md §4.3); left out, it is the Moon exactly as before (MOON_BODY).
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";

const R = 1, MOON_KM = 1737.4;
/** The globe's body when a course names none: the Moon, its LRO colour map and its radius (docs/COURSES.md §4.3). */
export const MOON_BODY = Object.freeze({ name: "Moon", map: "/media/img/moon4k.jpg", km: MOON_KM });
/** A course's globe body ({map, km, name}), filled from the Moon for anything left out. Pure (tested). */
export function globeBody(b) {
  if (!b || typeof b !== "object") return MOON_BODY;
  const km = Number(b.km) > 0 ? Number(b.km) : MOON_KM;
  return { name: typeof b.name === "string" && b.name ? b.name : (km === MOON_KM ? MOON_BODY.name : "Globe"),
           map: typeof b.map === "string" && b.map ? b.map : MOON_BODY.map, km };
}

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
/**
 * The camera distance that frames a place: its diameter fills about a third of the view (38° field), clamped so a small
 * crater is never closer than 2.2 and a sea never farther than 3.4 (the default view is 3.6). Hardware markers: 2.3.
 */
export function frameDistance(f, bodyKm = MOON_KM) {
  if (!f) return 2.5;
  if (f.kind === "artifact") return 2.3;
  const diam = (f.km || 0) / bodyKm;   // radians across (the body's radius: the Moon's unless a course names another)
  return Math.max(2.2, Math.min(3.4, 1.9 + diam * 2.2));
}
/** A feature's angular radius in degrees. */
export const angRadius = (f, bodyKm = MOON_KM) => (f.km / 2) / bodyKm * 180 / Math.PI;

export function createGlobe({ stage, label, loading, places, onTap, onArtifact = () => {}, onMiss = () => {}, body }) {
  const BODY = globeBody(body), BODY_KM = BODY.km;
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

  const tex = new THREE.TextureLoader().load(BODY.map, () => loading.remove(), undefined,
    () => { loading.textContent = `Couldn't load the ${BODY.name} map.`; });
  tex.colorSpace = THREE.SRGBColorSpace; tex.anisotropy = renderer.capabilities.getMaxAnisotropy();
  const moon = new THREE.Mesh(new THREE.SphereGeometry(R, 128, 96), new THREE.MeshStandardMaterial({ map: tex, roughness: 1, metalness: 0 }));
  scene.add(moon);

  // stars: 1,400 random points until the real sky (the nasa_views pack's NASA SVS Deep Star Maps) is in (setSky)
  const starPts = (() => {
    const g = new THREE.BufferGeometry(), n = 1400, p = new Float32Array(n * 3);
    for (let i = 0; i < n; i++) { const v = new THREE.Vector3().randomDirection().multiplyScalar(30 + Math.random() * 20); p.set([v.x, v.y, v.z], i * 3); }
    g.setAttribute("position", new THREE.BufferAttribute(p, 3));
    const pts = new THREE.Points(g, new THREE.PointsMaterial({ color: 0xc8d0ff, size: 0.08, sizeAttenuation: true, transparent: true, opacity: .7 }));
    scene.add(pts); return pts;
  })();

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

  const ringMat = new THREE.MeshBasicMaterial({ color: 0xf3f5f8, side: THREE.DoubleSide, transparent: true, opacity: .8 });
  let ring = null, sel = null, fly = null;

  function highlight(f) {
    if (ring) { scene.remove(ring); ring.geometry.dispose(); }
    const ang = Math.max((f.km / 2) / BODY_KM, 0.035), r = Math.sin(ang), h = Math.cos(ang);
    ring = new THREE.Mesh(new THREE.RingGeometry(r * (f.kind === "artifact" ? 0.86 : 0.965), r, 96), ringMat);
    const n = ll2v(f.lat, f.lon).normalize();
    ring.position.copy(n.clone().multiplyScalar(h * R + 0.004)); ring.lookAt(n.clone().multiplyScalar(5));
    scene.add(ring); sel = f;
    ghosts.forEach(g => g.el.classList.toggle("is-on", g.a === f));
    label.textContent = f.name;
    if (f.est) { const s = document.createElement("small"); s.textContent = "est."; label.append(s); }
    label.hidden = false;
  }

  // 4th arg: maxLat (number; how close to a pole the camera may look, the map's polar view uses 88) or
  // [learning-v3] {clamp:false} (= 89, the pole views of the globe steps)
  const lessMotion = () => document.documentElement.dataset.motion === "reduce";   // a11y.js sets it (Settings or the OS)
  function flyTo(lat, lon, dist, opt = 75) {
    const maxLat = typeof opt === "number" ? opt : opt && opt.clamp === false ? 89 : 75;
    const d = ll2v(Math.max(-maxLat, Math.min(maxLat, lat)), lon).normalize();
    const from = camera.position.clone(), r0 = from.length();
    // [qa] Settings → Less motion (or the OS setting): cut straight to the view, no flight
    endFly();
    fly = { fd: from.clone().normalize(), td: d, r0, r1: dist || Math.min(Math.max(r0, 2.4), 3.2), t0: performance.now(), dur: lessMotion() ? 1 : 1300 };
    // resolves when the camera is there (or the flight was cut short: a drag, a spin, another flight); never hangs
    return new Promise(res => { const f = fly; f.done = res; setTimeout(() => { if (fly === f) { endFly(); } else res(); }, f.dur + 600); });
  }
  /** End the current flight (it lands where it is) and settle its promise. */
  function endFly() { const f = fly; fly = null; if (f && f.done) f.done(); }

  // selecting a place eases the zoom to frame it (the flight eases the distance with the turn): small craters come
  // closer, the big seas fit the view, whatever the kid zoomed to before (frameDistance)
  function showFeature(f, { dist } = {}) {
    highlight(f); flyTo(f.lat, f.lon, dist || frameDistance(f, BODY_KM));
    if (!mi.on && !sunLock) sun.position.copy(ll2v(f.lat + 15, f.lon - 40).multiplyScalar(5));
  }
  // ---------- Flight School globe verbs (docs/LEARNING_DESIGN.md §3) ----------
  let sunLock = false;
  /** Light the Moon from a sub-solar point (lat, lon): the day/night line is the real terminator. null = default light. */
  function setSunDir(lat, lon) {
    // the night side must read as night for a terminator step: dim the fill light while the Sun is locked
    if (lat == null) { sunLock = false; sun.position.copy(ll2v(10, -40).multiplyScalar(5)); if (!mi.on) ambient.intensity = 0.35 * Math.PI; return; }
    // [novice playtest 2] night reads as night: almost no fill light, so the edge is plain on any GPU (and SwiftShader)
    sunLock = true; sun.position.copy(ll2v(lat, lon).multiplyScalar(5)); ambient.intensity = 0.012 * Math.PI;
  }
  /** Look straight down on a pole (flyTo stops at 75°; the south-pole lessons need the view from above). */
  function poleView(pole = "south", dist = 2.2) { flyTo(pole === "north" ? 88 : -88, 0, dist, { clamp: false }); }
  /** Where the camera looks: the lat/lon at the centre of the view (graded by globe_side). */
  function centerLatLon() { return v2ll(camera.position); }

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
    setSite(site, { dist = 1.75, clamp } = {}) {
      mi.site = site; mi.f = frame(site);
      const p = ll2v(site.lat, site.lon, R * 1.004); outpostDot.position.copy(p); outpostMark.p.copy(p); outpostMark.el.textContent = site.short || "Outpost";
      // [0.4] {clamp: false}: the Mission picker looks straight down on the pole (docs/MEDIA.md), not from 75°S
      flyTo(site.lat, site.lon, dist, clamp === false ? { clamp: false } : undefined); label.hidden = true; sel = null; if (ring) { scene.remove(ring); ring = null; }
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

  // ---------- Route: the Flight School course map as pins on the Moon (academy/ui.js) ----------
  // Each stop is an HTML button the caller builds (patch art, label); the globe places it every frame at its real
  // lat/lon (plus an optional pixel nudge so close polar stops don't overlap), with a dot at the true spot and a dotted
  // line linking the stops in order. Stops round the back of the Moon fade out.
  const rlayer = document.createElement("div"); rlayer.className = "route"; rlayer.hidden = true; stage.append(rlayer);
  const rsvg = document.createElementNS("http://www.w3.org/2000/svg", "svg"); rsvg.setAttribute("class", "route-lines"); rsvg.setAttribute("aria-hidden", "true");
  rlayer.append(rsvg);
  let rstops = [], rdone = 0;
  const route = {
    /** stops: [{id, lat, lon, el, nudge:[dx,dy]}]; done = how many stops (from the start) are complete */
    set(stops, done = 0) {
      rlayer.querySelectorAll(".route-stop, .route-dot").forEach(e => e.remove());
      rstops = stops.map(s => {
        const dot = document.createElement("i"); dot.className = "route-dot"; rlayer.append(dot);
        s.el.classList.add("route-stop"); rlayer.append(s.el);
        s.el.dataset.lat = s.lat; s.el.dataset.lon = s.lon;   // [keys] focusing a pin flies the globe there (input/spatial.js)
        return { ...s, dot, p: ll2v(s.lat, s.lon, R * 1.003), x: 0, y: 0, on: false };
      });
      rdone = done; rlayer.hidden = !rstops.length;
    },
    clear() { route.set([]); },
  };
  function tickRoute() {
    if (rlayer.hidden) return;
    const w = stage.clientWidth, h = stage.clientHeight, cam = camera.position.clone().normalize();
    // pins on the near hemisphere only (fading out well before the limb, where they'd be squashed); then pushed apart
    // on screen so close stops (the south-pole cluster) never overlap, with a dot left on the true spot
    rstops.forEach(s => {
      const f = s.p.clone().normalize().dot(cam);
      s.f = f; s.on = f > 0.3; tmp.copy(s.p).project(camera);
      s.x = (tmp.x + 1) / 2 * w; s.y = (1 - tmp.y) / 2 * h; s.bx = s.x; s.by = s.y; s.r = (s.el.offsetWidth || 44) / 2 + (s.el.classList.contains("is-next") ? 42 : 8);   // the next pin keeps room for its label (playtest #28: it covered the pin below)
    });
    const vis = rstops.filter(s => s.on);
    for (let it = 0; it < 12; it++) vis.forEach((a, i) => vis.slice(i + 1).forEach(b => {
      const dx = b.bx - a.bx, dy = b.by - a.by, d = Math.hypot(dx, dy) || 0.01, need = a.r + b.r;
      if (d >= need) return;
      if (d < 0.5) { a.bx -= need / 2; b.bx += need / 2; return; }   // two lessons on the same place (a Class pin on a NASA one): side by side
      const k = (need - d) / 2 / d; a.bx -= dx * k; a.by -= dy * k; b.bx += dx * k; b.by += dy * k;
    }));
    rstops.forEach(s => {
      const op = Math.max(0, Math.min(1, (s.f - 0.3) / 0.15)).toFixed(2);
      s.dot.style.transform = `translate(${s.x.toFixed(1)}px,${s.y.toFixed(1)}px)`; s.dot.style.opacity = Math.hypot(s.bx - s.x, s.by - s.y) > 4 ? op : 0;
      s.el.style.transform = `translate(${s.bx.toFixed(1)}px,${s.by.toFixed(1)}px)`; s.el.style.opacity = op;
      s.el.style.visibility = s.on ? "" : "hidden"; s.el.tabIndex = s.on ? 0 : -1;
    });
    // the route follows the surface: each leg is a great-circle arc, drawn only where it faces the camera
    let d = "", dd = "";
    const q = new THREE.Vector3();
    for (let i = 1; i < rstops.length; i++) {
      // legs: solid between two done stops, dotted into the next stop, nothing else. Stops may carry their own state
      // ({done, next}); otherwise the first `rdone` stops are the done ones.
      const A = rstops[i - 1], B = rstops[i];
      if (A.noLeg || B.noLeg) continue;   // a Class lesson pin: on the Moon, off the NASA route
      const dn = x => (x.done != null ? !!x.done : rstops.indexOf(x) < rdone), nx = x => (x.next != null ? !!x.next : rstops.indexOf(x) === rdone);
      const solid = dn(A) && dn(B), dotted = dn(A) && nx(B);
      if (!solid && !dotted) continue;
      const a = A.p.clone().normalize(), b = B.p.clone().normalize();
      const om = Math.acos(Math.max(-1, Math.min(1, a.dot(b)))), n = Math.max(2, Math.ceil(om * 40)); let pen = false, seg = "";
      for (let k = 0; k <= n; k++) {
        const t = k / n, s0 = Math.sin(om) || 1;
        q.copy(a).multiplyScalar(Math.sin((1 - t) * om) / s0).add(b.clone().multiplyScalar(Math.sin(t * om) / s0)).normalize().multiplyScalar(R * 1.003);
        if (q.clone().normalize().dot(cam) < 0.08) { pen = false; continue; }
        tmp.copy(q).project(camera);
        seg += `${pen ? "L" : "M"}${((tmp.x + 1) / 2 * w).toFixed(1)},${((1 - tmp.y) / 2 * h).toFixed(1)}`; pen = true;
      }
      if (solid) dd += seg; else d += seg;
    }
    rsvg.setAttribute("viewBox", `0 0 ${w} ${h}`);
    rsvg.innerHTML = `<path class="route-todo" d="${d}"/><path class="route-done" d="${dd}"/>`;
  }

  // ---------- Guide marks (academy/guide.js, docs/PLAYTEST.md): what a Flight School step is about ----------
  // A ring sized to the place (its real angular radius, projected), an optional number (route stops) and label.
  // Never clickable: a tap on a mark falls through to the Moon, so it grades as a tap on that place.
  const glayer = document.createElement("div"); glayer.className = "guide"; glayer.hidden = true; stage.append(glayer);
  let gmarks = [];
  const guide = {
    /** marks: [{id, lat, lon, r (deg), label?, num?, ring?, gold?, pulse?}] */
    set(list) {
      glayer.textContent = "";
      gmarks = (list || []).map(m => {
        const el = document.createElement("div");
        el.className = "gd-mark" + (m.pulse ? " is-pulse" : "") + (m.ring ? " is-ring" : " is-dot") + (m.line ? " is-line" : "") + (m.gold ? " is-gold" : "") + (m.label ? " has-label" : "") + (m.above ? " is-above" : "");
        el.setAttribute("aria-hidden", "true");
        el.innerHTML = `<i class="gd-ring"></i>${m.num ? `<b class="gd-num"></b>` : ""}${m.label ? `<span class="gd-label"></span>` : ""}`;
        if (m.num) el.querySelector(".gd-num").textContent = String(m.num);
        if (m.label) el.querySelector(".gd-label").textContent = m.label;
        glayer.append(el);
        const up = m.lat > 0 ? -1 : 1;   // offset toward the equator, so a polar mark still has a size
        return { ...m, el, p: ll2v(m.lat, m.lon, R * 1.003), q: ll2v(m.lat + up * (m.r || 2), m.lon, R * 1.003) };
      });
      glayer.hidden = !gmarks.length;
    },
    clear() { guide.set([]); },
    /** The marks' text, for tests and the a11y "where am I" line. */
    get labels() { return gmarks.filter(m => m.label).map(m => m.label); },
  };
  function tickGuide() {
    if (glayer.hidden) return;
    const w = stage.clientWidth, h = stage.clientHeight, cam = camera.position.clone().normalize();
    gmarks.forEach(m => {
      const f = m.p.clone().normalize().dot(cam), on = f > 0.06;
      m.el.style.visibility = on ? "" : "hidden"; if (!on) return;
      tmp.copy(m.p).project(camera); const x = (tmp.x + 1) / 2 * w, y = (1 - tmp.y) / 2 * h;
      tmp.copy(m.q).project(camera);
      const r = Math.max(13, Math.min(150, Math.hypot((tmp.x + 1) / 2 * w - x, (1 - tmp.y) / 2 * h - y)));
      m.el.style.transform = `translate(${x.toFixed(1)}px,${y.toFixed(1)}px)`; m.el.style.setProperty("--r", r.toFixed(0) + "px");
    });
  }

  // ---------- 0.4 real NASA views (media/nasa_views.js): star sky, south-pole relief, hardware models ----------
  // All optional: each setter is called once its data is in; until then (or if a load fails) today's visuals stay.
  const maxAniso = renderer.capabilities.getMaxAnisotropy();
  let skyMesh = null;
  /** The real sky: SVS Deep Star Maps 2020 on a sphere around everything, replacing the random points. The celestial
   *  pole is tilted by the obliquity (23.44°) so the ecliptic lies along the Moon's equator (within its 1.5°). */
  function setSky(url, opt = {}) {
    return new Promise(res => new THREE.TextureLoader().load(url, t => {
      t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = maxAniso; t.wrapS = THREE.RepeatWrapping;
      if (opt.flipX) t.repeat.x = -1;
      t.offset.x = opt.offsetU || 0;
      if (skyMesh) { scene.remove(skyMesh); skyMesh.geometry.dispose(); skyMesh.material.map.dispose(); skyMesh.material.dispose(); }
      skyMesh = new THREE.Mesh(new THREE.SphereGeometry(60, 64, 32),
        new THREE.MeshBasicMaterial({ map: t, side: THREE.BackSide, depthWrite: false, color: new THREE.Color(opt.dim || 0.85, opt.dim || 0.85, opt.dim || 0.85) }));
      skyMesh.rotation.x = 23.44 * Math.PI / 180; skyMesh.renderOrder = -1;
      scene.add(skyMesh); starPts.visible = false; res(true);
    }, undefined, () => res(false)));   // a failed load keeps the random stars
  }

  let cap = null;
  /** A sharp south pole: the LOLA shaded relief (site_layers' relief.png, south polar stereographic, lon 0 up, ±extentKm)
   *  draped over the globe's blurry polar texels, fading out at its edge. Same projection as the site navigator's map. */
  function setPolarCap(url, extentKm = 210, { tone = [0.686, 0.674, 0.647], contrast = 0.8 } = {}) {
    return new Promise(res => new THREE.ImageLoader().load(url, img => {
      const t = new THREE.CanvasTexture(matchTone(img, tone, contrast));
      t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = maxAniso;
      const N = 96, E = extentKm, pos = [], nor = [], uv = [], idx = [];
      for (let j = 0; j <= N; j++) for (let i = 0; i <= N; i++) {
        const x = -E + 2 * E * i / N, y = -E + 2 * E * j / N, r = Math.hypot(x, y);
        const lat = 2 * Math.atan(r / (2 * MOON_KM)) * 180 / Math.PI - 90, lon = Math.atan2(x, y) * 180 / Math.PI;
        const v = ll2v(lat, lon, R * 1.0006), n = v.clone().normalize();
        pos.push(v.x, v.y, v.z); nor.push(n.x, n.y, n.z); uv.push(i / N, j / N);
      }
      const at = (i, j) => j * (N + 1) + i;
      // wind the triangles so their front faces look out from the Moon (checked on the first one)
      const A = new THREE.Vector3(...pos.slice(0, 3)), B = new THREE.Vector3(...pos.slice(3, 6)), C = new THREE.Vector3(...pos.slice(at(0, 1) * 3, at(0, 1) * 3 + 3));
      const out = B.clone().sub(A).cross(C.clone().sub(A)).dot(A) > 0;
      for (let j = 0; j < N; j++) for (let i = 0; i < N; i++) {
        const a = at(i, j), b = at(i + 1, j), c = at(i, j + 1), d = at(i + 1, j + 1);
        if (out) idx.push(a, b, c, b, d, c); else idx.push(a, c, b, b, c, d);
      }
      const g = new THREE.BufferGeometry();
      g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3)); g.setAttribute("normal", new THREE.Float32BufferAttribute(nor, 3));
      g.setAttribute("uv", new THREE.Float32BufferAttribute(uv, 2)); g.setIndex(idx);
      const fade = document.createElement("canvas"); fade.width = fade.height = 256;
      { const c = fade.getContext("2d"), gr = c.createRadialGradient(128, 128, 0, 128, 128, 128);
        gr.addColorStop(0, "#fff"); gr.addColorStop(.62, "#fff"); gr.addColorStop(1, "#000"); c.fillStyle = "#000"; c.fillRect(0, 0, 256, 256); c.fillStyle = gr; c.fillRect(0, 0, 256, 256); }
      if (cap) { moon.remove(cap); cap.geometry.dispose(); cap.material.dispose(); }
      cap = new THREE.Mesh(g, new THREE.MeshStandardMaterial({ map: t, alphaMap: new THREE.CanvasTexture(fade), transparent: true, roughness: 1, metalness: 0,
        depthWrite: false, polygonOffset: true, polygonOffsetFactor: -2 }));
      cap.name = "polar-cap"; moon.add(cap); res(true);
    }, undefined, () => res(false)));
  }

  /** The LOLA hillshade is darker and far more contrasty than the colour map around it: shift it to the colour map's
   *  polar mean (tone, sRGB 0..1) with a gentler contrast, so the sharp pole reads as the same Moon, not a patch. */
  function matchTone(img, tone, contrast) {
    const c = document.createElement("canvas"); c.width = img.width; c.height = img.height;
    const g = c.getContext("2d", { willReadFrequently: true }); g.drawImage(img, 0, 0);
    const d = g.getImageData(0, 0, c.width, c.height), px = d.data;
    let sum = 0, n = 0;
    for (let i = 0; i < px.length; i += 64) { sum += px[i]; n++; }
    const mean = sum / Math.max(1, n) / 255;
    for (let i = 0; i < px.length; i += 4) {
      const v = (px[i] / 255 - mean) * contrast;
      px[i] = 255 * Math.min(1, Math.max(0, tone[0] + v)); px[i + 1] = 255 * Math.min(1, Math.max(0, tone[1] + v)); px[i + 2] = 255 * Math.min(1, Math.max(0, tone[2] + v));
    }
    g.putImageData(d, 0, 0); return c;
  }

  // Hardware in 3D: a model stands on the surface at its marker (the HTML marker stays: focus, hover, tap, its card),
  // and orbiters circle the Moon. Not to scale (a real LM is 7 m): sized to read at the Library's zoom.
  const hw3d = new THREE.Group(), orbit3d = new THREE.Group(); hw3d.name = "hw3d"; orbit3d.name = "orbiters";
  scene.add(hw3d, orbit3d);
  const UP = new THREE.Vector3(0, 1, 0);
  /** Scale a model so its largest side is `size`, its base at y = 0, centred on x/z. -> a wrapper group */
  function fit(obj, size) {
    const box = new THREE.Box3().setFromObject(obj), dim = box.getSize(new THREE.Vector3()), c = box.getCenter(new THREE.Vector3());
    const k = size / Math.max(dim.x, dim.y, dim.z, 1e-6);
    obj.position.set(-c.x * k, -box.min.y * k, -c.z * k); obj.scale.setScalar(k);
    const w = new THREE.Group(); w.add(obj); return w;
  }
  /** models: (artifact) -> a fresh THREE.Object3D or null. Each artifact with a model loses its diamond. -> count */
  function setHardwareModels(modelFor, size = 0.03) {
    let n = 0;
    hw3d.clear();
    ghosts.forEach(g => {
      const obj = modelFor(g.a);
      g.el.classList.toggle("has-model", !!obj);
      if (!obj) return;
      const w = fit(obj, size), nrm = ll2v(g.a.lat, g.a.lon).normalize();
      w.position.copy(nrm.clone().multiplyScalar(R * 1.0005)); w.quaternion.setFromUnitVectors(UP, nrm);
      w.name = "hw:" + g.a.id; hw3d.add(w); n++;
    });
    return n;
  }
  const orbiters = [];
  /** list: [{id, obj, label, incl (deg, 90 = polar), alt (Moon radii above the surface), period (s), phase (0..1)}] */
  function setOrbiters(list) {
    orbiters.splice(0).forEach(o => o.tag.remove()); orbit3d.clear();
    list.forEach(o => {
      const w = fit(o.obj, o.size || 0.055); orbit3d.add(w);
      const tag = document.createElement("span"); tag.className = "orb-tag"; tag.textContent = o.label; tag.setAttribute("aria-hidden", "true"); layer.append(tag);
      const inc = (o.incl || 0) * Math.PI / 180;
      orbiters.push({ ...o, w, tag, r: R * (1 + (o.alt || 0.08)), n1: new THREE.Vector3(1, 0, 0), n2: new THREE.Vector3(0, Math.sin(inc), Math.cos(inc)) });
    });
    return orbiters.length;
  }
  const oc = new THREE.Vector3(), od = new THREE.Vector3();
  /** A point in space hidden behind the Moon (the camera's line to it passes through the sphere first). */
  function occluded(p) {
    od.copy(p).sub(camera.position); const t = -camera.position.dot(od) / od.lengthSq();
    return t > 0 && t < 1 && oc.copy(od).multiplyScalar(t).add(camera.position).length() < R;
  }
  function tickViews(now) {
    const on = layer.style.display !== "none" && document.body.dataset.mode === "cadet";
    hw3d.visible = orbit3d.visible = on;
    if (!orbiters.length) return;
    const w = stage.clientWidth, h = stage.clientHeight;
    orbiters.forEach(o => {
      const th = 2 * Math.PI * ((o.phase || 0) + (lessMotion() ? 0 : now / 1000 / (o.period || 60)));
      const p = o.n1.clone().multiplyScalar(Math.cos(th)).add(o.n2.clone().multiplyScalar(Math.sin(th))).multiplyScalar(o.r);
      const v = o.n2.clone().multiplyScalar(Math.cos(th)).sub(o.n1.clone().multiplyScalar(Math.sin(th)));
      o.w.position.copy(p); o.w.up.copy(p).normalize(); o.w.lookAt(p.clone().add(v));
      const hide = !on || occluded(p);
      o.tag.style.visibility = hide ? "hidden" : "";
      if (hide) return;
      tmp.copy(p).project(camera);
      o.tag.style.transform = `translate(${((tmp.x + 1) / 2 * w).toFixed(1)}px,${((1 - tmp.y) / 2 * h).toFixed(1)}px)`;
    });
  }

  // Viewport band: in the Mission cabin the Moon is seen through a window at the top of the stage, so the camera's
  // view is shifted (setViewOffset) to centre the globe in that band. null = the whole stage, as before.
  let band = null, paused = false;
  function resize() {
    const w = stage.clientWidth, h = stage.clientHeight; renderer.setSize(w, h, false); camera.aspect = w / h;
    if (band || bandX) { const hb = h * (band || 1); camera.setViewOffset(w, h, bandX * w, (h - hb) / 2, w, h); } else camera.clearViewOffset();
    camera.updateProjectionMatrix();
  }
  let decorOn = true, userPins = true, userHw = true;   // [qa] Library switches (setDecor keeps them)
  /** frac: the band's height share (the view's centre lifts above a bottom strip); [0.4] xFrac: a share of the width to
   *  shift the view's centre left by (a side panel on the right), 0 by default. */
  let bandX = 0;
  function setViewport(frac, xFrac = 0) { band = frac || null; bandX = +xFrac || 0; resize(); }
  new ResizeObserver(resize).observe(stage); resize();

  const tmp = new THREE.Vector3();
  function tick(now) {
    if (fly) {
      const t = Math.min(1, (now - fly.t0) / fly.dur), e = t < .5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
      const a = fly.fd, b = fly.td; let dir;
      if (a.dot(b) < -0.98) { const mid = new THREE.Vector3(0, 1, 0).cross(a).normalize(); dir = e < .5 ? a.clone().lerp(mid, e * 2) : mid.clone().lerp(b, (e - .5) * 2); }
      else dir = a.clone().lerp(b, e);
      camera.position.copy(dir.normalize().multiplyScalar(fly.r0 + (fly.r1 - fly.r0) * e)); camera.lookAt(0, 0, 0);
      if (t >= 1) endFly();
    }
    controls.update();
    if (ring) ring.material.opacity = lessMotion() ? .8 : .65 + .3 * Math.sin(now / 300);
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
    tickMission(); tickRoute(); tickGuide(); tickViews(now);
    if (!paused) renderer.render(scene, camera); requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);

  /** Nearest named place to a point, scored by distance minus a share of its radius. */
  function nearest(p) {
    let best = null, bd = 1e9;
    features.forEach(f => { const d = angDist(p, f) - angRadius(f, BODY_KM) * 0.6; if (d < bd) { bd = d; best = f; } });
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
    else onMiss();   // [audit2] a tap on space used to do nothing at all
  });

  return {
    showFeature, highlight, flyTo, nearest, mission, setViewport, setSunDir, poleView, centerLatLon,   // [learning-v3] sun / pole / centre
    /** Screen position (px in the stage) of a surface point, and whether it faces the camera. Used by the site pins. */
    project(lat, lon) { const p = ll2v(lat, lon, R * 1.004), v = p.clone().project(camera);
      const depth = p.clone().normalize().dot(camera.position.clone().normalize());   // 1 = facing the camera, 0 = on the edge
      return { x: (v.x + 1) / 2 * stage.clientWidth, y: (1 - v.y) / 2 * stage.clientHeight, facing: depth > 0.05, depth }; },
    /** Stop drawing (the cabin window covers the globe with a surface view); the camera keeps flying. */
    pause(on) { paused = !!on; renderer.domElement.style.visibility = on ? "hidden" : ""; },
    // [gestures] grab-to-rotate, two-hand zoom and stop (docs/GESTURES.md). dx, dy: fractions of the view; the surface
    // follows the hand, as a mouse drag does.
    rotateBy(dx, dy) {
      endFly(); const s = new THREE.Spherical().setFromVector3(camera.position);
      s.theta -= dx * Math.PI; s.phi = Math.max(0.15, Math.min(Math.PI - 0.15, s.phi - dy * Math.PI));
      camera.position.setFromSpherical(s); camera.lookAt(0, 0, 0);
    },
    zoomBy(f) {
      endFly(); const d = camera.position.length(), n = Math.max(controls.minDistance, Math.min(controls.maxDistance, d / (f || 1)));
      camera.position.multiplyScalar(n / d);
    },
    // [keys] the keyboard / gamepad Moon reticle (input/spatial.js): where the camera is, and a tap without a pointer
    get distance() { return (fly ? fly.r1 : camera.position.length()); },
    tap(lat, lon) { onTap({ lat, lon }); },
    tapArtifact(id) { const g = ghosts.find(x => x.a.id === id); if (g) onArtifact(g.a); },
    /** Stop any flight in progress where it is. */
    halt() { endFly(); },
    route, guide,
    // 0.4 real NASA views (media/nasa_views.js; all optional, today's visuals until called)
    setSky, setPolarCap, setHardwareModels, setOrbiters,
    get skyReal() { return !!skyMesh; }, get polarCap() { return !!cap; },
    /** Drop the highlight ring and its label (a globe step that moves the camera starts clean). */
    clearHighlight() { if (ring) { scene.remove(ring); ring.geometry.dispose(); ring = null; } sel = null; label.hidden = true; ghosts.forEach(g => g.el.classList.remove("is-on")); },
    /** Settings → Display → Graphics: "low" renders at 1× pixel ratio (lighter on older laptops). */
    setQuality(q) { renderer.setPixelRatio(q === "low" ? 1 : Math.min(devicePixelRatio, 2)); resize(); },
    /** Place dots + hardware markers on/off (off on Flight School screens, where the route pins are the map). */
    // [qa] the Library's Places / Hardware switches are the kid's choice: setDecor(true) brings back only what they left on
    setDecor(on) { if (mi.on) return; decorOn = !!on; pins.visible = decorOn && userPins; layer.style.display = decorOn && userHw ? "" : "none"; },
    togglePins() { userPins = !userPins; pins.visible = decorOn && userPins; return userPins; },
    toggleHardware() { userHw = !userHw; layer.style.display = decorOn && userHw ? "" : "none"; return userHw; },
    get pinsOn() { return userPins; },
    get hardwareOn() { return userHw; },
  };
}
