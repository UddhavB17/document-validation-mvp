"""Evidence bounding-box resolution. Implemented by ``ws-f-accuracy-ops-api``."""

from __future__ import annotations


def find_value_bbox(words: list[dict], value: str) -> list[float] | None:
    """Return normalized ``[x0, y0, x1, y1]`` for ``value`` or ``None``."""
    raise NotImplementedError("find_value_bbox is implemented by ws-f-accuracy-ops-api")
