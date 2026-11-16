"""[#92] Local diagnostics (app/diag.py, app/diagnostics.py, docs/DIAGNOSTICS.md): scrubbing (a log call with a
transcript or a token never writes it), rotation caps, the metrics and the daily summary, the metrics endpoint's
token rule, and the diagnostics file's contents (no forbidden fields or files)."""
from __future__ import annotations

import asyncio
import io
import json
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import diag, diagnostics
from app.local_guard import LocalGuard
from app.main import app

TOKEN = "Zq3-very-secret-launch-token-0123456789abcdefXYZ"
SAID = "fly me to shackleton crater please"
NAME = "Charlie Duke"


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    logs, data = tmp_path / "logs", tmp_path / "data"
    monkeypatch.setenv("LUNA_LOG_DIR", str(logs))
    monkeypatch.setenv("LUNA_DATA_DIR", str(data))
    return logs, data


def all_text(d: Path) -> str:
    return "".join(p.read_text(encoding="utf-8", errors="replace") for p in d.rglob("*") if p.is_file())


# ---- scrubbing ---------------------------------------------------------------------------------------------------
def test_a_log_call_with_a_transcript_names_audio_or_a_token_never_writes_them(dirs, monkeypatch):
    logs, _ = dirs
    monkeypatch.setenv("LUNA_TOKEN", TOKEN)
    log = diag.JsonLog("backend")
    log.event("turn", text=SAID, transcript=SAID, words=[{"w": "fly"}], spoken=SAID, heard=NAME,
              names=[{"heard": NAME, "entity": NAME}], name=NAME, audio=b"\x00\x01" * 100, pcm=b"x",
              token=TOKEN, luna_token=TOKEN, headers={"Authorization": f"Bearer {TOKEN}", "cookie": f"luna_token={TOKEN}"},
              note=f"called with X-Luna-Token: {TOKEN}", other=f"a token={TOKEN} in free text",
              path=str(Path.home() / "Library/Application Support/Outpost Luna/engine.json"),
              nested={"deep": {"question": SAID, "api_key": "sk-123456789"}}, turns=3, ear="arc")
    text = all_text(logs)
    for bad in (SAID, NAME, TOKEN, "sk-123456789", str(Path.home())):
        assert bad not in text, bad
    rec = json.loads((logs / "backend.jsonl").read_text().splitlines()[-1])
    assert set(rec) >= {"ts", "level", "svc", "event"} and rec["svc"] == "backend" and rec["event"] == "turn"
    assert rec["turns"] == 3 and rec["ear"] == "arc"           # what is not sensitive is kept
    assert rec["text"] == diag.SCRUBBED and rec["audio"] == diag.SCRUBBED
    assert rec["path"].startswith("~/")                         # the account name is not in a path


def test_scrub_keeps_hashes_and_numbers_but_not_token_like_runs():
    sha = "a" * 32 + "0123456789abcdef" * 2
    assert diag.scrub_str(f"sha256 {sha}") == f"sha256 {sha}"
    assert diag.SCRUBBED in diag.scrub_str("key AbCdEfGhIjKlMnOpQrStUvWxYz012345_-abc")
    assert diag.scrub({"rtf": 0.12, "n": 4, "ok": True, "x": float("nan")}) == {"rtf": 0.12, "n": 4, "ok": True, "x": None}
    assert len(diag.scrub_str("y" * 5000 + " ")) <= diag.MAX_STR + 1


def test_no_log_dir_no_file(tmp_path, monkeypatch):
    monkeypatch.delenv("LUNA_LOG_DIR", raising=False)
    rec = diag.JsonLog("backend").event("start")
    assert rec["event"] == "start" and not list(tmp_path.iterdir())


# ---- rotation ----------------------------------------------------------------------------------------------------
def test_rotation_caps_files_and_size(tmp_path):
    log = diag.JsonLog("backend", log_dir=tmp_path, max_bytes=2000, keep=3)
    for i in range(400):
        log.event("tick", i=i, pad="z" * 40)
    files = sorted(p.name for p in tmp_path.iterdir())
    assert files == ["backend.jsonl", "backend.jsonl.1", "backend.jsonl.2"]
    assert all((tmp_path / f).stat().st_size <= 2000 for f in files)
    last = json.loads((tmp_path / "backend.jsonl").read_text().splitlines()[-1])
    assert last["i"] == 399                                     # the newest lines are kept, the oldest dropped
    assert diag.LOG_MAX_BYTES == 5 * 1024 * 1024 and diag.LOG_KEEP == 5   # the shipped caps: 5 x 5 MB


