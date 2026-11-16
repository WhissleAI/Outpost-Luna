"""Client for the model server. Fails open: if the server is down, callers get None and fall back to rules."""
from __future__ import annotations

import asyncio

import httpx

from .config import settings
from .local_guard import auth_headers

_client: httpx.AsyncClient | None = None
_loop = None


def client() -> httpx.AsyncClient:
    """One pooled client per event loop (tests and scripts run several loops in one process)."""
    global _client, _loop
    loop = asyncio.get_running_loop()
    if _client is None or _loop is not loop:
        _client = httpx.AsyncClient(base_url=settings.model_server_url, timeout=settings.model_timeout_s,
                                    headers=auth_headers())
        _loop = loop
    return _client


async def tag(text: str, domain: str = "assistant") -> dict | None:
    try:
        r = await client().post("/v1/tag", json={"text": text, "domain": domain})
        r.raise_for_status()
        return r.json()
    except (httpx.HTTPError, RuntimeError, ValueError):
        return None


async def health() -> dict:
    try:
        r = await client().get("/health")
        return r.json()
    except httpx.HTTPError as e:
        return {"ok": False, "error": f"model server unreachable at {settings.model_server_url}: {e.__class__.__name__}"}


async def embed(texts: list[str], kind: str = "query", timeout: float | None = None) -> list[list[float]] | None:
    """Normalized vectors from the model server's tiny embedder (POST /v1/embed). None when it is off or down."""
    out: list[list[float]] = []
    try:
        for i in range(0, len(texts), 256):
            r = await client().post("/v1/embed", json={"texts": texts[i:i + 256], "kind": kind},
                                    timeout=timeout or settings.model_timeout_s)
            r.raise_for_status()
            out += r.json()["vectors"]
        return out
    except (httpx.HTTPError, RuntimeError, ValueError, KeyError):
        return None
