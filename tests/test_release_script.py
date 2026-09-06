"""Tests for scripts/release.sh placeholder substitution (owned by fx-deploy).

``release.sh`` once used ``sed -e ":TAG"":${TAG}g"`` — a sed *label*, not a
substitution — so rendered images kept the literal ``:TAG``. These tests run
``bash scripts/release.sh --dry-run`` (no alembic, gcloud, docker, network,
or credentials) and assert the tag renders as ``:v1.2.3``, not ``:TAG``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
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


def _fake_release_tools(
    tmp_path: Path, health: dict
) -> tuple[Path, subprocess.CompletedProcess[str]]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    log = tmp_path / "gcloud.log"
    gcloud = fake_bin / "gcloud"
    gcloud.write_text(
        "#!/usr/bin/env bash\n"
        'printf \'%s\\n\' "$*" >> "$GCLOUD_LOG"\n'
        'if [[ "$*" == *"services describe dmef-api"* ]]; then\n'
        "  printf 'https://api.example.test\\n'\n"
        "fi\n",
        encoding="utf-8",
    )
    curl = fake_bin / "curl"
    curl.write_text(
        "#!/usr/bin/env bash\nprintf '%s\\n' \"$HEALTH_RESPONSE\"\n",
        encoding="utf-8",
    )
    alembic = fake_bin / "alembic"
    alembic.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    python = fake_bin / "python"
    python.symlink_to(sys.executable)
    for executable in (gcloud, curl, alembic):
        executable.chmod(0o755)

    env = {
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "GCLOUD_LOG": str(log),
        "HEALTH_RESPONSE": json.dumps(health),
        "DATABASE_URL": "postgresql://operator:placeholder@localhost/dmef?sslmode=require",
        "PROJECT_ID": "test-project",
        "REGION": "asia-south1",
        "TAG": "v1.2.3",
        "FRONTEND_HOST": "frontend.example.test",
        "SKIP_MIGRATE": "1",
        "DMEF_HEALTH_ATTEMPTS": "1",
        "DMEF_HEALTH_RETRY_SECONDS": "0",
    }
    completed = _run(env)
    return log, completed


@needs_bash
def test_release_makes_api_and_frontend_public_but_not_worker(tmp_path) -> None:
    log, completed = _fake_release_tools(
        tmp_path,
        {
            "status": "ok",
            "database": "ok",
            "storage": "ok",
            "worker": {"status": "ok"},
        },
    )

    assert completed.returncode == 0, completed.stderr
    commands = log.read_text(encoding="utf-8").splitlines()
    assert any(
        "services update dmef-api" in command and "--no-invoker-iam-check" in command
        for command in commands
    )
    assert any(
        "deploy dmef-frontend" in command and "--allow-unauthenticated" in command
        for command in commands
    )
    worker = next(command for command in commands if "worker.yaml" in command)
    assert "allow-unauthenticated" not in worker
    assert "no-invoker-iam-check" not in worker


@needs_bash
def test_release_rejects_degraded_health(tmp_path) -> None:
    _, completed = _fake_release_tools(
        tmp_path,
        {
            "status": "degraded",
            "database": "ok",
            "storage": "ok",
            "worker": {"status": "stale"},
        },
    )

    assert completed.returncode != 0
    assert "worker did not become healthy" in completed.stderr


def test_scheduler_uses_dedicated_header_without_oidc() -> None:
    manifest = (ROOT / "deploy" / "scheduler" / "retention.yaml").read_text(encoding="utf-8")
    api_manifest = (ROOT / "deploy" / "cloudrun" / "api.yaml").read_text(encoding="utf-8")

    assert "X-DMEF-Scheduler-Token: DMEF_SCHEDULER_TOKEN_VALUE" in manifest
    assert "oidcToken:" not in manifest
    assert "\n      Authorization:" not in manifest
    assert "name: DMEF_SCHEDULER_TOKEN" in api_manifest
    assert "name: dmef-scheduler-token" in api_manifest
