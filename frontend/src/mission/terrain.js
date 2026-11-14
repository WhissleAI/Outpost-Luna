// The cabin window's surface views: real LRO LOLA terrain around the chosen south-pole site, built offline by
// frontend/tools/build_terrain.py into /terrain/<site>/ (three nested tiles: context 240 m/px · 123 km, site
// 40 m/px · 20 km, rover 10 m/px · 5 km). Nothing is fetched from the network: the tiles ship with the app.
//
// Views:  SITE  — descent from ~14 km onto the outpost, then a slow drift round it.
//         ROVER — low chase camera behind the rover, which drives its route on the real terrain.
//         EARTH — a long lens from the hab mast at the Earth (or the horizon where it is hiding).
// Sun and Earth come from the sim (JPL Horizons elevations), with the same azimuth convention as globe.js, so the
// window agrees with the SUN EL / EARTH EL readouts. The Moon's curvature is applied to the mesh (−d²/2R).
// Post: pmndrs postprocessing (bloom for the Sun's glare and the beacons, a light grain + vignette, ACES).
import * as THREE from "three";
import { CSM } from "three/examples/jsm/csm/CSM.js";
import { EffectComposer, RenderPass, EffectPass, BloomEffect, NoiseEffect, VignetteEffect, ToneMappingEffect, ToneMappingMode, BlendFunction } from "postprocessing";

const R_MOON = 1737400, SKY = 800e3, DEG = Math.PI / 180;
const LEVELS = ["context", "site", "rover"], STRIDE = { context: 2, site: 1, rover: 1 };
// Rover routes: real targets (Shackleton for ice, Cabeus where LCROSS found water); the route on screen is the first
// few km of the drive toward them, which is what the rover tile covers.
const TARGETS = { collect_ice: { lat: -89.67, lon: 129.78, km: 1.9, total: 10 }, explore: { lat: -84.68, lon: -48.7, km: 2.2, total: 8 },
  repair_array: { local: [34, 18], km: 0.04, total: 5 }, return: { km: 1.4, total: 5 } };
const smooth = (a, b, x) => { const t = Math.max(0, Math.min(1, (x - a) / (b - a))); return t * t * (3 - 2 * t); };
const ease = t => t < .5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
/** South polar stereographic (PDS LOLA): map metres; longitude 0 points to +y. Scene: x = map x, z = −map y. */
const polar = (lat, lon) => { const t = 2 * R_MOON * Math.tan(Math.PI / 4 + lat * DEG / 2); return [t * Math.sin(lon * DEG), t * Math.cos(lon * DEG)]; };
/** Unit vector toward a body at elevation `el` and grid longitude `lon` (seen from near the pole), scene frame. */
const skyDir = (elDeg, lonDeg) => { const e = elDeg * DEG, l = lonDeg * DEG; return new THREE.Vector3(Math.cos(e) * Math.sin(l), Math.sin(e), -Math.cos(e) * Math.cos(l)).normalize(); };
/** Same convention as globe.js mission.setSun: azimuth 140° + one turn per 708.7 h lunar day, from the Earth side. */
export const sunLon = timeH => -(140 + (timeH || 0) * 360 / 708.7);

async function loadHeights(url, px) {
  const blob = await (await fetch(url)).blob();
  const bmp = await createImageBitmap(blob, { colorSpaceConversion: "none", premultiplyAlpha: "none" });
  const c = document.createElement("canvas"); c.width = px; c.height = px;
  const g = c.getContext("2d", { willReadFrequently: true }); g.drawImage(bmp, 0, 0);
  const d = g.getImageData(0, 0, px, px).data, out = new Float32Array(px * px);
  for (let i = 0; i < px * px; i++) out[i] = d[i * 4] * 256 + d[i * 4 + 1];
  return out;
}

