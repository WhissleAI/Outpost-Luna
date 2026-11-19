"""Settings -> For grown-ups -> School network (docs/SCHOOL_IT.md): read and set School network mode.

  GET  /api/network   {school_network, locked, source, allow_hosts, open_links, off: [what needs the internet]}
  POST /api/network   {"school_network": bool}  (the per-launch token, like every POST; 409 when an IT admin's machine
                      policy turned it on: the app cannot turn it off). The change applies at once in this process,
                      the model server and the desktop shell (each re-reads <LUNA_DATA_DIR>/network.json).
The gate itself is app/netgate.py; nothing here opens a connection.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import netgate
from .config import settings

router = APIRouter()

# What uses the internet at all (everything else is on this computer). The page words them (frontend/src/network_ui.js).
NEEDS_INTERNET = ("videos", "downloads", "updates")


def setup() -> None:
    """make dev / the test suites have no LUNA_DATA_DIR: keep the choice next to the other writable caches."""
    if netgate.user_file() is None:
        netgate.set_user_file((settings.cache_dir or settings.data_dir / "cache") / netgate.USER_FILE_NAME)


def state() -> dict:
    p = netgate.policy()
    return {**{k: p[k] for k in ("school_network", "locked", "source", "allow_hosts", "open_links")},
            "off": list(NEEDS_INTERNET) if p["school_network"] else []}


class NetworkIn(BaseModel):
    school_network: bool


@router.get("/api/network")
def get_network():
    return state()


@router.post("/api/network")
def set_network(body: NetworkIn):
    p = netgate.policy()
    if p["locked"] and not body.school_network:
        raise HTTPException(409, "set by this computer's IT admin")
    netgate.set_user(body.school_network)
    return state()
