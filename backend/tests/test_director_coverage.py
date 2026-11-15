"""Round 8: the Director's capability x flow inventory (director_model/coverage.json, docs/DIRECTOR_COVERAGE.md) stays
in step with the code. A new router intent, course step type or screen fails here until it has a probe, a cell and a
generator: run `uv run --project backend python director_model/coverage.py` and add it to pools_r8 / coverage.py."""
import json
import random
import sys
from pathlib import Path

import pytest

DM = Path(__file__).resolve().parents[2] / "director_model"
sys.path.insert(0, str(DM))

import coverage as C  # noqa: E402
import pools_r8 as P8  # noqa: E402

INV = json.loads((DM / "coverage.json").read_text())


def test_every_router_intent_has_a_probe():
    missing = [i for i in C.router_intents() if i not in C.PROBES]
    assert not missing, f"router intents with no coverage probe (coverage.PROBES): {missing}"


def test_inventory_is_current():
    assert INV["router_intents"] == C.router_intents(), "rerun director_model/coverage.py: the router's intents changed"
    assert INV["step_types"] == C.step_types(), "rerun director_model/coverage.py: course.json has new step types"
    caps = C.capabilities()
    assert {c["cell"] for c in INV["cells"]} == set(caps), "rerun director_model/coverage.py: the cells changed"


def test_every_step_type_and_screen_has_cells():
    from app.director_model import features as FX
    cells = {c["cell"] for c in INV["cells"]}
    for t in C.step_types():
        assert f"lesson|step:{t}:answer" in cells and f"lesson|step:{t}:wrong" in cells, t
    for s in FX.SCREENS:
        assert f"{s}|question" in cells and f"{s}|ignore:chatter" in cells, s


def test_every_router_intent_is_reachable_somewhere():
    reach = {c["intent"][4:] for c in INV["cells"] if c["intent"].startswith("nav:")}
    lost = [i for i in C.router_intents() if i not in reach and i not in ("end_shift",)]
    assert not lost, f"intents no screen reaches with their probe (fix the probe): {lost}"


@pytest.mark.parametrize("seed", [0, 1])
def test_every_cell_has_a_generator(seed):
    rng = random.Random(seed)
    none = [c["cell"] for c in INV["cells"] if P8.cell_item(c, rng, "train") is None]
    assert not none, f"cells the coverage sweep cannot generate: {none[:20]}"


def test_merged_features_are_not_pending():
    """Round 8 run: video, prep, gestures and the OS-voice echo are merged; a pending cell must name a live branch."""
    for c in INV["cells"]:
        if c["screen"] in ("video", "prep") or c["intent"] in ("gesture+voice", "ignore:echo_os_voice",
                                                                "ignore:video_audio"):
            assert not c.get("pending"), c["cell"]
