"""Tiny local text embedder: all-MiniLM-L6-v2 on ONNX Runtime + `tokenizers` (no torch at runtime).

POST /v1/embed {texts:[...], kind:"query"|"doc"} -> {vectors:[[...384 floats, L2-normalized]], dim, model, ms}.
The API shape is model-agnostic: Head Start's future shared /v1/embed serves EmbeddingGemma behind the same request
(EmbeddingGemma uses `kind` to pick its query/document prompt; MiniLM is symmetric and ignores it).

EMBED=on|off (default on). Fails open: a missing model leaves /v1/embed at 503 and the reason in /health; the backend
then answers from rules + card aliases only. Weights: `uv run python tools/export_embedder.py [--int8]`.
"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import numpy as np
from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

MODEL_DIR = Path(os.environ.get("EMBED_MODEL_DIR", Path(__file__).resolve().parent.parent / "models/minilm"))
MODEL_FILE = os.environ.get("EMBED_MODEL_FILE", "model.int8.onnx")
MAX_TOKENS = 64        # kid questions and card questions are short; also bounds latency
MAX_TEXTS = 256

S: dict = {"sess": None, "tok": None, "error": None, "load_s": None, "rss_delta_mb": None, "file": None, "lock": threading.Lock()}


def _rss() -> float:
    import psutil
    return psutil.Process().memory_info().rss / 2**20


def load() -> None:
    if os.environ.get("EMBED", "on").lower() in ("off", "0", "false"):
        S["error"] = "EMBED=off"
        return
    t, r0 = time.perf_counter(), _rss()
    try:
        import onnxruntime as ort
        from tokenizers import Tokenizer
        f = MODEL_DIR / MODEL_FILE
        if not f.exists():
            f = MODEL_DIR / "model.onnx"
        tok = Tokenizer.from_file(str(MODEL_DIR / "tokenizer.json"))
        tok.enable_truncation(MAX_TOKENS)
        tok.enable_padding(pad_id=0, pad_token="[PAD]")
        so = ort.SessionOptions()
        so.intra_op_num_threads = 2
        S["sess"] = ort.InferenceSession(str(f), so, providers=["CPUExecutionProvider"])
        S["tok"], S["file"] = tok, f.name
        embed(["warm up"])
    except Exception as e:  # noqa: BLE001 - fail open
        S["sess"], S["error"] = None, f"{e.__class__.__name__}: {e}"
    S["load_s"] = round(time.perf_counter() - t, 2)
    S["rss_delta_mb"] = round(_rss() - r0)


def embed(texts: list[str]) -> np.ndarray:
    tok, sess = S["tok"], S["sess"]
    enc = tok.encode_batch([t or " " for t in texts])
    ids = np.array([e.ids for e in enc], dtype=np.int64)
    mask = np.array([e.attention_mask for e in enc], dtype=np.int64)
    feeds = {"input_ids": ids, "attention_mask": mask}
    if any(i.name == "token_type_ids" for i in sess.get_inputs()):
        feeds["token_type_ids"] = np.zeros_like(ids)
    with S["lock"]:
        hidden = sess.run(None, feeds)[0]                      # (b, t, 384)
    m = mask[..., None].astype(np.float32)
    v = (hidden * m).sum(1) / np.clip(m.sum(1), 1e-9, None)    # mean pooling (sentence-transformers config)
    return (v / np.clip(np.linalg.norm(v, axis=1, keepdims=True), 1e-9, None)).astype(np.float32)


def health() -> dict:
    return {"embedder": {"loaded": S["sess"] is not None, "error": S["error"], "model": "all-MiniLM-L6-v2",
                         "file": S["file"], "dim": 384, "load_s": S["load_s"], "rss_delta_mb": S["rss_delta_mb"]}}


class EmbedRequest(BaseModel):
    texts: list[str] = Field(..., min_length=1, max_length=MAX_TEXTS)
    kind: str = Field("query", pattern="^(query|doc)$")


router = APIRouter()


@router.post("/v1/embed")
async def embed_route(req: EmbedRequest):
    if S["sess"] is None:
        raise HTTPException(503, f"embedder not loaded: {S['error']}")
    t = time.perf_counter()
    v = await run_in_threadpool(embed, req.texts)
    return {"vectors": v.round(5).tolist(), "dim": int(v.shape[1]), "model": "all-MiniLM-L6-v2", "kind": req.kind,
            "ms": round((time.perf_counter() - t) * 1000, 2)}
