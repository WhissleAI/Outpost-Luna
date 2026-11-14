"""Contextual biasing of the Arc ear toward the screen's hot lists (round 7, docs/LOCAL_EAR.md).

The backend sends tiered lists ({"t":"context","hot":{"v","step":[...],"screen":[...]}}, backend/app/hotlist.py):
`step` = what the open step / offer / screen action expects (strongest), `screen` = the screen-wide vocabulary
(lighter). The ear uses them three ways, on top of Arc's own Tier A name bias:

  1. decoder prompt   the step list goes first in the decoder's context-list slot (~40 tokens), then the names
  2. shallow fusion   a prefix-tree boost (HotBias, a LogitsProcessor like arc_audio.bias.BiasProcessor) with a bonus
                      per tier on the first token of a hot phrase and a larger one on each token that continues a
                      phrase already started. Phrases that start with a function word ("go to the map") get no
                      start bonus, only continuation, so "the" / "go" / "what" are never pushed into silence.
  3. n-best rescoring the final decode's beams (Arc's builtin transcript already runs 4 beams) are returned with their
                      scores; each hypothesis gets + lambda_tier per hot phrase it contains; the top one is replaced only
                      when the rescored one is within `margin` of it (an acoustically close alternative).

Nothing here invents words: every output is one of the decoder's own beams. The n-best (texts + scores), the utterance
confidence (mean token probability of the chosen beam) and which hot list matched ride on the final `words` message
(arc_ear.TurnTracker): `alts`, `conf`, `hot`.
"""
from __future__ import annotations

import math
import re

from pydantic_settings import BaseSettings, SettingsConfigDict


class HotSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    ear_hot: str = "on"                 # on | off: use the hot lists the backend sends
    ear_hot_step_start: float = 1.0     # bonus (log-prob units) on the first token of a step-list phrase
    ear_hot_step_cont: float = 2.0      # ... on each token that continues a step-list phrase
    ear_hot_screen_start: float = 0.3   # screen-wide list: lighter
    ear_hot_screen_cont: float = 1.2
    ear_nbest_step: float = 0.35        # n-best rescoring: + per step-list phrase in a hypothesis (seq score units)
    ear_nbest_screen: float = 0.12
    ear_nbest_margin: float = 0.6       # only an alternative within this of the top beam may replace it
    ear_hot_prompt: int = 12            # step-list phrases put first in the decoder prompt


hot_settings = HotSettings()

STOP = set("""a an the of and or but to for from by with in on at into is are was were be it its this that i you we me
my our your he she they them what when where who why how which do does did can could would should will go going get
let lets please okay ok yes no oh um uh so just""".split())


