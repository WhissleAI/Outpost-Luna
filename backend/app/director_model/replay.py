"""Round 12: one decoded clip of the real ear -> the messages the live relay posts into the Session for it.

Live (EAR=arc): model_server `arc_ear.EarStream` emits, per kid turn,
    {"t":"turn","state":"start","text":t0}, {"t":"words","text":..,"final":false}*, {"t":"arc","device_directed":..,
    "command_complete":None,..}, {"t":"words","text":..,"final":true,"spoken","names","decoder_text","agree","alts",..},
    {"t":"turn","state":"end","text":..}
and `listen.py` posts each one, unchanged, into `Session.handle`. The training generator (director_model/
gen_sessions.py) replays cached decodes (director_model/real_ear.py) through the same Session; `compact` is what the
decode worker caches and `messages` is what the generator posts. Both live here so a test can prove the two paths
give the learned Director the same inputs (tests/test_director_r12.py: the same turn, live vs replayed, gives
identical feature vectors at every step).

Train/serve skews fixed here (round 12, docs/SPEECH_SIGNALS_AUDIT.md section 4):
- the final words carry the ear's names (link state / p), spoken words, decoder text and agreement, as live;
- command_complete is never invented: Arc Transcriber Space has no cc head, so it is None live and None here;
- the turn start carries the first decoded words (live does; the generator used to send "").

Round 13 (libarc ABI 2, docs/ARC_ABI2.md): the final words also carry the ABI 2 read-outs under their own keys
(ABI2_KEYS: per-word / utterance confidence, n-best, `almost` sound-alikes, typed quantities, clean_text, disfluencies,
dropped tail words, and, live, playback_leak / playback / barge / eot) plus the pace numbers; the Session keeps them on
k["ear"] (session.EAR_ABI2) and features.abi2_view turns them into the e13_* slots. `compact` caches them and `messages`
posts them back exactly as the ear sent them (tests/test_director_r13.py).
"""
from __future__ import annotations

FINAL_KEYS = ("spoken", "names", "decoder_text", "agree")
# libarc ABI 2's read-outs on the final words (model_server arc_ear._finish / abi2_view; backend session.EAR_ABI2) and the
# pace numbers arc_ear adds to every final
ABI2_KEYS = ("uconf", "min_wconf", "wconf", "nbest", "walts", "almost", "quantities", "clean_text", "disfl", "n_dropped",
             "playback_leak", "playback", "barge", "barge_p", "eot", "speech_s", "max_pause_s", "end_silence_s")


def _merge_abi2(fins: list[dict]) -> dict:
    """The ABI 2 read-outs of a clip's finals as ONE turn's (a clip is replayed as one turn). One final: verbatim.
    Several: the least sure confidence, the lists joined, the dropped words summed, the loudest leak, any barge / own
    playback, the last end-of-turn read, the pace summed."""
    if len(fins) == 1:
        return {k: fins[0][k] for k in ABI2_KEYS if fins[0].get(k) is not None}
    v = lambda k: [m[k] for m in fins if m.get(k) is not None]  # noqa: E731
    out: dict = {}
    for k in ("uconf", "min_wconf"):
        if v(k):
            out[k] = min(v(k))
    for k in ("wconf", "nbest", "walts", "almost", "quantities", "disfl"):
        if v(k):
            out[k] = [x for xs in v(k) for x in xs]
    if v("clean_text"):
        out["clean_text"] = " ".join(x.strip() for x in v("clean_text")).strip()
    if v("n_dropped"):
        out["n_dropped"] = sum(int(x) for x in v("n_dropped"))
    for k in ("playback_leak", "barge_p", "max_pause_s"):
        if v(k):
            out[k] = max(v(k))
    for k in ("playback", "barge"):
        if v(k):
            out[k] = any(v(k))
    for k in ("eot", "end_silence_s"):
        if v(k):
            out[k] = v(k)[-1]
    if v("speech_s"):
        out["speech_s"] = round(sum(v("speech_s")), 2)
    return out


