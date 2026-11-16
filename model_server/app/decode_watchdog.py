"""Decode watchdog (issue #87): a live decode that runs longer than EAR_DECODE_TIMEOUT_S is abandoned.

A native decode cannot be interrupted from Python, so "abandoned" means: the stream stops waiting for it, the client
gets {"t":"error","code":"decode_timeout"} and the socket closes (1011); the stream's worker thread is left behind
(never joined), and the shared model handle that hung is dropped and loaded again in the background
(arcmeta.reset_after_hang), so the next session gets a fresh one instead of queueing behind the stuck call. The backend
relays the error to the page (voice.js: "Voice paused. Reconnecting…"), which reconnects by itself.
A normal final decode of the longest turn (EAR_MAX_TURN_S = 15 s of audio) takes well under 2 s on a laptop CPU, so the
default limit is generous on purpose: it catches a hang, never a slow machine.
"""
from __future__ import annotations

import asyncio

from pydantic_settings import BaseSettings, SettingsConfigDict


class WatchdogSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    ear_decode_timeout_s: float = 20.0


watchdog_settings = WatchdogSettings()


class DecodeTimeout(Exception):
    """A guarded call ran past its limit; the call itself may still be running in its worker thread."""


async def guarded(loop, pool, fn, *args, limit: float | None = None):
    """loop.run_in_executor(pool, fn, *args), but give up after `limit` seconds (default EAR_DECODE_TIMEOUT_S)."""
    limit = watchdog_settings.ear_decode_timeout_s if limit is None else limit
    try:
        return await asyncio.wait_for(loop.run_in_executor(pool, fn, *args), limit)
    except asyncio.TimeoutError:
        raise DecodeTimeout(f"{getattr(fn, '__name__', 'decode')} took longer than {limit:g} s") from None