/** Grey regolith detail: fractal speckle + small craters, tiled in world space (gives the close-up texture). */
function detailTexture() {
  const N = 256, c = document.createElement("canvas"); c.width = c.height = N;
  const g = c.getContext("2d"), img = g.createImageData(N, N), v = new Float32Array(N * N);
  let seed = 7; const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
  for (let oct = 0, amp = 1, f = 4; oct < 5; oct++, amp *= .55, f *= 2) {
    const grid = []; for (let i = 0; i < f * f; i++) grid.push(rnd());
    for (let y = 0; y < N; y++) for (let x = 0; x < N; x++) {
      const gx = x / N * f, gy = y / N * f, x0 = Math.floor(gx), y0 = Math.floor(gy), tx = gx - x0, ty = gy - y0;
      const at = (i, j) => grid[((j % f) * f + (i % f))];
      const sx = tx * tx * (3 - 2 * tx), sy = ty * ty * (3 - 2 * ty);
      v[y * N + x] += amp * ((at(x0, y0) * (1 - sx) + at(x0 + 1, y0) * sx) * (1 - sy) + (at(x0, y0 + 1) * (1 - sx) + at(x0 + 1, y0 + 1) * sx) * sy);
    }
  }
  for (let k = 0; k < 40; k++) {   // craterlets: dark floor, bright rim (wraps)
    const cx = rnd() * N, cy = rnd() * N, r = 2 + rnd() * rnd() * 16;
    for (let y = -r - 2; y <= r + 2; y++) for (let x = -r - 2; x <= r + 2; x++) {
      const d = Math.hypot(x, y) / r, i = ((Math.round(cy + y) + N) % N) * N + ((Math.round(cx + x) + N) % N);
      if (d < 1) v[i] -= .35 * (1 - d * d); else if (d < 1.3) v[i] += .25 * (1.3 - d) / .3;
    }
  }
  let lo = 1e9, hi = -1e9; v.forEach(x => { lo = Math.min(lo, x); hi = Math.max(hi, x); });
  for (let i = 0; i < N * N; i++) { const t = (v[i] - lo) / (hi - lo), b = 178 + t * 77; img.data.set([b, b, b * .985, 255], i * 4); }
  g.putImageData(img, 0, 0);
  const tex = new THREE.CanvasTexture(c); tex.wrapS = tex.wrapT = THREE.RepeatWrapping; tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

function rover() {
  const g = new THREE.Group(), white = new THREE.MeshStandardMaterial({ color: 0xe4e1da, roughness: .55, metalness: .2 }),
    dark = new THREE.MeshStandardMaterial({ color: 0x25272b, roughness: .8 }), gold = new THREE.MeshStandardMaterial({ color: 0xc9a24a, roughness: .35, metalness: .85 }),
    cell = new THREE.MeshStandardMaterial({ color: 0x1b2d52, roughness: .25, metalness: .6 });
  const box = (w, h, d, m, x, y, z) => { const b = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), m); b.position.set(x, y, z); g.add(b); return b; };
  box(2.1, .45, 3.1, white, 0, 1.0, 0); box(1.7, .5, 1.2, gold, 0, 1.45, .6); box(2.3, .06, 1.6, cell, 0, 1.75, -.7);
  const wheels = [];
  [-1.15, 1.15].forEach(x => [-1.15, 0, 1.15].forEach(z => {
    const w = new THREE.Mesh(new THREE.CylinderGeometry(.42, .42, .34, 18), dark); w.rotation.z = Math.PI / 2; w.position.set(x, .42, z); g.add(w); wheels.push(w);
    box(.12, .5, .12, white, x * .9, .72, z);
  }));
  const mast = new THREE.Mesh(new THREE.CylinderGeometry(.05, .05, 1.5, 8), white); mast.position.set(.6, 1.95, 1.3); g.add(mast);
  box(.5, .22, .22, dark, .6, 2.75, 1.3);
  const dish = new THREE.Mesh(new THREE.SphereGeometry(.38, 16, 8, 0, Math.PI * 2, 0, .9), white); dish.position.set(-.6, 2.1, .9); dish.rotation.x = -1.1; g.add(dish);
  const beacon = new THREE.Mesh(new THREE.SphereGeometry(.08, 8, 6), new THREE.MeshBasicMaterial({ color: new THREE.Color(0, 6, 3) })); beacon.position.set(.6, 2.95, 1.3); g.add(beacon);
  g.traverse(o => { if (o.isMesh) o.castShadow = true; });
  const work = new THREE.PointLight(0xdfe9ff, 26, 30, 1.6); work.position.set(0, 3.4, -1.6); g.add(work);   // mast work light (it drives in the dark)
  const head = new THREE.SpotLight(0xfff2dc, 160, 90, .5, .6, 1.4); head.position.set(0, 1.4, 1.7); head.target.position.set(0, 0, 30); g.add(head, head.target);
  g.userData = { wheels, beacon };
  return g;
}

