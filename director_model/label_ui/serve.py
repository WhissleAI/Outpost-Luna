"""The Director's real-turn labelling tool (docs/ADULT_SESSIONS.md §5): review imported turns, confirm or correct them.

    python3 director_model/label_ui/serve.py --log outpost-luna-help-2026-11-22.zip [--log more.zip] [--port 8377]
    -> open http://127.0.0.1:8377  (local only: it binds 127.0.0.1 and loads nothing from the network)

For each turn it shows the heard words (and the audio clip when the export has one), the screen, the ear's numbers,
what the engine decided and said, the outcome signals and the import's weak label. The labeller confirms or corrects:

    act        ignore | answer | command | navigate | ask_clarify | nudge | confirm_yes | confirm_no | skip
    nav        which navigation (features.NAV_INTENTS) + its argument (a lesson / site / panel id)
    cmd        the order's slots ("allocate to=heaters amount=percent:40", "shelter_on", "dispatch task=collect_ice")
    place      the place the turn is about (a places.json id)
    reply      the line the app should have said (from candidates: what it said, "Say again?", stay quiet, or typed)
    split      held out (test) or not

Every save appends one row to data/review/reviewed.jsonl (import_logs.load_reviewed_full: the last row per turn wins)
and rebuilds data/real_turns.json with import_logs.run, the file gen_sessions / eval_real read. Nothing is uploaded;
data/ is git-ignored.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
DM = HERE.parent
ROOT = DM.parent
sys.path.insert(0, str(DM))
import import_logs as IL  # noqa: E402

ACTS = ["ignore", "answer", "command", "navigate", "ask_clarify", "nudge", "confirm_yes", "confirm_no", "skip"]
_ID = re.compile(r"^[0-9a-f]{8}-\d{1,6}$")
_SLOT = re.compile(r"^[a-z_]{1,24}$")
_ARG = re.compile(r"^[a-z0-9_:.\-]{1,48}$")


def nav_intents() -> list[str]:
    """features.NAV_INTENTS, read from the source (no numpy import needed here)."""
    try:
        src = (ROOT / "backend/app/director_model/features.py").read_text()
        m = re.search(r"^NAV_INTENTS = \[(.*?)\]\n", src, re.S | re.M)
        return [x for x in re.findall(r'"([a-z_]+)"', m.group(1)) if x != "none"]
    except (OSError, AttributeError):
        return ["accept_offer", "decline_offer", "back", "map", "academy", "library", "go_mission", "other"]


def fixed_lines() -> list[str]:
    """The Director's own fixed lines, offered as reply candidates (director.SAY_AGAIN, director.UNKNOWN)."""
    out = []
    try:
        src = (ROOT / "backend/app/director.py").read_text()
        for k in ("SAY_AGAIN", "UNKNOWN"):
            m = re.search(rf'^{k} = "([^"]+)"', src, re.M)
            if m:
                out.append(m.group(1))
    except OSError:
        pass
    return out or ["Say again? I missed that."]


def places() -> list[str]:
    try:
        return sorted(p["id"] for p in json.loads((ROOT / "backend/data/places.json").read_text())["places"])
    except (OSError, ValueError, KeyError):
        return []


def parse_cmd(s: str) -> dict | None:
    """"allocate to=heaters amount=percent:40" -> {"type": "allocate", "to": "heaters", "amount": {"kind": "percent",
    "value": 40}}. Words only from app enums; None for an empty or malformed line."""
    ws = (s or "").strip().lower().split()
    if not ws or not _SLOT.match(ws[0]):
        return None
    out: dict = {"type": ws[0]}
    for w in ws[1:]:
        if "=" not in w:
            return None
        k, v = w.split("=", 1)
        if not _SLOT.match(k):
            return None
        if k == "amount":
            kind, _, val = v.partition(":")
            if not _SLOT.match(kind):
                return None
            try:
                num = float(val) if val else None
            except ValueError:
                return None
            out["amount"] = {"kind": kind, "value": (int(num) if num is not None and num.is_integer() else num)}
        elif k == "on":
            out["on"] = v in ("1", "true", "yes", "on")
        elif _SLOT.match(v):
            out[k] = v
        else:
            return None
    return out


def cmd_text(c: dict | None) -> str:
    if not isinstance(c, dict) or not c.get("type"):
        return ""
    parts = [c["type"]]
    for k, v in c.items():
        if k == "type":
            continue
        if k == "amount" and isinstance(v, dict):
            parts.append(f"amount={v.get('kind')}" + (f":{v['value']}" if v.get("value") is not None else ""))
        elif isinstance(v, bool):
            parts.append(f"{k}={'true' if v else 'false'}")
        elif v is not None:
            parts.append(f"{k}={v}")
    return " ".join(parts)


