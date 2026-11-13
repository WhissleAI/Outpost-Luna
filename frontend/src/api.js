// Fetch wrappers for the backend contract (docs/CONTRACT.md). Moments come only from the server.

async function getJSON(url, opts) {
  const r = await fetch(url, opts);
  if (!r.ok) throw new Error(url + " " + r.status);
  return r.json();
}

/** Server moment → client shape (`clip` alias, places as ids, jargon sorted). */
export function normMoment(m) {
  if (!m) return null;
  return {
    ...m,
    clip_id: m.clip_id || m.clip,
    places: (m.places || []).map(p => (typeof p === "string" ? p : p.id)),
    jargon: (m.jargon || []).filter(j => j && j.explain).sort((a, b) => a.t - b.t),
    t0: +m.t0 || 0,
    t1: m.t1 != null ? +m.t1 : null,
  };
}

/** Hardware kind for an artifact's marker colour: the backend's type field if it has one, else a guess from the text. */
export function hwType(a) {
  const t = String(a.type || a.category || a.hardware || "").toLowerCase();
  for (const k of ["lander", "rover", "impact", "instrument", "memorial"]) if (t.includes(k)) return k;
  const s = `${a.name} ${a.status || ""} ${a.what_it_did || ""}`.toLowerCase();
  if (/rover|buggy|lunokhod|yutu|pragyan/.test(s)) return "rover";
  if (/impact|crash/.test(s)) return "impact";
  if (/memorial|plaque|figure|fallen/.test(s)) return "memorial";
  if (/mirror|retroreflector|seismometer|experiment|instrument|package|alsep/.test(s)) return "instrument";
  return "lander";
}

const clipCache = new Map();
const momentCache = new Map();

export const api = {
  async places() {
    const j = await getJSON("/api/places");
    return j.places.map(p => ({ ...p, kind: p.kind === "artifact" ? "artifact" : "feature", km: +p.diameter_km || 0, est: p.estimated,
      ...(p.kind === "artifact" ? { hw: hwType(p) } : {}) }));
  },
  /** Ranked kid-safe moments for a place (best first), or all when place is null. */
  moments(place) {
    const key = place || "*";
    if (!momentCache.has(key)) {
      const url = "/api/moments" + (place ? "?place=" + encodeURIComponent(place) : "");
      momentCache.set(key, getJSON(url).then(j => (j.moments || []).filter(m => m.kid_safe !== false).map(normMoment))
        .catch(() => { momentCache.delete(key); return []; }));
    }
    return momentCache.get(key);
  },
  /** One clip's words, tags and utterances (for karaoke + place-following). */
  clip(id) {
    if (!clipCache.has(id)) clipCache.set(id, getJSON("/api/clips/" + encodeURIComponent(id)).catch(e => { clipCache.delete(id); throw e; }));
    return clipCache.get(id);
  },
  ask(text, context) {
    return getJSON("/api/ask", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text, context }) });
  },
};