function outpost() {
  const g = new THREE.Group(), white = new THREE.MeshStandardMaterial({ color: 0xe7e4dc, roughness: .6, metalness: .15 }),
    gold = new THREE.MeshStandardMaterial({ color: 0xc89c45, roughness: .35, metalness: .85 }), cell = new THREE.MeshStandardMaterial({ color: 0x1c2f57, roughness: .2, metalness: .7 }),
    grey = new THREE.MeshStandardMaterial({ color: 0x777b80, roughness: .7, metalness: .4 });
  const cyl = (r, l, m, x, y, z, rx = 0, rz = 0) => { const c = new THREE.Mesh(new THREE.CylinderGeometry(r, r, l, 28), m); c.position.set(x, y, z); c.rotation.set(rx, 0, rz); g.add(c); return c; };
  cyl(2.3, 9, white, 0, 3.2, 0, 0, Math.PI / 2); cyl(2.3, 7, white, 0, 3.2, 6.5, Math.PI / 2, 0); cyl(1.4, 2, gold, 0, 3.2, -3.2, Math.PI / 2, 0);
  [[-3, -1.5], [3, -1.5], [-3, 1.5], [3, 1.5], [-1.6, 8.5], [1.6, 8.5]].forEach(([x, z]) => cyl(.12, 2.4, grey, x, 1.1, z));
  // vertical solar array (at the pole the Sun skims the horizon, so arrays stand upright and turn with it)
  const array = new THREE.Group(); array.position.set(34, 0, 18); g.add(array);
  const mast = new THREE.Mesh(new THREE.CylinderGeometry(.25, .35, 22, 10), grey); mast.position.y = 11; array.add(mast);
  const wing = new THREE.Group(); wing.position.y = 13; array.add(wing);
  [-4.4, 4.4].forEach(x => { const p = new THREE.Mesh(new THREE.BoxGeometry(8, 14, .12), cell); p.position.x = x; wing.add(p); });
  // comm dish aimed at Earth
  const dishM = new THREE.Group(); dishM.position.set(-12, 0, -6); g.add(dishM);
  const post = new THREE.Mesh(new THREE.CylinderGeometry(.15, .2, 4, 8), grey); post.position.y = 2; dishM.add(post);
  const dish = new THREE.Mesh(new THREE.SphereGeometry(1.6, 24, 10, 0, Math.PI * 2, 0, .8), white); dish.position.y = 4.4; dishM.add(dish);
  const beacon = new THREE.Mesh(new THREE.SphereGeometry(.18, 8, 6), new THREE.MeshBasicMaterial({ color: new THREE.Color(9, .6, .4) })); beacon.position.set(0, 5.7, 0); g.add(beacon);
  const lamp = new THREE.PointLight(0xffd7a0, 40, 60, 2); lamp.position.set(0, 7, 3); g.add(lamp);   // hab floodlight, for the night
  g.traverse(o => { if (o.isMesh) { o.castShadow = true; o.receiveShadow = true; } });
  g.userData = { wing, array, dish, beacon, lamp };
  return g;
}

