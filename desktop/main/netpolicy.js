// School network mode in the desktop shell (docs/SCHOOL_IT.md). No Electron import: unit-tested with node --test.
//
// The policy is the same as the servers' (backend/app/netgate.py, model_server/app/netgate.py):
//   machine  an IT admin's policy.json (OUTPOST_POLICY_FILE; the install folder on Windows; /Library/Application Support/
//            Outpost Luna on macOS; %ProgramData%\Outpost Luna on Windows; /etc/outpost-luna on Linux) and the
//            OUTPOST_SCHOOL_NETWORK / OUTPOST_ALLOW_HOSTS variables. When it turns the mode on, it is locked on.
//            main.js resolves it once and hands it to both servers as LUNA_NET_POLICY (their environment is an
//            allow-list, so the variables would not reach them otherwise).
//   user     <userData>/network.json, written by the backend when a grown-up flips Settings -> For grown-ups ->
//            School network. The shell re-reads it when it changes.
// A policy file that is there but unreadable fails closed: on, nothing allowed.
//
// Enforced in the shell in two places, one per kind of traffic:
//   the page   session.webRequest (permissions.js lockDownSession, `policy`): a request off our origin to a host the
//              policy does not allow is cancelled before it leaves (the YouTube embed included).
//   the shell  gateFetch wraps globalThis.fetch, which every main-process download uses (first-run assets, optional
//              assets, asset and app update checks): a blocked host throws {kind: "school", offline: true} before any
//              request, and every redirect hop is checked too.
"use strict";
const fs = require("fs");
const path = require("path");

const POLICY_NAME = "policy.json";
const USER_NAME = "network.json";

/** Where an IT admin's policy.json is looked for, in order. */
function machinePaths({ platform = process.platform, env = process.env, execPath = process.execPath } = {}) {
  const out = [];
  if (env.OUTPOST_POLICY_FILE) out.push(env.OUTPOST_POLICY_FILE);
  if (env.OUTPOST_POLICY_SEARCH === "0") return out;
  const P = platform === "win32" ? path.win32 : path.posix;
  if (platform === "win32") {
    out.push(P.join(P.dirname(execPath), POLICY_NAME));   // the install folder, next to "Outpost Luna.exe"
    out.push(P.join(env.ProgramData || env.PROGRAMDATA || "C:\\ProgramData", "Outpost Luna", POLICY_NAME));
  } else if (platform === "darwin") {
    // not inside the .app: changing a signed bundle breaks its signature
    out.push("/Library/Application Support/Outpost Luna/" + POLICY_NAME);
  } else {
    out.push(P.join(P.dirname(execPath), POLICY_NAME), "/etc/outpost-luna/" + POLICY_NAME);
  }
  return out;
}

function normHosts(v) {
  const list = typeof v === "string" ? v.split(",") : Array.isArray(v) ? v : [];
  const out = [];
  for (let h of list) {
    h = String(h).trim().toLowerCase().replace(/\.$/, "");
    if (h.startsWith("*.")) h = h.slice(2);
    h = h.replace(/^\.+/, "");
    if (h && /^[a-z0-9.:-]+$/.test(h) && !out.includes(h)) out.push(h);
  }
  return out;
}
const on = (v) => /^(1|true|yes|on)$/i.test(String(v || "").trim());

/** The machine policy -> {school_network, allow_hosts, open_links, source}. */
function readMachine({ platform = process.platform, env = process.env, execPath = process.execPath, readFile = (f) => fs.readFileSync(f, "utf8") } = {}) {
  let pol = { school_network: false, allow_hosts: [], open_links: true, source: "" };
  for (const f of machinePaths({ platform, env, execPath })) {
    let text;
    try { text = readFile(f); } catch (e) { if (e && e.code === "ENOENT") continue; text = null; }
    if (text === undefined) continue;
    try {
      if (text === null) throw new Error("unreadable");
      const p = JSON.parse(String(text).replace(/^\uFEFF/, ""));   // Notepad's BOM
      if (!p || typeof p !== "object" || Array.isArray(p)) throw new Error("not an object");
      pol = { school_network: p.school_network !== false, allow_hosts: normHosts(p.allow_hosts), open_links: p.open_links !== false, source: f };
    } catch {
      pol = { school_network: true, allow_hosts: [], open_links: false, source: `${f} (unreadable: on, nothing allowed)` };
    }
    break;
  }
  if (on(env.OUTPOST_SCHOOL_NETWORK)) { pol.school_network = true; pol.source = pol.source || "OUTPOST_SCHOOL_NETWORK"; }
  if (env.OUTPOST_ALLOW_HOSTS) pol.allow_hosts = normHosts([...pol.allow_hosts, ...normHosts(env.OUTPOST_ALLOW_HOSTS)]);
  return pol;
}

