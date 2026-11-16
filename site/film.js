// Launch-video slot (index.html, <figure data-film>). The figure shows the Moon still today. To ship the video, add the
// files below to site/ and publish; no HTML or JS edits are needed:
//
//   site/media/outpost-luna.mp4          the film: H.264 + AAC, 16:9 (1920x1080 or 1280x720), "faststart" (moov first)
//   site/media/outpost-luna-poster.jpg   its poster: a 16:9 still, about 1600x900 (optional; the Moon still is the fallback)
//   site/media/outpost-luna.vtt          English captions, WebVTT (optional, recommended)
//
// On load we ask for the mp4 with a HEAD request. If it is there, the still is swapped for a <video> with controls in the
// same 16:9 frame (no layout shift). It never autoplays, and preload="none" keeps the page light until someone presses play.
(() => {
  const fig = document.querySelector("[data-film]");
  if (!fig || !("fetch" in window)) return;
  const base = fig.dataset.film;                       // "media/outpost-luna"
  const has = (u) => fetch(u, { method: "HEAD", cache: "no-cache" }).then((r) => r.ok).catch(() => false);

  has(`${base}.mp4`).then(async (ok) => {
    if (!ok) return;
    const [poster, vtt] = await Promise.all([has(`${base}-poster.jpg`), has(`${base}.vtt`)]);
    const still = fig.querySelector("img");
    const v = document.createElement("video");
    v.controls = true;
    v.playsInline = true;
    v.preload = "none";
    v.poster = poster ? `${base}-poster.jpg` : (still && (still.currentSrc || still.src)) || "";
    v.setAttribute("aria-label", fig.dataset.filmLabel || "Outpost Luna film");
    const src = document.createElement("source");
    src.src = `${base}.mp4`;
    src.type = "video/mp4";
    v.append(src);
    if (vtt) {
      const t = document.createElement("track");
      Object.assign(t, { kind: "captions", srclang: "en", label: "English", src: `${base}.vtt` });
      v.append(t);
    }
    // A clear cover: the poster plus one big play button. Native controls appear once it plays.
    v.controls = false;
    const play = document.createElement("button");
    play.type = "button";
    play.className = "film-play";
    play.setAttribute("aria-label", `Play the ${fig.dataset.filmLabel || "film"}${fig.dataset.filmLength ? ` (${fig.dataset.filmLength})` : ""}`);
    play.innerHTML = `<span class="film-play-dot" aria-hidden="true"><svg viewBox="0 0 24 24" width="34" height="34"><path fill="currentColor" d="M8 5.5v13a1 1 0 0 0 1.5.86l10.4-6.5a1 1 0 0 0 0-1.72L9.5 4.64A1 1 0 0 0 8 5.5Z"/></svg></span>` +
      `<span class="film-play-label">Watch the film${fig.dataset.filmLength ? ` · ${fig.dataset.filmLength}` : ""}</span>`;
    const start = () => { fig.dataset.filmState = "playing"; v.controls = true; v.play().catch(() => {}); };
    play.addEventListener("click", start);
    v.addEventListener("play", () => { fig.dataset.filmState = "playing"; v.controls = true; });
    v.addEventListener("ended", () => { fig.dataset.filmState = "video"; });
    fig.querySelector(".frame").replaceChildren(v, play);
    fig.dataset.filmState = "video";
    const cap = fig.querySelector("figcaption");
    if (cap && fig.dataset.filmCaption) cap.textContent = fig.dataset.filmCaption;
  });
})();
