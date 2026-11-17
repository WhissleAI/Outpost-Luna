"""Settings → "What the app has learned" and "Reset learning" (docs/ON_DEVICE_LEARNING.md).

  GET  /api/learn?profile=p1               the view: this cadet's learned names, habits and thresholds, and this
                                           computer's echo numbers, in plain words (`lines`) and as numbers
  POST /api/learn/reset?profile=p1         forget what was learned for this cadet and this computer's echo settings
                                           (scope=all: every cadet on this computer)
  POST /api/learn/forget?profile=p1        body {"heard": "..."}: remove one learned name (it is never learned again)

All three need the local token (the GET too, like the diagnostics contents: the learned names are the kid's words), and
the POSTs the page's X-Outpost-Reset header.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from . import device, for_profile, forget_all, store

router = APIRouter()


def plain_lines(view: dict, echo: dict) -> list[str]:
    """Kid- and parent-friendly sentences for the view."""
    out = []
    al = view.get("aliases") or []
    if al:
        names = ", ".join(f"“{a['heard']}” means {a['name']}" if a.get("heard") else a["name"] for a in al[:6])
        out.append(f"Names you say your way: {names}.")
    else:
        out.append("No names learned yet. When the app asks “Did you mean…?” and you say yes, it remembers how you say it.")
    h = view.get("habits") or {}
    if h.get("end_silence_s", 0.5) > 0.5:
        out.append(f"It waits a little longer before answering ({h['end_silence_s']:.1f} s), so you can finish your thought.")
    else:
        out.append("It waits the usual short pause before answering.")
    if h.get("yes_words"):
        out.append("Your own ways of saying yes: " + ", ".join(h["yes_words"]) + ".")
    if echo.get("delay_ms") is not None:
        out.append(f"This computer's speakers reach its microphone in about {echo['delay_ms']:.0f} ms. "
                   "The app uses that to tell its own voice from yours.")
    else:
        out.append("It is still learning how this computer's speakers sound to its microphone.")
    out.append("Nothing leaves this computer. No recordings are kept. Reset learning erases all of it.")
    return out


@router.get("/api/learn")
def learn_view(request: Request, profile: str | None = None):
    from .. import diag
    if not diag.authorized(request.headers):   # the learned names are the kid's words: the token, even for a GET
        raise HTTPException(401, "missing or wrong local token")
    v = for_profile(profile).describe(include_aliases=True)
    e = device().echo.summary()
    return {"profile": v["profile"], "lines": plain_lines(v, e), "learned": v, "computer": e,
            "stored": "on this computer only", "audio_kept": False}


@router.post("/api/learn/reset")
def learn_reset(request: Request, profile: str | None = None, scope: str = "profile"):
    if request.headers.get("x-outpost-reset") != "1":
        raise HTTPException(400, "missing X-Outpost-Reset")
    if scope == "all":
        return {"ok": True, "scope": "all", "files": forget_all()}
    for_profile(profile).reset()
    device().reset()
    return {"ok": True, "scope": "profile", "profile": store.profile_id(profile)}


@router.post("/api/learn/forget")
async def learn_forget(request: Request, profile: str | None = None):
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    heard = body.get("heard") if isinstance(body, dict) else None
    if not isinstance(heard, str) or not heard.strip():
        raise HTTPException(400, "heard required")
    lr = for_profile(profile)
    ok = lr.aliases.remove(heard)
    lr.save()
    return {"ok": ok}
