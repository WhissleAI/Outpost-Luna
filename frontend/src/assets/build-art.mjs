// Outpost Luna art build: draws the patch SVGs and bundles every icon + patch into ./icons.js (offline, no fetches).
//
//   node src/assets/build-art.mjs          (from frontend/) writes patches/*.svg and icons.js
//   node src/assets/build-art.mjs --check  exits 1 if icons.js or a patch file is stale (the tests run this)
//
// Icons: the SVG files in ./icons are the source (Lucide, ISC, plus a few originals on the same 24px/2px grid).
// Patches: drawn here from simple shapes on a 160px grid, in an embroidered style: a satin-stitched border
// (merrowed edge), a twill field, a running stitch, and one bold emblem. Locked = dashed outline + grey silhouette.
// Inspired by crew mission patches; deliberately no agency logos, insignia or lettering.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));

// ---------- fixed patch palette (thread colours; reads on light, dark and high-contrast backgrounds) ----------
export const PALETTE = {
  navy: "#1A2B4C", deep: "#0E1A30", blue: "#2C5AA0", sky: "#5B9BE6", ice: "#A9DDF3",
  white: "#F3EFE4", paper: "#DCD5C3", gold: "#F0B43C", orange: "#E86F2C", red: "#C73A2E",
  moon: "#BCC3CE", moondk: "#7F8898", foot: "#55606F", green: "#4FA46A",
};
const P = PALETTE;
const LOCKED_GREY = "#7D8796";

// ---------- tiny element model ----------
// role: "e" emblem (kept as a silhouette when locked), "d" detail / "g" ground (dropped when locked)
const el = (t, a, role = "e", c) => ({ t, a, role, c });
const g = (a, c, role = "e") => el("g", a, role, c);
const circle = (cx, cy, r, fill, role, extra = {}) => el("circle", { cx, cy, r, fill, ...extra }, role);
const pathEl = (d, fill, role, extra = {}) => el("path", { d, fill, ...extra }, role);
const line = (d, stroke, w, role, extra = {}) => el("path", { d, fill: "none", stroke, "stroke-width": w, "stroke-linecap": "round", "stroke-linejoin": "round", ...extra }, role);
const f = n => +n.toFixed(2);

function star5(cx, cy, r, fill, role) {
  const pts = [];
  for (let i = 0; i < 10; i++) {
    const a = -Math.PI / 2 + (i * Math.PI) / 5, rr = i % 2 ? r * 0.45 : r;
    pts.push(`${f(cx + rr * Math.cos(a))} ${f(cy + rr * Math.sin(a))}`);
  }
  return pathEl(`M${pts.join("L")}Z`, fill, role, { "stroke-linejoin": "round" });
}
const sparkle = (cx, cy, r, fill, role) =>
  pathEl(`M${cx} ${cy - r}Q${cx} ${cy} ${cx + r} ${cy}Q${cx} ${cy} ${cx} ${cy + r}Q${cx} ${cy} ${cx - r} ${cy}Q${cx} ${cy} ${cx} ${cy - r}Z`, fill, role);
// the part of circle 1 outside circle 2 (a crescent), as one path
function crescent(x1, y1, r1, x2, y2, r2, fill, role) {
  const d = Math.hypot(x2 - x1, y2 - y1), a = (r1 * r1 - r2 * r2 + d * d) / (2 * d), h = Math.sqrt(r1 * r1 - a * a);
  const mx = x1 + (a * (x2 - x1)) / d, my = y1 + (a * (y2 - y1)) / d;
  const px = (h * (y2 - y1)) / d, py = (h * (x2 - x1)) / d;
  const A = [f(mx + px), f(my - py)], B = [f(mx - px), f(my + py)];
  return pathEl(`M${A[0]} ${A[1]}A${r1} ${r1} 0 1 0 ${B[0]} ${B[1]}A${r2} ${r2} 0 0 1 ${A[0]} ${A[1]}Z`, fill, role);
}
// arc on a circle centred (cx,cy), from angle a0 to a1 (degrees, screen coords: 0 = right, 90 = down), clockwise
function arc(cx, cy, r, a0, a1) {
  const p = a => [f(cx + r * Math.cos((a * Math.PI) / 180)), f(cy + r * Math.sin((a * Math.PI) / 180))];
  const [x0, y0] = p(a0), [x1, y1] = p(a1);
  return `M${x0} ${y0}A${r} ${r} 0 ${a1 - a0 > 180 ? 1 : 0} 1 ${x1} ${y1}`;
}

