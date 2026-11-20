"""tools/ear_quant.py, the lighter ear's packer (docs/LOCAL_EAR.md "Lighter ear"): float16 safetensors that read back as
the same tensors, Arc's packed 4-bit layout that dequantises the way libarc's arc_store.c does, the encoder transform on
a tiny graph (when `onnx` is installed: it is a build-time tool), and the real model through libarc when present."""
import importlib.util
import json
import os
from pathlib import Path

import numpy as np
import pytest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("ear_quant", HERE.parent / "tools/ear_quant.py")
EQ = importlib.util.module_from_spec(spec)
spec.loader.exec_module(EQ)


def test_fp16_round_trip_keeps_names_shapes_and_metadata(tmp_path):
    rng = np.random.default_rng(0)
    w = rng.standard_normal((64, 48)).astype(np.float32)
    b = rng.standard_normal(48).astype(np.float32)
    src, dst = tmp_path / "a.safetensors", tmp_path / "b.safetensors"
    EQ.st_write(src, [("x.weight", w), ("x.bias", b), ("ids", np.arange(4, dtype=np.int8))], {"format": "pt"})
    rep = EQ.to_fp16(src, dst)
    assert rep["to"] < rep["from"]
    head, meta, data = EQ.st_read(dst)
    assert meta == {"format": "pt"} and set(head) == {"x.weight", "x.bias", "ids"}
    assert head["x.weight"]["dtype"] == "F16" and head["ids"]["dtype"] == "I8"
    got = EQ.st_tensor(head, data, "x.weight").astype(np.float32)
    assert np.allclose(got, w, rtol=1e-3, atol=1e-4)
    from safetensors.numpy import load_file        # the reference reader agrees on the layout
    ref = load_file(str(dst))
    assert np.array_equal(ref["x.bias"], EQ.st_tensor(head, data, "x.bias"))


def test_fp16_refuses_a_tensor_that_does_not_fit(tmp_path):
    src = tmp_path / "a.safetensors"
    EQ.st_write(src, [("big", np.array([1e6], np.float32))], {})
    with pytest.raises(SystemExit):
        EQ.to_fp16(src, tmp_path / "b.safetensors")


def _dequant_like_arc_store(q, s, z, R, C, pad, g=32):
    """arc_store.c dequant(): w[r, c] = (code - zero) * scale, codes / zeros two per byte, low nibble first."""
    Cp = C + pad
    out = np.zeros((R, C), np.float32)
    for r in range(R):
        for c in range(C):
            k = r * Cp + c
            gi = k // g
            code = (q[k >> 1] >> ((k & 1) * 4)) & 15
            zero = (z[gi >> 1] >> ((gi & 1) * 4)) & 15
            out[r, c] = (code - zero) * s[gi]
    return out


def test_q4_pack_dequantises_as_libarc_does():
    rng = np.random.default_rng(1)
    w = rng.standard_normal((5, 70)).astype(np.float32)       # 70 columns: padded to 96 (groups of 32)
    q, s, z, pad = EQ.q4_pack(w)
    assert pad == 26 and len(s) == 5 * 3
    back = _dequant_like_arc_store(q, s, z, 5, 70, pad)
    step = s.reshape(5, 3).repeat(32, axis=1)[:, :70]
    assert np.all(np.abs(back - w) <= step / 2 + 1e-6)          # round to nearest: within half a step


def test_q4_folder_layout(tmp_path):
    rng = np.random.default_rng(2)
    src, dst = tmp_path / "m.safetensors", tmp_path / "m.q4.safetensors"
    EQ.st_write(src, [("model.decoder.layers.0.mlp.fc1.weight", rng.standard_normal((64, 32)).astype(np.float32)),
                      ("model.decoder.pos_emb.weight", rng.standard_normal((8, 32)).astype(np.float32)),
                      ("model.decoder.norm.weight", np.ones(32, np.float32))], {})
    rep = EQ.to_int4(src, dst)
    head, meta, _ = EQ.st_read(dst)
    lay = json.loads(meta["int4_layout"])
    assert rep["packed"] == 1 and list(lay) == ["model.decoder.layers.0.mlp.fc1.weight"]
    assert lay["model.decoder.layers.0.mlp.fc1.weight"]["rc"] == [64, 32, 0] and meta["group_size"] == "32"
    assert {"model.decoder.pos_emb.weight", "model.decoder.norm.weight"} <= set(head)   # tables / vectors stay float