class Labeller:
    """The tool's model: the imported turns of the given logs, the labels so far, saving and rebuilding."""

    def __init__(self, logs: list[str], out: Path = IL.OUT, review_dir: Path = IL.REVIEW, audio_dir: Path = IL.AUDIO,
                 by: str = ""):
        self.files = IL.files_of(logs)
        if not self.files:
            raise SystemExit(f"no turn logs in {logs}")
        self.out, self.review_dir, self.audio_dir, self.by = Path(out), Path(review_dir), Path(audio_dir), by
        self.wavs: dict[str, tuple] = {}      # turn id -> (zip path, member) or a file path
        for f in self.files:
            if isinstance(f, tuple):
                with zipfile.ZipFile(f[0]) as z:
                    for n in z.namelist():
                        m = IL.ZIP_WAV.match(n)
                        if m:
                            self.wavs[m.group(1)] = (f[0], n)
            else:
                d = Path(f).parent / "playtest"
                if d.is_dir():
                    for w in d.glob("*.wav"):
                        if _ID.match(w.stem):
                            self.wavs[w.stem] = w
        self.fixed = fixed_lines()

    def turns(self) -> list[dict]:
        ts, sigs = IL.read(self.files)
        by_id = {t["id"]: t for t in ts}
        lab = IL.load_reviewed_full(self.review_dir)
        rows = []
        for t in ts:
            t["_sigs"] = sigs.get(t["id"], [])
        for t in ts:
            text = t.get("text") or ""
            private = bool(t.get("guard")) or not text
            act, conf, why = IL.weak_label(t, t["_sigs"], by_id) if not private else (None, 0.0, "private")
            d = t.get("director") or {}
            rep = t.get("reply") if isinstance(t.get("reply"), dict) else {}
            said = [s for s in rep.get("say") or [] if isinstance(s, str)]
            cands = list(dict.fromkeys([*said, *self.fixed]))
            nav = (rep.get("nav") or {}) if isinstance(rep.get("nav"), dict) else {}
            rt = t.get("router") or {}
            cmd = d.get("cmd") if isinstance(d.get("cmd"), dict) else None
            ear = t.get("ear") or {}
            rows.append({
                "id": t["id"], "s": t.get("s"), "t": t.get("t"), "text": text, "private": private,
                "audio": t["id"] in self.wavs and not private, "collect": bool(t.get("collect")),
                "frame": t.get("frame") or {}, "mode": t.get("mode"), "course": t.get("course"), "src": t.get("src"),
                "arc": t.get("arc") or {}, "ear": {k: ear.get(k) for k in ("uconf", "min_wconf", "eot", "barge",
                                                                          "playback", "speech_s") if k in ear},
                "cls": (t.get("seen") or {}).get("cls"), "router": rt,
                "director": {k: d.get(k) for k in ("rules", "model", "p", "override", "final", "source", "confirm")
                             if d.get(k) is not None},
                "cmd": cmd, "reply": said, "reply_nav": nav, "place": rep.get("place"),
                "signals": [{"sig": s["sig"], "dt": s.get("dt")} for s in t["_sigs"]],
                "weak": {"act": act, "conf": round(conf, 2), "why": why},
                "split": IL.split_of(text) if text else None,
                "label": lab.get(t["id"]),
                # what the form starts with: the existing label, else the engine's own decision
                "start": self._start(lab.get(t["id"]), act, rt, nav, cmd, rep, said),
                "candidates": cands,
            })
        rows.sort(key=lambda r: (r["s"] or "", r["t"] if isinstance(r["t"], (int, float)) else 0))
        return rows

    @staticmethod
    def _start(lab, act, rt, nav, cmd, rep, said) -> dict:
        if lab:
            return {"act": lab.get("fix"), "nav": lab.get("nav") or "", "nav_arg": lab.get("nav_arg") or "",
                    "cmd": cmd_text(lab.get("cmd")), "place": lab.get("place") or "",
                    "reply": lab.get("reply") if isinstance(lab.get("reply"), str) else (said[0] if said else ""),
                    "test": lab.get("split") == "test"}
        return {"act": act or "ignore", "nav": nav.get("intent") or (rt.get("intent") if rt.get("outcome") == "navigate"
                                                                     else "") or "",
                "nav_arg": nav.get("arg") or "", "cmd": cmd_text(cmd), "place": (rep or {}).get("place") or "",
                "reply": said[0] if said else "", "test": False}

    def audio(self, tid: str) -> bytes | None:
        src = self.wavs.get(tid) if _ID.match(tid or "") else None
        if src is None:
            return None
        if isinstance(src, tuple):
            with zipfile.ZipFile(src[0]) as z:
                return z.read(src[1])
        return Path(src).read_bytes()

    def label(self, b: dict) -> dict:
        """One labeller decision -> a reviewed.jsonl row (validated), then real_turns.json rebuilt."""
        tid = str(b.get("id") or "")
        if not _ID.match(tid):
            raise ValueError("bad turn id")
        act = b.get("act")
        if act not in ACTS:
            raise ValueError(f"act must be one of {ACTS}")
        row: dict = {"id": tid, "fix": act, "by": (str(b.get("by") or self.by)[:24] or None),
                     "day": dt.date.today().isoformat()}
        if act == "navigate":
            nav = b.get("nav") or ""
            if nav and nav not in nav_intents():
                raise ValueError("unknown navigation intent")
            row["nav"] = nav or None
            arg = (b.get("nav_arg") or "").strip()
            if arg and not _ARG.match(arg):
                raise ValueError("a navigation argument is an app id (letters, digits, _ - : .)")
            row["nav_arg"] = arg or None
        if act == "command":
            c = parse_cmd(b.get("cmd") or "")
            if b.get("cmd") and c is None:
                raise ValueError("command slots: type key=value ... (amount=kind:value)")
            row["cmd"] = c
        place = (b.get("place") or "").strip()
        if place and not _ARG.match(place):
            raise ValueError("a place is a places.json id")
        row["place"] = place or None
        if isinstance(b.get("reply"), str):
            row["reply"] = b["reply"].strip()[:300]
        row["split"] = "test" if b.get("test") else None
        row = {k: v for k, v in row.items() if v is not None}
        self.review_dir.mkdir(parents=True, exist_ok=True)
        with open(self.review_dir / "reviewed.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
        res = self.write()
        return {"ok": True, "row": row, "items_total": res.get("items_total")}

    def write(self) -> dict:
        return IL.run(self.files, self.out, self.review_dir, quiet=True, audio_dir=self.audio_dir)

    def meta(self) -> dict:
        return {"acts": ACTS, "nav": nav_intents(), "places": places(), "fixed": self.fixed,
                "out": str(self.out), "reviewed": str(self.review_dir / "reviewed.jsonl"),
                "sources": [":".join(map(str, f)) if isinstance(f, tuple) else str(f) for f in self.files]}


def make_handler(L: Labeller):
    page = (HERE / "index.html").read_bytes()

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):   # quiet
            pass

        def _send(self, code: int, body: bytes, ctype: str = "application/json"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            # the page loads nothing from the network: everything is this server's
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; "
                                                        "script-src 'self' 'unsafe-inline'; media-src 'self' blob:")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code=200):
            self._send(code, json.dumps(obj).encode())

        def _local(self) -> bool:
            host = (self.headers.get("Host") or "").split(":")[0]
            return host in ("127.0.0.1", "localhost")

        def do_GET(self):
            if not self._local():
                return self._json({"error": "local only"}, 403)
            p = self.path.split("?")[0]
            if p in ("/", "/index.html"):
                return self._send(200, page, "text/html; charset=utf-8")
            if p == "/api/meta":
                return self._json(L.meta())
            if p == "/api/turns":
                return self._json(L.turns())
            m = re.match(r"^/api/audio/([0-9a-f]{8}-\d{1,6})$", p)
            if m:
                b = L.audio(m.group(1))
                return self._send(200, b, "audio/wav") if b else self._json({"error": "no audio"}, 404)
            return self._json({"error": "not found"}, 404)

        def do_POST(self):
            if not self._local() or self.headers.get("X-Label-UI") != "1":
                return self._json({"error": "local page only"}, 403)
            n = int(self.headers.get("Content-Length") or 0)
            try:
                b = json.loads(self.rfile.read(min(n, 65536)) or b"{}")
            except ValueError:
                return self._json({"error": "bad json"}, 400)
            p = self.path.split("?")[0]
            try:
                if p == "/api/label":
                    return self._json(L.label(b if isinstance(b, dict) else {}))
                if p == "/api/write":
                    return self._json(L.write())
            except ValueError as e:
                return self._json({"error": str(e)}, 400)
            return self._json({"error": "not found"}, 404)

    return H


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", action="append", required=True, help="an adult export / playtest .zip, a turnlog folder "
                    "or .jsonl (repeatable)")
    ap.add_argument("--port", type=int, default=8377)
    ap.add_argument("--by", default="", help="the labeller's initials, kept on each label row")
    ap.add_argument("--out", default=str(IL.OUT))
    ap.add_argument("--review", default=str(IL.REVIEW))
    a = ap.parse_args(argv)
    if a.port in (47310, 47210):
        raise SystemExit("that port is the app's: pick another")
    L = Labeller(a.log, Path(a.out), Path(a.review), by=a.by)
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), make_handler(L))
    print(f"label tool: http://127.0.0.1:{a.port}  ({len(L.turns())} turns; labels -> {a.review}/reviewed.jsonl, "
          f"{a.out})")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