def norm(t: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", (t or "").lower().replace("'", " "))).strip()


def clean_lists(hot) -> dict:
    """{"step": [...], "screen": [...], "v"} from the context message (a bare list = the step list)."""
    if isinstance(hot, list):
        hot = {"step": hot}
    if not isinstance(hot, dict):
        return {"step": [], "screen": [], "v": None}
    out = {"v": hot.get("v")}
    for k, cap in (("step", 64), ("screen", 400)):
        xs = hot.get(k) if isinstance(hot.get(k), list) else []
        out[k] = [str(x).strip()[:60] for x in xs if isinstance(x, (str, int, float)) and str(x).strip()][:cap]
    return out


def forms(phrase: str) -> set[str]:
    """Surface forms the decoder may write: as given, lowercase, Capitalised, Title Case."""
    p = " ".join(str(phrase).split())
    return {p, p.lower(), p[:1].upper() + p[1:], p.title()} if p else set()


class HotTrie:
    """Token prefix tree over the hot phrases, per tier ("step" | "screen" | "names"), like arc_audio.bias.Trie."""

    def __init__(self, tok, tiers: dict[str, list[str]]):
        self.prefix: dict = {}
        self.starts: dict = {}
        self.maxlen = 0
        bos, eos = getattr(tok, "bos_token_id", None), getattr(tok, "eos_token_id", None)
        for tier, phrases in tiers.items():
            for ph in phrases or []:
                lead_stop = norm(ph).split()[:1] and norm(ph).split()[0] in STOP
                for f in forms(ph):
                    ids = [i for i in tok(f).input_ids if i not in (bos, eos)]
                    if not ids:
                        continue
                    if not lead_stop:
                        self.starts.setdefault(ids[0], set()).add(tier)
                    for k in range(1, len(ids)):
                        self.prefix.setdefault(tuple(ids[:k]), {}).setdefault(ids[k], set()).add(tier)
                    self.maxlen = max(self.maxlen, len(ids))


def make_processor(trie: HotTrie, start: dict, cont: dict, prompt_len: int = 1):
    """A LogitsProcessor (one row; the beam path wraps it in arc_audio.bias.RowBias)."""
    import torch
    try:
        from transformers import LogitsProcessor
    except Exception:  # noqa: BLE001
        LogitsProcessor = object

    class HotBias(LogitsProcessor):
        def __init__(self):
            self.p0 = prompt_len
            self.sb = {t: max(start.get(x, 0.0) for x in tys) for t, tys in trie.starts.items()}
            self.sb = {t: b for t, b in self.sb.items() if b > 0}
            self._dev = None

        def __call__(self, input_ids, scores):
            gen = input_ids[0].tolist()
            add: dict = {}
            for k in range(min(len(gen), trie.maxlen - 1), 0, -1):
                nxt = trie.prefix.get(tuple(gen[-k:]))
                if nxt:
                    for t, tys in nxt.items():
                        add[t] = max(add.get(t, 0.0), max(cont.get(x, 0.0) for x in tys))
                    break
            if not self.sb and not add:
                return scores
            scores = torch.log_softmax(scores.float(), -1).to(scores.dtype)
            if self.sb:
                if self._dev != scores.device:
                    ks = list(self.sb)
                    self._si = torch.tensor(ks, device=scores.device, dtype=torch.long)
                    self._sv = torch.tensor([self.sb[k] for k in ks], device=scores.device, dtype=scores.dtype)
                    self._dev = scores.device
                scores[0, self._si] += self._sv
            ex = {t: b - self.sb.get(t, 0.0) for t, b in add.items() if b > self.sb.get(t, 0.0)}
            if ex:
                scores[0, torch.tensor(list(ex), device=scores.device)] += torch.tensor(
                    list(ex.values()), device=scores.device, dtype=scores.dtype)
            return scores

    return HotBias()


def hits(text: str, phrases: list[str]) -> list[str]:
    t = " " + norm(text) + " "
    return [p for p in phrases if norm(p) and f" {norm(p)} " in t]


def rescore(nbest: list[dict], lists: dict, s=hot_settings) -> int:
    """Index of the hypothesis to keep: the top beam unless an alternative within `margin` scores higher once each
    contains its hot phrases (+lambda per step / screen phrase it has and the top beam lacks)."""
    if len(nbest) < 2:
        return 0
    top = nbest[0]
    th = set(hits(top["text"], lists.get("step") or [])), set(hits(top["text"], lists.get("screen") or []))

    nt = len(norm(top["text"]).split())

    def val(h):
        if abs(len(norm(h["text"]).split()) - nt) > 1:
            return -1e9          # a hot word must REPLACE heard words, never ride in on an extra tail
        st = set(hits(h["text"], lists.get("step") or [])) - th[0]
        sc = set(hits(h["text"], lists.get("screen") or [])) - th[1]
        return h["score"] + s.ear_nbest_step * len(st) + s.ear_nbest_screen * len(sc)
    best = max(range(len(nbest)), key=lambda i: (val(nbest[i]), -i))
    return best if top["score"] - nbest[best]["score"] <= s.ear_nbest_margin else 0


def match_info(text: str, lists: dict) -> dict:
    """Which hot list the final words matched: {"tier": step|screen|None, "hits": [...]}."""
    a, b = hits(text, lists.get("step") or []), hits(text, lists.get("screen") or [])
    return {"tier": "step" if a else "screen" if b else None, "hits": (a or b)[:4]}


def install(tr, tok, names_forms: list[str], lists: dict, s=hot_settings) -> None:
    """Put the tiered bias (names = Arc's Tier A, at its usual weight) and the n-best capture on one Transcriber."""
    from transformers import LogitsProcessorList
    from arc_audio.bias import DEFAULT
    trie = HotTrie(tok, {"names": names_forms, "step": lists.get("step") or [], "screen": lists.get("screen") or []})
    start = {"names": DEFAULT["start_bonus"], "step": s.ear_hot_step_start, "screen": s.ear_hot_screen_start}
    cont = {"names": DEFAULT["cont_bonus"], "step": s.ear_hot_step_cont, "screen": s.ear_hot_screen_cont}
    tr.trie = trie
    tr._procs = lambda span_types: LogitsProcessorList([make_processor(trie, start, cont)])
    tr.hot_lists = lists
    if not getattr(tr, "_nbest_on", False):
        tr._gen_orig = tr._gen
        tr._gen = lambda *a, **k: _gen_nbest(tr, *a, **k)
        tr.nbest = {}
        tr._nbest_on = True


def _gen_nbest(tr, kw, n_samples, span_types, prefix=None, return_ids=False, final=False):
    """Transcriber._gen with the final beams returned (num_return_sequences) and rescored against the hot lists."""
    import torch
    from transformers import LogitsProcessorList
    nb = int(tr.c.get("final_beams", 1)) if final and not prefix and not return_ids else 1
    if nb <= 1:
        return tr._gen_orig(kw, n_samples, span_types, prefix=prefix, return_ids=return_ids, final=final)
    from arc_audio.bias import RowBias
    procs = tr._procs(span_types)
    P = tr._prompt_ids()
    st = tr.m.config.decoder_start_token_id
    pre, guards = tr._guards(len(P) + 1)
    lp = pre + ([RowBias(procs[0])] if procs else []) + guards
    extra = {"logits_processor": LogitsProcessorList(lp)} if lp else {}
    if P:
        kw = dict(kw, decoder_input_ids=torch.tensor([P + [st]], device=tr.dev, dtype=torch.long), decoder_start_token_id=P[0])
    out = tr.m.generate(**kw, max_length=tr._max_len(n_samples) + len(P), do_sample=False, num_beams=nb,
                        num_return_sequences=nb, output_scores=True, return_dict_in_generate=True, **extra)
    seqs = [[int(t) for t in row.tolist()][len(P):] for row in out.sequences]
    scores = [float(x) for x in out.sequences_scores.tolist()] if getattr(out, "sequences_scores", None) is not None \
        else [0.0] * len(seqs)
    nbest = [{"text": tr.tok.decode(ids, skip_special_tokens=True).strip(), "score": round(sc, 4), "ids": ids}
             for ids, sc in zip(seqs, scores)]
    lists = getattr(tr, "hot_lists", None) or {}
    k = rescore(nbest, lists) if (lists.get("step") or lists.get("screen")) else 0
    conf = None
    try:
        ts = tr.m.compute_transition_scores(out.sequences, out.scores, out.beam_indices, normalize_logits=False)
        row = [float(x) for x in ts[k].tolist() if x != 0 and math.isfinite(float(x))]
        conf = round(sum(math.exp(min(0.0, x)) for x in row) / len(row), 3) if row else None
    except Exception:  # noqa: BLE001
        conf = None
    tr.last_ids = nbest[k]["ids"]
    text = nbest[k]["text"]
    rec = {"alts": [{"text": h["text"], "score": h["score"]} for h in nbest], "pick": k, "conf": conf}
    tr.nbest[text] = rec
    try:
        from arc_audio.transcribe import loopfix
        tr.nbest[loopfix(text)] = rec
    except Exception:  # noqa: BLE001
        pass
    if len(tr.nbest) > 64:
        for key in list(tr.nbest)[:-32]:
            tr.nbest.pop(key, None)
    return text
