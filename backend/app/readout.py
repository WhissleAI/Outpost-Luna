"""Turns Arc Tagger's raw output into the few signals the app uses."""
from __future__ import annotations

HARD_PII = {"street_address", "phone_number", "email", "card_account_number", "gov_id", "date_of_birth", "url_handle"}


def summarize(out: dict | None) -> dict:
    if not out:
        return {"available": False}
    utt = (out.get("utterances") or [{}])[-1]
    on = lambda key: [x["tag"].split(".")[-1] for x in utt.get(key) or [] if x.get("on")]  # noqa: E731
    spans = out.get("spans") or []
    pii = sorted({s["type"].split(".")[-1] for s in spans if s.get("family") == "pii"})
    return {
        "available": True,
        "act": on("act"),
        "intent": on("intent"),
        "mentions": [s["text"].strip(".,!?") for s in spans if s.get("family") == "entity"],
        "numbers": [s["text"] for s in spans if s.get("family") == "number" and s["type"] != "entity.numeral"],
        "pii": pii,
        "hard_pii": sorted(set(pii) & HARD_PII),
        # The words behind each PII tag, so the Director can drop false hits on Moon names ("Moon" -> street_address).
        "pii_spans": [{"type": s["type"].split(".")[-1], "text": s.get("text", "")} for s in spans
                      if s.get("family") == "pii"],
        "complete": any(e.get("type") == "discourse.assistant.command_complete" for e in out.get("events") or []),
        "ms": out.get("ms"),
    }