// ---------- outlines ----------
const C = 80;
function shieldD(i) { // i = inset from the outer edge
  return `M80 ${6 + i}L${146 - i} ${26 + i * 0.3}V78C${146 - i} ${116 - i * 0.6} ${118 - i * 0.6} ${140 - i} 80 ${154 - i * 1.15}`
    + `C${42 + i * 0.6} ${140 - i} ${14 + i} ${116 - i * 0.6} ${14 + i} 78V${26 + i * 0.3}Z`;
}
const roundD = r => `M${C - r} ${C}a${r} ${r} 0 1 0 ${2 * r} 0a${r} ${r} 0 1 0 ${-2 * r} 0Z`;
const OUTLINE = {
  round: { outer: roundD(76), field: roundD(68), mid: roundD(72), stitch: roundD(63.5) },
  shield: { outer: shieldD(0), field: shieldD(8), mid: shieldD(4), stitch: shieldD(12.5) },
};
// ground (a horizon at y0 bulging up by `bulge`), drawn past the field edge; the border ring covers the overhang
function ground(shape, y0, bulge, fill) {
  if (shape === "round") {
    const r = 72, dx = f(Math.sqrt(r * r - (y0 - C) ** 2));
    return pathEl(`M${C - dx} ${y0}Q${C} ${y0 - 2 * bulge} ${C + dx} ${y0}A${r} ${r} 0 0 1 ${C - dx} ${y0}Z`, fill, "g");
  }
  // shield: follow the mid outline below y0 (sampled), then the horizon curve back
  const pts = sampleShield(4).filter(p => p[1] >= y0);
  const right = pts.filter(p => p[0] >= C).sort((a, b) => a[1] - b[1]);
  const left = pts.filter(p => p[0] < C).sort((a, b) => b[1] - a[1]);
  const xr = right[0][0], xl = left[left.length - 1][0];
  return pathEl(`M${f(xl)} ${y0}Q${C} ${y0 - 2 * bulge} ${f(xr)} ${y0}` + [...right, ...left].map(p => `L${f(p[0])} ${f(p[1])}`).join("") + "Z", fill, "g");
}
function sampleShield(i) {
  const cub = (p0, p1, p2, p3) => Array.from({ length: 41 }, (_, k) => {
    const t = k / 40, u = 1 - t;
    return [0, 1].map(j => u * u * u * p0[j] + 3 * u * u * t * p1[j] + 3 * u * t * t * p2[j] + t * t * t * p3[j]);
  });
  const R = [[146 - i, 78], [146 - i, 116 - i * 0.6], [118 - i * 0.6, 140 - i], [80, 154 - i * 1.15]];
  const right = cub(...R);
  const side = Array.from({ length: 21 }, (_, k) => [146 - i, 30 + (48 * k) / 20]);
  const r = [...side, ...right];
  return [...r, ...r.map(([x, y]) => [160 - x, y])];
}

