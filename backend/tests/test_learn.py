"""On-device learning (app/learn, docs/ON_DEVICE_LEARNING.md): personal aliases and their guards, speech habits, echo per
computer, the bounded Director thresholds, storage (atomic, no audio, no transcripts), reset, the API, diagnostics."""
import asyncio
import io
import json
import zipfile

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app import director as D
from app import learn
from app import session as sessions
from app.config import settings
from app.entities import registry
from app.gazetteer import Gazetteer
from app.learn import store
from app.learn.aliases import CAP, HALF_LIFE_DAYS, PersonalAliases
from app.learn.echo import THR_MAX, THR_MIN, DeviceEcho
from app.learn.habits import END_MAX, END_MIN, Habits
from app.learn.policy import IGNORE_MAX, IGNORE_SHIPPED, LINK_MIN, LINK_SHIPPED, Policy
from app.moments import MomentIndex


class Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture(scope="module")
def world():
    return Gazetteer(settings.data_dir / "places.json"), MomentIndex(settings.data_dir / "index/clips.json")


# ------------------------------------------------------------------------------------------- aliases and their guards
def test_two_confirmations_make_an_alias_and_it_links_directly(world):
    al = PersonalAliases(registry(), clock=Clock())
    assert al.confirm("ticko", "tycho") == "pending"
    assert al.lookup("fly to ticko") is None
    assert al.confirm("Ticko!", "tycho") == "learned"
    assert al.lookup("fly to ticko please") == ("tycho", "ticko")
    read = {"ear_names": [], "ear_spoken": "fly to ticko", "available": True, "mentions": [],
            "learned_aliases": al.pairs()}
    place, how, cands = D._link("fly to ticko", read, world[0])
    assert place.id == "tycho" and how == "learned_alias" and not cands
    # without the learned alias the same turn does not act on Tycho
    place0, _, _ = D._link("fly to ticko", {k: v for k, v in read.items() if k != "learned_aliases"}, world[0])
    assert place0 is None or place0.id != "tycho"


def test_one_confirmation_is_enough_only_for_a_very_close_offer():
    al = PersonalAliases(registry(), clock=Clock())
    assert al.confirm("tie co", "tycho", p=0.6) == "pending"
    al2 = PersonalAliases(registry(), clock=Clock())
    assert al2.confirm("tie co", "tycho", p=0.9) == "learned"


@pytest.mark.parametrize("heard,why", [
    ("the moon", "common_words"), ("go there", "common_words"), ("yes", "common_words"), ("a", "too_short"),
    ("copernicus", "owned_by_another"), ("tycho", "already_this_name"), ("fly to the big copernicus place now", "too_long"),
    ("copernicus crater", "owned_by_another"), ("ohm rim", "contains_another"),
])
def test_never_common_words_or_another_entitys_name(heard, why):
    al = PersonalAliases(registry(), clock=Clock())
    r = al.confirm(heard, "tycho", p=0.99)
    assert r.startswith("refused:") and why in r, r
    assert al.aliases == []


def test_never_from_a_no_and_never_from_an_echo():
    al = PersonalAliases(registry(), clock=Clock())
    assert al.confirm("ticko", "tycho", echo=True) == "refused:echo"
    assert al.confirm("ticko", "tycho", p=0.99, echo=True) == "refused:echo"
    al.confirm("ticko", "tycho")
    al.reject("ticko", "tycho")                    # a "no": what was gathered goes, and it is blocked
    assert al.confirm("ticko", "tycho") == "refused:blocked"
    assert al.confirm("ticko", "tycho", p=0.99) == "refused:blocked" and al.aliases == [] and al.pending == []


def test_an_alias_of_another_entity_is_refused():
    al = PersonalAliases(registry(), clock=Clock())
    al.confirm("ticko", "tycho", p=0.95)
    assert al.confirm("ticko", "copernicus", p=0.95) == "refused:alias_of_another"


