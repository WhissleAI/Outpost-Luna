"""Question -> answer without an LLM (docs/LOCAL_BRAIN.md).

1. Entity: the gazetteer link (aliases + Arc mentions, done by the Director) or a card alias in the words.
2. Attribute: keyword rules ("how big" -> size, "where" -> where, "who" -> who, ...).
3. When the rules don't settle it: the tiny embedder's nearest card+attribute over the canonical question bank.
   >= ACCEPT answer; >= ASK offer the top 2 ("Did you mean ...?"); below: an honest "I don't know that one yet".
4. The line is one of the card's 2-3 templates: the first one first, then rotated per session (deterministic).
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

import numpy as np

from .. import models_client
from ..gazetteer import norm
from .cards import ATTR_LABEL, Q_FOR_LABEL, STYLE

# Cosine thresholds for all-MiniLM-L6-v2 (calibrated on tests/eval/kid_questions.json, see docs/LOCAL_BRAIN.md).
ACCEPT, ASK, RELATED = 0.62, 0.48, 0.30
ENTITY_BOOST = 0.10     # a card whose name/alias is in the words wins ties against look-alikes

ATTR_RULES = [  # first match wins; order matters ("what year" is when, not what)
    ("size", re.compile(r"\b(how (big|wide|large|deep|tall|huge|long|far across)|what size|size of|how many (km|kilometers|miles))\b")),
    ("when", re.compile(r"\b(when|what year|how old|how long ago|what day|which year)\b")),
    ("who", re.compile(r"\b(who|whose|named after)\b")),
    ("where", re.compile(r"\b(where|which side|what side|location)\b")),
    ("science", re.compile(r"\b(science|experiments?|discover(ed)?|find out|learn)\b")),
    ("why", re.compile(r"\b(why|what for|how come)\b")),
    ("story", re.compile(r"\b(story|what happened)\b")),
    ("what", re.compile(r"\b(what (is|s|are|was|does)|whats|what kind|mean|means|meaning|explain|define)\b")),
    ("about", re.compile(r"\b(tell me|talk about|fun fact|cool|more about|something about)\b")),
]
SIZE_ALIASES = {"size": ["size"], "about": ["about", "story", "what"], "story": ["story", "about", "what"],
                "what": ["what", "about", "story", "misconception"]}
DEFAULT_ATTR = {"place": "about", "artifact": "story", "term": "what", "concept": "what", "site": "what", "lesson": "what",
                "misconception": "misconception"}


def detect_attr(q: str) -> str | None:
    for attr, pat in ATTR_RULES:
        if pat.search(q):
            return attr
    return None


class Brain:
    def __init__(self, cards: list[dict], cache_dir: Path | None = None):
        self.cards = {c["id"]: c for c in cards}
        self.bank: list[tuple[str, str, str]] = [(q, c["id"], a) for c in cards for a, qs in c["questions"].items() for q in qs]
        self.vecs: np.ndarray | None = None
        self.cache_dir = cache_dir
        self._rot: dict[tuple, int] = {}
        self._alias = [(re.compile(rf"(?<![a-z0-9]){re.escape(norm(a))}(?![a-z0-9])"), c["id"])
                       for c in cards if c["kind"] not in ("place", "artifact") for a in c["aliases"] if len(norm(a)) >= 3]
        self.embed_ms: list[float] = []

    # ---- vectors --------------------------------------------------------------------------------------------------
    def _key(self) -> str:
        return hashlib.sha1(json.dumps([b[0] for b in self.bank]).encode()).hexdigest()[:16]

    async def warm(self) -> bool:
        """Embed the question bank (disk cache keyed by the bank's text). False when the embedder is down."""
        if self.vecs is not None:
            return True
        f = self.cache_dir / f"card_vectors_{self._key()}.npy" if self.cache_dir else None
        if f and f.exists():
            self.vecs = np.load(f)
            return True
        v = await models_client.embed([b[0] for b in self.bank], "doc", timeout=60.0)
        if v is None:
            return False
        self.vecs = np.asarray(v, dtype=np.float32)
        if f:
            f.parent.mkdir(parents=True, exist_ok=True)
            np.save(f, self.vecs)
        return True

    async def nearest(self, text: str, boost: set[str] | None = None, only: set[str] | None = None) -> list[tuple[float, str, str]]:
        """[(score, card_id, attr)] best first, one entry per card+attr. [] when the embedder is down."""
        if not await self.warm():
            return []
        t = time.perf_counter()
        q = await models_client.embed([text], "query")
        if not q:
            return []
        sims = self.vecs @ np.asarray(q[0], dtype=np.float32)
        self.embed_ms.append((time.perf_counter() - t) * 1000)
        best: dict[tuple[str, str], float] = {}
        for i in np.argsort(-sims)[:60]:
            _, cid, attr = self.bank[i]
            if only and cid not in only:
                continue
            s = float(sims[i]) + (ENTITY_BOOST if boost and cid in boost else 0.0)
            best[(cid, attr)] = max(best.get((cid, attr), -1.0), s)
        return sorted(((s, c, a) for (c, a), s in best.items()), reverse=True)

    # ---- lines ----------------------------------------------------------------------------------------------------
    def line(self, cid: str, attr: str, session: str = "") -> str:
        lines = self.cards[cid]["answers"][attr]
        k = (session, cid, attr)
        n = self._rot.get(k, 0)  # the first line is the canonical one (a definition, the size); repeats rotate
        self._rot[k] = n + 1
        return lines[n % len(lines)]

    def attr_for(self, cid: str, attr: str | None) -> str | None:
        c = self.cards[cid]
        if attr and attr in c["answers"]:
            return attr
        if attr in (None, "about", "story", "what"):
            for a in SIZE_ALIASES.get(attr or "about", []) + [DEFAULT_ATTR[c["kind"]]]:
                if a in c["answers"]:
                    return a
        return None

    def alias_cards(self, q: str) -> set[str]:
        return {cid for pat, cid in self._alias if pat.search(q)}

    def label(self, cid: str, attr: str) -> tuple[str, str]:
        """(spoken label, the question a tap sends)."""
        t = self.cards[cid]["title"]
        return ATTR_LABEL.get(attr, "{t}").format(t=t), Q_FOR_LABEL.get(attr, "{t}").format(t=t)

    def result(self, status: str, cid: str | None, attr: str | None, say: str, score: float | None, source: str,
               options: list[dict] | None = None) -> dict:
        c = self.cards.get(cid or "")
        return {"status": status, "card": cid, "kind": c["kind"] if c else None, "attr": attr, "say": say,
                "place": c["place"] if c else None, "sources": c["sources"] if c else [], "score": score,
                "source": source, "options": options or [], "style_hint": STYLE.get(attr or "", "question" if status == "ask" else "explain")}

    # ---- the answer -----------------------------------------------------------------------------------------------
    def for_card(self, cid: str, question: str, session: str = "") -> dict | None:
        """The entity is known (a place the Director linked): pick the attribute by rule, the line by template."""
        if cid not in self.cards:
            return None
        attr = self.attr_for(cid, detect_attr(norm(question)))
        if attr is None:
            attr = self.attr_for(cid, None)
        if attr is None:
            return None
        return self.result("answer", cid, attr, self.line(cid, attr, session), None, "card+rules")

    async def answer(self, text: str, session: str = "", place_hint: str | None = None) -> dict:
        q = norm(text)
        rule_attr = detect_attr(q)
        ents = self.alias_cards(q)
        if place_hint:  # a named place beats generic glossary words in the same question ("how big is X crater")
            ents = {cid for cid in ents if self.cards[cid]["kind"] != "term" or rule_attr == "what" and len(ents) == 1}
            ents |= {cid for cid, c in self.cards.items() if c["place"] == place_hint}
        elif rule_attr not in ("what", None):  # "how big is the oldest basin": "basin" is not a definition question
            ents = {cid for cid in ents if self.cards[cid]["kind"] != "term"}
        # Rules settle it: exactly one named card that has the asked-for attribute.
        if len(ents) == 1:
            cid = next(iter(ents))
            attr = self.attr_for(cid, rule_attr)
            if attr:
                return self.result("answer", cid, attr, self.line(cid, attr, session), None, "card+rules")
        hits = await self.nearest(text, boost=ents)
        if not hits:
            return self.result("unknown", None, None, UNKNOWN, None, "none")
        s1, c1, a1 = hits[0]
        if rule_attr and ents and c1 in ents and rule_attr in self.cards[c1]["answers"]:
            a1 = rule_attr
        if s1 >= ACCEPT:
            return self.result("answer", c1, a1, self.line(c1, a1, session), round(s1, 3), "card+embed")
        if s1 >= ASK:
            alt = next(((s, c, a) for s, c, a in hits[1:] if (c, a) != (c1, a1) and s >= ASK - 0.06), None)
            opts = [(c1, a1)] + ([(alt[1], alt[2])] if alt else [])
            labs = [self.label(c, a) for c, a in opts]
            say = (f"Did you mean {labs[0][0]} or {labs[1][0]}?" if len(labs) == 2 else f"Did you mean {labs[0][0]}?")
            return self.result("ask", c1, a1, say, round(s1, 3), "card+embed",
                               [{"card": c, "attr": a, "label": lab, "send": send} for (c, a), (lab, send) in zip(opts, labs)])
        if s1 >= RELATED:
            t = self.cards[c1]["title"]
            return self.result("unknown", c1, None, f"I don't know that one yet. Want to hear about {t}?", round(s1, 3),
                               "card+embed", [{"card": c1, "attr": DEFAULT_ATTR[self.cards[c1]['kind']],
                                               "label": t, "send": f"Tell me about {t}"}])
        return self.result("unknown", None, None, UNKNOWN, round(s1, 3), "none")


UNKNOWN = "I don't know that one yet."   # spoken; the examples are on the card (director.TRY), never spoken
