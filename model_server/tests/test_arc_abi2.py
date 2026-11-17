"""libarc ABI 2 on the real model (skips without it): confidences, n-best, almost names, quantities, the live stream's
events, mid-stream names, the playback reference. Fixture: 7 s of a real crew voice (Reid Wiseman, NASA audio)."""
import base64
import json
from pathlib import Path

import numpy as np
import pytest

from app import arc_ear, arcmeta, nft2
from app.routes_meta import ref_pcm

FIX = Path(__file__).resolve().parents[2] / "backend/tests/fixtures/crew_orientale_16k.s16le"
NAMES = [{"name": "Orientale Basin", "kind": "lunar_feature", "aliases": ["Orientale", "Mare Orientale"]},
         {"name": "Hertzsprung", "kind": "lunar_feature"}, {"name": "Reid Wiseman", "kind": "crew"}]


@pytest.fixture(scope="module")
def model():
    if arcmeta.STATE.get("arc") is None:
        arcmeta.load()
    m = arcmeta.STATE.get("arc")
    if m is None:
        pytest.skip(f"Arc Transcriber Space not loaded: {arcmeta.STATE['error']}")
    return m


def pcm():
    return np.frombuffer(FIX.read_bytes(), dtype="<i2").astype(np.float32) / 32768.0


def test_abi_is_2(model):
    assert model.abi == 2 and model.version.startswith("1.3.0")


def test_transcribe_reads_out_conf_nbest_and_almost(model):
    out = model.transcribe(pcm(), names=NAMES, almost=True, nbest=4)
    u = out["utts"][0]
    assert 0 <= u["conf"] <= 1 and isinstance(u["quantities"], list) and isinstance(u["n_dropped"], int)
    assert all("conf" in w for w in u["words"]) and u["clean_text"]
    assert len(u["nbest"]) >= 1 and all(0 <= a["p"] <= 1 for a in u["nbest"])
    assert all(n["state"] in ("linked", "abstain", "not_in_list", "almost") for n in out["names"])
    plain = model.transcribe(pcm(), names=NAMES)
    assert [w["w"] for w in plain["utts"][0]["words"]] == [w["w"] for w in u["words"]]   # n-best leaves the words alone


def run_live(es, x, chunk=1280):
    b = (np.clip(x, -1, 1) * 32767).astype("<i2").tobytes()
    msgs = []
    for i in range(0, len(b), 2 * chunk):
        msgs += es.feed_all(b[i:i + 2 * chunk])
    return msgs + es.flush_all()


def test_live_stream_partials_then_a_linked_final(model):
    es = arc_ear.EarStream(names=NAMES, s=arc_ear.EarSettings(ear_live=True))
    assert es.live
    msgs = run_live(es, np.concatenate([pcm(), np.zeros(32000, np.float32)]))
    es.close()
    part = [m for m in msgs if m["t"] == "words" and not m["final"]]
    fin = [m for m in msgs if m["t"] == "words" and m["final"]]
    assert part and fin and msgs.index(part[0]) < msgs.index(fin[0])
    assert any(n["entity"] == "Orientale Basin" and n["state"] == "linked" for m in fin for n in m["names"])
    f = fin[0]
    assert f["conf"] is None and f["alts"] == []      # the round-7 fields the shipped weights read stay empty
    for k in ("uconf", "nbest", "almost", "quantities", "clean_text", "n_dropped", "playback", "barge"):
        assert k in f, k
    assert any(m["t"] == "eot" for m in msgs)
    assert es.ends and es.ends[0]["first_partial"] is not None


def test_mid_stream_names_reach_the_open_stream(model):
    es = arc_ear.EarStream(names=[{"name": "Hertzsprung", "kind": "lunar_feature"}], s=arc_ear.EarSettings(ear_live=True))
    x = (np.clip(pcm(), -1, 1) * 32767).astype("<i2").tobytes()
    msgs = es.feed_all(x[:2560 * 5])
    assert es.st is not None
    es.set_names(NAMES)                       # arc_nft2_stream_set_names on the open stream
    assert es.st.names == es.names
    msgs += es.feed_all(x[2560 * 5:]) + es.feed_all(bytes(64000)) + es.flush_all()
    es.close()
    fin = [m for m in msgs if m["t"] == "words" and m["final"]]
    assert any(n["entity"] == "Orientale Basin" for m in fin for n in m["names"])


def test_our_own_playback_is_flagged_with_the_reference(model):
    """The clip played by the app (reference) and heard back through a quiet speaker path, nobody else talking."""
    rng = np.random.default_rng(0)
    ref = pcm()
    lead = int(0.12 * 16000)
    echo = np.convolve(ref, np.r_[0.25, np.zeros(400), 0.08, np.zeros(900), 0.03])[: len(ref)]
    mic = np.concatenate([np.zeros(16000 + lead, np.float32), echo, np.zeros(32000, np.float32)])
    mic = (mic + rng.standard_normal(len(mic)) * 1e-3).astype(np.float32)
    es = arc_ear.EarStream(names=NAMES, s=arc_ear.EarSettings(ear_live=True))
    es.feed_ref(np.concatenate([np.zeros(16000, np.float32), ref]), 0.0)
    msgs = run_live(es, mic)
    es.close()
    fin = [m for m in msgs if m["t"] == "words" and m["final"]]
    arc = [m for m in msgs if m["t"] == "arc"]
    assert arc and all(m["playback_leak"] is not None for m in arc)
    assert not fin or all(m["playback"] for m in fin), fin
    assert not any(m["t"] == "barge_in" for m in msgs)


def test_ref_message_decoding():
    x = (np.arange(320) % 7).astype("<i2")
    got = ref_pcm({"t": "ref", "at": 1.0, "pcm": base64.b64encode(x.tobytes()).decode()})
    assert got is not None and len(got) == 320
    assert ref_pcm({"pcm": "!!"}) is None and ref_pcm({"pcm": ""}) is None
    assert ref_pcm({"pcm": base64.b64encode(b"\x00" * (13 * 32000)).decode()}) is None   # > 12 s


def test_options_default_to_abi1_behaviour():
    o, _ = nft2.options()
    assert (o.almost, o.nbest, o.live, o.no_guard, o.echo_decode, o.playback_drop) == (0, 0, 0, 0, 0, 0)
    assert json.dumps(nft2.EVENT_TYPES)