// ---------- the patches ----------
// One per Flight School lesson (ids from backend/data/academy/course.json), plus mission patches.
export const PATCHES = {
  moon: { name: "Moon Scout", badge: "scout", kind: "lesson", shape: "round", border: P.gold, field: P.navy, emblem: moonScout },
  comms: { name: "Radio Ready", badge: "radio", kind: "lesson", shape: "round", border: P.white, field: P.blue, emblem: radioReady },
  power: { name: "Sun Tracker", badge: "sun", kind: "lesson", shape: "round", border: P.orange, field: P.navy, emblem: sunTracker },
  radiation: { name: "Storm Watcher", badge: "storm", kind: "lesson", shape: "shield", border: P.red, field: P.deep, emblem: stormWatcher },
  life: { name: "Ice Hunter", badge: "ice", kind: "lesson", shape: "round", border: P.ice, field: P.navy, emblem: iceHunter },
  history: { name: "Historian", badge: "history", kind: "lesson", shape: "round", border: P.blue, field: P.moon, stitch: P.gold, emblem: historian },
  words: { name: "Word Explorer", badge: "words", kind: "lesson", shape: "round", border: P.sky, field: P.navy, emblem: wordExplorer },
  checkride: { name: "Mission Commander", badge: "commander", kind: "lesson", shape: "shield", border: P.gold, field: P.navy, emblem: commander },
  storm_survivor: { name: "Storm Survivor", kind: "mission", shape: "round", border: P.red, field: P.deep, emblem: stormSurvivor },
  outpost_luna: { name: "Outpost Luna", kind: "mission", shape: "round", border: P.gold, field: P.deep, emblem: outpostLuna },
};

