import { defineConfig } from "vite";
import { resolve } from "node:path";

// Dev: Vite serves the UI on :5173 and forwards API and media calls to the backend.
// Prod: `npm run build` → dist/, which the backend serves itself.
const backend = process.env.BACKEND_URL || "http://127.0.0.1:8100";

export default defineConfig({
  server: {
    port: 5173,
    strictPort: true,
    proxy: { "/api": backend, "/media": backend },
  },
  build: {
    rollupOptions: {
      input: { main: resolve(__dirname, "index.html"), about: resolve(__dirname, "about.html") },
    },
  },
});
