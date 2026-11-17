"""[vidfix] The connectivity probe behind /api/video/{id}/available: online but slow is not offline."""
import httpx
import pytest

from app import video


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    video._probe.clear()
    monkeypatch.setattr(video.settings, "video_offline", False, raising=False)
    yield
    video._probe.clear()


def _head(script):
    calls = []

    def head(url, timeout=None, headers=None, verify=None):
        calls.append(timeout)
        r = script[min(len(calls), len(script)) - 1]
        if isinstance(r, Exception):
            raise r
        return r
    return head, calls


def test_slow_first_probe_is_retried_not_offline(monkeypatch):
    head, calls = _head([httpx.ReadTimeout("slow"), httpx.Response(200)])
    monkeypatch.setattr(video.httpx, "head", head)
    assert video.online("youtube") is True
    assert len(calls) == 2 and calls[1] > calls[0]


def test_any_http_answer_is_online(monkeypatch):
    head, _ = _head([httpx.Response(403)])
    monkeypatch.setattr(video.httpx, "head", head)
    assert video.online("youtube") is True


def test_refused_connection_is_offline_without_waiting_for_a_retry(monkeypatch):
    head, calls = _head([httpx.ConnectError("no route")])
    monkeypatch.setattr(video.httpx, "head", head)
    assert video.online("nasa") is False
    assert len(calls) == 1


def test_a_failed_probe_is_not_remembered_for_long(monkeypatch):
    t = [1000.0]
    monkeypatch.setattr(video.time, "monotonic", lambda: t[0])
    head, calls = _head([httpx.ConnectError("blip"), httpx.Response(200)])
    monkeypatch.setattr(video.httpx, "head", head)
    assert video.online("youtube") is False
    t[0] += video.PROBE_FAIL_TTL_S + 0.1
    assert video.online("youtube") is True
    t[0] += video.PROBE_TTL_S - 1      # success is remembered
    assert video.online("youtube") is True and len(calls) == 2


def test_video_offline_forces_no(monkeypatch):
    monkeypatch.setattr(video.settings, "video_offline", True, raising=False)
    assert video.online("youtube") is False
