"""Operations payload builder for ``GET /ops/applications/{id}``.

Implemented by ``ws-f-accuracy-ops-api`` per contracts §5.
"""

from __future__ import annotations


def build_ops_payload(application_id: int) -> dict:
    """Build the operator-facing payload for one application."""
    raise NotImplementedError("build_ops_payload is implemented by ws-f-accuracy-ops-api")
