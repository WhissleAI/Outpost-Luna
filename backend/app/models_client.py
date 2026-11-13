"""Client for the model server. Fails open: if the server is down, callers get None and fall back to rules."""
from __future__ import annotations

import httpx

from .config import settings

_client: httpx.AsyncClient | None = None


def client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(base_url=settings.model_server_url, timeout=settings.model_timeout_s)
    return _client


async def tag(text: str, domain: str = "assistant") -> dict | None:
    try:
        r = await client().post("/v1/tag", json={"text": text, "domain": domain})
        r.raise_for_status()
        return r.json()
    except httpx.HTTPError:
        return None


async def health() -> dict:
    try:
        r = await client().get("/health")
        return r.json()
    except httpx.HTTPError as e:
        return {"ok": False, "error": f"model server unreachable at {settings.model_server_url}: {e.__class__.__name__}"}
