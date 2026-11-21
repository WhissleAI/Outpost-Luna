"""Turn log retention (docs/SECURITY.md "Retention"): 30 days by date, on top of the 5 MB size cap."""
from __future__ import annotations

import datetime as dt
import json
import os
import time

from app import turnlog


def _line(day: str | None, k: str = "turn") -> dict:
    d = {"k": k, "v": turnlog.VERSION, "s": "s1", "id": f"s1-{day}", "text": "go to shackleton"}
    if day:
        d["day"] = day
    return d


def _write(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in rows), encoding="utf-8")


def _days(path):
    return [json.loads(x).get("day") for x in path.read_text(encoding="utf-8").splitlines()]


def test_retention_is_30_days_and_reported(tmp_path):
    st = turnlog.Store(tmp_path)
    assert turnlog.RETAIN_DAYS == 30 and st.retain_days == 30
    assert turnlog.STORE.retain_days == 30
    assert st.stats()["retain_days"] == 30


def test_prune_drops_lines_30_days_old_keeps_29(tmp_path):
    st = turnlog.Store(tmp_path)
    today = dt.date(2026, 11, 21)
    rows = [_line((today - dt.timedelta(days=n)).isoformat()) for n in (45, 30, 29, 1, 0)]
    rows.append(_line((today - dt.timedelta(days=31)).isoformat(), k="signal"))
    _write(st.path, rows)
    assert st.prune(today=today.isoformat()) == 3
    assert _days(st.path) == ["2026-10-23", "2026-11-20", "2026-11-21"]


def test_prune_covers_the_rotated_file_and_removes_it_when_empty(tmp_path):
    st = turnlog.Store(tmp_path)
    _write(st.path.with_name("turns.1.jsonl"), [_line("2026-09-01"), _line("2026-09-02")])
    _write(st.path, [_line("2026-11-20")])
    assert st.prune(today="2026-11-21") == 2
    assert not st.path.with_name("turns.1.jsonl").exists()
    assert st.files() == [st.path]


def test_line_without_day_goes_with_an_old_file_only(tmp_path):
    st = turnlog.Store(tmp_path)
    _write(st.path, [_line(None), _line("2026-11-20")])
    assert st.prune(today="2026-11-21") == 0           # a fresh file: an undated line stays
    old = time.time() - 40 * 86400
    os.utime(st.path, (old, old))
    assert st.prune(today="2026-11-21", force=True) == 1
    assert _days(st.path) == ["2026-11-20"]


def test_old_playtest_clips_are_deleted(tmp_path):
    st = turnlog.Store(tmp_path)
    d = tmp_path / "playtest"
    d.mkdir()
    old, new = d / "s1-1.wav", d / "s1-2.wav"
    old.write_bytes(b"RIFF"); new.write_bytes(b"RIFF")
    t = time.time() - 31 * 86400
    os.utime(old, (t, t))
    assert st.prune(today=dt.date.today().isoformat()) == 1
    assert not old.exists() and new.exists()


def test_prune_runs_once_a_day_unless_forced(tmp_path):
    st = turnlog.Store(tmp_path)
    _write(st.path, [_line("2026-11-20")])
    assert st.prune(today="2026-11-21") == 0
    _write(st.path, [_line("2026-01-01"), _line("2026-11-20")])
    assert st.prune(today="2026-11-21") == 0           # already ran today
    assert st.prune(today="2026-11-21", force=True) == 1
    _write(st.path, [_line("2026-01-01")])
    assert st.prune(today="2026-11-22") == 1           # a new day runs again
    assert st.files() == []


def test_append_and_stats_prune(tmp_path):
    st = turnlog.Store(tmp_path)
    _write(st.path, [_line("2000-01-01"), _line(dt.date.today().isoformat())])
    assert st.append(_line(dt.date.today().isoformat()))
    assert len(_days(st.path)) == 2 and "2000-01-01" not in _days(st.path)
    st2 = turnlog.Store(tmp_path)
    _write(st2.path, [_line("2000-01-01"), _line(dt.date.today().isoformat(), k="turn")])
    assert st2.stats()["turns"] == 1


def test_size_cap_still_applies(tmp_path):
    st = turnlog.Store(tmp_path, cap=2000)
    for _ in range(40):
        assert st.append(_line(dt.date.today().isoformat()))
    assert sum(f.stat().st_size for f in st.files()) <= 2000 + 200


def test_prune_never_raises_on_a_bad_day_or_missing_dir(tmp_path):
    st = turnlog.Store(tmp_path / "missing")
    assert st.prune(today="not-a-day") == 0
    assert st.prune(today="2026-11-21") == 0
