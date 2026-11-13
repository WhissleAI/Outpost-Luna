import numpy as np
import pytest

from app import embed

pytestmark = pytest.mark.skipif(not (embed.MODEL_DIR / "tokenizer.json").exists(),
                                reason="embedder weights not exported (tools/export_embedder.py)")


@pytest.fixture(scope="module", autouse=True)
def loaded():
    embed.load()
    assert embed.S["sess"] is not None, embed.S["error"]


def test_vectors_normalized_and_semantic():
    v = embed.embed(["how big is tycho crater", "what is the size of tycho", "turn on the heaters"])
    assert v.shape == (3, 384)
    assert np.allclose(np.linalg.norm(v, axis=1), 1, atol=1e-3)
    assert v[0] @ v[1] > v[0] @ v[2] + 0.2


def test_route():
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        r = c.post("/v1/embed", json={"texts": ["hello moon"], "kind": "query"})
        assert r.status_code == 200 and r.json()["dim"] == 384
        assert c.get("/health").json()["models"]["embedder"]["loaded"]
        assert c.post("/v1/embed", json={"texts": []}).status_code == 422