function readUser(file) {
  try { return JSON.parse(fs.readFileSync(file, "utf8")).school_network === true; } catch { return false; }
}

function effective(machine, userOn) {
  const onNow = !!machine.school_network || !!userOn;
  return { school_network: onNow, locked: !!machine.school_network, allow_hosts: onNow ? [...(machine.allow_hosts || [])] : [],
    open_links: machine.open_links !== false, source: machine.school_network ? "machine" : userOn ? "user" : "off" };
}

function isLoopback(host) {
  const h = String(host || "").trim().toLowerCase().replace(/^\[|\]$/g, "");
  return h === "localhost" || h.endsWith(".localhost") || h === "::1" || /^127\.\d{1,3}\.\d{1,3}\.\d{1,3}$/.test(h);
}
function hostMatches(host, allow) {
  const h = String(host || "").toLowerCase().replace(/^\[|\]$/g, "").replace(/\.$/, "");
  return (allow || []).some((a) => h === a || h.endsWith("." + a));
}
function hostAllowed(host, pol) {
  return !pol || !pol.school_network || isLoopback(host) || hostMatches(host, pol.allow_hosts);
}
function hostOf(url) { try { return new URL(url).hostname.toLowerCase(); } catch { return ""; } }
/** data:, blob:, file: and friends never touch the network; http(s) / ws(s) go by host. */
function urlAllowed(url, pol) {
  if (!pol || !pol.school_network) return true;
  let u; try { u = new URL(url); } catch { return false; }
  if (!/^(https?|wss?):$/.test(u.protocol)) return true;
  return hostAllowed(u.hostname, pol);
}

function blockedError(host) {
  return Object.assign(new Error(`School network mode: ${host} is not on the allow list`),
    { kind: "school", school: true, offline: true, code: "SCHOOL_NETWORK", host });
}

/**
 * globalThis.fetch behind the policy. Off: the real fetch, untouched. On: a blocked host throws blockedError before any
 * request; redirects are followed here, one hop at a time, so each hop's host is checked too.
 */
function gateFetch(realFetch, getPolicy, log = () => {}) {
  const told = new Set();
  const refuse = (host) => { if (!told.has(host)) { told.add(host); log(`school network: blocked ${host}`); } return blockedError(host); };
  const gated = async function fetch(input, opts = {}) {
    const pol = getPolicy();
    if (!pol || !pol.school_network) return realFetch(input, opts);
    let url = typeof input === "string" ? input : input && input.url ? input.url : String(input);
    if (!urlAllowed(url, pol)) throw refuse(hostOf(url));
    if (opts.redirect === "manual" || opts.redirect === "error") return realFetch(url, opts);
    for (let hop = 0; hop < 10; hop++) {
      const r = await realFetch(url, { ...opts, redirect: "manual" });
      const loc = r.status >= 300 && r.status < 400 && r.headers && r.headers.get && r.headers.get("location");
      if (!loc) return r;
      const next = new URL(loc, url).toString();
      if (!urlAllowed(next, pol)) throw refuse(hostOf(next));
      url = next;
    }
    throw Object.assign(new Error("too many redirects"), { kind: "error" });
  };
  gated.__real = realFetch;
  return gated;
}

module.exports = { POLICY_NAME, USER_NAME, machinePaths, normHosts, readMachine, readUser, effective, isLoopback, hostMatches,
  hostAllowed, urlAllowed, blockedError, gateFetch };