def compact(msgs: list[dict], agreement=None) -> tuple[list[dict], dict | None]:
    """The live message stream of one clip -> (events, final extras): what the decode cache stores. Events keep the
    order and the fields the Session reads; the extras are the final words' ear fields, merged over the clip's finals
    (a clip is replayed as ONE turn; with several finals, agreement is re-measured on the merged texts with
    `agreement`, model_server arc_ear.agreement, exactly as the ear measures one final)."""
    ev: list[dict] = []
    fins = []
    for m in msgs:
        t = m.get("t")
        if t == "words":
            ev.append({"t": "words", "text": m.get("text") or "", "final": bool(m.get("final")),
                       **{k: m[k] for k in ("alts", "conf", "hot", "rescored") if m.get(k) is not None}})
            if m.get("final"):
                fins.append(m)
        elif t == "turn":
            ev.append({"t": "turn", "state": m.get("state"), "text": m.get("text") or ""})
        elif t == "arc":
            ev.append({"t": "arc", "dd": m.get("device_directed"), "cc": m.get("command_complete")})
    if not fins:
        return ev, None
    sp = " ".join((m.get("spoken") or "").strip() for m in fins).strip()
    dec = " ".join((m.get("decoder_text") or "").strip() for m in fins).strip()
    fx = {"spoken": sp, "names": [n for m in fins for n in m.get("names") or []], "decoder_text": dec or None,
          "agree": fins[0].get("agree") if len(fins) == 1 else (agreement(sp, dec) if agreement and dec else None),
          **_merge_abi2(fins)}
    return ev, fx


def messages(d: dict, dd: float | None = None, text_of=None) -> list[dict] | None:
    """A cached decode (real_ear.py dec/<key>.json) -> the Session messages of its turn, in the live order. `dd`
    overrides the ear's device_directed (the generator's draw), else the decode's own. None when the decode has no
    words or predates round 12 (no final extras: x.final)."""
    ev = d.get("events") or []
    fx = (d.get("x") or {}).get("final")
    hyp = (d.get("hyp") or "").strip()
    if fx is None or not hyp:
        return None
    starts = [i for i, e in enumerate(ev) if e["t"] == "turn" and e["state"] == "start"]
    ends = [i for i, e in enumerate(ev) if e["t"] == "turn" and e["state"] == "end"]
    fins = [e for e in ev if e["t"] == "words" and e.get("final")]
    arcs = [e for e in ev if e["t"] == "arc" and e.get("dd") is not None]
    a_dd = dd if dd is not None else (arcs[-1]["dd"] if arcs else None)
    final = {"t": "words", "text": hyp, "final": True, **({"alts": fins[-1]["alts"]} if fins and "alts" in fins[-1]
                                                          else {"alts": []}),
             **{k: fx[k] for k in FINAL_KEYS + ABI2_KEYS if fx.get(k) is not None}}
    if len(starts) == 1 and len(ends) == 1 and len(fins) == 1 and starts[0] < ends[0]:
        out = []
        for e in ev[starts[0]:ends[0] + 1]:
            if e["t"] == "turn":
                out.append({"t": "turn", "state": e["state"], "text": e["text"]})
            elif e["t"] == "arc":
                if e.get("dd") is None and dd is None:
                    continue      # a wordless segment's read: the Session ignores a None dd anyway
                out.append({"t": "arc", "device_directed": a_dd, "command_complete": e.get("cc")})
            elif e.get("final"):
                out.append(dict(final))
            else:
                out.append({"t": "words", "text": e["text"], "final": False})
        if not any(m["t"] == "arc" for m in out) and a_dd is not None:
            out.insert(len(out) - 2, {"t": "arc", "device_directed": a_dd, "command_complete": None})
        return out
    # several segments in one clip (or a malformed stream): one turn, the live order, the clip's partial texts
    parts = []
    for e in ev:
        if e["t"] == "words" and not e.get("final") and e["text"].strip() and (not parts or parts[-1] != e["text"]):
            parts.append(e["text"])
    out = [{"t": "turn", "state": "start", "text": parts[0] if parts else hyp}]
    out += [{"t": "words", "text": p, "final": False} for p in parts]
    if a_dd is not None:
        out.append({"t": "arc", "device_directed": a_dd, "command_complete": None})
    out += [final, {"t": "turn", "state": "end", "text": hyp}]
    return out
