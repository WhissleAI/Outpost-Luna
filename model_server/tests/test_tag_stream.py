import json

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app import tag_stream
from app.config import settings
from app.main import STATE, app

# a question with a revision ("Tycho" -> "Copernicus" from word 3) and an endpoint, as Head Start's session sends it
SCRIPT = [
    ("push", {"words": ["show", "me", "Tycho"], "from": None, "endpoint": False}),
    ("poll", {}),
    ("push", {"words": ["Copernicus", "crater", "please"], "from": 2, "endpoint": False}),
    ("poll", {}),
    ("endpoint", {}),
    ("poll", {}),
    ("reset", {}),
    ("push", {"words": ["my", "name", "is", "Maya", "and", "I", "live", "at", "42", "Oak", "Street"],
              "from": None, "endpoint": True}),
    ("poll", {}),
    ("tag_text", {"text": "how big is Orientale"}),
]


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        if not c.get("/health").json()["ok"]:
            pytest.skip("Arc Tagger library/model not available on this machine")
        yield c


def _strip(d):
    d = dict(d)
    d.pop("ms", None)
    return d


def _direct(tg, domain="assistant"):
    """The same script straight through the ctypes binding, on its own handle."""
    h, outs = tg.open_stream(domain), []
    try:
        for op, m in SCRIPT:
            if op == "push":
                if m["from"] is None and not m["endpoint"]:
                    tg.push_words(h, json.dumps(m["words"]).encode())
                else:
                    p = {"words": m["words"]}
                    if m["from"] is not None:
                        p["from"] = m["from"]
                    if m["endpoint"]:
                        p["endpoint"] = True
                    tg.push_words(h, json.dumps(p).encode())
            elif op == "endpoint":
                tg.push_words(h, b'{"endpoint": true}')
            elif op == "reset":
                tg.reset(h)
            elif op == "poll":
                outs.append(tg.poll(h))
            elif op == "tag_text":
                outs.append(tg.tag_text_on(h, m["text"]))
    finally:
        tg.close_stream(h)
    return outs


def test_round_trip_matches_library(client):
    want = _direct(STATE["tagger"])
    got = []
    with client.websocket_connect("/v1/tag/stream?domain=assistant") as ws:
        assert ws.receive_json()["op"] == "ready"
        for op, m in SCRIPT:
            ws.send_json({"op": op, **m})
            if op in ("poll", "tag_text"):
                got.append(ws.receive_json())
    assert [_strip(g) for g in got] == [_strip(w) for w in want]
    # the revision took: Copernicus, not Tycho, is what the stream holds
    assert "Copernicus" in json.dumps(got[1]) and len(got) == 5


def test_handle_is_destroyed_on_close(client):
    n0 = STATE["tagger"].streams
    with client.websocket_connect("/v1/tag/stream") as ws:
        ws.receive_json()
        assert STATE["tagger"].streams == n0 + 1
    for _ in range(50):
        if STATE["tagger"].streams == n0:
            break
        import time
        time.sleep(0.01)
    assert STATE["tagger"].streams == n0 and tag_stream.ACTIVE["n"] == 0


def test_bad_push_error_comes_back_on_next_reply(client):
    with client.websocket_connect("/v1/tag/stream") as ws:
        ws.receive_json()
        ws.send_json({"op": "set", "key": "no_such_option", "value": "1"})
        ws.send_json({"op": "poll"})
        assert ws.receive_json()["op"] == "error"
        ws.send_json({"op": "poll"})          # the error is reported once; the stream keeps working
        assert ws.receive_json().get("op") != "error"


def test_cap_closes_with_1013(client, monkeypatch):
    monkeypatch.setattr(settings, "tag_stream_max", 1)
    with client.websocket_connect("/v1/tag/stream") as ws:
        ws.receive_json()
        with client.websocket_connect("/v1/tag/stream") as ws2:
            with pytest.raises(WebSocketDisconnect) as e:
                ws2.receive_json()
            assert e.value.code == 1013


def test_unknown_domain_closes_1008(client):
    with client.websocket_connect("/v1/tag/stream?domain=nope") as ws:
        with pytest.raises(WebSocketDisconnect) as e:
            ws.receive_json()
        assert e.value.code == 1008
