"""Make a lighter copy of the ear's model (Arc Transcriber Space nft2/) for the int8 study (docs/LOCAL_EAR.md "Lighter
ear"). The 4-bit Arc trunk (model.q4.safetensors) and the already-int8 encoder MatMuls are kept as they are; what is
still float32 can be:

  --encoder int8   the conformer's float32 MatMuls (both feed-forward linear2 of every layer, linear_pos, pre_encode.out:
                   left out of the upstream int8 plan because per-TENSOR int8 cost 15% Arc-frame rel L2) as per-CHANNEL
                   8-bit weights (uint8 + zero point), com.microsoft DynamicQuantizeMatMul (the op ORT fuses the shipped
                   int8 pattern into).
                   The two encoder graphs keep sharing ONE encoder.weights (libarc maps it once: arc_nft2_ort.c), tensors
                   deduplicated by content, 64-byte aligned.
  --decoder fp16   decoder/model.safetensors (the Moonshine text decoder) stored float16; libarc widens it to float32 at
                   load (arc_store.c), so RAM is unchanged, the download halves.
  --decoder int4   ... its matrices in Arc's packed 4-bit layout (decoder/model.q4.safetensors, groups of 32 with a zero
                   point: the trunk's format, used in place by arc_q4_linear; libarc prefers model.q4.safetensors).
  --adapters fp16  adapters.safetensors (heads, events, the Arc adapter) stored float16 (widened at load).

    uv run --with onnx python tools/ear_quant.py --src <nft2 dir> --out <new nft2 dir> --encoder int8 --decoder fp16 \
        --adapters fp16

Files that are not changed are hard-linked (or copied) from --src. config.json's encoder_onnx quantization note is
updated. Needs `onnx` (not a model-server dependency: a build-time tool)."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
from pathlib import Path

import numpy as np

ALIGN = 64


# ------------------------------------------------------------------------------------------------- safetensors
def st_read(path: Path) -> tuple[dict, dict, bytes]:
    raw = path.read_bytes()
    n = struct.unpack("<Q", raw[:8])[0]
    head = json.loads(raw[8:8 + n])
    meta = head.pop("__metadata__", {}) or {}
    return head, meta, raw[8 + n:]


DT = {"F32": np.float32, "F16": np.float16, "U8": np.uint8, "I8": np.int8}


def st_tensor(head: dict, data: bytes, name: str) -> np.ndarray:
    h = head[name]
    a, b = h["data_offsets"]
    return np.frombuffer(data[a:b], DT[h["dtype"]]).reshape(h["shape"])


def st_write(path: Path, tensors: list[tuple[str, np.ndarray]], meta: dict) -> None:
    head, off, blobs = {}, 0, []
    for name, a in tensors:
        a = np.ascontiguousarray(a)
        dt = {np.float32: "F32", np.float16: "F16", np.uint8: "U8", np.int8: "I8"}[a.dtype.type]
        b = a.tobytes()
        head[name] = {"dtype": dt, "shape": list(a.shape), "data_offsets": [off, off + len(b)]}
        blobs.append(b)
        off += len(b)
    if meta:
        head["__metadata__"] = {k: (v if isinstance(v, str) else json.dumps(v, separators=(",", ":")))
                                for k, v in meta.items()}
    hj = json.dumps(head, separators=(",", ":")).encode()
    hj += b" " * ((8 - len(hj) % 8) % 8)
    with open(path, "wb") as f:
        f.write(struct.pack("<Q", len(hj)))
        f.write(hj)
        for b in blobs:
            f.write(b)


def to_fp16(src: Path, dst: Path) -> dict:
    head, meta, data = st_read(src)
    out = []
    for name in head:
        a = st_tensor(head, data, name)
        if a.dtype == np.float32:
            if np.abs(a).max(initial=0) > 65000:
                raise SystemExit(f"{src.name}: {name} does not fit float16")
            a = a.astype(np.float16)
        out.append((name, a))
    st_write(dst, out, meta)
    return {"from": src.stat().st_size, "to": dst.stat().st_size}


def q4_pack(w: np.ndarray, g: int = 32) -> tuple[np.ndarray, np.ndarray, np.ndarray, int]:
    """Arc's packed 4-bit layout (arc_store.h): rows of W [R, C] padded to Cp (a multiple of g), per group of g an
    asymmetric (code - zero) * scale, codes / zeros two per byte, low nibble first. Round to nearest, min/max range."""
    R, C = w.shape
    pad = (-C) % g
    wp = np.pad(w.astype(np.float32), ((0, 0), (0, pad)))
    Cp = C + pad
    grp = wp.reshape(R, Cp // g, g)
    lo, hi = grp.min(-1), grp.max(-1)
    lo, hi = np.minimum(lo, 0), np.maximum(hi, 0)
    scale = (hi - lo) / 15.0
    scale[scale == 0] = 1.0
    zero = np.clip(np.round(-lo / scale), 0, 15)
    code = np.clip(np.round(grp / scale[..., None]) + zero[..., None], 0, 15).astype(np.uint8).reshape(-1)
    q = (code[0::2] | (code[1::2] << 4)).astype(np.uint8)
    z = zero.astype(np.uint8).reshape(-1)
    if len(z) % 2:
        z = np.append(z, 0)
    zp = (z[0::2] | (z[1::2] << 4)).astype(np.uint8)
    return q, scale.astype(np.float32).reshape(-1), zp, pad


def to_int4(src: Path, dst: Path, keep_float: tuple[str, ...] = ()) -> dict:
    """Every 2-D float matrix of the decoder (projections, mlp, the tied embedding) packed; vectors and pos_emb stay."""
    head, meta, data = st_read(src)
    out, layout = [], {}
    for name in head:
        a = st_tensor(head, data, name)
        if a.ndim == 2 and a.dtype == np.float32 and name.endswith(".weight") and "pos_emb" not in name \
                and not any(k in name for k in keep_float) and a.shape[1] >= 32:
            q, s, z, pad = q4_pack(a)
            layout[name] = {"shape": list(a.shape), "axis": -1, "rc": [a.shape[0], a.shape[1], pad], "dtype": "float32"}
            out += [(f"{name}.q", q), (f"{name}.s", s), (f"{name}.z", z)]
        else:
            out.append((name, a))
    meta = {**meta, "group_size": "32", "int4_layout": layout}
    st_write(dst, out, meta)
    return {"from": src.stat().st_size, "to": dst.stat().st_size, "packed": len(layout)}


# ------------------------------------------------------------------------------------------------- encoder
def quantize_encoder(src: Path, dst: Path, skip: str | None = None) -> dict:
    """skip: a regex over MatMul node names kept float32 (e.g. "^/pre_encode/")."""
    import onnx
    from onnx import TensorProto, helper, numpy_helper

    graphs = {}
    for g in ("encoder.onnx", "encoder_first.onnx"):
        if (src / g).exists():
            graphs[g] = onnx.load(str(src / g), load_external_data=True)
    stats = {"quantized": 0, "fp32_bytes": 0, "int8_bytes": 0}
    for gname, m in graphs.items():
        inits = {t.name: t for t in m.graph.initializer}
        users: dict[str, list] = {}
        for n in m.graph.node:
            for i in n.input:
                users.setdefault(i, []).append(n)
        new_nodes, done = [], {}
        for n in m.graph.node:
            w = inits.get(n.input[1]) if n.op_type == "MatMul" and len(n.input) == 2 else None
            if w is None or w.data_type != TensorProto.FLOAT or len(w.dims) != 2 or len(users[w.name]) != 1 or \
                    (skip and re.search(skip, n.name or "")):
                new_nodes.append(n)
                continue
            W = numpy_helper.to_array(w).astype(np.float32)          # [K, N]
            # per output channel, asymmetric uint8 with a zero point: ONNX Runtime then runs u8 x u8, which has no
            # int16 saturation on x86 AVX2 without VNNI (u8 x s8 goes through vpmaddubsw there: older Windows PCs)
            lo, hi = np.minimum(W.min(axis=0), 0.0), np.maximum(W.max(axis=0), 0.0)
            scale = np.where(hi > lo, (hi - lo) / 255.0, 1.0).astype(np.float32)
            zp = np.clip(np.round(-lo / scale), 0, 255).astype(np.uint8)
            Q = np.clip(np.round(W / scale) + zp, 0, 255).astype(np.uint8)
            qn, sn, zn = w.name + "_q8c", w.name + "_s8c", w.name + "_z8c"
            done[w.name] = (numpy_helper.from_array(Q, qn), numpy_helper.from_array(scale, sn),
                            numpy_helper.from_array(zp, zn))
            new_nodes.append(helper.make_node("DynamicQuantizeMatMul", [n.input[0], qn, sn, zn], list(n.output),
                                              name=(n.name or n.output[0]) + "_dq8c", domain="com.microsoft"))
            if gname == "encoder.onnx":
                stats["quantized"] += 1
                stats["fp32_bytes"] += W.nbytes
                stats["int8_bytes"] += Q.nbytes + scale.nbytes + zp.nbytes
        keep = [t for t in m.graph.initializer if t.name not in done]
        del m.graph.initializer[:]
        m.graph.initializer.extend(keep + [t for pair in done.values() for t in pair])
        del m.graph.node[:]
        m.graph.node.extend(new_nodes)
        if not any(o.domain == "com.microsoft" for o in m.opset_import):
            m.opset_import.append(helper.make_opsetid("com.microsoft", 1))
    # one shared encoder.weights: every initializer with data, and the big Constant tensors (the [1, 9999, 512]
    # positional table, external upstream too: ORT reads it from the folder libarc names), deduplicated by content
    blob, where = bytearray(), {}
    for m in graphs.values():
        consts = [a.t for n in m.graph.node if n.op_type == "Constant" for a in n.attribute
                  if a.type == onnx.AttributeProto.TENSOR and a.t.ByteSize() > (1 << 20)]
        for t in list(m.graph.initializer) + consts:
            arr = numpy_helper.to_array(t)
            b = arr.tobytes()
            if not b:
                continue
            key = (t.data_type, tuple(t.dims), hashlib.sha256(b).hexdigest())
            if key not in where:
                blob += b"\0" * ((-len(blob)) % ALIGN)
                where[key] = (len(blob), len(b))
                blob += b
            off, ln = where[key]
            t.ClearField("raw_data")
            for f in ("float_data", "int32_data", "int64_data", "double_data", "uint64_data", "string_data"):
                t.ClearField(f)
            t.data_location = TensorProto.EXTERNAL
            del t.external_data[:]
            for k, v in (("location", "encoder.weights"), ("offset", str(off)), ("length", str(ln))):
                e = t.external_data.add()
                e.key, e.value = k, v
    dst.mkdir(parents=True, exist_ok=True)
    (dst / "encoder.weights").write_bytes(bytes(blob))
    for g, m in graphs.items():
        with open(dst / g, "wb") as f:
            f.write(m.SerializeToString())
    stats["weights_bytes"] = len(blob)
    return stats


# ------------------------------------------------------------------------------------------------- folder
def link_or_copy(a: Path, b: Path) -> None:
    """A copy-on-write clone where the file system has one (APFS: `cp -c`), else a copy. Never a hard link: the source
    is often an installed asset that must not change if the new folder is edited."""
    b.parent.mkdir(parents=True, exist_ok=True)
    if b.exists():
        b.unlink()
    if sys.platform == "darwin" and subprocess.run(["cp", "-c", str(a), str(b)], capture_output=True).returncode == 0:
        return
    shutil.copy2(a, b)


def build(src: Path, out: Path, encoder: str, decoder: str, adapters: str, encoder_skip: str | None = None) -> dict:
    if out.exists():
        shutil.rmtree(out)
    rep = {}
    replaced = set()
    if encoder == "int8":
        rep["encoder"] = quantize_encoder(src / "encoder_onnx", out / "encoder_onnx", encoder_skip)
        replaced |= {"encoder_onnx/encoder.onnx", "encoder_onnx/encoder_first.onnx", "encoder_onnx/encoder.weights"}
    if decoder == "fp16":
        (out / "decoder").mkdir(parents=True, exist_ok=True)
        rep["decoder"] = to_fp16(src / "decoder/model.safetensors", out / "decoder/model.safetensors")
        replaced.add("decoder/model.safetensors")
    elif decoder == "int4":
        (out / "decoder").mkdir(parents=True, exist_ok=True)
        rep["decoder"] = to_int4(src / "decoder/model.safetensors", out / "decoder/model.q4.safetensors")
        replaced.add("decoder/model.safetensors")       # libarc reads model.q4.safetensors first; drop the float copy
    if adapters == "fp16":
        rep["adapters"] = to_fp16(src / "adapters.safetensors", out / "adapters.safetensors")
        replaced.add("adapters.safetensors")
    for p in sorted(src.rglob("*")):
        rel = p.relative_to(src).as_posix()
        if p.is_file() and rel not in replaced and not (out / rel).exists():
            link_or_copy(p, out / rel)
    if encoder == "int8":
        cfgp = out / "encoder_onnx/config.json"
        cfg = json.loads(cfgp.read_text())
        q = cfg.setdefault("quantization", {})
        q["outpost_int8"] = {"kind": "per-channel 8-bit weights (uint8 + zero point), com.microsoft DynamicQuantizeMatMul",
                             "ops": "every float32 MatMul left by the upstream plan (feed_forward linear2, "
                                    "pre_encode.out)", "kept_float32": encoder_skip, "tool": "model_server/tools/ear_quant.py",
                             "encoder.weights": rep["encoder"]["weights_bytes"]}
        cfgp.unlink()
        cfgp.write_text(json.dumps(cfg, indent=1))
    return rep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", type=Path, required=True, help="the shipped nft2/ folder")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--encoder", choices=["keep", "int8"], default="keep")
    ap.add_argument("--decoder", choices=["keep", "fp16", "int4"], default="keep")
    ap.add_argument("--adapters", choices=["keep", "fp16"], default="keep")
    ap.add_argument("--encoder-skip", default=None, help="regex: encoder MatMul nodes kept float32")
    a = ap.parse_args()
    rep = build(a.src, a.out, a.encoder, a.decoder, a.adapters, a.encoder_skip)
    size = sum(p.stat().st_size for p in a.out.rglob("*") if p.is_file())
    print(json.dumps({**rep, "total_bytes": size}, indent=1))


if __name__ == "__main__":
    main()
