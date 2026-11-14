"""One-time: put all-MiniLM-L6-v2 as ONNX under model_server/models/minilm/ (gitignored).

Tries the upstream ONNX file first (the HF repo ships onnx/model.onnx); without network it exports the cached
safetensors with torch.onnx. Run: `cd model_server && uv run python tools/export_embedder.py`.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

REPO = "sentence-transformers/all-MiniLM-L6-v2"
OUT = Path(__file__).resolve().parent.parent / "models/minilm"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    from huggingface_hub import hf_hub_download, snapshot_download
    snap = Path(snapshot_download(REPO, allow_patterns=["*.json", "vocab.txt", "*.safetensors"]))
    shutil.copy(snap / "tokenizer.json", OUT / "tokenizer.json")
    try:
        if not (OUT / "model.onnx").exists():
            shutil.copyfile(hf_hub_download(REPO, "onnx/model.onnx"), OUT / "model.onnx")
        print("downloaded upstream onnx/model.onnx")
    except Exception as e:  # noqa: BLE001
        print(f"upstream ONNX unavailable ({e.__class__.__name__}); exporting with torch.onnx")
        import torch
        from transformers import AutoModel
        m = AutoModel.from_pretrained(str(snap)).eval()
        ids = torch.ones(1, 8, dtype=torch.long)
        torch.onnx.export(m, (ids, ids, torch.zeros_like(ids)), str(OUT / "model.onnx"),
                          input_names=["input_ids", "attention_mask", "token_type_ids"],
                          output_names=["last_hidden_state"], opset_version=17, dynamo=False,
                          dynamic_axes={k: {0: "b", 1: "t"} for k in ("input_ids", "attention_mask", "token_type_ids",
                                                                       "last_hidden_state")})
    if "--int8" in sys.argv:
        from onnxruntime.quantization import QuantType, quantize_dynamic
        quantize_dynamic(str(OUT / "model.onnx"), str(OUT / "model.int8.onnx"), weight_type=QuantType.QInt8)
        print("wrote model.int8.onnx")
    print("ok", sorted(x.name for x in OUT.iterdir()))


if __name__ == "__main__":
    main()