# ---- metrics + the daily summary ---------------------------------------------------------------------------------
def test_histogram_quantiles():
    h = diag.Hist()
    for v in range(1, 101):
        h.observe(v)
    s = h.summary()
    assert s["n"] == 100 and 40 <= s["p50"] <= 60 and 90 <= s["p95"] <= 100 and s["p99"] <= 100 and s["max"] == 100
    assert diag.Hist().summary()["p50"] is None


def test_daily_summary_merges_and_keeps_30_days(dirs):
    _, data = dirs
    m = diag.Metrics("backend")
    m.inc("turns", ear="arc")
    m.observe("ear_decode_ms", 120, kind="final")
    assert diag.flush(m)
    m.inc("turns", ear="arc", n=2)
    m.observe("ear_decode_ms", 80, kind="final")
    assert diag.flush(m)
    assert not diag.flush(m)                                    # nothing new: nothing written
    doc = json.loads((data / "metrics/daily-backend.json").read_text())
    (day,) = doc["days"]
    b = doc["days"][day]
    assert b["counters"]["turns{ear=arc}"] == 3
    assert b["histograms"]["ear_decode_ms{kind=final}"]["n"] == 2 and b["histograms"]["ear_decode_ms{kind=final}"]["p95"]
    for i in range(40):
        doc = diag.merge_daily(doc, {"turns": 1}, {}, f"2026-01-{i % 28 + 1:02d}" if i < 28 else f"2026-02-{i - 27:02d}")
    assert len(doc["days"]) == diag.KEEP_DAYS


