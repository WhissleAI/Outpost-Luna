// Outpost Luna desktop: "Export playtest" (Settings -> For grown-ups -> Playtest session, docs/DIRECTOR_LOOP.md §1b).
// No Electron import: main.js passes the app hooks in, and playtest.test.js drives it with a fake backend.
//
// The page navigates to /__outpost/playtest-export; main.js stops that, asks the grown-up where to save (a save
// dialog), gets the zip from the backend (POST /api/playtest/export with the app version only the shell knows: turn
// log + the playtest's audio clips + manifest.json) and writes it there. Nothing is ever uploaded. The playtest itself
// lives in the backend process, so it is off again whenever the app quits.
"use strict";
const fs = require("fs");

const EXPORT_PATH = "/__outpost/playtest-export";

const isExportUrl = (url, origin) => { try { const u = new URL(url); return u.origin === origin && u.pathname === EXPORT_PATH; } catch { return false; } };
const day = (t) => { const d = new Date(t); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; };
const defaultName = (t = Date.now()) => `outpost-luna-playtest-${day(t)}.zip`;

/** POST the app version to the backend, write the zip it returns to `file` (via a .part file). Returns the bytes. */
async function saveExport({ backend, token, appVersion, file, fetchFn = fetch }) {
  const r = await fetchFn(`${backend}/api/playtest/export`, { method: "POST",
    headers: { "Content-Type": "application/json", "X-Luna-Token": token }, body: JSON.stringify({ app_version: appVersion }) });
  if (!r.ok) throw new Error(`the backend answered ${r.status}`);
  const buf = Buffer.from(await r.arrayBuffer());
  if (buf.length < 22 || buf.readUInt32LE(0) !== 0x04034b50) throw new Error("the backend did not send a zip");
  fs.writeFileSync(file + ".part", buf);
  fs.renameSync(file + ".part", file);
  return buf.length;
}

module.exports = { EXPORT_PATH, isExportUrl, defaultName, saveExport };
