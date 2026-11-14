from fastapi.testclient import TestClient

from app.main import app


def test_clip_route_returns_one_clip_with_word_timings():
    with TestClient(app) as c:
        m = c.get("/api/moments?place=aristarchus").json()["moments"]
        cid = m[0]["clip_id"] if m else "aristarchus"
        r = c.get(f"/api/clips/{cid}")
        assert r.status_code == 200
        j = r.json()
        assert j["id"] == cid and j["file"] and j["words"] and isinstance(j["tags"], list)
        assert set(j) == {"id", "title", "file", "dur", "words", "tags", "utterances", "gain_db"}   # gain: §4d
        assert c.get("/api/clips/nope-not-a-clip").status_code == 404
