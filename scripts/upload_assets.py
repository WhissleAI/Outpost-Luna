"""Upload the first-run asset pack (scripts/asset_pack.py) to Dropbox and write the public links into the manifest.

    DROPBOX_TOKEN_FILE=~/secrets/dbx_token python scripts/upload_assets.py          # or --token-file PATH
    python scripts/upload_assets.py --verify-only                                    # re-check the links anonymously

The token is read from a file (DROPBOX_TOKEN_FILE / --token-file) or DROPBOX_TOKEN, never from the command line and never
printed, logged or written anywhere. It needs files.content.write + sharing.write (+ files.metadata.read).

For every asset tar and the offline zip in desktop/build/assets (desktop/assets.manifest.json):
  1. skip the upload when Dropbox already has the same bytes there (its content_hash, computed locally);
  2. else upload with the chunked upload_session API (start / append_v2 / finish, 32 MB pieces, overwrite);
  3. create_shared_link_with_settings (public; shared_link_already_exists -> list_shared_links) and store it as dl=1;
  4. verify ANONYMOUSLY (no token): HEAD gives the size, and the first MB equals the local file's.
Stdlib only. Deletes nothing.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(os.environ.get("ASSET_OUT", ROOT / "desktop/build/assets"))
MANIFEST = ROOT / "desktop/assets.manifest.json"
API, CONTENT = "https://api.dropboxapi.com/2/", "https://content.dropboxapi.com/2/"
CHUNK = 32 << 20
UA = "outpost-luna-asset-upload"


class DropboxError(Exception):
    pass


def token(path: str | None) -> str:
    p = path or os.environ.get("DROPBOX_TOKEN_FILE")
    t = Path(p).expanduser().read_text().strip() if p else os.environ.get("DROPBOX_TOKEN", "").strip()
    if not t:
        sys.exit("no Dropbox token: set DROPBOX_TOKEN_FILE (a file holding the token) or --token-file")
    return t


def call(tok: str, url: str, args: dict | None = None, data: bytes | None = None, content: bool = False, retries: int = 4):
    """One Dropbox API call. content: args go in Dropbox-API-Arg, data is the body. Never shows the token."""
    for attempt in range(retries):
        h = {"Authorization": "Bearer " + tok, "User-Agent": UA}
        if content:
            h["Dropbox-API-Arg"] = json.dumps(args or {}, ensure_ascii=True)
            h["Content-Type"] = "application/octet-stream"
            body = data or b""
        else:
            h["Content-Type"] = "application/json"
            body = json.dumps(args).encode() if args is not None else b"null"
        req = urllib.request.Request(url, data=body, headers=h, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                raw = r.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            msg = e.read().decode("utf-8", "replace")[:500]
            if e.code == 401:
                raise DropboxError("401 unauthorised: the token is missing, wrong or EXPIRED") from None
            if e.code == 409:
                raise DropboxError("409 " + msg) from None
            if e.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                time.sleep(float(e.headers.get("Retry-After") or 2 ** attempt))
                continue
            raise DropboxError(f"HTTP {e.code} {msg}") from None
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise DropboxError(f"network: {e}") from None


def content_hash(p: Path) -> str:
    """Dropbox's content_hash: sha256 over the concatenated sha256 of each 4 MiB block."""
    outer = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(4 << 20), b""):
            outer.update(hashlib.sha256(b).digest())
    return outer.hexdigest()


def upload(tok: str, p: Path, dest: str) -> None:
    size = p.stat().st_size
    try:
        meta = call(tok, API + "files/get_metadata", {"path": dest})
        if meta.get("size") == size and meta.get("content_hash") == content_hash(p):
            print(f"  {p.name}: already in Dropbox (same content), not uploaded", flush=True)
            return
    except DropboxError as e:
        if "not_found" not in str(e):
            raise
    t, sent = time.time(), 0
    with open(p, "rb") as f:
        first = f.read(CHUNK)
        sid = call(tok, CONTENT + "files/upload_session/start", {"close": False}, first, content=True)["session_id"]
        sent = len(first)
        while sent < size:
            b = f.read(CHUNK)
            call(tok, CONTENT + "files/upload_session/append_v2",
                 {"cursor": {"session_id": sid, "offset": sent}, "close": False}, b, content=True)
            sent += len(b)
            print(f"  {p.name}: {sent / 1e6:7.0f} / {size / 1e6:.0f} MB  ({sent / 1e6 / max(time.time() - t, 1e-3):.1f} MB/s)",
                  flush=True)
        call(tok, CONTENT + "files/upload_session/finish",
             {"cursor": {"session_id": sid, "offset": sent},
              "commit": {"path": dest, "mode": "overwrite", "autorename": False, "mute": True}}, b"", content=True)
    print(f"  {p.name}: uploaded {size / 1e6:.0f} MB in {time.time() - t:.0f} s", flush=True)


