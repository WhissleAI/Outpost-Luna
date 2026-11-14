// Writes an HTML contact sheet of every icon and patch (light, dark, high contrast) to the path given.
//   node src/assets/contact-sheet.mjs out.html [tokens.css]
// Render it to docs/img/art/contact-sheet.jpg with headless Chromium (see docs/img/art/README in the PR).
import fs from "node:fs";
import { icon, iconNames, patch, patchIds, PATCHES } from "./icons.js";

const [out, tokensPath] = process.argv.slice(2);
const tokens = tokensPath ? fs.readFileSync(tokensPath, "utf8") : "";
const themes = [["Light", 'data-theme="light"'], ["Dark", 'data-theme="dark"'], ["High contrast", 'data-theme="dark" data-contrast="high"']];

const iconCell = n => `<figure class="ic-cell">${icon(n, { size: 32 })}${icon(n, { size: 20 })}<figcaption>${n}</figcaption></figure>`;
const accentRow = () => `<div class="row">${["mic", "play", "next", "check-circle", "warning", "alert"].map((n, i) =>
  `<span class="btn ${["accent", "plain", "plain", "ok", "warn", "danger"][i]}">${icon(n, { size: 20 })}${n}</span>`).join("")}
  <span class="btn-icon">${icon("close", { size: 20, title: "Close" })}</span><span class="btn-icon">${icon("settings", { size: 20, title: "Settings" })}</span></div>`;
const patchCell = id => `<figure class="p-cell">
  <div class="p-big">${patch(id, { size: 160 })}</div>
  <div class="p-small">${patch(id, { size: 40 })}${patch(id, { size: 40, earned: false })}${patch(id, { size: 64, earned: false })}</div>
  <figcaption><b>${PATCHES[id].name}</b><span>${id}${PATCHES[id].kind === "mission" ? " · mission" : ""}</span></figcaption></figure>`;

const html = `<!doctype html><html><head><meta charset="utf-8"><title>Outpost Luna art</title><style>
${tokens.replace(/:root/g, ".th")}
body{margin:0;font:14px/1.4 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;background:#888}
.th{background:var(--color-bg);color:var(--color-text);padding:28px 32px 32px}
h1{margin:0 0 4px;font-size:24px} h2{margin:22px 0 10px;font-size:13px;letter-spacing:.08em;text-transform:uppercase;color:var(--color-text-3)}
.grid{display:grid;grid-template-columns:repeat(13,1fr);gap:6px}
.ic-cell{margin:0;padding:10px 4px 6px;background:var(--color-surface);border:1px solid var(--color-line);border-radius:10px;display:flex;flex-direction:column;align-items:center;gap:6px}
.ic-cell svg:first-child{color:var(--color-text)} .ic-cell svg+svg{color:var(--color-text-2)}
.ic-cell figcaption{font:11px ui-monospace,Menlo,monospace;color:var(--color-text-3)}
.row{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
.btn{display:inline-flex;align-items:center;gap:8px;height:44px;padding:0 16px;border-radius:10px;font-weight:600;background:var(--color-surface-2);border:1px solid var(--color-line-strong)}
.btn.accent{background:var(--color-accent);color:var(--color-on-accent);border-color:transparent}
.btn.ok{color:var(--color-success)} .btn.warn{color:var(--color-warning)} .btn.danger{color:var(--color-danger)}
.btn-icon{display:inline-grid;place-items:center;width:44px;height:44px;border-radius:10px;border:1px solid var(--color-line-strong);background:var(--color-surface)}
.pgrid{display:grid;grid-template-columns:repeat(5,1fr);gap:12px}
.p-cell{margin:0;padding:14px;background:var(--color-surface);border:1px solid var(--color-line);border-radius:16px;display:flex;flex-direction:column;align-items:center;gap:10px}
.p-small{display:flex;gap:10px;align-items:center}
.p-cell figcaption{text-align:center;display:flex;flex-direction:column} .p-cell figcaption span{font:11px ui-monospace,Menlo,monospace;color:var(--color-text-3)}
.space{background:var(--color-space);border-radius:16px;padding:14px;display:flex;gap:14px;align-items:center;color:var(--color-on-space-2)}
</style></head><body>
${themes.map(([name, attrs]) => `<section class="th" ${attrs}>
  <h1>Outpost Luna art · ${name}</h1>
  <h2>UI icons · 32px and 20px · currentColor</h2><div class="grid">${iconNames().map(iconCell).join("")}</div>
  <h2>In buttons (44px targets)</h2>${accentRow()}
  <h2>Patches · 160px earned · 40px earned and locked · 64px locked</h2><div class="pgrid">${patchIds().map(patchCell).join("")}</div>
  <h2>Earned shelf on the cabin's always-dark space surface · 40px</h2>
  <div class="space">${patchIds().map(id => patch(id, { size: 40, earned: id.length % 3 !== 0 })).join("")}</div>
</section>`).join("")}
</body></html>`;
fs.writeFileSync(out, html);
console.log("wrote", out);
