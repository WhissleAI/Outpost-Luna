"""Silent test runs (owner rule): no sound from the browser, ever. Every e2e here imports this.

There is ONE silent helper: frontend/tools/silent.py (the mission-UI tools import it too). Loading it patches
Playwright for the whole process (launch flags, a mute init script on every page and context, the app's own Mute pref
kept on). This module re-exports its pieces under the names the e2e tests use. After a run,
`pmset -g assertions | grep -i "playing audio"` must show nothing from it.
"""
import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location("outpost_silent", Path(__file__).resolve().parents[2] / "tools" / "silent.py")
_silent = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_silent)

LAUNCH_ARGS = list(_silent.SILENT_ARGS)
MUTE_JS = _silent.SILENT_INIT


def silence(ctx):
    """Register the mute script on a browser context (call it after any script that clears localStorage)."""
    ctx.add_init_script(MUTE_JS)
