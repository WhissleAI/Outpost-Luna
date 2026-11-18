// A small turntable for one 3D model (0.4 nasa_views): drag to turn, it spins slowly by itself (not with reduced
// motion), and it draws only while `running`. Shared by the Library's Moon rocks tray (rocks_tray.js) and the Field
// School rock step (academy/field_steps.js). The models are the pack's GLBs (NASA/Astromaterials 3D, CC0).
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { loadModel } from "./nasa_views.js";

/**
 * @param {HTMLCanvasElement} canvas  sized by its parent
 * @returns {{show(url): Promise<boolean>, start(), stop(), size(), dispose()}}
 */
export function createTurntable(canvas) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(32, 1, 0.01, 50); camera.position.set(0, 0.6, 3);
  scene.add(new THREE.HemisphereLight(0xeef2ff, 0x2a2622, 0.9 * Math.PI));
  const key = new THREE.DirectionalLight(0xfff2e0, 1.6 * Math.PI); key.position.set(3, 4, 2); scene.add(key);
  const controls = new OrbitControls(camera, canvas);
  Object.assign(controls, { enablePan: false, enableDamping: true, minDistance: 1.4, maxDistance: 6, autoRotate: true, autoRotateSpeed: 1.2 });
  let current = null, raf = 0, running = false, seq = 0;

  function size() {
    const r = canvas.parentElement.getBoundingClientRect();
    renderer.setSize(Math.max(1, r.width), Math.max(1, r.height), false); camera.aspect = r.width / Math.max(1, r.height); camera.updateProjectionMatrix();
  }
  function loop() {
    if (!running || !canvas.isConnected) { raf = 0; return; }
    controls.autoRotate = document.documentElement.dataset.motion !== "reduce";
    controls.update(); renderer.render(scene, camera); raf = requestAnimationFrame(loop);
  }
  /** Load and centre a GLB (the same url loads once: nasa_views caches it). False if it didn't load or a newer
   *  show() came first. */
  async function show(url) {
    const my = ++seq;
    const obj = await loadModel(url);
    if (my !== seq) return false;
    if (current) scene.remove(current);
    const box = new THREE.Box3().setFromObject(obj), dim = box.getSize(new THREE.Vector3()), c = box.getCenter(new THREE.Vector3());
    const k = 1.6 / Math.max(dim.x, dim.y, dim.z, 1e-6);
    obj.scale.setScalar(k); obj.position.copy(c.multiplyScalar(-k));
    current = new THREE.Group(); current.add(obj); scene.add(current);
    camera.position.set(0, 0.6, 3); controls.target.set(0, 0, 0);
    return true;
  }
  return {
    show, size,
    start() { running = true; size(); if (!raf) raf = requestAnimationFrame(loop); },
    stop() { running = false; },
    get hasModel() { return !!current; },
    dispose() { running = false; seq++; controls.dispose(); renderer.dispose(); },
  };
}