def test_encoder_transform_on_a_tiny_graph(tmp_path):
    onnx = pytest.importorskip("onnx")
    ort = pytest.importorskip("onnxruntime")
    from onnx import TensorProto, helper, numpy_helper
    rng = np.random.default_rng(3)
    W = rng.standard_normal((16, 8)).astype(np.float32)
    pos = rng.standard_normal((1, 600, 512)).astype(np.float32)      # > 1 MB: the positional-table Constant
    g = helper.make_graph(
        [helper.make_node("MatMul", ["x", "w"], ["y0"]),
         helper.make_node("Constant", [], ["pos"], value=numpy_helper.from_array(pos, "pos")),
         helper.make_node("ReduceSum", ["pos"], ["ps"], keepdims=0),
         helper.make_node("Add", ["y0", "ps"], ["y"])],
        "g", [helper.make_tensor_value_info("x", TensorProto.FLOAT, [2, 16])],
        [helper.make_tensor_value_info("y", TensorProto.FLOAT, None)], [numpy_helper.from_array(W, "w")])
    m = helper.make_model(g, opset_imports=[helper.make_opsetid("", 17)])
    m.ir_version = 8
    src = tmp_path / "src"
    src.mkdir()
    for name in ("encoder.onnx", "encoder_first.onnx"):
        onnx.save(m, str(src / name), save_as_external_data=True, all_tensors_to_one_file=True,
                  location="encoder.weights", size_threshold=0)
    dst = tmp_path / "dst"
    st = EQ.quantize_encoder(src, dst)
    assert st["quantized"] == 1
    m2 = onnx.load(str(dst / "encoder.onnx"), load_external_data=False)
    assert any(n.op_type == "DynamicQuantizeMatMul" for n in m2.graph.node)
    assert all(t.data_location == TensorProto.EXTERNAL for t in m2.graph.initializer)
    offs = [int({e.key: e.value for e in t.external_data}["offset"]) for t in m2.graph.initializer]
    assert all(o % EQ.ALIGN == 0 for o in offs)
    # the two graphs share one weights file: the same tensors at the same offsets
    m3 = onnx.load(str(dst / "encoder_first.onnx"), load_external_data=False)
    ext = lambda mm: sorted((t.name, tuple((e.key, e.value) for e in t.external_data)) for t in mm.graph.initializer)
    assert ext(m2) == ext(m3)
    x = rng.standard_normal((2, 16)).astype(np.float32)
    ref = x @ W + pos.sum()
    got = ort.InferenceSession(str(dst / "encoder.onnx"), providers=["CPUExecutionProvider"]).run(None, {"x": x})[0]
    assert np.allclose(got, ref, rtol=0.05, atol=0.05 * np.abs(x @ W).max())


ARC_DIR = os.environ.get("ARC_SPACE_DIR")


@pytest.mark.skipif(not (ARC_DIR and os.environ.get("ARC_LIB") and os.environ.get("EAR_QUANT_DIR")),
                    reason="set ARC_LIB, ARC_SPACE_DIR (the shipped nft2) and EAR_QUANT_DIR (the lighter copy)")
def test_lighter_ear_hears_the_smoke_clip_like_the_shipped_one():
    from app.nft2 import Nft2
    x = np.frombuffer((HERE.parents[1] / "backend/tests/fixtures/crew_orientale_16k.s16le").read_bytes(),
                      np.int16).astype(np.float32) / 32768
    names = [{"name": "Orientale Basin", "kind": "lunar_feature"}, {"name": "Artemis II", "kind": "mission"}]
    out = []
    for d in (ARC_DIR, os.environ["EAR_QUANT_DIR"]):
        m = Nft2(os.environ["ARC_LIB"], d, threads=2, verify=False)
        m.set_names(names)
        r = m.transcribe(x)
        m.close()
        out.append((r["utts"][0]["text"], [(n["entity"], n["state"]) for n in r["names"]]))
    assert out[0] == out[1]
    assert ("Orientale Basin", "linked") in out[1][1]
