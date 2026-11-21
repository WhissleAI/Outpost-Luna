// Render check for the open-data viewer (no app, no server): node tests/fixtures/render_open_data.mjs <out.html>
// writes a static page with the real Archaeology charts (chartView), a layer key (legendHtml) and the app's CSS tokens,
// for a headless-browser screenshot (docs/MEDIA.md "Open data": how the PR's screenshots were made).
import { readFileSync, writeFileSync } from "node:fs";
import { parseChart } from "../../src/media/chart.js";
import { chartView, legendHtml, normalizeLibrary } from "../../src/field_library.js";

const base = new URL("../../../backend/data/courses/archaeology/", import.meta.url);
const lib = JSON.parse(readFileSync(new URL("library.json", base), "utf8"));
const css = ["tokens.css", "field_library.css"].map(f => readFileSync(new URL(`../../src/${f}`, import.meta.url), "utf8")).join("\n");
const data = lib.shelves.find(s => s.id === "data").items;
const panels = data.map(it => {
  if (it.kind === "layer") {
    const L = normalizeLibrary({ shelves: [{ id: "d", title: "d", items: [{ ...it, url: `/api/courses/archaeology/media/${it.file}` }] }] });
    return `<aside class="flv" style="position:relative;left:0;top:0;width:620px;margin:16px"><header class="flv-head"><h2>${it.title}</h2></header>
      <div class="flv-body">${legendHtml(L.items.get(it.id))}</div></aside>`;
  }
  const ch = parseChart(readFileSync(new URL(`media/${it.file}`, base), "utf8"), it.file);
  return `<aside class="flv" style="position:relative;left:0;top:0;width:620px;max-height:none;margin:16px"><header class="flv-head"><h2>${it.title}</h2></header>
    <div class="flv-body">${chartView(it, ch)}</div><p class="flv-credit">credit line</p></aside>`;
}).join("");
writeFileSync(process.argv[2], `<!doctype html><meta charset="utf-8"><style>${css}
  body{margin:0;background:#05070b;color:#f3f5f8;font-family:system-ui;display:flex;flex-wrap:wrap}</style><body data-mode="cadet">${panels}</body>`);
