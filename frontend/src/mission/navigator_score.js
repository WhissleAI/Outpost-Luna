// The landing-site navigator's score (docs/SITE_NAVIGATOR.md). Mirrors backend/app/mission/navigator.py: the same
// criteria, ranges and presets (backend/tests/test_navigator.py and frontend/tests/navigator.test.js check the same cases).
// NASA's own criteria for the Artemis III regions: power (sunlight), talking to Earth, ice access, a safe landing.

export const CRITERIA = Object.freeze({
  power: { field: "sunlight_pct", lo: 30, hi: 90, better: "high", label: "Power", icon: "sun" },
  comms: { field: "earth_pct", lo: 0, hi: 100, better: "high", label: "Talk to Earth", icon: "earth" },
  ice: { field: "ice_km", lo: 0, hi: 15, better: "low", label: "Ice nearby", icon: "ice" },
  safety: { field: "slope_deg", lo: 0, hi: 15, better: "low", label: "Safe landing", icon: "site" },
});
export const CRITERIA_IDS = Object.freeze(Object.keys(CRITERIA));

export const PRESETS = Object.freeze({
  balanced: { power: 1, comms: 1, ice: 1, safety: 1 },
  power_first: { power: 3, comms: 1, ice: 1, safety: 1 },
  ice_first: { power: 1, comms: 1, ice: 3, safety: 1 },
  comms_first: { power: 1, comms: 3, ice: 1, safety: 1 },
  safety_first: { power: 1, comms: 1, ice: 1, safety: 3 },
});
export const PRESET_LABEL = Object.freeze({ balanced: "Balanced", power_first: "Power first", ice_first: "Ice first",
  comms_first: "Radio first", safety_first: "Safe landing first" });

const clamp01 = v => Math.max(0, Math.min(1, v));

/** 0..1 (1 = best) for one criterion of one place. A missing number scores 0. */
export function criterion(place, id) {
  const c = CRITERIA[id], f = place && place[c.field], v = f && f.value;
  if (v == null || !Number.isFinite(+v)) return 0;
  const t = clamp01((+v - c.lo) / (c.hi - c.lo));
  return c.better === "high" ? t : 1 - t;
}

/** Python's round(): half to even, so both sides give the same integer. */
function roundHalfEven(x) {
  const r = Math.round(x);
  return Math.abs(x % 1) === 0.5 && r % 2 !== 0 ? r - 1 : r;
}

/** 0..100: the weighted mean of the four criteria (weights 0..3; all zero counts as balanced). */
export function score(place, weights = PRESETS.balanced) {
  let w = Object.fromEntries(CRITERIA_IDS.map(k => [k, Math.max(0, +((weights || {})[k] ?? 1) || 0)]));
  if (!CRITERIA_IDS.some(k => w[k] > 0)) w = { ...PRESETS.balanced };
  const tot = CRITERIA_IDS.reduce((s, k) => s + w[k], 0);
  return roundHalfEven(100 * CRITERIA_IDS.reduce((s, k) => s + w[k] * criterion(place, k), 0) / tot);
}

/** The place that wins one question: most sunlight / Earth, least ice distance / slope; "best" = the top score. */
export function bestFor(places, what, weights) {
  const list = (places || []).filter(Boolean);
  if (!list.length) return null;
  if (what === "best") return list.reduce((a, b) => (score(b, weights) > score(a, weights) ? b : a));
  const id = { sunlight: "power", earth: "comms", ice: "ice", slope: "safety" }[what];
  if (!id) return null;
  const c = CRITERIA[id], ok = list.filter(p => p[c.field] && p[c.field].value != null);
  if (!ok.length) return null;
  return ok.reduce((a, b) => {
    const va = +a[c.field].value, vb = +b[c.field].value;
    return (c.better === "high" ? vb > va : vb < va) ? b : a;
  });
}

/** The preset a set of weights is, or null (sliders moved by hand). */
export function presetOf(weights) {
  return Object.keys(PRESETS).find(k => CRITERIA_IDS.every(c => +PRESETS[k][c] === +(weights || {})[c])) || null;
}

/** A place name, short: "Shackleton Rim", "de Gerlache Rim". */
export const short = n => String(n || "").replace(/ Crater /, " ").split(" (")[0];

export const LAYER_SAY = {
  sunlight: "Sunlight map. Yellow spots get the most Sun all year.",
  slope: "Slope map. Green is flat. Red is too steep to land.",
  ice: "Ice map. Blue never sees the Sun. White is cold enough for ice.",
  earth: "Earth view map. Bright blue sees Earth the most.",
  off: "Plain map.",
};
export const TAG = {
  nasa_2024: "On NASA's 2024 Artemis III list",
  dropped_2022: "Studied, dropped (NASA's 2022 list)",
  studied: "Studied by scientists",
};

/** One number, kid-sized: "87%", "2.9 km", "11°", "64 h". */
export function fmt(p, key) {
  const f = p && p[key]; const v = f && f.value;
  if (v == null) return "–";
  if (key === "sunlight_pct" || key === "earth_pct") return `${Math.round(v)}%`;
  if (key === "ice_km" || key === "psr_km") return v < 0.15 ? "here" : `${(+v).toFixed(1)} km`;
  if (key === "slope_deg") return `${Math.round(v)}°`;
  if (key === "longest_dark_h") return v >= 8760 ? "never lit" : v >= 72 ? `${(v / 24).toFixed(1)} days` : `${v} h`;
  return String(v);
}

/** The spoken answer to "which site has the most ice?" (≤ 20 words). */
export function queryLine(p, what) {
  const n = short(p.name);
  const fly = p.playable ? "Say take command to fly it." : "It's on NASA's list. We can't fly it yet.";
  if (what === "ice") return `${n}. ${p.ice_km.value < 0.15 ? "Ice can last right there" : `Ice can last ${fmt(p, "ice_km")} away`}. ${fly}`;
  if (what === "sunlight") return `${n}. Sun ${fmt(p, "sunlight_pct")} of the year. ${fly}`;
  if (what === "earth") return `${n}. Earth in view ${fmt(p, "earth_pct")} of the time. ${fly}`;
  if (what === "slope") return `${n}. Only ${fmt(p, "slope_deg")} of slope. ${fly}`;
  return `${n} scores best right now. ${fly}`;
}

