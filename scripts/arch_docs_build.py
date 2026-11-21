"""Documents the Archaeology course cites, kept in its pack so they open in the app, offline (library.json `docs`,
backend/app/course_library.py). `make arch-docs`.

Each is downloaded once, kept unchanged (media/<id>.pdf) and rendered page by page to pictures (media/<id>_p<n>.jpg,
200 dpi, pdftoppm from poppler) that the app's picture viewer shows with zoom and pan. Only public-domain or openly
licensed documents: the licence is checked by hand on the publisher's page and recorded in media/credits.json.

  nps_rack_artifacts  "What If I Find an Artifact?", NPS Archeology Program rack card (2 pages). A work of the US federal
                      government (17 U.S.C. 105). nps.gov/aboutus/disclaimer.htm: "material created by the National
                      Park Service and presented on this website, unless otherwise indicated, is generally considered in
                      the public domain." The card's photos are "(NPS photo)". It carries the NPS Arrowhead (a
                      registered mark), shown as part of the unmodified card, never used on its own.

    python3 scripts/arch_docs_build.py          (needs pdftoppm: brew install poppler)
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "backend/data/courses/archaeology/media"
LIB = ROOT / "backend/data/courses/archaeology/library.json"
DOCS = [{
    "id": "nps_rack_artifacts",
    "url": "https://www.nps.gov/subjects/archeology/upload/RackArtifactsVisitors_508.pdf",
    "title": "What If I Find an Artifact?",
    "by": "NPS Archeology Program",
    "sha256": "97c727921eefc92d902b521c4bae9848d8113b623b84ab849f4009671cbd34a5",
    "credit": "National Park Service, Archeology Program (NPS photos)",
    "licence": "Public domain (US Government work, 17 U.S.C. 105; nps.gov/aboutus/disclaimer.htm). The NPS Arrowhead is a registered mark, shown only as part of the unmodified card.",
    "alts": ["Page 1 of the NPS rack card What If I Find an Artifact?: what an artifact is; leave it be; document the location; alert a park ranger. Photo: visitors helping archeologists at a dig.",
             "Page 2 of the NPS rack card: defacing rock images is illegal; taking artifacts is illegal under federal law (ARPA); if you see something wrong, tell a ranger; learn more."],
}]


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def main():
    if not shutil.which("pdftoppm"):
        sys.exit("pdftoppm not found (brew install poppler)")
    credits = json.loads((MEDIA / "credits.json").read_text())
    lib = json.loads(LIB.read_text())
    out_docs = []
    for d in DOCS:
        req = urllib.request.Request(d["url"], headers={"User-Agent": "outpost-luna-build"})
        with urllib.request.urlopen(req, timeout=120) as r:
            pdf = r.read()
        if sha(pdf) != d["sha256"]:
            sys.exit(f"{d['id']}: the PDF changed upstream (sha256 {sha(pdf)}); check its licence again, then update the pin")
        (MEDIA / f"{d['id']}.pdf").write_bytes(pdf)
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "doc.pdf"; src.write_bytes(pdf)
            subprocess.run(["pdftoppm", "-r", "200", "-jpeg", "-jpegopt", "quality=85", str(src), str(Path(tmp) / "p")], check=True)
            pages = sorted(Path(tmp).glob("p-*.jpg"), key=lambda p: int(p.stem.split("-")[1]))
            files = []
            for n, pg in enumerate(pages, 1):
                name = f"{d['id']}_p{n}.jpg"; shutil.copyfile(pg, MEDIA / name); files.append(name)
        entries = [(f"{d['id']}.pdf", f"{d['title']} ({d['by']}), the original PDF", d["alts"][0])] + \
                  [(f, f"{d['title']} ({d['by']}), page {n}", d["alts"][n - 1] if n - 1 < len(d["alts"]) else f"Page {n}")
                   for n, f in enumerate(files, 1)]
        for f, title, alt in entries:
            b = (MEDIA / f).read_bytes()
            c = {"file": f, "title": title, "credit": d["credit"], "licence": d["licence"], "source_url": d["url"], "alt": alt,
                 "bytes": len(b), "sha256": sha(b), "licence_class": "pd"}
            credits = [x for x in credits if x.get("file") != f] + [c]
        out_docs.append({"id": d["id"], "url": d["url"], "title": d["title"], "by": d["by"], "pdf": f"{d['id']}.pdf",
                         "pages": [{"file": f, "alt": d["alts"][n] if n < len(d["alts"]) else f"Page {n + 1}"} for n, f in enumerate(files)]})
    (MEDIA / "credits.json").write_text(json.dumps(credits, indent=1, ensure_ascii=False) + "\n")
    lib["docs"] = out_docs
    LIB.write_text(json.dumps(lib, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps(out_docs, indent=1))


if __name__ == "__main__":
    main()
