"""Durable pipeline worker loop. Implemented by ``ws-c-queue-batch``."""

from __future__ import annotations


def run_worker(poll_seconds: float = 2.0, once: bool = False) -> None:
    """Poll ``pipeline_jobs`` and run due jobs. Stub owned by ws-c."""
    raise NotImplementedError("run_worker is implemented by ws-c-queue-batch")
