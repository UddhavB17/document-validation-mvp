"""Runtime checks for supported Python versions."""

from __future__ import annotations

import sys


REQUIRED_MAJOR = 3
REQUIRED_MINOR = 11


def require_python_311() -> None:
    if sys.version_info[:2] != (REQUIRED_MAJOR, REQUIRED_MINOR):
        version = ".".join(str(part) for part in sys.version_info[:3])
        raise RuntimeError(
            f"DMEF's supported runtime is Python 3.11.x; found Python {version}. "
            "Create the environment with `python3.11 -m venv .venv`."
        )