function moonScout(s) {
  const tilt = { transform: "rotate(-18 80 84)" };
  return [
    g(tilt, [line("M22 84A58 17 0 0 1 138 84", P.white, 3.5, "e", { opacity: 0.55 })]),
    circle(80, 84, 38, P.moon),
    pathEl("M80 46A38 38 0 0 1 80 122A24 38 0 0 0 80 46Z", P.moondk, "d"),
    circle(64, 72, 7.5, P.moondk, "d"), circle(88, 100, 9, P.moondk, "d"), circle(68, 105, 4.5, P.moondk, "d"), circle(92, 66, 4, P.moondk, "d"),
    g(tilt, [line("M22 84A58 17 0 0 0 138 84", P.white, 5)]),
    circle(132, 70, 6.5, P.gold, "e", { transform: "rotate(-18 80 84)" }),
    sparkle(40, 46, 7, P.white), sparkle(118, 38, 5, P.white), sparkle(44, 124, 4.5, P.white),
  ];
}
function radioReady(s) {
  const c = [70, 78];
  return [
    ground(s, 114, 7, P.moon),
    ...[13, 23, 33].map(r => line(arc(c[0], c[1], r, -72, -18), P.gold, 5.5)),
    circle(112, 44, 14, P.sky),
    pathEl("M104 36c5-4 11-2 12 3s-3 6-1 10-5 6-8 2-6-11-3-15Z", P.green, "d"),
    pathEl("M115 52c3-2 6-1 6 1", "none", "d", { stroke: P.white, "stroke-width": 2.5, "stroke-linecap": "round" }),
    g({ transform: "rotate(-38 62 92)" }, [
      pathEl("M38 92A24 24 0 0 0 86 92Z", P.white),
      line("M62 92V72", P.white, 3.5), circle(62, 70, 4, P.white),
    ]),
    line("M64 100V114", P.white, 6), line("M54 116H74", P.white, 5),
    sparkle(36, 52, 6, P.white), sparkle(94, 26, 4.5, P.white),
  ];
}
function sunTracker(s) {
  const rays = Array.from({ length: 12 }, (_, k) => {
    const a = (k * Math.PI) / 6, r0 = 26, r1 = k % 2 ? 32 : 37;
    return `M${f(80 + r0 * Math.cos(a))} ${f(56 + r0 * Math.sin(a))}L${f(80 + r1 * Math.cos(a))} ${f(56 + r1 * Math.sin(a))}`;
  }).join("");
  return [
    ground(s, 134, 4, P.moon),
    line(rays, P.gold, 5),
    circle(80, 56, 20, P.gold),
    circle(80, 56, 13, P.orange, "d", { opacity: 0.55 }),
    line("M80 118V134", P.moondk, 6),
    pathEl("M40 96H120L110 120H50Z", P.blue, "e", { stroke: P.white, "stroke-width": 3, "stroke-linejoin": "round" }),
    line("M60 96L63.3 120M80 96V120M100 96L96.7 120M45 108H115", P.white, 2, "d", { opacity: 0.75 }),
  ];
}
function stormWatcher(s) {
  return [
    ground(s, 124, 4, P.moondk),
    line(arc(80, 58, 26, 200, 340), P.orange, 5),             // prominence loop
    circle(80, 58, 20, P.orange),
    circle(73, 52, 6, P.gold, "d", { opacity: 0.85 }),
    line("M64 82C58 94 46 100 34 104", P.gold, 5),
    line("M80 88V100", P.gold, 5), line("M80 110V112", P.gold, 5),
    line("M96 82C102 94 114 100 126 104", P.gold, 5),
    sparkle(36, 40, 5.5, P.white), sparkle(124, 40, 5.5, P.white),
  ];
}
function iceHunter(s) {
  const arm = a => {
    const r = Math.PI / 180, cx = 80, cy = 68, L = 36, b = 21, bl = 11;
    const ex = cx + L * Math.cos(a * r), ey = cy + L * Math.sin(a * r);
    const bx = cx + b * Math.cos(a * r), by = cy + b * Math.sin(a * r);
    const br = d => `M${f(bx)} ${f(by)}L${f(bx + bl * Math.cos((a + d) * r))} ${f(by + bl * Math.sin((a + d) * r))}`;
    return `M${cx} ${cy}L${f(ex)} ${f(ey)}${br(40)}${br(-40)}`;
  };
  return [
    ground(s, 116, 5, P.moon),
    pathEl("M50 128A30 8 0 0 1 110 128A30 8 0 0 1 50 128Z", P.deep, "d"),
    line([-90, -30, 30, 90, 150, 210].map(arm).join(""), P.white, 6),
    pathEl("M80 58L88.7 63V73L80 78L71.3 73V63Z", P.ice, "d"),
    sparkle(66, 128, 4, P.ice), sparkle(96, 127, 3, P.ice),
  ];
}
function historian(s) {
  const T = "rotate(-12 80 74) translate(80 74) scale(.86) translate(-80 -74)";
  return [
    g({ transform: T }, [
      pathEl("M80 22C99 22 106 40 104 56C102 69 96 75 96 86C96 100 101 110 93 119C86 127 74 127 67 119C59 110 64 100 64 86C64 75 58 69 56 56C54 40 61 22 80 22Z", P.foot),
      line("M69 36H91M63 47H97M62 58H98M65 69H95M70 96H90M70 107H90", P.moon, 5, "d"),
    ]),
    star5(62, 136, 6.5, P.gold), star5(80, 139, 6.5, P.gold), star5(98, 136, 6.5, P.gold),
  ];
}
function wordExplorer(s) {
  return [
    crescent(78, 62, 25, 91, 55, 21, P.gold),
    line("M58 96L53 89M80 98V91M102 96L107 89", P.gold, 3.5),
    pathEl("M80 106C68 98 50 96 34 100V130C50 126 68 128 80 136Z", P.white),
    pathEl("M80 106C92 98 110 96 126 100V130C110 126 92 128 80 136Z", P.paper),
    line("M43 109C53 107 63 108 72 112M43 118C53 116 63 117 72 121M88 112C97 108 107 107 117 109M88 121C97 117 107 116 117 118", P.moondk, 2.5, "d"),
    sparkle(116, 40, 6.5, P.white), sparkle(44, 44, 5, P.white),
  ];
}
function commander(s) {
  return [
    ground(s, 128, 4, P.moon),
    pathEl("M64 82L48 102V112L64 102Z", P.red), pathEl("M96 82L112 102V112L96 102Z", P.red),
    pathEl("M73 104C73 116 80 124 80 132C80 124 87 116 87 104Z", P.orange),
    pathEl("M76.5 104C76.5 111 80 116 80 121C80 116 83.5 111 83.5 104Z", P.gold, "d"),
    pathEl("M70 96H90L87 104H73Z", P.moondk),
    pathEl("M80 26C95 38 99 60 97 96H63C61 60 65 38 80 26Z", P.white),
    pathEl("M70.5 40H89.5C88 36 84.5 31 80 27C75.5 31 72 36 70.5 40Z", P.red, "d"),
    circle(80, 62, 8.5, P.sky, "d", { stroke: P.blue, "stroke-width": 3 }),
    line("M80 74V92", P.paper, 2.5, "d"),
    star5(44, 52, 8, P.gold), star5(116, 52, 8, P.gold),
  ];
}
function stormSurvivor(s) {
  const rays = Array.from({ length: 10 }, (_, k) => {
    const a = Math.PI + (k * Math.PI) / 9, r0 = 18, r1 = k % 2 ? 23 : 28;
    return `M${f(80 + r0 * Math.cos(a))} ${f(42 + r0 * Math.sin(a))}L${f(80 + r1 * Math.cos(a))} ${f(42 + r1 * Math.sin(a))}`;
  }).join("");
  return [
    ground(s, 120, 3, P.moon),
    line(rays, P.orange, 4.5),
    circle(80, 42, 14, P.orange),
    line("M58 58C50 66 40 70 28 72M102 58C110 66 120 70 132 72", P.gold, 4.5),
    line(arc(80, 120, 40, 180, 360), P.ice, 6),
    pathEl("M56 120A24 24 0 0 1 104 120Z", P.white),
    pathEl("M74 120V110A6 6 0 0 1 86 110V120Z", P.navy, "d"),
    star5(80, 138, 7, P.gold),
  ];
}
function outpostLuna(s) {
  const dots = Array.from({ length: 10 }, (_, k) => {
    const a = (200 + (k * 140) / 9) * (Math.PI / 180);
    return circle(f(80 + 57 * Math.cos(a)), f(80 + 57 * Math.sin(a)), 3.2, P.white);
  });
  return [
    ...dots,
    circle(110, 66, 15, P.sky),
    pathEl("M102 58c5-4 11-2 12 3s-3 6-1 10-5 6-8 2-6-11-3-15Z", P.green, "d"),
    ground(s, 106, 6, P.moon),
    pathEl("M44 112A20 20 0 0 1 84 112Z", P.white),
    pathEl("M58 112V104A6 6 0 0 1 70 104V112Z", P.navy, "d"),
    line("M98 104V120", P.moondk, 4),
    pathEl("M86 88H112L108 104H90Z", P.blue, "e", { stroke: P.white, "stroke-width": 2.5, "stroke-linejoin": "round" }),
    line("M64 92V70", P.white, 3), pathEl("M64 70H80L75 75L80 80H64Z", P.gold),
  ];
}

