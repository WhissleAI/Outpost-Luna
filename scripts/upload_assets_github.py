"""Mirror the first-run asset tars on a GitHub release and write the mirror links into the manifest.

    python scripts/upload_assets_github.py                       # tars from desktop/build/assets (ASSET_OUT)
    python scripts/upload_assets_github.py --dir A --dir B       # look for the tars in these folders, in order
    python scripts/upload_assets_github.py --verify-only         # re-check the mirror links anonymously

Why: Dropbox is the primary host (scripts/upload_assets.py); on 2026-11-20 it had a major outage and every first-run
download failed with HTTP 503. Each manifest entry may list `mirrors`: extra links to the IDENTICAL tar (same sha256),
tried in order after `url` by desktop/main/assets.js (older apps ignore the field). This script makes the GitHub mirror:

  1. every tar must match its manifest entry (size + sha256) before it is uploaded; a tar that is not found is skipped
     (that asset keeps its current mirrors) and reported;
  2. the release is the dedicated asset tag (default assets-<pack>, e.g. assets-v2): a PRE-release, never "latest", so
     the site's releases/latest download links still point at the app; created on first use;
  3. `gh release upload --clobber` (needs the gh CLI logged in with write access); a release asset with the same name
     and size is not uploaded again;
  4. verify ANONYMOUSLY (no token, redirects followed): HEAD gives the size, the first MB equals the local file's, and a
     tar up to 64 MB is downloaded whole and its sha256 checked;
  5. the link https://github.com/<repo>/releases/download/<tag>/<file> goes into the entry's `mirrors` (replacing an
     older GitHub release mirror, keeping any other) and both manifest copies are written (scripts/asset_manifest.py).
To ship: commit, merge, `bash scripts/publish_site.sh` (docs/DESKTOP.md "How to ship an asset update"). Stdlib + gh.
Deletes nothing on GitHub.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

import asset_manifest  # scripts/asset_manifest.py: the two manifest copies + schema 2

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(os.environ.get("ASSET_OUT", ROOT / "desktop/build/assets"))
REPO = "WhissleAI/Outpost-Luna"
UA = "outpost-luna-asset-mirror"
FULL_CHECK = 64 << 20   # download whole and hash tars up to this size


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def mirror_url(repo: str, tag: str, file: str) -> str:
    return f"https://github.com/{repo}/releases/download/{tag}/{file}"


def is_release_mirror(url: str, repo: str) -> bool:
    return url.lower().startswith(f"https://github.com/{repo}/releases/download/".lower())


def set_mirror(entry: dict, url: str, repo: str) -> None:
    """Put url first among the GitHub release mirrors of repo (an older tag's link is replaced), others kept."""
    rest = [u for u in entry.get("mirrors") or [] if not is_release_mirror(u, repo)]
    entry["mirrors"] = [url] + rest


def gh(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", *args], capture_output=True, text=True, check=check)


def ensure_release(repo: str, tag: str, pack: str) -> dict:
    """The release's assets {name: size}; creates the pre-release (not latest) when it is not there."""
    r = gh("release", "view", tag, "-R", repo, "--json", "assets,isPrerelease", check=False)
    if r.returncode != 0:
        notes = (f"Mirror of the Outpost Luna first-run assets (pack {pack}), the same tars as the Dropbox links, "
                 "sha256-pinned in assets.manifest.json. The app downloads these by itself; you do not need them. "
                 "Not an app release: get the app from the latest release.")
        gh("release", "create", tag, "-R", repo, "--prerelease", "--latest=false",
           "--title", f"First-run assets ({pack}) mirror", "--notes", notes)
        print(f"created pre-release {tag} on {repo}", flush=True)
        r = gh("release", "view", tag, "-R", repo, "--json", "assets,isPrerelease")
    info = json.loads(r.stdout)
    if not info.get("isPrerelease"):
        sys.exit(f"{tag} is not a pre-release: refusing (it could become the site's releases/latest)")
    return {a["name"]: a.get("size") for a in info.get("assets") or []}


def verify(url: str, p: Path, sha: str) -> None:
    """Anonymous: HEAD for the size, the first MB, and the whole file's sha256 when it is small."""
    size = p.stat().st_size
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        n = int(r.headers.get("Content-Length") or -1)
    if n != size:
        raise RuntimeError(f"{p.name}: mirror size {n} != local {size}")
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Range": "bytes=0-1048575"})
    with urllib.request.urlopen(req, timeout=60) as r:
        got = r.read(1 << 20)
    with open(p, "rb") as f:
        if got != f.read(1 << 20):
            raise RuntimeError(f"{p.name}: the mirror's first MB differs from the local file")
    how = "first MB matches"
    if size <= FULL_CHECK:
        h = hashlib.sha256()
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=300) as r:
            for b in iter(lambda: r.read(1 << 20), b""):
                h.update(b)
        if h.hexdigest() != sha:
            raise RuntimeError(f"{p.name}: the mirror's sha256 differs from the manifest")
        how = "full download, sha256 matches"
    print(f"  {p.name}: verified anonymously ({size / 1e6:.0f} MB, {how})", flush=True)


def find(file: str, dirs: list[Path]) -> Path | None:
    for d in dirs:
        if (d / file).is_file():
            return d / file
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", action="append", type=Path, help="folder holding the tars (repeatable; default ASSET_OUT)")
    ap.add_argument("--repo", default=REPO)
    ap.add_argument("--tag", help="release tag (default assets-<pack>, e.g. assets-v2)")
    ap.add_argument("--only", help="comma-separated asset ids")
    ap.add_argument("--verify-only", action="store_true")
    a = ap.parse_args()
    m = asset_manifest.read()
    prev = json.loads(json.dumps(m))
    pack = m.get("pack") or "v2"
    tag = a.tag or f"assets-{pack}"
    if not re.fullmatch(r"assets-[\w.-]+", tag):
        sys.exit(f"tag {tag!r}: use assets-<something> (never an app tag like v0.5.0)")
    dirs = a.dir or [OUT]
    items = [x for x in m["assets"] if not a.only or x["id"] in a.only.split(",")]
    have = {} if a.verify_only else ensure_release(a.repo, tag, pack)
    failed, skipped, done = [], [], []
    for it in items:
        p = find(it["file"], dirs)
        if p is None or p.stat().st_size != it["size"]:
            skipped.append(it["id"])
            print(f"  {it['id']}: {it['file']} not found (or wrong size) in {', '.join(map(str, dirs))}: no mirror",
                  flush=True)
            continue
        if sha256_file(p) != it["sha256"]:
            failed.append(it["id"])
            print(f"  {it['id']}: {p} does not match the manifest sha256: not uploaded", flush=True)
            continue
        url = mirror_url(a.repo, tag, it["file"])
        try:
            if not a.verify_only:
                if have.get(it["file"]) == it["size"]:
                    print(f"  {it['file']}: already on {tag} (same size), not uploaded", flush=True)
                else:
                    print(f"  {it['file']}: uploading {it['size'] / 1e6:.0f} MB to {tag}", flush=True)
                    gh("release", "upload", tag, str(p), "-R", a.repo, "--clobber")
            verify(url, p, it["sha256"])
            if not a.verify_only:
                set_mirror(it, url, a.repo)
                asset_manifest.write(m, prev)   # after each file: a later failure keeps the rest
            done.append(it["id"])
        except (subprocess.CalledProcessError, urllib.error.URLError, RuntimeError, OSError) as e:
            failed.append(it["id"])
            msg = e.stderr.strip() if isinstance(e, subprocess.CalledProcessError) else str(e)
            print(f"  {it['id']}: FAILED: {msg}", flush=True)
    print(f"mirrored on {tag}: {', '.join(done) or 'none'}" + (f"; no local tar: {', '.join(skipped)}" if skipped else ""))
    if failed:
        sys.exit(f"{len(failed)} failed: {', '.join(failed)}")


if __name__ == "__main__":
    main()
