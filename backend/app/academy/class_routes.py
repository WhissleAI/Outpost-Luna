"""Class lessons API (docs/CURRICULUM.md): teacher-written lesson packs, stored on this computer only.

GET    /api/class/packs            every pack (as written) + the loader's problems
GET    /api/class/packs/{id}       one pack, as written (Export)
PUT    /api/class/packs/{id}       save (validated; 422 with {errors, warnings} when it fails the checks)
DELETE /api/class/packs/{id}
POST   /api/class/validate         check a pack without saving: {ok, errors, warnings}
POST   /api/class/preview          {pack, lesson}: play one lesson as it will look, without saving → {lesson_id}
DELETE /api/class/preview
GET    /api/class/places           the places a lesson may use: [{id, name}]

Writes need the app's own page (same origin + `X-Outpost-Class: 1`), like Reset: another web page can't add lessons.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from . import classpacks

router = APIRouter()


def _guard(req: Request) -> None:
    from ..reset import _same_origin
    if req.headers.get("x-outpost-class") != "1" or not _same_origin(req):
        raise HTTPException(403, "class lessons are only changed from the app itself")


async def _body(req: Request):
    raw = await req.body()
    if len(raw) > classpacks.MAX_BYTES:
        raise HTTPException(413, f"a pack is at most {classpacks.MAX_BYTES // 1000} KB")
    try:
        import json
        return json.loads(raw or b"null")
    except ValueError:
        return None


@router.get("/api/class/packs")
def list_packs():
    return {"packs": [{"id": p["id"], "title": p["title"], "pack": p["source"],
                       "lessons": [l["id"] for l in p["lessons"]]} for p in classpacks.packs()],
            "problems": classpacks.problems()}


@router.get("/api/class/places")
def class_places():
    return classpacks.places()


@router.get("/api/class/packs/{pack_id}")
def get_pack(pack_id: str):
    p = classpacks.get(pack_id)
    if p is None:
        raise HTTPException(404, "no such pack")
    return {k: v for k, v in p.items() if k != "saved_at"}


@router.post("/api/class/validate")
async def validate_pack(req: Request):
    errs, warns = classpacks.validate(await _body(req))
    return {"ok": not errs, "errors": errs, "warnings": warns}


@router.put("/api/class/packs/{pack_id}")
async def put_pack(pack_id: str, req: Request):
    _guard(req)
    pack = await _body(req)
    if isinstance(pack, dict) and pack.get("id") != pack_id:
        return JSONResponse({"ok": False, "errors": [{"at": "id", "msg": "The pack id doesn't match."}], "warnings": []}, 422)
    try:
        errs, warns = classpacks.save(pack) if isinstance(pack, dict) else classpacks.validate(pack)
    except OSError as e:
        return JSONResponse({"ok": False, "errors": [{"at": "", "msg": f"Couldn't save on this computer ({e.strerror or e})."}],
                             "warnings": []}, 507)
    if errs:
        return JSONResponse({"ok": False, "errors": errs, "warnings": warns}, 422)
    return {"ok": True, "errors": [], "warnings": warns}


@router.delete("/api/class/packs/{pack_id}")
def delete_pack(pack_id: str, req: Request):
    _guard(req)
    if not classpacks.delete(pack_id):
        raise HTTPException(404, "no such pack")
    return {"ok": True}


@router.post("/api/class/preview")
async def preview(req: Request):
    _guard(req)
    b = await _body(req)
    if not isinstance(b, dict) or not isinstance(b.get("pack"), dict):
        return JSONResponse({"ok": False, "errors": [{"at": "", "msg": "Nothing to preview."}]}, 422)
    errs, lid = classpacks.set_preview(b["pack"], int(b.get("lesson") or 0))
    if errs:
        return JSONResponse({"ok": False, "errors": errs}, 422)
    return {"ok": True, "lesson_id": lid}


@router.delete("/api/class/preview")
def end_preview(req: Request):
    _guard(req)
    classpacks.set_preview(None)
    return {"ok": True}
