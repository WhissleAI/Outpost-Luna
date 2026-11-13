"""Backward-compat: the rule resolver became the Director (director.py, docs/REVAMP.md §3.5)."""
from .director import direct as resolve  # noqa: F401