def test_cap_decay_and_removal():
    c = Clock()
    al = PersonalAliases(registry(), clock=c)
    ids = [e.id for e in registry().entities if e.type == "place"][:CAP + 5]
    for i, eid in enumerate(ids):
        al.confirm(f"zorbu{chr(97 + i % 26)}{chr(97 + i // 26)}", eid, p=0.95)
    assert len(al.aliases) == CAP
    heard = al.aliases[-1]["heard"]
    assert al.remove(heard) and al.lookup(heard) is None and al.confirm(heard, al.aliases[0]["id"]) == "refused:blocked"
    c.t += 86400 * HALF_LIFE_DAYS * 3          # unused for 4.5 months: strength 1 -> 0.125, under MIN_STRENGTH
    al.decay()
    assert al.aliases == []


# ------------------------------------------------------------------------------------------- habits
def test_end_of_turn_silence_moves_only_inside_its_range():
    h = Habits()
    for _ in range(200):
        h.observe_turn(6, 2.0, 0.6, cut_off=True)
    assert h.end_silence_s() == END_MAX
    h2 = Habits({"habits": {"end_silence": 0.7}})
    for _ in range(400):
        h2.observe_turn(4, 1.2, 0.1, cut_off=False)
    assert h2.end_silence_s() == END_MIN
    assert Habits({"habits": {"end_silence": 3.0}}).end_silence_s() == END_MAX
    assert Habits({"habits": {"end_silence": 0.1}}).end_silence_s() == END_MIN


def test_a_kids_own_yes_word_needs_two_sightings_and_never_both_ways():
    h = Habits()
    assert h.observe_reply("yesh", meant_yes=True) is None and not h.is_yes("yesh")
    assert h.observe_reply("yesh", meant_yes=True) == "yesh" and h.is_yes("yesh")
    assert h.observe_reply("fly", meant_yes=True) is None        # a common word is never a yes word
    h.observe_reply("mm k", meant_yes=True)
    h.observe_reply("mm k", meant_yes=False)                      # used both ways: dropped
    assert not h.is_yes("mm k") and not h.is_no("mm k")


def test_did_you_mean_thresholds_stay_in_range():
    h = Habits()
    assert (h.near_score(), h.almost_min_p()) == (D.NEAR_SCORE, D.ALMOST_MIN_P)
    for _ in range(20):
        h.observe_offer(True)
    assert 0.75 <= h.near_score() < D.NEAR_SCORE and 0.45 <= h.almost_min_p() < D.ALMOST_MIN_P
    for _ in range(80):
        h.observe_offer(False)
    assert D.NEAR_SCORE < h.near_score() <= 0.86 and D.ALMOST_MIN_P < h.almost_min_p() <= 0.6


# ------------------------------------------------------------------------------------------- echo per computer
def test_echo_delay_drift_and_shift(monkeypatch):
    from app.learn import echo as learn_echo
    c = Clock()
    e = DeviceEcho(clock=c)
    assert e.delay_ms() is None and e.ref_shift_s() == 0.0
    for i, ms in enumerate([141, 141, 142, 154, 154, 159, 159, 148, 148]):
        c.t += 120
        assert e.observe_delay(ms, 300)
    assert not e.observe_delay(900, 300) and not e.observe_delay(150, 8)   # out of range / no clear peak
    assert 145 <= e.delay_ms() <= 155 and e.spread_ms()[0] <= 142
    monkeypatch.setattr(learn_echo, "USE_SHIFT", True)
    assert 0.1 <= e.ref_shift_s() <= 0.25
    assert e.drift_ms_per_h() is not None


def test_device_threshold_needs_both_sides_and_stays_bounded():
    e = DeviceEcho()
    assert e.threshold() == sessions.PLAYBACK_THRESHOLD           # the shipped default until there is evidence
    for _ in range(30):
        e.observe_leak(0.97, "echo")
    assert e.threshold() == sessions.PLAYBACK_THRESHOLD           # no kid evidence yet
    for _ in range(10):
        e.observe_leak(0.02, "kid")
    assert e.threshold() == THR_MIN                               # midpoint 0.5, clamped to the safe range
    e1 = DeviceEcho()
    for _ in range(30):
        e1.observe_leak(0.97, "echo")
        e1.observe_leak(0.81, "kid")
    assert e1.threshold() == 0.89 and THR_MIN <= e1.threshold() <= THR_MAX
    e2 = DeviceEcho()
    for _ in range(30):
        e2.observe_leak(0.8, "echo")
        e2.observe_leak(0.9, "kid")
    assert e2.threshold() == sessions.PLAYBACK_THRESHOLD          # they overlap: keep the shipped value


