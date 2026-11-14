import { defineConfig } from "vite";

// Dev: Vite serves the UI on :5173 and forwards API and media calls to the backend.
// Prod: `npm run build` → dist/, which the backend serves itself.
const backend = process.env.BACKEND_URL || "http://127.0.0.1:8100";

export default defineConfig({
  // pre-bundle three + its addons + postprocessing together, so dev never loads two copies of three
  optimizeDeps: { include: ["three", "three/examples/jsm/controls/OrbitControls.js", "three/examples/jsm/csm/CSM.js", "postprocessing"] },
  // [gestures] the vision worker is an ES module: MediaPipe's module WASM loader (public/vision/, bundled offline by
  // tools/fetch_vision.mjs) only loads in a module worker. docs/GESTURES.md.
  worker: { format: "es" },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": backend,
      "/media": backend,
      "/ws": { target: backend.replace(/^http/, "ws"), ws: true },
    },
  },
});
