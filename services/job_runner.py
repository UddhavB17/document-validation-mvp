"""Background execution for long-running pipeline work."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from typing import Callable, TypeVar

from services.config import get_int

T = TypeVar("T")

_executor: ThreadPoolExecutor | None = None


def _get_executor() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(
            max_workers=get_int("DMEF_PIPELINE_WORKERS", 1, minimum=1),
            thread_name_prefix="dmef-pipeline",
        )
    return _executor


def submit_job(fn: Callable[..., T], *args, **kwargs) -> Future[T]:
    return _get_executor().submit(fn, *args, **kwargs)
