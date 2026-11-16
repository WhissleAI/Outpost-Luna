#!/usr/bin/env python3
"""Guard the public site (site/*.html) before it is published. Stdlib only; scripts/publish_site.sh runs it.

    python3 scripts/check_site.py          # exit 1 and list every problem

Checks:
- Landing copy budgets (index.html): h1 <= 9 words, h2 <= 8, any visible sentence <= 20 words. Detail belongs in
  guide.html or the README, or behind a <details> disclosure (exempt).
- Every page: the NASA disclaimer line in the footer; no LLM vendor or model names; nothing about kids or ages.
- Every <img>: alt, width and height (no layout shift).
- index.html: both download buttons (the Windows one carries data-win for dl.js) and the video slot
  (<figure data-film="media/outpost-luna">, see site/film.js).
"""
from __future__ import annotations

import re
import sys
from html.parser import HTMLParser
from pathlib import Path

SITE = Path(__file__).resolve().parent.parent / "site"
DISCLAIMER = "Inspired by NASA's Artemis program. Uses NASA open data; not endorsed by NASA."
BANNED = re.compile(r"\b(gpt[-\w]*|openai|chatgpt|claude|anthropic|gemini|llama|bedrock|mistral|kids?|children|child|ages? \d)\b", re.I)
SKIP = {"script", "style", "svg", "details", "title"}


class Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.blocks: list[tuple[str, str]] = []   # (tag, text) for h1/h2/p/li/dd/figcaption
        self.imgs: list[dict] = []
        self.links: list[dict] = []
        self.figs: list[dict] = []
        self._buf: list[list] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "img":
            self.imgs.append(a)
        if tag == "a":
            self.links.append(a)
        if tag == "figure":
            self.figs.append(a)
        if tag in ("img", "source", "meta", "link", "br", "input", "path", "rect", "circle"):
            return
        self.stack.append(tag)
        if tag in ("h1", "h2", "p", "li", "dd", "figcaption") and not (SKIP & set(self.stack)):
            self._buf.append([tag, ""])

    def handle_endtag(self, tag):
        if tag in self.stack:
            while self.stack and self.stack.pop() != tag:
                pass
        if self._buf and self._buf[-1][0] == tag:
            t, txt = self._buf.pop()
            self.blocks.append((t, " ".join(txt.split())))

    def handle_data(self, data):
        if self._buf and not (SKIP & set(self.stack)):
            for b in self._buf:
                b[1] += data


def words(s: str) -> int:
    return len(s.split())


def check(path: Path) -> list[str]:
    html = path.read_text(encoding="utf-8")
    p = Page()
    p.feed(html)
    errs: list[str] = []
    name = path.name

    if DISCLAIMER not in html:
        errs.append(f"{name}: footer disclaimer missing: {DISCLAIMER!r}")
    visible = re.sub(r"<!--.*?-->|<script.*?</script>|<style.*?</style>", " ", html, flags=re.S)
    visible = re.sub(r'(href|src|srcset)="[^"]*"', " ", visible)
    for m in BANNED.finditer(visible):
        errs.append(f"{name}: banned term {m.group(0)!r}")
    for img in p.imgs:
        for k in ("alt", "width", "height"):
            if k not in img:
                errs.append(f"{name}: <img src={img.get('src')!r}> has no {k}")

    if name == "index.html":
        for tag, txt in p.blocks:
            if tag == "h1" and words(txt) > 9:
                errs.append(f"{name}: h1 over 9 words: {txt!r}")
            if tag == "h2" and words(txt) > 8:
                errs.append(f"{name}: h2 over 8 words: {txt!r}")
            for s in re.split(r"(?<=[.!?])\s+", txt):
                if words(s) > 20:
                    errs.append(f"{name}: sentence over 20 words: {s!r}")
        hrefs = [a.get("href", "") for a in p.links]
        if not any(h.endswith("/Outpost-Luna-mac-arm64.dmg") for h in hrefs):
            errs.append(f"{name}: no Download for Mac link")
        if not any("data-win" in a and a.get("href", "").endswith("/Outpost-Luna-win-x64.exe") for a in p.links):
            errs.append(f"{name}: no Download for Windows link with data-win")
        if not any(f.get("data-film") == "media/outpost-luna" for f in p.figs):
            errs.append(f"{name}: video slot <figure data-film=\"media/outpost-luna\"> missing")
    return errs


def main() -> int:
    errs = [e for f in sorted(SITE.glob("*.html")) for e in check(f)]
    for e in errs:
        print(e)
    print(f"check_site: {len(errs)} problem(s)" if errs else "check_site: ok")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