// ---------- serialise ----------
const attr = a => Object.entries(a).filter(([, v]) => v !== undefined).map(([k, v]) => ` ${k}="${v}"`).join("");
function ser(e, locked) {
  if (locked && e.role !== "e") return "";
  let a = e.a;
  if (locked) {
    a = { ...a };
    if (a.fill && a.fill !== "none") a.fill = "currentColor";
    if (a.stroke && a.stroke !== "none") a.stroke = "currentColor";
    delete a.opacity;
  }
  if (e.t === "g") return `<g${attr(a)}>${e.c.map(x => ser(x, locked)).join("")}</g>`;
  return `<${e.t}${attr(a)}/>`;
}
const shade = (hex, k) => "#" + [1, 3, 5].map(i => Math.round(parseInt(hex.slice(i, i + 2), 16) * k).toString(16).padStart(2, "0")).join("");

export function patchInner(id, earned) {
  const p = PATCHES[id], o = OUTLINE[p.shape];
  const emblem = p.emblem(p.shape);
  if (!earned) {
    return `<path d="${o.mid}" fill="none" stroke="currentColor" stroke-width="3" stroke-dasharray="7 6" stroke-linecap="round"/>`
      + `<g opacity=".7">${emblem.map(e => ser(e, true)).join("")}</g>`;
  }
  const stitch = p.stitch || (p.border === P.navy ? P.gold : P.white);
  return [
    `<path d="${o.field}" fill="${p.field}"/>`,
    `<path d="${o.stitch}" fill="none" stroke="${stitch}" stroke-width="1.6" stroke-dasharray="3.5 3" stroke-linecap="round" opacity=".55"/>`,
    ...emblem.map(e => ser(e, false)),
    // merrowed border: the ring, satin-stitch ticks, and a dark hem so it holds on white
    `<path d="${o.outer} ${o.field}" fill="${p.border}" fill-rule="evenodd"/>`,
    `<path d="${o.mid}" fill="none" stroke="${shade(p.border, 0.72)}" stroke-width="7" stroke-dasharray="1 1.8" opacity=".55"/>`,
    `<path d="${o.outer}" fill="none" stroke="#0B1222" stroke-opacity=".45" stroke-width="1.5"/>`,
    `<path d="${o.field}" fill="none" stroke="#0B1222" stroke-opacity=".35" stroke-width="1"/>`,
  ].join("");
}
export const patchFile = (id, earned) =>
  `<svg xmlns="http://www.w3.org/2000/svg" width="160" height="160" viewBox="0 0 160 160"${earned ? "" : ` color="${LOCKED_GREY}"`}>`
  + `<title>${PATCHES[id].name}${earned ? "" : " (locked)"}</title>${patchInner(id, earned)}</svg>\n`;

