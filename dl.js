// Download buttons (the Mac <a data-mac>, every Windows <a data-win>): never a link that 404s, and always the version.
// Releases go Mac first and Windows follows (docs/RELEASING.md), so the newest release may have no .exe yet. The HTML
// points at the stable asset of the latest release. On load we ask the GitHub API for the releases (newest first, up
// to 300) and link each button to the newest published release that really carries its file, showing that version on
// the button ("0.3.8"). No release has it -> the Windows build guide / the Releases page. The API fails or is
// rate-limited -> keep the stable link, no version. A click before the answer arrives waits for it (at most 4 s).
(() => {
  const REPO = "WhissleAI/Outpost-Luna";
  const RELEASES = `https://github.com/${REPO}/releases`;
  const KINDS = {
    mac: { asset: "Outpost-Luna-mac-arm64.dmg", sel: "a[data-mac]", fallback: { href: RELEASES, label: "Mac: see all releases" } },
    win: { asset: "Outpost-Luna-win-x64.exe", sel: "a[data-win]",
      fallback: { href: `https://github.com/${REPO}/blob/main/docs/BUILD_WINDOWS.md`, label: "Windows: build guide" } },
  };
  const PER_PAGE = 100, MAX_PAGES = 3;

  /** The newest usable release carrying `asset` (published first, then a pre-release), or null. Pure: tested. */
  function pick(releases, asset) {
    const pub = (Array.isArray(releases) ? releases : []).filter((r) => r && !r.draft);
    const has = (r) => (r.assets || []).find((a) => a && a.name === asset && a.browser_download_url);
    const r = pub.find((x) => !x.prerelease && has(x)) || pub.find(has);
    if (!r) return null;
    const latest = pub.find((x) => !x.prerelease);
    return { href: has(r).browser_download_url, version: String(r.tag_name || "").replace(/^v/i, ""), latest: r === latest };
  }

  /** What each button becomes, from the release list (or null: the API failed). Pure: tested. */
  function plan(releases, kind) {
    const k = KINDS[kind];
    if (!releases) return { state: "assumed" };
    const p = pick(releases, k.asset);
    if (!p) return { state: "fallback", href: k.fallback.href, label: k.fallback.label };
    return { state: p.latest ? "latest" : "release", href: p.href, version: p.version };
  }

  /** Every page we may need: stop at a short page, or once every kind has a release with its file. */
  async function fetchReleases(fetchFn, signal) {
    let all = [];
    for (let page = 1; page <= MAX_PAGES; page++) {
      const res = await fetchFn(`https://api.github.com/repos/${REPO}/releases?per_page=${PER_PAGE}&page=${page}`, {
        headers: { Accept: "application/vnd.github+json" }, signal });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const rels = await res.json();
      if (!Array.isArray(rels)) throw new Error("unexpected reply");
      all = all.concat(rels);
      if (rels.length < PER_PAGE || Object.values(KINDS).every((k) => pick(all, k.asset))) break;
    }
    return all;
  }

  if (typeof module === "object" && module.exports) module.exports = { pick, plan, fetchReleases, KINDS };
  if (typeof document === "undefined") return;

  const buttons = Object.keys(KINDS).flatMap((kind) => [...document.querySelectorAll(KINDS[kind].sel)].map((a) => ({ a, kind })));
  if (!buttons.length) return;

  const apply = (rels) => {
    const out = {};
    for (const { a, kind } of buttons) {
      const r = (out[kind] = out[kind] || plan(rels, kind));
      a.dataset.dlState = r.state;
      if (r.href) a.href = r.href;
      if (r.label) {
        const span = a.querySelector("[data-win-label],[data-mac-label]");
        if (span) span.textContent = r.label; else a.textContent = r.label;
      }
      const ver = a.querySelector("[data-ver]");
      if (ver && r.version) { ver.textContent = r.version; ver.hidden = false; a.title = `Version ${r.version}`; }
    }
  };

  const ctl = "AbortController" in window ? new AbortController() : null;
  const timer = setTimeout(() => ctl && ctl.abort(), 4000);
  const ready = fetchReleases(fetch.bind(window), ctl ? ctl.signal : undefined)
    .catch(() => null)
    .then((rels) => { clearTimeout(timer); apply(rels); });

  for (const { a } of buttons) {
    a.addEventListener("click", (e) => {
      if (a.dataset.dlState || e.metaKey || e.ctrlKey || e.shiftKey || e.button) return;
      e.preventDefault();
      ready.then(() => { location.href = a.href; });
    });
  }
})();
