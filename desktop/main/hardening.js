// Electron hardening, in one place (docs/SECURITY.md "The desktop shell", docs/SCHOOL_IT.md). No Electron import:
// main.js applies these, hardening.test.js checks them (and that main.js uses them for every window).
//
//   WEB_PREFS      every window: sandboxed, context-isolated, no Node in the page, no <webview>, no spell-check (on
//                  Windows Chromium would download its dictionaries from Google), no navigation by drag and drop
//   CHROMIUM_OFF   Chromium features off by switch: the media router (Cast discovery over mDNS / SSDP / DIAL on the
//                  local network) and its relatives. The app never looks for other devices.
//   csp(origin)    the page's Content-Security-Policy, added to every response from our origin by the session:
//                  scripts only from our origin (+ WebAssembly for the gesture models), no inline script, frames only
//                  the YouTube embed, connections only to our origin, no plugins, no <base>, no framing by others
//   navigation(url, origin)   will-navigate: "ours" stays; everything else is stopped, and a web link we allow opens in
//                  the system browser ("youtube" behind the grown-up gate)
//   linkAllowed(url)  which links may open in the system browser at all: the science and NASA sites the app cites, our
//                  own repo and site (https); never a file:, a custom scheme or an unknown host
"use strict";

const WEB_PREFS = Object.freeze({ sandbox: true, contextIsolation: true, nodeIntegration: false, nodeIntegrationInWorker: false,
  nodeIntegrationInSubFrames: false, webviewTag: false, spellcheck: false, navigateOnDragDrop: false, safeDialogs: true,
  webSecurity: true, allowRunningInsecureContent: false, experimentalFeatures: false });

const CHROMIUM_OFF = ["MediaRouter", "DialMediaRouteProvider", "CastMediaRouteProvider", "GlobalMediaControlsCastStartStop"];

const YT_EMBED = "https://www.youtube-nocookie.com";

function csp(origin) {
  const ws = origin.replace(/^http/, "ws");
  return [
    "default-src 'self'",
    "script-src 'self' 'wasm-unsafe-eval'",
    "worker-src 'self' blob:",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "media-src 'self' data: blob:",
    "font-src 'self' data:",
    `connect-src 'self' ${ws} data: blob:`,
    `frame-src ${YT_EMBED}`,
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
  ].join("; ");
}

// The sites the app's sources and credits link to (backend/data, frontend/src), by registrable domain.
// [0.5.6] and the Archaeology course's (backend/data/courses/archaeology: sources, credits, places). None were listed, so
// every web source in that course was a dead click ("link refused (not on the list)", owner playtest 0.5.5). The test
// (hardening.test.js) reads every course file and fails on a cited link that is not here.
const LINK_HOSTS = ["nasa.gov", "usgs.gov", "noaa.gov", "nih.gov", "doi.org", "wustl.edu", "unh.edu", "ucla.edu", "mit.edu",
  "dlr.de", "esa.int", "im-ldi.com", "apollojournals.org",
  // Archaeology: US agencies, the law, the data sources and the archaeology sites it cites
  "nps.gov", "usda.gov", "nationalmap.gov", "achp.gov", "ecfr.gov", "federalregister.gov", "law.cornell.edu",
  "copernicus.eu", "naturalearthdata.com", "naciscdn.org", "element84.com", "opendata.aws", "p3k14c.org",
  "crowcanyon.org", "saa.org", "radiocarbon.com", "whoi.edu", "forestresearch.gov.uk"];
const OUR_REPO = "/whissleai/outpost-luna";
// [0.5.6] a cited dataset on GitHub that is not ours (p3k14c, the radiocarbon dates): its repo only, never all of GitHub
const CITED_REPOS = ["/people3k/p3k14c"];

function linkAllowed(url) {
  let u; try { u = new URL(url); } catch { return false; }
  if (!/^https?:$/.test(u.protocol) || u.username || u.password) return false;
  const h = u.hostname.toLowerCase();
  // a few cited data sources are http only (imbrium.mit.edu); our own pages must be https
  if (u.protocol === "http:" && (h === "github.com" || h === "whissleai.github.io")) return false;
  const under = (pth, root) => pth === root || pth.startsWith(root + "/");
  if (h === "github.com") return u.protocol === "https:" && [OUR_REPO, ...CITED_REPOS].some(r => under(u.pathname.toLowerCase(), r));
  if (h === "raw.githubusercontent.com") return u.protocol === "https:" && CITED_REPOS.some(r => under(u.pathname.toLowerCase(), r));
  if (h === "whissleai.github.io") return u.pathname === "/Outpost-Luna" || u.pathname.startsWith("/Outpost-Luna/");
  return LINK_HOSTS.some((d) => h === d || h.endsWith("." + d));
}

function sameOrigin(url, origin) { try { return new URL(url).origin === origin; } catch { return false; } }

/** -> "ours" | "youtube" | "external" | "refuse": what a navigation or a new window may become. */
function navigation(url, origin, classify) {
  if (sameOrigin(url, origin)) return "ours";
  const kind = classify ? classify(url, origin) : null;
  if (kind === "youtube") return "youtube";
  return linkAllowed(url) ? "external" : "refuse";
}

module.exports = { WEB_PREFS, CHROMIUM_OFF, csp, linkAllowed, navigation, sameOrigin, LINK_HOSTS, CITED_REPOS };
