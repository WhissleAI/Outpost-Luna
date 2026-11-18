// The first-run screen's numbers (firstrun.html): the overall total and percent, the speed and the time left, from the
// per-asset state main.js sends ({assets: [{id, title, size, done, state}]}). Pure and offline: no Electron, no DOM.
// Loaded by the page as a classic script (window.FirstRunProgress) and by node --test (module.exports).
"use strict";
(function (root) {
  /** MB with one decimal under 10 (so 2.5 MB/s, not 3), else whole; GB at 1,000 MB and over. */
  function bytes(b) {
    const mb = Math.max(0, +b || 0) / 1e6;
    if (mb >= 1000) return `${(mb / 1000).toFixed(mb >= 10000 ? 0 : 1)} GB`;
    return `${mb < 10 ? mb.toFixed(1).replace(/\.0$/, "") : Math.round(mb)} MB`;
  }

  /** Overall progress: an installed asset counts as all its bytes; done never exceeds size. */
  function summarize(assets) {
    let total = 0, done = 0;
    for (const a of assets || []) {
      const size = Math.max(0, +a.size || 0);
      total += size;
      done += a.state === "installed" ? size : Math.min(size, Math.max(0, +a.done || 0));
    }
    const pct = total ? Math.min(100, Math.floor((100 * done) / total)) : 0;
    return { total, done, left: total - done, pct, complete: total > 0 && done >= total };
  }

  /**
   * Speed over a sliding window (default 8 s) of (time, bytes done) samples. Bytes going down (an asset re-checked,
   * an import restarting) restart the window. -> { add(t, done), speed() bytes/s or 0, reset() }.
   */
  function createRate({ windowMs = 8000, minSpanMs = 1500 } = {}) {
    let pts = [];
    return {
      add(t, done) {
        const last = pts[pts.length - 1];
        if (last && done < last.done) pts = [];
        pts.push({ t, done });
        while (pts.length > 2 && t - pts[0].t > windowMs) pts.shift();
      },
      speed() {
        if (pts.length < 2) return 0;
        const a = pts[0], b = pts[pts.length - 1], span = b.t - a.t;
        return span >= minSpanMs && b.done > a.done ? ((b.done - a.done) * 1000) / span : 0;
      },
      reset() { pts = []; },
    };
  }

  /** "about 3 min left", "under a minute left", "about 1 h 20 min left"; "" when the speed is unknown. */
  function eta(leftBytes, speed) {
    if (!(speed > 0) || !(leftBytes > 0)) return "";
    const s = leftBytes / speed;
    if (s < 60) return "under a minute left";
    const m = Math.round(s / 60);
    if (m < 60) return `about ${m} min left`;
    const h = Math.floor(m / 60), r = m % 60;
    return `about ${h} h${r ? ` ${r} min` : ""} left`;
  }

  /** The headline lines for the screen: "312 MB of 510 MB · 61%" and "4.2 MB/s · about 1 min left". */
  function lines(sum, speed) {
    const top = sum.total ? `${bytes(sum.done)} of ${bytes(sum.total)} · ${sum.pct}%` : "";
    const rate = speed > 0 && !sum.complete ? `${bytes(speed)}/s` : "";
    const left = sum.complete ? "" : eta(sum.left, speed);
    return { top, rate: [rate, left].filter(Boolean).join(" · ") };
  }

  const api = { bytes, summarize, createRate, eta, lines };
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.FirstRunProgress = api;
})(typeof window !== "undefined" ? window : globalThis);
