// Windows download links (every <a data-win>): never a link that 404s.
// The HTML points at the stable asset of the latest release. On load we ask the GitHub API which recent release
// carries it: latest has it -> keep; an older (or pre-) release has it -> link that file; none -> the build guide;
// the API fails -> the Releases page. A click before the answer arrives waits for it (at most 4 s).
(() => {
  const REPO = "WhissleAI/Outpost-Luna";
  const ASSET = "Outpost-Luna-win-x64.exe";
  const GUIDE = `https://github.com/${REPO}/blob/main/docs/BUILD_WINDOWS.md`;
  const RELEASES = `https://github.com/${REPO}/releases/latest`;
  const links = [...document.querySelectorAll("a[data-win]")];
  if (!links.length) return;

  const setLabel = (a, text) => {
    const span = a.querySelector("[data-win-label]");
    if (span) span.textContent = text; else a.textContent = text;
  };
  const apply = (r) => {
    for (const a of links) {
      a.href = r.href;
      if (r.label) setLabel(a, r.label);
      a.dataset.winState = r.state;
    }
    return r;
  };

  const ctl = "AbortController" in window ? new AbortController() : null;
  const timer = setTimeout(() => ctl && ctl.abort(), 4000);
  const ready = fetch(`https://api.github.com/repos/${REPO}/releases?per_page=5`, {
    headers: { Accept: "application/vnd.github+json" }, signal: ctl ? ctl.signal : undefined,
  })
    .then((res) => { if (!res.ok) throw new Error(`HTTP ${res.status}`); return res.json(); })
    .then((rels) => {
      if (!Array.isArray(rels)) throw new Error("unexpected reply");
      const pub = rels.filter((r) => !r.draft);
      const asset = (r) => (r.assets || []).find((a) => a.name === ASSET);
      const latest = pub.find((r) => !r.prerelease);
      if (latest && asset(latest)) return { state: "latest", href: links[0].getAttribute("href") };
      const older = pub.find(asset);
      if (older) return { state: "release", href: asset(older).browser_download_url };
      return { state: "guide", href: GUIDE, label: "Windows: build guide" };
    })
    .catch(() => ({ state: "releases", href: RELEASES, label: "Windows: all releases" }))
    .then((r) => { clearTimeout(timer); return apply(r); });

  for (const a of links) {
    a.addEventListener("click", (e) => {
      if (a.dataset.winState || e.metaKey || e.ctrlKey || e.shiftKey || e.button) return;
      e.preventDefault();
      ready.then((r) => { location.href = r.href; });
    });
  }
})();
