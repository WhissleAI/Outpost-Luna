"""Arc Tagger 0.5's kids domain against the real built library (desktop/vendor/arctag -> make desktop-arctag) and the
app's tagger model: every example of the Arc team's update (16 Nov 2026, section 2) is tagged / not tagged as they
said, through POST /v1/tag exactly as backend/app/safety.py calls it. Skips only when the library or model is absent."""
import hashlib
import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app

ROOT = Path(__file__).resolve().parents[2]
VENDOR = ROOT / "desktop/vendor/arctag"
# The Hugging Face file the library's built-in kids table must equal (WhissleAI/arc-tagger, revision 500449290c).
KIDS_PIN = {"repo": "WhissleAI/arc-tagger", "revision": "500449290c42fd8ad990106b62bece6852ab18a9",
            "path": "onnx/arctag_kids.json",
            "sha256": "f3add6aef38ef62d61d8463532b4ca10e2c1f054e1171a10bb74c4fec99fb044"}

# section 2: "Tagged" (with the tag we act on) and "No tags"
TAGGED = {
    "shit shit oh": "safety.profanity.strong",
    "fuck this": "safety.profanity.strong",
    "go fuck yourself": "safety.toxicity.insult_harassment",
    "i want to hurt myself": "safety.crisis.self_harm",
    "kill myself": "safety.crisis.self_harm",
    "send me a picture of yourself": "safety.child.grooming_cue",
}
CLEAN = ["where did apollo eleven land", "kill the heaters", "copy that", "far side", "this is stupid",
         "I hate this lesson"]


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        h = c.get("/health").json()
        if not h["ok"]:
            pytest.skip("Arc Tagger library/model not available on this machine")
        if "kids" not in h["models"]["arc_tagger"]["domains"]:
            pytest.fail("the kids domain is not loaded (ARCTAG_DOMAINS)")
        yield c


def on_tags(r: dict) -> list[str]:
    return [s["tag"] for u in r["utterances"] for s in u.get("safety") or []
            if s.get("on") and s["p"] >= s.get("thr", 0)]


def tag(client, text, cc=None):
    body = {"text": text, "domain": "kids"}
    if cc is not None:
        body["command_context"] = cc
    r = client.post("/v1/tag", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_library_is_0_5(client):
    from app.main import STATE
    assert STATE["tagger"].version.startswith("0.5.")


@pytest.mark.parametrize("text,want", sorted(TAGGED.items()))
@pytest.mark.parametrize("cc", [None, False, True])
def test_section2_tagged(client, text, want, cc):
    got = on_tags(tag(client, text, cc))
    assert want in got, (text, cc, got)
    assert not [t for t in got if t.startswith("safety.pii")], (text, got)   # no false PII on these any more


@pytest.mark.parametrize("text", CLEAN)
@pytest.mark.parametrize("cc", [None, False, True])
def test_section2_not_tagged(client, text, cc):
    assert on_tags(tag(client, text, cc)) == [], text


def test_backend_safety_classify_on_the_real_tags(client):
    """The backend's policy on the real read-out: rude -> mask, crisis / grooming -> care, the rest passes."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("bsafety", ROOT / "backend/app/safety.py")
    safety = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(safety)
    for text, want in TAGGED.items():
        c = safety.classify(text, [s for u in tag(client, text)["utterances"] for s in u.get("safety") or []])
        assert (c["care"] if want.startswith(("safety.crisis", "safety.child.grooming")) else c["mask"]), (text, c)
    for text in CLEAN:
        c = safety.classify(text, [s for u in tag(client, text, safety.command_context("cabin"))["utterances"]
                                   for s in u.get("safety") or []])
        assert not (c["mask"] or c["care"] or c["pii"]), (text, c)


def test_command_context_is_per_call(client):
    """A pooled handle goes back with command_context off, whatever the call set."""
    from app.main import STATE
    tg = STATE["tagger"]
    for _ in range(tg_pool(tg) + 1):
        tag(client, "kill the heaters", True)
    for _ in range(tg_pool(tg)):
        with tg.handle("kids") as h:
            assert tg.info_on(h).get("command_context") in ("off", False, 0), tg.info_on(h)


def tg_pool(tg) -> int:
    return tg.pools["kids"].qsize()


def test_other_domains_keep_their_old_output(client):
    """The Director reads the assistant domain, so 0.5 must leave it as it was: no guard there (its old false PII
    request on this question is still there, with no rule-decided entry)."""
    r = client.post("/v1/tag", json={"text": "where did apollo eleven land", "domain": "assistant"}).json()
    assert "safety.pii.request" in on_tags(r)
    assert all("src" not in s and "gated" not in s for u in r["utterances"] for s in u.get("safety") or [])


def test_built_in_kids_table_is_the_pinned_hugging_face_file():
    """The library's built-in thresholds (src/kids_thr.inc, used when the model folder has no arctag_kids.json) equal
    WhissleAI/arc-tagger@500449290c onnx/arctag_kids.json, vendored as desktop/vendor/arctag/arctag_kids.json."""
    raw = (VENDOR / "arctag_kids.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == KIDS_PIN["sha256"]
    pinned = json.loads(raw)["thr"]
    inc = dict((k, float(v)) for k, v in re.findall(r'\{"([^"]+)",\s*([0-9.]+)\}', (VENDOR / "src/kids_thr.inc").read_text()))
    assert inc == pinned