# ------------------------------------------------------------------------------------------- Director thresholds
def test_link_threshold_comes_down_slowly_and_back_on_a_no():
    p = Policy()
    assert p.link_act_p == LINK_SHIPPED
    for _ in range(100):
        p.observe_link_offer(0.98, True)
    assert p.link_act_p == LINK_MIN
    p.observe_link_offer(0.975, False)
    assert p.link_act_p == LINK_SHIPPED
    p.observe_link_offer(0.5, True)                 # far below the band: never counts
    assert p.band_yes == 0


def test_model_ignore_threshold_only_goes_up():
    p = Policy()
    assert p.policy_overrides() == {}
    for _ in range(50):
        p.observe_model_ignore_repeated()
    assert p.model_ignore == IGNORE_MAX and p.policy_overrides() == {"ignore": IGNORE_MAX}
    assert Policy({"policy": {"model_ignore": 0.5}}).model_ignore == IGNORE_SHIPPED


def test_policy_bounds_keep_shipped_decisions(world):
    """The shipped guarded r10 weights decide exactly as shipped with nothing learned; with the learned `ignore` bar at its
    bound, only turns whose p(ignore) lies in [0.95, 0.99) change, and they change to "rules decide"."""
    from app.director_model import runtime
    m = runtime.model()
    if m is None:
        pytest.skip("no shipped weights")
    thr = {**m.meta["policy"], **(m.meta["policy"].get("guarded") or {})}
    s = sessions.Session("lp", world[0], world[1])
    assert runtime.learned_thr(thr, s) == thr                      # nothing learned: identical policy
    lr = learn.for_profile(s.prefs.get("profile"))
    for _ in range(50):
        lr.policy.observe_model_ignore_repeated()
    moved = runtime.learned_thr(thr, s)
    assert moved["ignore"] == 0.99 and {k: v for k, v in moved.items() if k != "ignore"} == \
        {k: v for k, v in thr.items() if k != "ignore"}
    rng = np.random.default_rng(0)
    for p_ign in np.concatenate([rng.uniform(0, 1, 400), [0.95, 0.97, 0.989, 0.99, 0.995]]):
        from app.director_model import features as FX
        act = np.zeros(len(FX.ACTS))
        act[FX.ACTS.index("ignore")] = p_ign
        act[FX.ACTS.index("answer")] = 1 - p_ign
        out = {"act": act}
        a = runtime.policy(dict(out), ["the", "moon", "is", "big"], [], False, thr)
        b = runtime.policy(dict(out), ["the", "moon", "is", "big"], [], False, moved)
        if not (0.95 <= p_ign < 0.99):
            assert a == b, p_ign
        else:
            assert b is None


def test_learned_extras_never_reach_the_director_features(world):
    """The learned aliases / thresholds are added to the read AFTER the Director model's step (session._direct_turn)."""
    import inspect
    src = inspect.getsource(sessions.Session._direct_turn)
    assert src.index("self.dm.step(") < src.index("read_extras()")


# ------------------------------------------------------------------------------------------- storage
def test_storage_holds_numbers_and_confirmed_names_only(tmp_path, monkeypatch):
    monkeypatch.setenv("LEARN_DIR", str(tmp_path))
    learn.forget_cached()
    lr = learn.for_profile("p2")
    lr.aliases.confirm("ticko", "tycho", p=0.95)
    lr.habits.observe_reply("yesh", True)
    lr.save()
    raw = (tmp_path / "profile-p2.json").read_text()
    body = json.loads(raw)
    assert body["schema"] == store.SCHEMA and body["aliases"][0]["heard"] == "ticko"
    # anything else a bug might add is dropped before the write
    assert store.write("profile-p3", {"aliases": [{"heard": "ticko", "id": "tycho", "text": "fly to ticko now"}],
                                      "transcript": "hello", "audio": [1, 2, 3], "habits": {"turns": 3, "words": "x"}})
    b3 = json.loads((tmp_path / "profile-p3.json").read_text())
    assert "transcript" not in b3 and "audio" not in b3 and "text" not in b3["aliases"][0] and "words" not in b3["habits"]
    assert not list(tmp_path.glob("*.tmp"))
    (tmp_path / "profile-p4.json").write_text("{not json")
    assert store.read("profile-p4") == {}


