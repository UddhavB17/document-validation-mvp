"""Retention job (source files, exports, telemetry). Implemented by ``ws-a-data-diet``."""

from __future__ import annotations

from typing import Any


def run_retention(now: Any = None, dry_run: bool = True) -> dict:
    """Delete expired rows/files per the retention budgets. Stub owned by ws-a."""
    raise NotImplementedError("run_retention is implemented by ws-a-data-diet")