# ---- the metrics endpoint ----------------------------------------------------------------------------------------
def test_metrics_endpoint_needs_the_token_when_one_is_set(monkeypatch):
    c = TestClient(app)
    assert c.get("/api/metrics").status_code == 200             # no token configured (dev, tests)
    monkeypatch.setenv("LUNA_TOKEN", TOKEN)
    assert c.get("/api/metrics").status_code == 401             # a GET too: no other local process reads it
    assert c.get("/api/metrics", headers={"X-Luna-Token": "wrong"}).status_code == 401
    assert c.get("/api/metrics", headers={"X-Luna-Token": TOKEN}).status_code == 200
    assert c.get("/api/metrics", headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 200
    c.cookies.set("luna_token", TOKEN)                          # the app's own page (the shell's HttpOnly cookie)
    r = c.get("/api/metrics")
    assert r.status_code == 200
    d = r.json()
    assert d["svc"] in ("backend", "app") and {"counters", "histograms", "rss_mb", "uptime_s"} <= set(d)
    assert TOKEN not in r.text


def test_metrics_endpoint_behind_the_guard_refuses_other_origins(monkeypatch):
    monkeypatch.setenv("LUNA_TOKEN", TOKEN)
    g = TestClient(LocalGuard(app, token=TOKEN, allowed_hosts=["testserver"]))
    assert g.get("/api/metrics", headers={"origin": "https://evil.example", "X-Luna-Token": TOKEN}).status_code == 403
    assert g.get("/api/metrics", headers={"host": "evil.example", "X-Luna-Token": TOKEN}).status_code == 403
    assert g.get("/api/metrics").status_code == 401
    assert g.get("/api/metrics", headers={"X-Luna-Token": TOKEN}).status_code == 200
    assert g.get("/api/diagnostics/contents").status_code == 401
    assert g.post("/api/diagnostics/bundle", json={}).status_code == 401


def test_listen_counts_turns_and_errors_without_words():
    stat = {"ear": None, "turns": 0, "errors": 0}
    before = diag.METRICS.snapshot()["counters"]
    from app.listen import _count
    _count({"t": "ear", "ear": "arc"}, stat)
    _count({"t": "turn", "state": "end", "text": SAID}, stat)
    _count({"t": "error", "code": "decode_timeout", "message": "the ear stopped responding"}, stat)
    after = diag.METRICS.snapshot()["counters"]
    assert stat == {"ear": "arc", "turns": 1, "errors": 1}
    assert after["turns{ear=arc}"] == before.get("turns{ear=arc}", 0) + 1
    assert after["errors{code=decode_timeout}"] == before.get("errors{code=decode_timeout}", 0) + 1
    assert SAID not in json.dumps(after)


def test_mission_saves_and_loads_are_counted():
    from app.mission import registry
    assert getattr(registry, "_diag_hooked", False)
    c = lambda k: diag.METRICS.snapshot()["counters"].get(k, 0)  # noqa: E731
    s0, l0, f0 = c("mission_saves"), c("mission_loads"), c("mission_load_failures")
    m = registry.create("shackleton_rim", 3, level="cadet")
    registry.step(m.id, 1.0)
    assert c("mission_saves") > s0
    registry.MISSIONS.clear()
    assert registry.resume() is not None and c("mission_loads") == l0 + 1
    (registry.save_dir() / "mission.json").write_text("{not json")
    assert registry.resume() is None and c("mission_load_failures") == f0 + 1


# ---- the diagnostics file ----------------------------------------------------------------------------------------
FORBIDDEN_KEYS = {"text", "transcript", "words", "spoken", "heard", "names", "token", "luna_token", "audio"}


def walk(v, path=""):
    if isinstance(v, dict):
        for k, x in v.items():
            yield path + "/" + k, k, x
            yield from walk(x, path + "/" + k)
    elif isinstance(v, list):
        for i, x in enumerate(v):
            yield from walk(x, f"{path}[{i}]")


def planted(logs: Path, data: Path):
    """A log folder as a real run leaves it, plus everything that must NOT end up in the file."""
    log = diag.JsonLog("backend", log_dir=logs)
    log.event("start", pid=1)
    log.event("turn", text=SAID, names=[NAME], ear="arc")
    with open(logs / "models.jsonl", "a") as f:                  # a line some other code wrote raw: re-scrubbed
        f.write(json.dumps({"ts": "x", "event": "oops", "text": SAID, "msg": f"Bearer {TOKEN}"}) + "\n")
        f.write(f"not json: {SAID} {TOKEN}\n")                   # dropped
    (logs / "backend.log").write_text(f"uvicorn said {SAID} {TOKEN}\n")   # human-readable logs never go in
    (logs / "clip.wav").write_bytes(b"RIFF....WAVE")
    (data / "cache/turnlog").mkdir(parents=True)
    (data / "cache/turnlog/turns.jsonl").write_text(json.dumps({"text": SAID}) + "\n")
    m = diag.Metrics("backend")
    m.inc("turns", ear="arc")
    diag.flush(m, diag.daily_path("backend", data))
    (data / "metrics/daily-main.json").write_text(json.dumps({"format": 1, "days": {"2026-11-16": {"counters": {"sessions": 1}}}}))


def build(logs, data, **kw):
    shell = {"app": {"version": "0.3.8", "electron": "44.10.0"}, "os": {"platform": "darwin", "release": "25.2.0"},
             "hardware": {"cpu": "Apple M3", "cores": 8, "memory_gb": 16},
             "engine": {"format": 1, "backend": "http://127.0.0.1:48310", "model_server": "http://127.0.0.1:48210",
                        "token": TOKEN, "pid": 1, "version": "0.3.8"},
             "main_metrics": {"svc": "main", "counters": {"sessions": 1}, "note": f"Bearer {TOKEN}"}}
    mh = {"ok": True, "models": {"arc_ear": {"available": True, "model": "arc-transcriber-space", "revision": "abc1234",
                                             "engine": {"abi": 3, "ort": "1.22.0", "verify": {"verified": True}},
                                             "ort_wheel": "1.22.0", "model_dir": str(Path.home() / "x/nft2")},
                                 "os_tts": {"voices": [{"name": "Samantha"}]}}}
    return asyncio.run(diagnostics.build(shell, log_dir=logs, data_dir=data, models_health=mh,
                                         models_metrics={"svc": "models", "counters": {}},
                                         backend_health={"ok": True}, **kw))


def test_bundle_holds_exactly_the_listed_parts_and_nothing_forbidden(tmp_path, monkeypatch):
    logs, data = tmp_path / "logs", tmp_path / "data"
    logs.mkdir()
    planted(logs, data)
    monkeypatch.setenv("LUNA_TOKEN", TOKEN)
    body, names = build(logs, data)
    z = zipfile.ZipFile(io.BytesIO(body))
    assert sorted(z.namelist()) == sorted(names)
    assert {"README.txt", "system.json", "versions.json", "engine.json", "health/backend.json",
            "health/model_server.json", "metrics/backend.json", "metrics/model_server.json", "metrics/main.json",
            "metrics/daily-backend.json", "metrics/daily-main.json", "logs/backend.jsonl", "logs/models.jsonl"} == set(names)
    # every part is one of the listed kinds (the page shows the list before saving)
    listed = {n for n, _ in diagnostics.CONTENTS}
    assert all(n in listed or n.split("/")[0] + "/" in listed for n in names)
    for n in names:
        assert not n.lower().endswith((".wav", ".pcm", ".webm", ".mp3", ".log")), n
        assert "turnlog" not in n
        raw = z.read(n).decode("utf-8")
        for bad in (SAID, NAME, TOKEN, str(Path.home())):
            assert bad not in raw, (n, bad)
        if n.endswith(".json"):
            for p, k, v in walk(json.loads(raw)):
                assert not (k in FORBIDDEN_KEYS and v not in (None, "", [], {}, diag.SCRUBBED)), (n, p)
        if n.endswith(".jsonl"):
            assert all(json.loads(line)["event"] for line in raw.splitlines())   # only our structured lines
    eng = json.loads(z.read("engine.json"))
    assert "token" not in eng and eng["backend"].endswith(":48310")
    v = json.loads(z.read("versions.json"))
    assert v["app"] == "0.3.8" and v["abi"] == 3 and v["ort"] == "1.22.0"
    assert v["models"]["arc_ear"]["revision"] == "abc1234" and v["models"]["arc_ear"]["engine"]["verify"]["verified"]
    assert "Nothing was uploaded" in z.read("README.txt").decode()


def test_contents_list_matches_the_bundle(tmp_path):
    logs = tmp_path / "logs"
    diag.JsonLog("backend", log_dir=logs).event("start")
    c = diagnostics.contents(logs)
    assert [x["name"] for x in c["items"]] == [n for n, _ in diagnostics.CONTENTS]
    assert "(1 files)" in c["items"][-1]["what"] and c["uploaded"] is False
    assert [x["name"] for x in diagnostics.contents(tmp_path / "none")["items"]][-1] == "metrics/"


def test_bundle_endpoint_returns_a_zip_and_needs_the_token(tmp_path, monkeypatch):
    logs, data = tmp_path / "logs", tmp_path / "data"
    logs.mkdir()
    planted(logs, data)
    monkeypatch.setenv("LUNA_LOG_DIR", str(logs))
    monkeypatch.setenv("LUNA_DATA_DIR", str(data))
    monkeypatch.setenv("LUNA_TOKEN", TOKEN)
    c = TestClient(app)
    assert c.post("/api/diagnostics/bundle", json={}).status_code == 401
    r = c.post("/api/diagnostics/bundle", json={"engine": {"token": TOKEN, "pid": 1}}, headers={"X-Luna-Token": TOKEN})
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    assert "outpost-luna-diagnostics-" in r.headers["content-disposition"]
    z = zipfile.ZipFile(io.BytesIO(r.content))
    assert "engine.json" in z.namelist() and "logs/backend.jsonl" in z.namelist()
    assert all(TOKEN not in z.read(n).decode("utf-8") and SAID not in z.read(n).decode("utf-8") for n in z.namelist())
    lst = c.get("/api/diagnostics/contents", headers={"X-Luna-Token": TOKEN}).json()
    assert [x["name"] for x in lst["items"]][:3] == ["README.txt", "system.json", "versions.json"]
