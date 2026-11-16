import os

# [#84] app/local_guard.py: Starlette's TestClient sends Host: testserver; no per-launch token unless a test sets one
# (tests/test_local_guard.py wraps the app in its own guard with a token).
os.environ["LUNA_ALLOWED_HOSTS"] = "testserver"
for _k in ("LUNA_TOKEN", "LUNA_DEV_COOKIE", "LUNA_ORIGINS"):
    os.environ.pop(_k, None)

# [#92] app/diag.py: tests never write the developer's logs or daily metrics (a test that wants them sets its own dirs)
for _k in ("LUNA_LOG_DIR", "LUNA_DATA_DIR"):
    os.environ.pop(_k, None)