export function createTerrainView(host, { reduced = () => false } = {}) {
  const canvas = document.createElement("canvas"); canvas.className = "tv-canvas"; canvas.setAttribute("aria-hidden", "true");
  host.prepend(canvas);
  const marks = document.createElement("div"); marks.className = "tv-marks"; marks.setAttribute("aria-hidden", "true"); host.append(marks);
  const mk = (cls, text) => { const e = document.createElement("span"); e.className = "tv-mark " + cls; e.textContent = text; marks.append(e); return e; };
  const mHab = mk("is-hab", "OUTPOST"), mRover = mk("is-rover", "ROVER"), mEarth = mk("is-earth", "EARTH"), mSun = mk("is-sun", "SUN");
  const tag = document.createElement("span"); tag.className = "tv-tag"; marks.append(tag);
  const credit = document.createElement("span"); credit.className = "tv-credit";
  credit.textContent = "NASA LRO LOLA · Blue Marble · not endorsed by NASA"; credit.title = "Terrain: NASA LRO LOLA elevation · Earth: NASA Blue Marble · Uses NASA open data; not endorsed by NASA.";
  marks.append(credit);

  let renderer;
  try { renderer = new THREE.WebGLRenderer({ canvas, antialias: false, powerPreference: "high-performance", logarithmicDepthBuffer: true, stencil: false, depth: true }); }
  catch (e) { canvas.remove(); return null; }
  renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 1.5));
  renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  const scene = new THREE.Scene(); scene.background = new THREE.Color(0x000000);
  const camera = new THREE.PerspectiveCamera(50, 1, .3, 1.5e6);
  const composer = new EffectComposer(renderer, { frameBufferType: THREE.HalfFloatType });
  composer.addPass(new RenderPass(scene, camera));
  const bloom = new BloomEffect({ luminanceThreshold: .92, luminanceSmoothing: .12, intensity: 1.1, mipmapBlur: true, radius: .8 });
  const noise = new NoiseEffect({ premultiply: true, blendFunction: BlendFunction.SCREEN }); noise.blendMode.opacity.value = .045;
  const vignette = new VignetteEffect({ offset: .32, darkness: .62 });
  composer.addPass(new EffectPass(camera, bloom, vignette, noise, new ToneMappingEffect({ mode: ToneMappingMode.ACES_FILMIC })));

  // ---- lights: the Sun (shadow-casting), a faint earthshine fill, and nothing else (the Moon has no sky light) ----
  // Cascaded shadow maps (three's CSM addon): at a 1-2° Sun a ridge 10 km up-sun shades the site, so the shadows
  // must reach far; three cascades cover 0-26 km from the camera, the light sits 60 km up-sun.
  const csm = new CSM({ camera, parent: scene, cascades: 3, maxFar: 26000, mode: "practical", shadowMapSize: 2048, shadowBias: -0.00003,
    lightDirection: new THREE.Vector3(0, -1, 0), lightIntensity: 3.2, lightNear: 1, lightFar: 160000, lightMargin: 60000 });
  csm.lights.forEach((l, i) => { l.color.set(0xfff4e6); l.shadow.normalBias = [0.4, 2, 8][i]; });
  const sun = { set intensity(v) { csm.lights.forEach(l => { l.intensity = v; }); }, get intensity() { return csm.lights[0].intensity; } };
  const earthshine = new THREE.HemisphereLight(0x9fb8e0, 0x000000, .06); scene.add(earthshine);
  // Earthshine / camera fill: a soft directional light from the Earth's side (no shadows). With the Earth up it is
  // real earthshine; otherwise it stands for the camera's exposure, so relief in the shadows still reads, as it does
  // in LRO's low-Sun oblique frames. Strength is set in aimSky().
  const fill = new THREE.DirectionalLight(0xb8cbe8, .3); scene.add(fill, fill.target);

  // ---- sky: stars, the Sun's disc (HDR, so bloom makes the glare), the Earth (NASA Blue Marble), all at "infinity" ----
  const sky = new THREE.Group(); scene.add(sky);
  { const n = 2600, p = new Float32Array(n * 3), col = new Float32Array(n * 3);
    for (let i = 0; i < n; i++) { const v = new THREE.Vector3().randomDirection().multiplyScalar(SKY * 1.1); p.set([v.x, v.y, v.z], i * 3); const b = .35 + Math.pow(Math.random(), 3) * 1.6; col.set([b * .92, b * .95, b], i * 3); }
    const geo = new THREE.BufferGeometry(); geo.setAttribute("position", new THREE.BufferAttribute(p, 3)); geo.setAttribute("color", new THREE.BufferAttribute(col, 3));
    sky.add(new THREE.Points(geo, new THREE.PointsMaterial({ size: 1.6, sizeAttenuation: false, vertexColors: true, depthWrite: false }))); }
  const sunDisc = new THREE.Mesh(new THREE.SphereGeometry(SKY * Math.tan(.2665 * DEG), 24, 12), new THREE.MeshBasicMaterial({ color: new THREE.Color(28, 26, 22), fog: false }));
  sky.add(sunDisc);
  const earthTex = new THREE.TextureLoader().load("/terrain/earth.jpg"); earthTex.colorSpace = THREE.SRGBColorSpace;
  const earth = new THREE.Mesh(new THREE.SphereGeometry(SKY * Math.tan(.95 * DEG), 48, 24), new THREE.MeshStandardMaterial({ map: earthTex, roughness: .7, metalness: 0, emissive: 0x0a1630, emissiveIntensity: .25 }));
  earth.rotation.y = 2.2; sky.add(earth);
  const halo = new THREE.Mesh(new THREE.SphereGeometry(SKY * Math.tan(1.02 * DEG), 32, 16), new THREE.MeshBasicMaterial({ color: 0x4f8fff, transparent: true, opacity: .07, side: THREE.BackSide, depthWrite: false }));
  earth.add(halo);

  // ---- terrain + models ----
  const detail = detailTexture(); detail.anisotropy = renderer.capabilities.getMaxAnisotropy();
  const groundMat = new THREE.MeshStandardMaterial({ color: 0x8f8b84, roughness: 1, metalness: 0, map: detail, bumpMap: detail, bumpScale: .12 });
  // break the tiling: modulate the detail with a second, rotated, 7.3× larger sample of itself
  groundMat.onBeforeCompile = sh => {
    sh.fragmentShader = sh.fragmentShader.replace("#include <map_fragment>", `
      vec4 dA = texture2D( map, vMapUv );
      vec4 dB = texture2D( map, mat2(0.8, -0.6, 0.6, 0.8) * vMapUv * 0.137 + 0.31 );
      diffuseColor *= vec4( mix( vec3(1.0), dA.rgb * 1.08, 0.35 ) * mix( vec3(1.0), dB.rgb * 1.12, 0.5 ), 1.0 );`);
  };
  const terrain = new THREE.Group(); scene.add(terrain);
  const hab = outpost(); scene.add(hab);
  const rv = rover(); scene.add(rv);
  const track = new THREE.Line(new THREE.BufferGeometry(), new THREE.LineDashedMaterial({ color: 0x7cffb0, dashSize: 6, gapSize: 5, transparent: true, opacity: .55, depthWrite: false }));
  scene.add(track);
  // every lit material reads the cascades (the CSM lights would otherwise add up); keep the ground's detail patch
  const groundPatch = groundMat.onBeforeCompile;
  const lit = new Set([groundMat, earth.material]);
  [hab, rv].forEach(g => g.traverse(o => { if (o.isMesh && o.material.isMeshStandardMaterial) lit.add(o.material); }));
  lit.forEach(m => csm.setupMaterial(m));
  const csmPatch = groundMat.onBeforeCompile;
  groundMat.onBeforeCompile = (sh, r) => { csmPatch(sh, r); groundPatch(sh, r); };

  const S = { site: null, meta: null, levels: {}, h0: 0, view: "site", visible: false, sunEl: 1, sunLon: sunLon(0), earthEl: 3, storm: false, alarm: false,
    rover: { d: 0, dGoal: 0, heading: new THREE.Vector3(0, 0, -1), busy: false, task: null }, cam: null, tween: null, t0: performance.now(), drift: 0,
    frames: [], loading: null, earthUp: true };

  /** Terrain height (scene y) at scene x, z: finest tile that covers the point; Moon curvature included. */
  function heightAt(x, z) {
    for (const lv of ["rover", "site", "context"]) {
      const L = S.levels[lv]; if (!L) continue;
      const c = (L.px - 1) / 2, fx = (x - L.dx) / L.mpp + c, fz = (z - L.dz) / L.mpp + c;
      if (fx < 0 || fz < 0 || fx > L.px - 2 || fz > L.px - 2) continue;
      const i = Math.floor(fx), j = Math.floor(fz), tx = fx - i, tz = fz - j, h = L.h, p = L.px;
      const v = (h[j * p + i] * (1 - tx) + h[j * p + i + 1] * tx) * (1 - tz) + (h[(j + 1) * p + i] * (1 - tx) + h[(j + 1) * p + i + 1] * tx) * tz;
      return v - (x * x + z * z) / (2 * R_MOON);
    }
    return -(x * x + z * z) / (2 * R_MOON);
  }

  function buildLevel(lv, L, inner) {
    const st = STRIDE[lv], n = Math.floor((L.px - 1) / st) + 1, c = (L.px - 1) / 2, pos = new Float32Array(n * n * 3), uv = new Float32Array(n * n * 2);
    const half = c * L.mpp, rep = lv === "context" ? 240 : 30;
    for (let j = 0; j < n; j++) for (let i = 0; i < n; i++) {
      const pi = i * st, pj = j * st, k = j * n + i, x = L.dx + (pi - c) * L.mpp, z = L.dz + (pj - c) * L.mpp;
      let y = L.h[pj * L.px + pi] - (x * x + z * z) / (2 * R_MOON);
      if (lv === "context") { const r = Math.max(Math.abs(x - L.dx), Math.abs(z - L.dz)) / half; y -= Math.pow(smooth(.82, 1, r), 2) * 2500; }
      if (inner && Math.abs(x - inner.dx) < inner.half && Math.abs(z - inner.dz) < inner.half) y -= .6;   // tuck just under the finer tile
      pos.set([x, y, z], k * 3); uv.set([x / rep, z / rep], k * 2);
    }
    const idx = [];
    for (let j = 0; j < n - 1; j++) for (let i = 0; i < n - 1; i++) {
      if (inner) { const x = L.dx + ((i + .5) * st - c) * L.mpp, z = L.dz + ((j + .5) * st - c) * L.mpp;
        if (Math.abs(x - inner.dx) < inner.half - L.mpp * st && Math.abs(z - inner.dz) < inner.half - L.mpp * st) continue; }
      const a = j * n + i, b = a + 1, d = a + n, e = d + 1; idx.push(a, d, b, b, d, e);
    }
    const geo = new THREE.BufferGeometry(); geo.setAttribute("position", new THREE.BufferAttribute(pos, 3)); geo.setAttribute("uv", new THREE.BufferAttribute(uv, 2));
    geo.setIndex(n * n > 65535 ? new THREE.Uint32BufferAttribute(idx, 1) : new THREE.Uint16BufferAttribute(idx, 1)); geo.computeVertexNormals();
    const m = new THREE.Mesh(geo, groundMat); m.receiveShadow = true; m.castShadow = lv !== "context"; m.name = lv;
    return m;
  }

  async function setSite(site) {
    if (!site || (S.site && S.site.id === site.id)) return S.loading;
    S.site = site; S.levels = {}; terrain.clear();
    S.loading = (async () => {
      const meta = await (await fetch(`/terrain/${site.id}/meta.json`)).json(); S.meta = meta;
      const [sx, sy] = polar(meta.lat, meta.lon);
      const h0 = meta.levels.rover.site_h_m; S.h0 = h0;
      for (const lv of LEVELS) {
        const m = meta.levels[lv], q = await loadHeights(`/terrain/${site.id}/${lv}.png`, m.px), h = new Float32Array(q.length);
        for (let i = 0; i < q.length; i++) h[i] = (q[i] + m.dn_min) * m.dn_scale_m - h0;
        S.levels[lv] = { px: m.px, mpp: m.m_per_px, dx: m.center_x_m - sx, dz: -(m.center_y_m - sy), h };
      }
      // Feather each finer tile's border into its parent (different LOLA products differ by a few metres), so the
      // nested meshes meet without a step; a step would cast a long false shadow at these grazing Sun angles.
      const sample = (L, x, z) => { const c = (L.px - 1) / 2, fx = Math.max(0, Math.min(L.px - 1.001, (x - L.dx) / L.mpp + c)), fz = Math.max(0, Math.min(L.px - 1.001, (z - L.dz) / L.mpp + c));
        const i = Math.floor(fx), j = Math.floor(fz), tx = fx - i, tz = fz - j, h = L.h, p = L.px;
        return (h[j * p + i] * (1 - tx) + h[j * p + i + 1] * tx) * (1 - tz) + (h[(j + 1) * p + i] * (1 - tx) + h[(j + 1) * p + i + 1] * tx) * tz; };
      [["site", "context"], ["rover", "site"]].forEach(([lv, up]) => {
        const L = S.levels[lv], U = S.levels[up], c = (L.px - 1) / 2, band = 24;
        for (let j = 0; j < L.px; j++) for (let i = 0; i < L.px; i++) {
          const e = Math.min(i, j, L.px - 1 - i, L.px - 1 - j); if (e >= band) continue;
          const w = smooth(0, band, e), k = j * L.px + i;
          L.h[k] = L.h[k] * w + sample(U, L.dx + (i - c) * L.mpp, L.dz + (j - c) * L.mpp) * (1 - w);
        }
      });
      const box = lv => { const L = S.levels[lv]; return { dx: L.dx, dz: L.dz, half: (L.px - 1) / 2 * L.mpp }; };
      terrain.add(buildLevel("context", S.levels.context, box("site")), buildLevel("site", S.levels.site, box("rover")), buildLevel("rover", S.levels.rover, null));
      // the outpost sits on a flat-ish pad at the site; settle each module on the ground
      hab.position.set(0, heightAt(0, 0), 0);
      S.rover.d = S.rover.dGoal = 0; placeRover(0);
      aimSky(); if (S.visible) poseNow();
    })();
    return S.loading;
  }

  // ---- Sun, Earth ----
  function aimSky() {
    const sd = skyDir(S.sunEl, S.sunLon), ed = skyDir(S.earthEl, 0);
    sunDisc.position.copy(sd).multiplyScalar(SKY); earth.position.copy(ed).multiplyScalar(SKY);
    // The Sun stays on a little below the site's horizon: peaks and far rims that still see it stay lit, and the
    // shadow map (with the Moon's curvature in the mesh) keeps the site itself dark. That is the real polar look.
    sun.intensity = 5.6 * smooth(-3, .4, S.sunEl); sunDisc.visible = S.sunEl > -3;   // exposed for the lit regolith
    // In the dark the window is a low-light camera (said on the glass), so the terrain stays readable.
    S.lowLight = S.sunEl < .3;
    earthshine.intensity = S.lowLight ? .7 : S.earthEl > 0 ? .3 : .16;
    earthshine.color.set(S.lowLight ? 0xa9c9bb : 0x9fb8e0);
    fill.position.copy(skyDir(Math.max(S.earthEl, 0) + 14, 25)).multiplyScalar(1000); fill.target.position.set(0, 0, 0);
    fill.intensity = S.lowLight ? 1.5 : S.earthEl > 0 ? .75 : .45;
    fill.color.set(S.lowLight ? 0xbfe3cf : 0xb8cbe8);
    tag.textContent = S.lowLight ? "LOW-LIGHT CAMERA" : "";
    hab.userData.wing.rotation.y = Math.atan2(sd.x, sd.z);                         // arrays track the Sun
    hab.userData.dish.lookAt(hab.userData.dish.getWorldPosition(new THREE.Vector3()).add(ed.clone().multiplyScalar(100)));
    hab.userData.dish.rotateX(Math.PI / 2);
    S.sunDir = sd; S.earthDir = ed;
  }
  function placeShadow() { csm.lightDirection.copy(S.sunDir || skyDir(1, 0)).negate(); csm.update(); }

  // ---- rover on its route ----
  function routeDir(task) {
    const t = TARGETS[task];
    if (t && t.lat != null) { const [sx, sy] = polar(S.meta.lat, S.meta.lon), [tx, ty] = polar(t.lat, t.lon); return new THREE.Vector3(tx - sx, 0, -(ty - sy)).normalize(); }
    if (t && t.local) return new THREE.Vector3(t.local[0], 0, t.local[1]).normalize();
    return S.rover.heading.clone();
  }
  const PARK = new THREE.Vector3(14, 0, 9);
  function routePoint(d, dir) {   // a gently wandering line, starting at the rover park beside the hab
    const side = new THREE.Vector3(-dir.z, 0, dir.x), w = Math.sin(d / 260) * Math.min(1, d / 200) * 40;
    return PARK.clone().addScaledVector(dir, d).addScaledVector(side, w);
  }
  function placeRover(dt) {
    const R = S.rover; if (!S.meta) return;
    const before = R.d;
    if (reduced() || dt === 0) R.d = R.dGoal; else R.d += Math.sign(R.dGoal - R.d) * Math.min(Math.abs(R.dGoal - R.d), Math.max(4, Math.abs(R.dGoal - R.d) * 1.2) * dt);
    const p = routePoint(R.d, R.heading), ahead = routePoint(R.d + (R.dGoal >= R.d ? 3 : -3), R.heading);
    p.y = heightAt(p.x, p.z); ahead.y = heightAt(ahead.x, ahead.z);
    rv.position.copy(p); rv.lookAt(ahead.x, p.y + (ahead.y - p.y), ahead.z);
    const moved = R.d - before; rv.userData.wheels.forEach(w => { w.rotation.x += moved / .42; });
    R.moving = Math.abs(moved) > .01;
  }
  function drawTrack() {
    const R = S.rover, pts = [];
    if (R.busy && S.meta) for (let i = 0; i <= 80; i++) { const p = routePoint(R.dMax * i / 80, R.heading); p.y = heightAt(p.x, p.z) + .3; pts.push(p); }
    track.geometry.dispose(); track.geometry = new THREE.BufferGeometry().setFromPoints(pts.length ? pts : [new THREE.Vector3(), new THREE.Vector3()]);
    track.computeLineDistances(); track.visible = pts.length > 0;
  }

  // ---- cameras ----
  const pose = (pos, look, fov) => ({ pos, look, fov });
  function sitePose(t) {
    // hovering ~190 m out and 60 m up, looking past the outpost toward the Earth side, drifting slowly round it
    const base = Math.PI + .45, a = base + (reduced() ? 0 : t * .012), r = 64;
    const pos = new THREE.Vector3(Math.sin(a) * r + 10, 0, -Math.cos(a) * r + 6);
    pos.y = Math.max(heightAt(pos.x, pos.z) + 8, hab.position.y + 17);
    return pose(pos, new THREE.Vector3(Math.sin(a) * -18 + 10, hab.position.y + 5, Math.cos(a) * 18 + 6), 44);
  }
  function roverPose() {
    const fwd = new THREE.Vector3(0, 0, 1).applyQuaternion(rv.quaternion); fwd.y = 0; fwd.normalize();
    // chase camera: low, just above the mast, the rover in the lower third and the route ahead
    const pos = rv.position.clone().addScaledVector(fwd, -6.2); pos.y = Math.max(heightAt(pos.x, pos.z) + 1.4, rv.position.y + 2.5);
    const look = rv.position.clone().addScaledVector(fwd, 26); look.y = rv.position.y + (heightAt(look.x, look.z) - rv.position.y) * .35 + .2;
    return pose(pos, look, 38);
  }
  function earthPose() {
    // a long lens from the hab: Earth above the lunar skyline when it is up, the skyline where it hides when not
    const pos = new THREE.Vector3(-12, hab.position.y + 7, -6), el = S.earthEl;
    const look = pos.clone().add(skyDir(el > -1.5 ? el - 1.6 : 0, 0).multiplyScalar(1000));
    return pose(pos, look, 9);
  }
  function descentStart() {
    const ed = skyDir(0, 0); const pos = ed.clone().multiplyScalar(-26000); pos.y = hab.position.y + 14000;
    return pose(pos, new THREE.Vector3(0, hab.position.y, 0), 52);
  }
  const target = () => S.view === "rover" ? roverPose() : S.view === "earth" ? earthPose() : sitePose((performance.now() - S.t0) / 1000);
  function apply(p) { camera.position.copy(p.pos); camera.lookAt(p.look); if (Math.abs(camera.fov - p.fov) > .01) { camera.fov = p.fov; camera.updateProjectionMatrix(); csm.updateFrustums(); } S.cam = { pos: p.pos.clone(), look: p.look.clone(), fov: p.fov }; }
  function poseNow() { apply(target()); S.tween = null; }
  /** Fly the camera from where it is to the new view; long hops arc upward like a hopper. */
  function flyTo(from, dur) {
    if (reduced() || !from) { poseNow(); return; }
    S.tween = { from: { pos: from.pos.clone(), look: from.look.clone(), fov: from.fov }, t0: performance.now(), dur };
  }

  // ---- render loop (only while the window shows a surface view) ----
  let raf = 0, last = performance.now();
  const tmp = new THREE.Vector3();
  function project(el, p, show) {
    if (!show) { el.style.visibility = "hidden"; return; }
    tmp.copy(p).project(camera);
    const on = tmp.z < 1 && Math.abs(tmp.x) < 1.05 && Math.abs(tmp.y) < 1.05;
    el.style.visibility = on ? "" : "hidden";
    if (on) el.style.transform = `translate(${((tmp.x + 1) / 2 * W).toFixed(1)}px,${((1 - tmp.y) / 2 * H).toFixed(1)}px)`;
  }
  let W = 1, H = 1;
  function frame(now) {
    raf = requestAnimationFrame(frame);
    const dt = Math.min(.1, (now - last) / 1000); last = now;
    S.frames.push(now); while (S.frames.length && now - S.frames[0] > 2000) S.frames.shift();
    if (!S.meta) return;
    placeRover(dt);
    let p = target();
    if (S.tween) {
      const k = Math.min(1, (now - S.tween.t0) / S.tween.dur), e = ease(k), f = S.tween.from;
      const hop = Math.sin(Math.PI * e) * Math.min(4000, f.pos.distanceTo(p.pos) * .35);
      p = pose(f.pos.clone().lerp(p.pos, e).add(new THREE.Vector3(0, hop, 0)), f.look.clone().lerp(p.look, e), f.fov + (p.fov - f.fov) * e);
      if (k >= 1) S.tween = null;
    }
    apply(p);
    sky.position.copy(camera.position);
    placeShadow();
    const blink = (Math.sin(now / 260) > .6) || reduced();
    hab.userData.beacon.visible = blink; rv.userData.beacon.visible = S.rover.busy && (Math.sin(now / 200 + 1) > .2 || reduced());
    hab.userData.lamp.intensity = S.sunEl < 0 ? 60 : 0;
    bloom.intensity = (S.storm ? 2.2 : 1.1) * (S.view === "earth" ? .7 : 1);
    composer.render(dt);
    project(mHab, tmp.set(0, hab.position.y + 14, 0).clone(), S.view !== "earth");
    project(mRover, rv.position.clone().add(new THREE.Vector3(0, 4, 0)), S.view === "site" && S.rover.busy);
    project(mEarth, camera.position.clone().addScaledVector(S.earthDir, 1e5), S.earthEl > -2 && S.view !== "earth");
    project(mSun, camera.position.clone().addScaledVector(S.sunDir, 1e5).add(new THREE.Vector3(0, 0, 0)), S.sunEl > -1 && S.view !== "earth");
  }
  function resize() {
    W = host.clientWidth || 1; H = host.clientHeight || 1;
    renderer.setSize(W, H, false); composer.setSize(W, H); camera.aspect = W / H; camera.updateProjectionMatrix(); csm.updateFrustums();
  }
  new ResizeObserver(resize).observe(host); resize();
  document.addEventListener("visibilitychange", () => { if (document.hidden) { cancelAnimationFrame(raf); raf = 0; } else if (S.visible && !raf) { last = performance.now(); raf = requestAnimationFrame(frame); } });

  const api = {
    get view() { return S.view; },
    get ready() { return !!S.meta; },
    setSite,
    /** v: site | rover | earth. `from`: "orbit" starts the SITE descent from altitude. */
    async setView(v, { from } = {}) {
      const prevCam = S.cam && S.visible ? S.cam : null;
      S.view = v; S.visible = true; host.classList.add("is-surface");
      if (S.loading) await S.loading;
      if (!raf) { last = performance.now(); raf = requestAnimationFrame(frame); }
      if (from === "orbit" || !prevCam) {
        if (v === "site" && !reduced()) { S.t0 = performance.now(); flyTo(descentStart(), 7000); }
        else if (!reduced() && v !== "site") { flyTo(descentStart(), 5200); }
        else poseNow();
      } else flyTo(prevCam, v === "earth" || S.view === "earth" ? 2600 : 3000);
    },
    /** Leave the surface (back to ORBIT): climb for a moment, then stop rendering. */
    hide() {
      host.classList.remove("is-surface"); S.visible = false;
      setTimeout(() => { if (!S.visible && raf) { cancelAnimationFrame(raf); raf = 0; } }, reduced() ? 0 : 900);
    },
    setSun(elDeg, timeH) { S.sunEl = +elDeg || 0; S.sunLon = sunLon(timeH); aimSky(); },
    setEarth(elDeg) { if (elDeg == null) return; S.earthEl = +elDeg; aimSky(); },
    /** Rover from sim state: {busy, task, eta_h}; `elapsedH` = hours of telemetry since that state. */
    setRover(r = {}, elapsedH = 0) {
      const R = S.rover, t = TARGETS[r.task] || TARGETS.explore, busy = !!r.busy;
      if (busy && r.task !== "return") R.heading = routeDir(r.task);
      R.busy = busy; R.task = r.task;
      R.dMax = (t.km || 1.5) * 1000;
      if (!busy) R.dGoal = 0;
      else {
        const eta = Math.max(0, (r.eta_h || 0) - elapsedH), f = 1 - eta / t.total;
        R.dGoal = r.task === "return" ? Math.min(R.d || R.dMax * .6, R.dMax) * Math.min(1, eta / t.total) : R.dMax * (f < .5 ? f * 2 : (1 - f) * 2);
      }
      if (!S.visible || !S.meta) { R.d = R.dGoal; placeRover(0); }
      drawTrack();
    },
    setStorm(on) { S.storm = !!on; },
    get fps() { const f = S.frames; return f.length > 1 ? Math.round((f.length - 1) / ((f[f.length - 1] - f[0]) / 1000)) : 0; },
    get earthAbove() { return S.earthEl > 0; },
    get debug() { return { S, camera, terrain, sun, earthshine, hab, rv, renderer }; },
    dispose() { cancelAnimationFrame(raf); renderer.dispose(); canvas.remove(); marks.remove(); },
  };
  return api;
}
