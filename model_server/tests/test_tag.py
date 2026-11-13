import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        if not c.get("/health").json()["ok"]:
            pytest.skip("Arc Tagger library/model not available on this machine")
        yield c


def test_question_act_and_place_mention(client):
    r = client.post("/v1/tag", json={"text": "how big is Orientale", "domain": "assistant"}).json()
    assert any(s["text"] == "Orientale" for s in r["spans"])
    acts = [a["tag"] for a in r["utterances"][0]["act"] if a["on"]]
    assert "discourse.act.question" in acts


def test_words_keep_indices(client):
    words = ["Look", "at", "Glushko", "and", "go", "northwest."]
    r = client.post("/v1/tag", json={"words": words, "domain": "news"}).json()
    assert r["words"] == words


def test_street_address_is_pii(client):
    r = client.post("/v1/tag", json={"text": "I live at 42 Oak Street", "domain": "assistant"}).json()
    assert any(s["type"].endswith("street_address") for s in r["spans"])


def test_rejects_both_inputs(client):
    assert client.post("/v1/tag", json={"text": "a", "words": ["a"]}).status_code == 422
