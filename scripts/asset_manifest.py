"""The asset manifest's two copies and its schema (docs/DESKTOP.md "Asset updates"). Used by asset_pack.py and
upload_assets.py; stdlib only.

    site/assets/manifest.json      the PUBLISHED one (scripts/publish_site.sh -> https://whissleai.github.io/Outpost-Luna/
                                   assets/manifest.json): installed apps check it and update their assets from it
    desktop/assets.manifest.json   the BUNDLED copy: the first-run source and the offline fallback (electron-builder)
Both are written together with the same content; backend/tests/test_asset_manifest.py checks they match.

Schema 2: {schema, version, published_at, remote_url, pack, folder, note, assets: [entry], offline_pack}
  entry: id, title, version (bump on every new sha256), file, url (https Dropbox dl=1 / Hugging Face / GitHub; null =
         not uploaded), sha256, size, required, min_app / max_app (app versions it works with, null = open),
         requires ([{id, min_version}]: other assets it needs), min_version (only meaningful in the bundled copy: older
         installs are replaced in the foreground), licence, files [{path, size, sha256}] (sha256 per file: re-checked by the model server at load), env, subdir, fallback?
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUNDLED = ROOT / "desktop/assets.manifest.json"
PUBLISHED = ROOT / "site/assets/manifest.json"
REMOTE_URL = "https://whissleai.github.io/Outpost-Luna/assets/manifest.json"
SCHEMA = 2
DEFAULTS = {"version": "1", "min_app": "0.1.0", "max_app": None, "requires": []}


def read() -> dict:
    for p in (PUBLISHED, BUNDLED):
        if p.exists():
            return json.loads(p.read_text())
    return {"assets": []}


def normalize(m: dict, prev: dict | None = None) -> dict:
    """Fill the schema-2 fields; an entry whose sha256 changed since `prev` gets the next version."""
    old = {a["id"]: a for a in (prev or {}).get("assets", [])}
    for a in m.get("assets", []):
        for k, v in DEFAULTS.items():
            a.setdefault(k, v)
        o = old.get(a["id"])
        if o and o.get("sha256") != a.get("sha256") and str(a.get("version")) == str(o.get("version", "1")):
            a["version"] = str(int(str(o.get("version", "1")).split(".")[0]) + 1)
    m["schema"] = SCHEMA
    m["remote_url"] = REMOTE_URL
    return m


def write(m: dict, prev: dict | None = None) -> None:
    """Stamp version + published_at and write both copies (same bytes)."""
    m = normalize(m, prev)
    t = time.gmtime()
    m["published_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", t)
    m["version"] = time.strftime("%Y.%m.%d.%H%M", t)
    text = json.dumps(m, indent=1) + "\n"
    for p in (PUBLISHED, BUNDLED):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
