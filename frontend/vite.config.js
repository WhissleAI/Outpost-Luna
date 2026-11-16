import { defineConfig } from "vite";
import { readFileSync } from "node:fs";

// The About drawer shows this (frontend/package.json "version", bumped with every release).
const APP_VERSION = JSON.parse(readFileSync(new URL("./package.json", import.meta.url), "utf8")).version;

// Dev: Vite serves the UI on :5173 and forwards API and media calls to the backend.
// Prod: `npm run build` → dist/, which the backend serves itself.
const backend = process.env.BACKEND_URL || "http://127.0.0.1:8100";
// [#84] `make dev` runs the servers with a per-run LUNA_TOKEN (docs/SECURITY.md): the dev server hands the page the
// same HttpOnly cookie the desktop shell sets, so every proxied /api POST and /ws socket carries it. No token: nothing.
const token = process.env.LUNA_TOKEN || "";
const devToken = {
  name: "luna-dev-token",
  configureServer(server) {
    server.middlewares.use((req, res, next) => {
      if (token && req.method === "GET" && !["cross-site", "same-site"].includes(req.headers["sec-fetch-site"])) {
        res.setHeader("Set-Cookie", `luna_token=${token}; Path=/; HttpOnly; SameSite=Strict`);
      }
      next();
    });
  },
};

export default defineConfig({
  plugins: [devToken],
  define: { __APP_VERSION__: JSON.stringify(APP_VERSION) },
  // pre-bundle three + its addons + postprocessing together, so dev never loads two copies of three
  optimizeDeps: { include: ["three", "three/examples/jsm/controls/OrbitControls.js", "three/examples/jsm/csm/CSM.js", "postprocessing"] },
  // [gestures] the vision worker is an ES module: MediaPipe's module WASM loader (public/vision/, bundled offline by
  // tools/fetch_vision.mjs) only loads in a module worker. docs/GESTURES.md.
  worker: { format: "es" },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      // [#84] changeOrigin off (the string shorthand turns it on): the backend sees the page's own Host, so a POST's
      // Origin (http://localhost:<vite port>) is same-origin for its Origin check (backend/app/local_guard.py)
      "/api": { target: backend, changeOrigin: false },
      "/media": { target: backend, changeOrigin: false },
      "/ws": { target: backend.replace(/^http/, "ws"), ws: true },
    },
  },
});