def public_link(tok: str, dest: str) -> str:
    try:
        url = call(tok, API + "sharing/create_shared_link_with_settings",
                   {"path": dest, "settings": {"requested_visibility": "public", "audience": "public",
                                               "access": "viewer"}})["url"]
    except DropboxError as e:
        if "shared_link_already_exists" not in str(e):
            raise
        links = call(tok, API + "sharing/list_shared_links", {"path": dest, "direct_only": True}).get("links") or []
        pub = [x for x in links if (x.get("link_permissions") or {}).get("resolved_visibility", {}).get(".tag")
               in (None, "public")] or links
        if not pub:
            raise DropboxError(f"{dest}: a shared link exists but list_shared_links returned none") from None
        url = pub[0]["url"]
    u = urllib.parse.urlsplit(url)
    q = [(k, v) for k, v in urllib.parse.parse_qsl(u.query) if k != "dl"] + [("dl", "1")]
    return urllib.parse.urlunsplit((u.scheme, u.netloc, u.path, urllib.parse.urlencode(q), ""))


def verify(url: str, p: Path) -> None:
    """Anonymous: HEAD for the size, then the first MB against the local file."""
    size = p.stat().st_size
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        n = int(r.headers.get("Content-Length") or -1)
    if n != size:
        raise DropboxError(f"{p.name}: public link size {n} != local {size}")
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Range": "bytes=0-1048575"})
    with urllib.request.urlopen(req, timeout=60) as r:
        got = r.read(1 << 20)
    with open(p, "rb") as f:
        want = f.read(1 << 20)
    if got != want:
        raise DropboxError(f"{p.name}: the public link's first MB differs from the local file")
    print(f"  {p.name}: verified anonymously ({size / 1e6:.0f} MB, first MB matches)", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--token-file")
    ap.add_argument("--folder", help="Dropbox folder (default: the manifest's `folder`)")
    ap.add_argument("--verify-only", action="store_true")
    ap.add_argument("--only", help="comma-separated file names")
    a = ap.parse_args()
    m = json.loads(MANIFEST.read_text())
    folder = (a.folder or m.get("folder") or "/Outpost Luna/assets/v2/").rstrip("/") + "/"
    items = m["assets"] + [m["offline_pack"]]
    if a.only:
        items = [x for x in items if x["file"] in a.only.split(",")]
    tok = None if a.verify_only else token(a.token_file)
    failed = []
    for it in items:
        p = OUT / it["file"]
        if not p.exists() or p.stat().st_size != it["size"]:
            failed.append(it["file"])
            print(f"  {it['file']}: not built (make asset-pack)", flush=True)
            continue
        try:
            if not a.verify_only:
                upload(tok, p, folder + it["file"])
                it["url"] = public_link(tok, folder + it["file"])
                MANIFEST.write_text(json.dumps(m, indent=1) + "\n")    # after each file: a later failure keeps the rest
            if it.get("url"):
                verify(it["url"], p)
        except DropboxError as e:
            failed.append(it["file"])
            print(f"  {it['file']}: FAILED: {e}", flush=True)
            if "401" in str(e):
                break
    MANIFEST.write_text(json.dumps(m, indent=1) + "\n")
    if failed:
        sys.exit(f"{len(failed)} failed: {', '.join(failed)}")
    print("all assets uploaded and verified; links are in desktop/assets.manifest.json")


if __name__ == "__main__":
    main()
