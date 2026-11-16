import os

# [#84] app/local_guard.py: Starlette's TestClient sends Host: testserver; no per-launch token unless a test sets one
# (tests/test_local_guard.py wraps the app in its own guard with a token).
os.environ["LUNA_ALLOWED_HOSTS"] = "testserver"
for _k in ("LUNA_TOKEN", "LUNA_DEV_COOKIE", "LUNA_ORIGINS"):
    os.environ.pop(_k, None)