// ---------- icons ----------
export function readIcons() {
  const dir = path.join(HERE, "icons"), out = {};
  for (const fn of fs.readdirSync(dir).filter(n => n.endsWith(".svg")).sort()) {
    const s = fs.readFileSync(path.join(dir, fn), "utf8");
    const m = s.match(/<svg[^>]*>([\s\S]*?)<\/svg>/);
    if (!m) throw new Error("bad svg " + fn);
    out[fn.slice(0, -4)] = m[1].replace(/\s*\n\s*/g, "").replace(/\s+\/>/g, "/>").trim();
  }
  return out;
}

export function buildIconsJs() {
  const icons = readIcons();
  const patches = {};
  for (const id of Object.keys(PATCHES)) {
    const p = PATCHES[id];
    patches[id] = { name: p.name, kind: p.kind, shape: p.shape, ...(p.badge ? { badge: p.badge } : {}), earned: patchInner(id, true), locked: patchInner(id, false) };
  }
  const tpl = fs.readFileSync(path.join(HERE, "icons.template.js"), "utf8");
  return tpl
    .replace("/*@ICONS@*/{}", JSON.stringify(icons, null, 0).replace(/","/g, '",\n  "').replace(/^\{/, "{\n  ").replace(/\}$/, "\n}"))
    .replace("/*@PATCHES@*/{}", JSON.stringify(patches, null, 1));
}

if (process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1])) {
  const check = process.argv.includes("--check");
  const want = { [path.join(HERE, "icons.js")]: buildIconsJs() };
  for (const id of Object.keys(PATCHES)) {
    want[path.join(HERE, "patches", `${id}.svg`)] = patchFile(id, true);
    want[path.join(HERE, "patches", `${id}-locked.svg`)] = patchFile(id, false);
  }
  let stale = 0;
  for (const [fp, s] of Object.entries(want)) {
    const cur = fs.existsSync(fp) ? fs.readFileSync(fp, "utf8") : null;
    if (cur === s) continue;
    if (check) { console.error("stale:", path.relative(HERE, fp)); stale++; }
    else { fs.mkdirSync(path.dirname(fp), { recursive: true }); fs.writeFileSync(fp, s); }
  }
  if (check && stale) { console.error("run: node src/assets/build-art.mjs"); process.exit(1); }
  console.log(check ? "art up to date" : `wrote ${Object.keys(want).length} files`);
}
