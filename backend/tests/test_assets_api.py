"""Settings -> Storage & updates (app/assets_api.py): the desktop's asset summary, the check request, the busy flag."""
import json

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


def test_dev_checkout_is_not_managed(monkeypatch):
    monkeypatch.setattr(settings, "assets_state_file", None)
    monkeypatch.setattr(settings, "assets_check_file", None)
    with TestClient(app) as c:
        assert c.get("/api/assets").json() == {"managed": False}
        assert c.post("/api/assets/check").json() == {"ok": False, "managed": False}


def test_desktop_summary_and_check_request(tmp_path, monkeypatch):
    st, req = tmp_path / "summary.json", tmp_path / "check-request"
    summary = {"managed": True, "app_version": "0.1.0", "installed": [{"id": "ear", "version": "2", "bytes": 5}],
               "total_bytes": 5, "update": {"state": "ready", "ready": ["ear"]}}
    st.write_text(json.dumps(summary))
    monkeypatch.setattr(settings, "assets_state_file", st)
    monkeypatch.setattr(settings, "assets_check_file", req)
    with TestClient(app) as c:
        assert c.get("/api/assets").json() == summary
        assert c.post("/api/assets/check").json() == {"ok": True}
        assert req.exists()                        # the desktop main process watches this file
        st.write_text("{broken")
        assert c.get("/api/assets").json()["managed"] is True
        b = c.get("/api/assets/busy").json()
        assert set(b) == {"busy"} and isinstance(b["busy"], bool)