def test_reset_clears_learning(tmp_path, monkeypatch):
    from app import reset
    monkeypatch.setenv("LEARN_DIR", str(tmp_path))
    learn.forget_cached()
    learn.for_profile("p1").aliases.confirm("ticko", "tycho", p=0.95)
    learn.for_profile("p1").save()
    learn.device().save()
    assert tmp_path in reset.targets("start")["start"]
    reset.reset("start")
    assert not list(tmp_path.glob("*.json"))
    assert learn.for_profile("p1").aliases.aliases == []


# ------------------------------------------------------------------------------------------- the session
def _explorer(world, sid="lrn"):
    s = sessions.Session(sid, world[0], world[1])
    asyncio.run(s.handle({"t": "hello", "mode": "cadet"}))
    asyncio.run(s.handle({"t": "ui", "event": "screen", "screen": "map"}))
    return s


def test_yes_to_an_offer_teaches_and_no_blocks(world):
    s = _explorer(world)
    r = {"source": "ear_near", "action": "ask", "ask": {"options": ["tycho"], "labels": ["Tycho"], "heard": "ticko",
                                                       "p": 0.6}}
    for _ in range(2):
        s.learning.on_offer(r, {}, echo=False)
        assert s.learning.on_reply("yeah", echo=False) == "yes"
    lr = learn.for_profile("p1")
    assert lr.aliases.lookup("ticko") == ("tycho", "ticko")
    s.learning.on_offer({**r, "ask": {**r["ask"], "heard": "tie ko"}}, {}, echo=False)
    assert s.learning.on_reply("no", echo=False) == "no"
    s.learning.on_offer({**r, "ask": {**r["ask"], "heard": "tie ko"}}, {}, echo=False)
    s.learning.on_reply("yes", echo=False)
    assert lr.aliases.lookup("tie ko") is None
    # an echo "yes" is never an answer we learn from
    s.learning.on_offer({**r, "ask": {**r["ask"], "heard": "tai ko"}}, {}, echo=False)
    s.learning.on_reply("yes", echo=True)
    s.learning.on_offer({**r, "ask": {**r["ask"], "heard": "tai ko"}}, {}, echo=False)
    s.learning.on_reply("yes", echo=True)
    assert lr.aliases.lookup("tai ko") is None
    # an offer made on an echo turn never teaches either
    s.learning.on_offer({**r, "ask": {**r["ask"], "heard": "tay ko"}}, {}, echo=True)
    s.learning.on_reply("yes", echo=False)
    s.learning.on_offer({**r, "ask": {**r["ask"], "heard": "tay ko"}}, {}, echo=True)
    s.learning.on_reply("yes", echo=False)
    assert lr.aliases.lookup("tay ko") is None


def test_a_tap_teaches_the_kids_own_yes_word(world):
    s = _explorer(world, "tap")
    r = {"source": "ear_near", "action": "ask", "ask": {"options": ["tycho"], "labels": ["Tycho"], "heard": "ticko"}}
    for _ in range(2):
        s.learning.on_offer(r, {}, echo=False)
        assert s.learning.on_reply("yesh", echo=False) is None
        asyncio.run(s.handle({"t": "ui", "event": "confirm_pick", "id": "tycho"}))
    lr = learn.for_profile("p1")
    assert lr.habits.is_yes("yesh") and lr.aliases.lookup("ticko") == ("tycho", "ticko")


def test_echo_delay_messages_reach_the_device_learner(world):
    s = _explorer(world, "dly")
    for _ in range(8):
        asyncio.run(s.on_listen({"t": "echo_delay", "ms": 148.0, "peak": 300.0}))
    assert learn.device().echo.delay_ms() == 148.0
    assert s.ear_tune()["ref_shift_s"] == 0.0        # measured, stored, but the shift is off (docs/ARC_ABI2.md 8)


