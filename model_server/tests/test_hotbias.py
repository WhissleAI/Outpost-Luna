"""Round 7: the ear's hot-list biasing (app/hotbias.py), pure logic with a toy tokenizer (no model)."""
import torch

from app import hotbias as HB


class Tok:
    """word-level toy tokenizer: bos 1, eos 2, each word its own id."""
    bos_token_id, eos_token_id = 1, 2

    def __init__(self):
        self.v = {}

    def __call__(self, s):
        class R:
            pass
        r = R()
        r.input_ids = [1] + [self.v.setdefault(w, 10 + len(self.v)) for w in s.split()]
        return r


def test_clean_lists():
    assert HB.clean_lists(["ice", "rover"]) == {"v": None, "step": ["ice", "rover"], "screen": []}
    c = HB.clean_lists({"v": "x", "step": ["a b", 3, None, ""], "screen": "nope"})
    assert c["step"] == ["a b", "3"] and c["screen"] == []
    assert HB.clean_lists(None)["step"] == []


def test_trie_no_start_bonus_on_function_words():
    tok = Tok()
    t = HB.HotTrie(tok, {"step": ["far side", "go to the map"], "screen": ["Malapert"]})
    far, go, mal = tok("far").input_ids[1], tok("go").input_ids[1], tok("Malapert").input_ids[1]
    assert far in t.starts and mal in t.starts and go not in t.starts
    assert (far,) in t.prefix and (go,) in t.prefix


def test_processor_boosts_start_and_continuation():
    tok = Tok()
    t = HB.HotTrie(tok, {"step": ["far side"]})
    far, side = tok("far").input_ids[1], tok("side").input_ids[1]
    p = HB.make_processor(t, {"step": 1.0}, {"step": 3.0})
    V = 64
    s0 = torch.zeros(1, V)
    out = p(torch.tensor([[0, 5]]), s0.clone())
    base = torch.log_softmax(s0, -1)[0, 0]
    assert abs(float(out[0, far] - base) - 1.0) < 1e-5 and abs(float(out[0, side] - base)) < 1e-5
    out = p(torch.tensor([[0, far]]), s0.clone())
    assert abs(float(out[0, side] - base) - 3.0) < 1e-5


def test_rescore_prefers_a_close_beam_with_the_hot_word():
    lists = {"step": ["ice"], "screen": ["rover"]}
    nb = [{"text": "rover go get eyes", "score": -0.30}, {"text": "rover go get ice", "score": -0.45}]
    assert HB.rescore(nb, lists) == 1
    far = [{"text": "rover go get eyes", "score": -0.30}, {"text": "rover go get ice", "score": -1.5}]
    assert HB.rescore(far, lists) == 0           # outside the margin: the top beam stays
    same = [{"text": "rover go get ice", "score": -0.3}, {"text": "Rover, go get ice.", "score": -0.32}]
    assert HB.rescore(same, lists) == 0          # no new hot word: never move
    assert HB.rescore(nb[:1], lists) == 0


def test_match_info():
    m = HB.match_info("Show me the far side.", {"step": ["far side"], "screen": ["Malapert"]})
    assert m == {"tier": "step", "hits": ["far side"]}
    assert HB.match_info("hello", {"step": ["x"]})["tier"] is None
