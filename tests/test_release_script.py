"""Tests for scripts/release.sh placeholder substitution (owned by fx-deploy).

``release.sh`` once used ``sed -e ":TAG"":${TAG}g"`` — a sed *label*, not a
substitution — so rendered images kept the literal ``:TAG``. These tests run
``bash scripts/release.sh --dry-run`` (no alembic, gcloud, docker, network,
or credentials) and assert the tag renders as ``:v1.2.3``, not ``:TAG``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "release.sh"

needs_bash = pytest.mark.skipif(shutil.which("bash") is None, reason="bash not found")


def _run(extra_env: dict[str, str] | None = None, *args: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=ROOT,
        env=env,
        timeout=60,
    )


@needs_bash
def test_release_dry_run_renders_tag() -> None:
    completed = _run(
        {"PROJECT_ID": "my-proj", "REGION": "asia-south1", "TAG": "v1.2.3"},
        "--dry-run",
    )
    assert completed.returncode == 0, completed.stderr
    assert "asia-south1-docker.pkg.dev/my-proj/dmef/api:v1.2.3" in completed.stdout
    assert "asia-south1-docker.pkg.dev/my-proj/dmef/frontend:v1.2.3" in completed.stdout
    assert ":TAG" not in completed.stdout
    assert "PROJECT_ID" not in completed.stdout


@needs_bash
def test_release_dry_run_needs_no_credentials() -> None:
    env = dict(os.environ)
    for key in ("PROJECT_ID", "REGION", "TAG", "DATABASE_URL", "FRONTEND_HOST", "API_HOST"):
        env.pop(key, None)
    completed = subprocess.run(
        ["bash", str(SCRIPT), "--dry-run"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        env=env,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    assert "dry-run OK" in completed.stdout


@needs_bash
def test_release_rejects_unknown_arg() -> None:
    completed = _run(None, "--bogus-flag")
    assert completed.returncode != 0