def test_learning_off(world, monkeypatch):
    monkeypatch.setenv("LEARN", "0")
    s = _explorer(world, "off")
    assert s.ear_tune() is None and s.learning.read_extras() == {}


# ------------------------------------------------------------------------------------------- API and diagnostics
def test_api_view_forget_reset():
    from app.main import app
    c = TestClient(app)
    lr = learn.for_profile("p1")
    lr.aliases.confirm("ticko", "tycho", p=0.95)
    lr.save()
    v = c.get("/api/learn?profile=p1").json()
    assert v["learned"]["aliases"][0]["heard"] == "ticko" and v["audio_kept"] is False and v["lines"]
    assert any("ticko" in line for line in v["lines"])
    assert c.post("/api/learn/forget?profile=p1", json={"heard": "ticko"}).json()["ok"]
    assert c.get("/api/learn?profile=p1").json()["learned"]["aliases"] == []
    assert c.post("/api/learn/reset?profile=p1").status_code == 400          # needs the page's header
    assert c.post("/api/learn/reset?profile=p1", headers={"X-Outpost-Reset": "1"}).json()["ok"]


def test_diagnostics_redacts_learned_names_unless_asked():
    from app import diagnostics
    lr = learn.for_profile("p1")
    lr.aliases.confirm("ticko", "tycho", p=0.95)
    lr.save()
    body, names = asyncio.run(diagnostics.build({}, models_health={}, models_metrics={}, backend_health={}))
    z = zipfile.ZipFile(io.BytesIO(body))
    assert "learning.json" in names and b"ticko" not in z.read("learning.json")
    body, _ = asyncio.run(diagnostics.build({"learning_aliases": True}, models_health={}, models_metrics={},
                                            backend_health={}))
    assert b"ticko" in zipfile.ZipFile(io.BytesIO(body)).read("learning.json")


def test_the_learning_view_needs_the_token(monkeypatch):
    from app.main import app
    monkeypatch.setenv("LUNA_TOKEN", "t" * 43)
    c = TestClient(app)
    assert c.get("/api/learn?profile=p1").status_code == 401
    assert c.get("/api/learn?profile=p1", headers={"X-Luna-Token": "t" * 43}).status_code == 200


def test_end_to_end_through_the_session(world):
    """A heard turn the ear links at low p -> "Did you mean Tycho?" -> "yes" (twice) -> the next "fly to ticko" goes
    straight to Tycho, through the session's own turn path."""
    s = _explorer(world, "e2e")

    def heard(text, ear):
        asyncio.run(s.on_listen({"t": "turn", "state": "start", "text": text}))
        asyncio.run(s.on_listen({"t": "arc", "device_directed": 0.95}))
        asyncio.run(s.on_listen({"t": "words", "final": True, "text": text, "conf": None, "alts": [], **ear}))
        asyncio.run(s.on_listen({"t": "turn", "state": "end", "text": text}))

    low = {"names": [{"heard": "ticko", "entity": "Tycho", "state": "linked", "p": 0.9}], "spoken": "fly to ticko"}
    for said in ("fly to Tycho", "show me Tycho"):        # two different turns (the session de-duplicates repeats)
        heard(said, low)
        asks = [d for d in s.outbox if d.get("t") == "answer" and (d.get("r") or {}).get("action") == "ask"]
        assert asks and "Did you mean" in asks[-1]["r"]["say"], s.outbox[-1]
        assert s.learning.offer and s.learning.offer["heard"] == "ticko"
        heard("yes" if said.startswith("fly") else "yeah", {"names": [], "spoken": "yes"})
    assert learn.for_profile("p1").aliases.lookup("ticko") == ("tycho", "ticko")
    n = len(s.outbox)
    heard("fly to ticko", {"names": [], "spoken": "fly to ticko"})
    new = s.outbox[n:]
    ans = [d for d in new if d.get("t") == "answer"]
    assert ans and ans[-1]["r"].get("action") != "ask" and ans[-1]["r"].get("place") == "tycho", ans
