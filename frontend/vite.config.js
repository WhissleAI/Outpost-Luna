import { defineConfig } from "vite";

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
