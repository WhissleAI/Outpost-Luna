"""Round 11: what the real ear (Arc Transcriber Space via libarc) makes of the Mac voice bank, for the Arc modelling
team. Numbers from the round-11 decodes (real_ear.py jobs --r11; cache dec/*.json with `x` extras), plus the round-9
Steer TTS decodes (group test / val / train, no extras) as the comparison row.

  backend/.venv/bin/python director_model/ear_analysis.py --cache director_model/cache/real_ear_r11 \
      [--data director_model/data/ds_r11] --out director_model/runs/<date>-r11/ear_analysis.md
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "backend"))
sys.path.insert(0, str(HERE))

NUMW = {"zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7",
        "eight": "8", "nine": "9", "ten": "10", "eleven": "11", "twelve": "12", "fifteen": "15", "twenty": "20",
        "thirty": "30", "forty": "40", "fifty": "50", "hundred": "100", "a hundred": "100", "one hundred": "100",
        "half": "half"}


def norm(t: str) -> list[str]:
    t = (t or "").lower().replace("%", " percent").replace("-", " ")
    t = re.sub(r"[^a-z0-9' ]", " ", t)
    out = []
    for w in t.split():
        w = w.strip("'")
        if w:
            out.append(NUMW.get(w, w))
    return out


def edits(ref: list[str], hyp: list[str]) -> int:
    sm = difflib.SequenceMatcher(a=ref, b=hyp, autojunk=False)
    return sum(max(i2 - i1, j2 - j1) for op, i1, i2, j1, j2 in sm.get_opcodes() if op != "equal")


def auc(pos: list[float], neg: list[float]) -> float | None:
    if not pos or not neg:
        return None
    p, n = np.asarray(pos), np.asarray(neg)
    gt = (p[:, None] > n[None, :]).sum() + 0.5 * (p[:, None] == n[None, :]).sum()
    return float(gt / (len(p) * len(n)))


def pct(a, b):
    return f"{100 * a / b:.1f} %" if b else "-"


def load(cache: Path):
    rows = []
    for f in (cache / "dec").glob("*.json"):
        r = json.loads(f.read_text())
        rows.append(r)
    jobs = {}
    for line in open(cache / "jobs.jsonl"):
        j = json.loads(line)
        jobs[j["key"]] = j
    return rows, jobs


def dd_of(r):
    a = [e for e in r["events"] if e["t"] == "arc" and e.get("dd") is not None]
    return max(e["dd"] for e in a) if a else None


def wer_table(rows, keyf, title, min_n=10):
    g = defaultdict(lambda: [0, 0, 0, 0, 0])     # edits, ref words, clips, empty, exact
    for r in rows:
        ref, hyp = norm(r["text"]), norm(r["hyp"])
        k = keyf(r)
        if k is None or not ref:
            continue
        x = g[k]
        x[0] += edits(ref, hyp)
        x[1] += len(ref)
        x[2] += 1
        x[3] += not hyp
        x[4] += ref == hyp
    out = [f"\n### {title}\n", "| group | clips | WER | exact | empty |", "|---|---|---|---|---|"]
    for k, x in sorted(g.items(), key=lambda kv: -kv[1][2]):
        if x[2] >= min_n:
            out.append(f"| {k} | {x[2]} | {100 * x[0] / max(1, x[1]):.1f} % | {pct(x[4], x[2])} | {pct(x[3], x[2])} |")
    return out


def name_hits(ref_text: str, names: list[dict]) -> list[tuple[str, str, list[str]]]:
    """(entity, the alias said, its words) for each list entry the reference names."""
    rt = " " + " ".join(norm(ref_text)) + " "
    out = []
    for n in names or []:
        forms = [n["name"]] + list(n.get("aliases") or [])
        for f in sorted(forms, key=lambda s: -len(s)):
            fw = norm(f)
            if fw and " " + " ".join(fw) + " " in rt:
                out.append((n["name"], f, fw))
                break
    # keep the longest non-overlapping
    out.sort(key=lambda x: -len(x[2]))
    kept, used = [], set()
    for e in out:
        s = " ".join(e[2])
        if any(s in u for u in used):
            continue
        used.add(s)
        kept.append(e)
    return kept


def aligned_span(ref: list[str], hyp: list[str], span: list[str]) -> str:
    """The hyp words aligned to the reference span."""
    for i in range(len(ref) - len(span) + 1):
        if ref[i:i + len(span)] == span:
            a, b = i, i + len(span)
            break
    else:
        return "?"
    sm = difflib.SequenceMatcher(a=ref, b=hyp, autojunk=False)
    hs = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if i2 <= a or i1 >= b:
            continue
        if op == "equal":
            hs += hyp[j1 + max(0, a - i1): j1 + min(i2, b) - i1]
        else:
            hs += hyp[j1:j2]
    return " ".join(hs) or "(nothing)"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", required=True)
    ap.add_argument("--data", default="")
    ap.add_argument("--odd-cache", default="", help="the novelty / sung voice decodes (WER tables only)")
    ap.add_argument("--stress-cache", default="", help="the harsh-chain decodes (a WER table only)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    rows, jobs = load(Path(a.cache))
    new = [r for r in rows if "x" in r]
    import voice_bank as VB
    for r in new:     # the first round-11 renders wrote an os_echo turn's echo voice over the kid's voice in the meta;
        j = jobs.get(r["key"])  # the kid's voice is the render's first draw (voice_bank.pick_voice), so recompute it
        if j and j.get("vb") == "mac" and r["render"].get("noise") == "os_echo" and "echo_voice" not in r["render"]:
            r["render"]["echo_voice"] = r["render"]["voice"]
            r["render"]["voice"] = VB.pick_voice(j["group"], np.random.default_rng(j["seed"]))
    kid = [r for r in new if r["group"] in ("train", "val", "voice_ho")]
    echo = [r for r in new if r["group"] == "echo_bank"]
    steer = [r for r in rows if "x" not in r and r["group"] in ("train", "val", "test")]
    L = ["# Round 11: the real ear on the Mac voice bank (ear analysis)", "",
         "Ear: Arc Transcriber Space (nft2, the installed app's downloaded model) through libarc, the same "
         "`model_server/app/arc_ear.EarStream` path as `real_ear.py decode` (partials every 3 s), with each turn's "
         "screen names list (`names_list.screen_names`, what the app sends) as the ear's names list. "
         "**All audio is synthetic** (macOS `say` voices pitched / sped toward a child, a laptop-mic band, room reverb, "
         "one noise bed per turn); treat these as a stress test of the ear on TTS-like speech, not as kid data.", "",
         f"Clips: {len(kid)} kid turns in Mac voices (train {sum(r['group'] == 'train' for r in kid)}, val "
         f"{sum(r['group'] == 'val' for r in kid)}, held-out voices {sum(r['group'] == 'voice_ho' for r in kid)}), "
         f"{len(echo)} echo-bank clips (our own lines / crew clips alone), {len(steer)} round-9 Steer TTS kid turns "
         "(comparison).", "",
         "WER: word edits / reference words after lower-casing, removing punctuation, number words -> digits and "
         "`%` -> percent on both sides (so ITN form differences do not count as errors here; they are measured "
         "separately below)."]
    # 1. WER
    L.append("\n## 1. WER and empty decodes")
    L += wer_table(kid + steer, lambda r: r.get("render", {}).get("vgroup") or ("steer (r9, " + r["group"] + ")"),
                   "By voice group (Mac groups: natural = the system voices, eloquence = Eddy/Flo/Grandma/... UK+US, "
                   "novelty = Albert/Bahh/Boing/..., sung = Bells/Cellos/Organ/Good News/Bad News)")
    L += wer_table(kid, lambda r: r["render"].get("noise"), "Mac-voice kid turns by noise bed")
    L += wer_table(kid, lambda r: r["render"].get("voice"), "By voice (>= 10 clips)")

    def pitch_k(r):
        m = r["render"]
        return "sox pitch +%d00 c" % (m["cents"] // 100) if m.get("cents") else (
            "resample x%.1f" % m["speed"] if m.get("speed", 1) > 1 else "no shift")
    L += wer_table(kid, pitch_k, "By pitch shift")
    L += wer_table(kid, lambda r: ("laptop mic" if r["render"].get("mic_hi") else "full band") +
                   (" + reverb" if r["render"].get("rt60") else ""), "By mic chain")

    def snr_k(r):
        s = r["render"].get("snr_db")
        n = r["render"].get("noise")
        if n not in ("babble", "tv", "music"):
            return None
        return f"{n} SNR " + ("< 8 dB" if s < 8 else "8-14 dB" if s < 14 else ">= 14 dB")
    L += wer_table(kid, snr_k, "By SNR (babble / TV / music)")
    if a.stress_cache:
        srows, _ = load(Path(a.stress_cache))
        sk = [r for r in srows if "x" in r and r["group"] in ("train", "val", "voice_ho")]
        L += ["", f"**The harsh chain (stress set, {len(sk)} clips, not trained on):** the first decodes of this round "
              "used a harder chain (rate up to 230 wpm, pitch up to +700 cents, reverb RT60 to 0.7 s with a weak "
              "direct path, SNR down to 3 dB). Same voices and texts; it is kept as a stress set:"]
        L += wer_table(sk, lambda r: r["render"].get("vgroup"), "Harsh chain, by voice group")

        def rv(r):
            m = r["render"]
            return ("reverb" if m.get("rt60") else "no reverb") + (", rate >= 200" if m.get("rate", 0) >= 200 else
                                                                   ", rate < 200")
        L += wer_table([r for r in sk if r["render"].get("vgroup") in ("natural", "eloquence")], rv,
                       "Harsh chain, natural + eloquence voices, by reverb and speaking rate")
    if a.odd_cache:
        orows, _ = load(Path(a.odd_cache))
        ok = [r for r in orows if "x" in r and r["group"] in ("train", "val", "voice_ho")]
        L += ["", f"**Novelty and sung voices (stress set, {len(ok)} clips, removed from training and from "
              "test_voice_heldout):** not plausible kid speech; their decodes were re-rendered in the other voices of "
              "the same split and these are reported only:"]
        L += wer_table(ok, lambda r: r["render"].get("vgroup"), "Novelty / sung voices (moderate chain), by group")
        L += wer_table([r for r in ok if r["render"].get("noise") != "os_echo"], lambda r: r["render"].get("voice"),
                       "Novelty / sung voices, by voice (turns without an OS-voice echo bed: those renders recorded "
                       "the echo's voice in place of the kid's)", min_n=5)
    # 2. names
    L.append("\n## 2. Lunar names: words and the ear's linker (`names` on the final words)")
    st = defaultdict(Counter)
    mis = defaultdict(Counter)
    exs = defaultdict(list)
    per_name = defaultdict(Counter)
    for r in kid:
        j = jobs.get(r["key"], {})
        nl = j.get("names") or []
        scr = (j.get("frame") or {}).get("screen") or "?"
        ref, hyp = norm(r["text"]), norm(r["hyp"])
        for ent, form, fw in name_hits(r["text"], nl):
            said = " ".join(fw) in " ".join(hyp)
            links = [n for n in r["x"]["names"] if n.get("entity") == ent]
            other = [n for n in r["x"]["names"] if n.get("state") == "linked" and n.get("entity") != ent]
            if links and any(n["state"] == "linked" for n in links):
                ls = "linked (right)"
            elif links and any(n["state"] == "abstain" for n in links):
                ls = "abstain"
            elif other:
                ls = "linked (WRONG entity)"
            elif any(n.get("state") == "not_in_list" for n in r["x"]["names"]):
                ls = "not_in_list"
            else:
                ls = "no name returned"
            c = st[scr]
            c["n"] += 1
            c["words right"] += said
            c[ls] += 1
            per_name[ent]["n"] += 1
            per_name[ent]["right"] += said
            per_name[ent]["linked"] += ls == "linked (right)"
            if not said:
                h = aligned_span(ref, hyp, fw)
                mis[ent][h] += 1
                if len(exs[ent]) < 2:
                    exs[ent].append(f"\"{r['text']}\" -> \"{r['hyp']}\"")
    states = ["linked (right)", "abstain", "linked (WRONG entity)", "not_in_list", "no name returned"]
    L += ["", "Per screen (the screen's names list was the ear's list); a turn counts once per list name it says.", "",
          "| screen | name mentions | words right | " + " | ".join(states) + " |",
          "|---|---|---|" + "---|" * len(states)]
    T = Counter()
    for scr, c in sorted(st.items(), key=lambda kv: -kv[1]["n"]):
        T.update(c)
        L.append(f"| {scr} | {c['n']} | {pct(c['words right'], c['n'])} | " +
                 " | ".join(pct(c[s], c['n']) for s in states) + " |")
    L.append(f"| **all** | {T['n']} | {pct(T['words right'], T['n'])} | " +
             " | ".join(pct(T[s], T['n']) for s in states) + " |")
    worst = sorted(((e, c) for e, c in per_name.items() if c["n"] >= 4), key=lambda kv: kv[1]["right"] / kv[1]["n"])
    L += ["", "Most misheard names (>= 4 mentions; words right, linked right; the top mishearings):", "",
          "| name | mentions | words right | linked right | heard as (count) |", "|---|---|---|---|---|"]
    for e, c in worst[:20]:
        top = "; ".join(f"\"{h}\" ({k})" for h, k in mis[e].most_common(4))
        L.append(f"| {e} | {c['n']} | {pct(c['right'], c['n'])} | {pct(c['linked'], c['n'])} | {top} |")
    L += ["", "Examples:", ""]
    for e, _ in worst[:8]:
        for x in exs[e]:
            L.append(f"- {e}: {x}")
    # 3. numbers
    L.append("\n## 3. Numbers and percents (ITN)")
    num = Counter()
    forms = Counter()
    nex = []
    for r in kid:
        rt = r["text"].lower()
        rnum = [w for w in norm(rt) if w.isdigit()]
        if not rnum and "percent" not in rt:
            continue
        hn = [w for w in norm(r["hyp"]) if w.isdigit()]
        num["n"] += 1
        num["numbers right"] += Counter(rnum) == Counter(hn)
        num["number dropped"] += bool(set(rnum) - set(hn))
        if "percent" in rt or "%" in rt:
            num["percent turns"] += 1
            h = r["hyp"]
            forms["N%" if re.search(r"\d\s?%", h) else "N percent" if re.search(r"\d+ percent", h.lower()) else
                  "words" if "percent" in h.lower() else "percent lost"] += 1
        hw = r["hyp"].lower()
        if any(w in hw.split() for w in ("one", "two", "three", "four", "five", "ten", "twenty", "fifty")):
            forms["number left as a word"] += 1
        if Counter(rnum) != Counter(hn) and len(nex) < 8:
            nex.append(f"\"{r['text']}\" -> \"{r['hyp']}\"")
    L += ["", f"Turns with a number or percent in the reference: {num['n']}. Numbers exactly right (as digits after "
          f"normalising number words): {pct(num['numbers right'], num['n'])}; a reference number missing from the "
          f"decode: {pct(num['number dropped'], num['n'])}.", "",
          f"Written form of percents ({num['percent turns']} turns): " +
          ", ".join(f"{k} {pct(v, num['percent turns'])}" for k, v in forms.items() if k != "number left as a word") +
          f". Turns where a number stayed a word in the written form: {forms['number left as a word']}.", "",
          "Examples of number errors:", ""] + [f"- {x}" for x in nex]
    # 4. short turns
    L.append("\n## 4. One- and two-word turns")
    L += wer_table(kid, lambda r: f"{min(len(norm(r['text'])), 3)}{'+' if len(norm(r['text'])) >= 3 else ''} words",
                   "By reference length")
    sh = Counter()
    for r in kid:
        if len(norm(r["text"])) <= 2:
            sh[(r["text"].lower().strip(" .!?"), " ".join(norm(r["hyp"])) or "(empty)")] += 0 if norm(
                r["text"]) == norm(r["hyp"]) else 1
    L += ["", "Most frequent short-turn errors: " + "; ".join(f"\"{a}\" -> \"{b}\" ({k})" for (a, b), k in
                                                            sh.most_common(12) if k)]
    # 5. echo leakage
    L.append("\n## 5. Echo leakage: our own voice and crew clips alone through speaker -> mic")
    eg = defaultdict(lambda: [0, 0, 0])
    for r in echo:
        k = r["render"].get("voice") or "crew clip"
        hw = norm(r["hyp"])
        eg[k][0] += 1
        eg[k][1] += bool(hw)
        eg[k][2] += len(hw)
    tot = [sum(v[i] for v in eg.values()) for i in range(3)]
    L += ["", f"All: {tot[0]} clips, words out on {pct(tot[1], tot[0])}, {tot[2] / max(1, tot[0]):.1f} words per clip.",
          "", "| voice | clips | produced words | words / clip |", "|---|---|---|---|"]
    import render_r8 as R8
    for k, v in sorted(eg.items(), key=lambda kv: -kv[1][1] / max(1, kv[1][0])):
        L.append(f"| {k}{' (app OS voice)' if k in R8.OS_VOICES else ''} | {v[0]} | {pct(v[1], v[0])} | "
                 f"{v[2] / max(1, v[0]):.1f} |")
    ins = defaultdict(lambda: [0, 0])
    for r in kid:
        n = r["render"].get("noise")
        ref, hyp = norm(r["text"]), norm(r["hyp"])
        sm = difflib.SequenceMatcher(a=ref, b=hyp, autojunk=False)
        extra = sum((j2 - j1) - (i2 - i1) for op, i1, i2, j1, j2 in sm.get_opcodes() if op in ("insert", "replace")
                    and (j2 - j1) > (i2 - i1))
        ins[n][0] += 1
        ins[n][1] += extra >= 2
    L += ["", "Kid turns with an echo under them: share with >= 2 inserted words (the echo leaking into the kid's turn):",
          ""] + [f"- {n}: {pct(v[1], v[0])} of {v[0]}" for n, v in sorted(ins.items())]
    # 6. device directed
    L.append("\n## 6. device_directed: room talk vs directed")
    pos, neg, negr, dhp, dhn = [], [], [], [], []
    for r in kid:
        d = dd_of(r)
        ga = r.get("gold_act")
        cat = r.get("cat") or ""
        if d is None:
            continue
        if ga == "ignore" or "chatter" in cat or "roomtalk" in cat:
            neg.append(d)
            if "chatter" in cat or "roomtalk" in cat:
                negr.append(d)
        elif ga is not None:
            pos.append(d)
    eneg = [dd_of(r) for r in echo if dd_of(r) is not None]
    L += ["", f"Kid turns with a gold act: directed {len(pos)}, not directed (gold ignore: room talk, chatter, echo-like) "
          f"{len(neg)} (of which room talk / chatter {len(negr)}). `dd` = the app's remapped head (max over the clip's "
          "segments; a wordless segment has none).", "",
          "| comparison | AUC | dd >= 0.5: directed / other |", "|---|---|---|",
          f"| directed vs gold-ignore kid turns | {auc(pos, neg) or 0:.3f} | {pct(sum(x >= .5 for x in pos), len(pos))} / "
          f"{pct(sum(x >= .5 for x in neg), len(neg))} |",
          f"| directed vs room talk / chatter | {auc(pos, negr) or 0:.3f} | {pct(sum(x >= .5 for x in pos), len(pos))} / "
          f"{pct(sum(x >= .5 for x in negr), len(negr))} |",
          f"| directed vs echo-bank clips with words | {auc(pos, eneg) or 0:.3f} | "
          f"{pct(sum(x >= .5 for x in pos), len(pos))} / {pct(sum(x >= .5 for x in eneg), len(eneg))} |"]
    # 7. end of turn
    L.append("\n## 7. End of turn")
    lat, split, early, nend = [], 0, 0, 0
    dec = []
    for r in kid:
        ends = r["x"].get("ends") or []
        sp = r["render"].get("speech_s")
        if not sp:
            continue
        nend += 1
        if len(ends) > 1:
            split += 1
        if ends:
            e0 = ends[0]
            if e0["at"] < sp[1] - 0.15 and len(ends) > 1:
                early += 1
            lat.append(ends[-1]["at"] - sp[1])
            dec += [e["decode_ms"] for e in ends]
    lat = np.asarray(lat)
    L += ["", f"{nend} kid clips (speech end known from the render). Turn closes per clip: more than one (the turn was "
          f"cut into pieces) on {pct(split, nend)}; the first close before the speech ended (a premature cut-off) on "
          f"{pct(early, nend)}.",
          f"Close latency after the speech ends (audio time; the end-silence wait is in it): p50 "
          f"{np.percentile(lat, 50):.2f} s, p90 {np.percentile(lat, 90):.2f} s. Final decode time per close: p50 "
          f"{np.percentile(dec, 50):.0f} ms, p90 {np.percentile(dec, 90):.0f} ms (under the machine's load)."
          if len(lat) else "no data"]
    # 8. compound commands
    L.append("\n## 8. Compound commands and commands kept")
    try:
        from app.mission import nlu
        cc = defaultdict(lambda: [0, 0, 0])
        for r in kid:
            cat = r.get("cat") or ""
            if r.get("gold_act") != "command":
                continue
            k = "compound" if "compound" in cat else "single"
            rc = [c.get("type") for c in map(nlu.valid, nlu.parse(r["text"]).get("commands") or []) if c]
            hc = [c.get("type") for c in map(nlu.valid, nlu.parse(r["hyp"]).get("commands") or []) if c]
            if not rc:
                continue
            cc[k][0] += 1
            cc[k][1] += rc == hc
            cc[k][2] += len(hc) < len(rc)
        L += ["", "Turns whose gold act is a command and whose reference parses (mission NLU): the decode parses to the "
              "same command types / loses a command.", "", "| kind | turns | same commands | a command lost |",
              "|---|---|---|---|"] + [f"| {k} | {v[0]} | {pct(v[1], v[0])} | {pct(v[2], v[0])} |" for k, v in cc.items()]
    except Exception as e:  # noqa: BLE001
        L.append(f"(nlu not importable here: {e})")
    # 9. features
    L.append("\n## 9. Director features the ear leaves at 0")
    if a.data and Path(a.data, "test_voice_heldout.npz").exists():
        from app.director_model import features as FX
        z = np.load(Path(a.data, "test_voice_heldout.npz"))
        f = z["feats"]
        ev = f[:, FX.FEATS.index("ev_turn_end")] > 0 if "ev_turn_end" in FX.FEATS else np.ones(len(f), bool)
        ff = f[ev]
        cols = ["ear_avail", "ear_conf", "ear_alts", "ear_alt_hot", "ear_rescored", "ear_tier_step", "ear_tier_screen",
                "dd_avail", "dd", "cc_avail", "cc", "tag_avail", "hot_avail", "hot_step", "hot_screen", "hot_step_sa",
                "hot_screen_sa"] + [c for c in FX.FEATS if c.startswith("emo_")]
        L += ["", f"test_voice_heldout, {ev.sum()} turn-end steps (every turn a real-ear decode): share of steps where "
              "the feature is non-zero.", "", "| feature | non-zero |", "|---|---|"]
        for c in cols:
            if c in FX.FEATS:
                L.append(f"| {c} | {pct(int((ff[:, FX.FEATS.index(c)] != 0).sum()), len(ff))} |")
        ncc = sum(1 for r in new for e in r["events"] if e["t"] == "arc" and e.get("cc") is not None)
        narc = sum(1 for r in new for e in r["events"] if e["t"] == "arc")
        L += ["", f"**`cc` is a train / serve skew:** the ear sent `command_complete` on {ncc} of {narc} arc messages "
              "(it has no such head), so in the app `cc_avail` = `cc` = 0; but `gen_sessions.run` sends its own "
              "`command_complete` = U(0.5, 0.95) with every turn, real-ear turns included, so every train and test set "
              "has `cc` non-zero on ~85 % of turn ends. `ear_avail` is 1 in both (the final words carry an empty `alts` "
              "list), but every value behind it (conf, alts, rescored, tiers) is empty. `emo_*` comes from the "
              "generator's emotion items, not the ear (it sends none).",
              "", "Not features at all (the ear sends them, the Director never reads them): `names` link state / "
              "link p / entity kind, `audio_events`, `spoken`, `tags`, `directed_head` (raw)."]
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
