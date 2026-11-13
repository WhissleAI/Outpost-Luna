"""Fallback for questions the rules and the gazetteer can't place. Uses the Anthropic SDK; off without a key."""
from __future__ import annotations

import json
import re

from .config import settings
from .gazetteer import Gazetteer

_client = None


def available() -> bool:
    return bool(settings.anthropic_api_key)


async def place_question(text: str, gaz: Gazetteer) -> dict | None:
    global _client
    if not available():
        return None
    if _client is None:
        from anthropic import AsyncAnthropic
        _client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    places = "\n".join(f"{p.id}: {p.name} ({p.lat}, {p.lon})" for p in gaz.places.values())
    prompt = (f'You are the Moon Guide in a kids\' app (ages 5-10). A child asked: "{text}"\n'
              f"Known Moon places:\n{places}\n"
              'Pick the one place that best answers them, or null if none fits. Reply ONLY as JSON: '
              '{"feature": "<id or null>", "say": "<1-2 short sentences in simple words, friendly, true>"}. '
              "If the question isn't about space, kindly steer them back to the Moon.")
    msg = await _client.messages.create(model=settings.ask_model, max_tokens=300,
                                        messages=[{"role": "user", "content": prompt}])
    out = "".join(b.text for b in msg.content if b.type == "text")
    m = re.search(r"\{[\s\S]*\}", out)
    try:
        ans = json.loads(m.group(0)) if m else {"feature": None, "say": out.strip()}
    except json.JSONDecodeError:
        ans = {"feature": None, "say": out.strip()}
    fid = ans.get("feature")
    return {"place": fid if fid in gaz.places else None, "say": str(ans.get("say") or "")}
