"""[0.4.1] The release smoke never writes to the owner's real data (docs/RELEASING.md): desktop/scripts/smoke.py
refuses the owner's data folder and ports, and needs a test app (--engine / OUTPOST_USER_DATA / --base)."""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def smoke():
    spec = importlib.util.spec_from_file_location("outpost_smoke", ROOT / "desktop/scripts/smoke.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_refuses_the_owners_data_folder_and_ports(smoke, tmp_path):
    owner = tmp_path / "Outpost Luna"
    (owner).mkdir()
    assert "data folder" in smoke.refuse_reason(str(owner / "engine.json"), None, owner)
    assert "data folder" in smoke.refuse_reason(str(owner), None, owner)
    for port in (47310, 47210):
        assert "port" in smoke.refuse_reason(None, f"http://127.0.0.1:{port}", owner)
    assert "no test app" in smoke.refuse_reason(None, None, owner)


def test_a_temp_test_app_is_fine(smoke, tmp_path):
    owner = tmp_path / "Outpost Luna"
    test_ud = tmp_path / "outpost-rc-x" / "userdata"
    assert smoke.refuse_reason(str(test_ud / "engine.json"), None, owner) == ""
    assert smoke.refuse_reason(None, "http://127.0.0.1:53111", owner) == ""


def test_engine_defaults_to_the_test_apps_data_folder_never_the_owners(smoke, monkeypatch, tmp_path):
    monkeypatch.delenv("OUTPOST_USER_DATA", raising=False)
    assert smoke.default_engine() is None
    monkeypatch.setenv("OUTPOST_USER_DATA", str(tmp_path / "ud"))
    assert smoke.default_engine() == str(tmp_path / "ud" / "engine.json")
    src = (ROOT / "desktop/scripts/smoke.py").read_text(encoding="utf-8")
    assert "47310\")" not in src and '"http://127.0.0.1:47310"' not in src, "no fallback to the owner's port"


def test_make_smoke_installed_launches_on_temp_data_and_free_ports():
    mk = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "smoke-installed:" in mk
    assert 'release_check.py --app "$(or $(APP),/Applications/Outpost Luna.app)" --gates smoke' in mk
    rc = (ROOT / "desktop/scripts/release_check.py").read_text(encoding="utf-8")
    assert '"OUTPOST_USER_DATA": str(self.ud)' in rc and '"OUTPOST_HEADLESS": "1"' in rc
    assert "OWNER_PORTS = {47310" in rc
