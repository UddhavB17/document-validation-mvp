"""Dry-run tests for scripts/smoke_batch.py (owned by ws-j-deploy-smoke).

``--dry-run`` validates arguments and prints the plan without any network
I/O, so these tests never need credentials, docker, or a live API.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "smoke_batch.py"
SMOKE_FIXTURES = ROOT / "tests" / "fixtures" / "smoke"


def _load_smoke_module():  # scripts/ is not a package; load by path.
    spec = importlib.util.spec_from_file_location("smoke_batch", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _pdf_bytes(tag: str) -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), f"smoke dry run {tag}")
    data = doc.tobytes()
    doc.close()
    return data


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=ROOT,
        timeout=60,
    )


def test_dry_run_prints_plan(tmp_path: Path) -> None:
    files_dir = tmp_path / "files"
    files_dir.mkdir()
    (files_dir / "loan-a.pdf").write_bytes(_pdf_bytes("a"))
    (files_dir / "loan-b.pdf").write_bytes(_pdf_bytes("b"))

    completed = _run(
        "--api", "http://localhost:8000",
        "--email", "admin@example.com",
        "--password", "x",
        "--files", str(files_dir),
        "--timeout", "1800",
        "--dry-run",
    )
    assert completed.returncode == 0, completed.stderr
    assert "Smoke plan" in completed.stdout
    assert "POST http://localhost:8000/upload/batch" in completed.stdout
    assert "loan-a.pdf" in completed.stdout
    assert "1800s" in completed.stdout


def test_dry_run_rejects_empty_dir(tmp_path: Path) -> None:
    files_dir = tmp_path / "empty"
    files_dir.mkdir()
    completed = _run(
        "--api", "http://localhost:8000",
        "--email", "admin@example.com",
        "--password", "x",
        "--files", str(files_dir),
        "--dry-run",
    )
    assert completed.returncode != 0
    assert "no .pdf/.zip files" in completed.stderr


def test_dry_run_rejects_bad_api(tmp_path: Path) -> None:
    files_dir = tmp_path / "files"
    files_dir.mkdir()
    (files_dir / "loan-a.pdf").write_bytes(_pdf_bytes("a"))
    completed = _run(
        "--api", "not-a-url",
        "--email", "admin@example.com",
        "--password", "x",
        "--files", str(files_dir),
        "--dry-run",
    )
    assert completed.returncode != 0
    assert "--api must be an http(s) URL" in completed.stderr


def test_smoke_fixtures_dir_has_generated_pdfs() -> None:
    # Checked-in dry-run fixtures: tiny generated one-page PDFs, no loan-file
    # PII. Regenerate with the minimal-PDF writer if ever lost (see git log).
    assert SMOKE_FIXTURES.is_dir(), "tests/fixtures/smoke is missing"
    pdfs = sorted(
        entry
        for entry in SMOKE_FIXTURES.iterdir()
        if entry.is_file() and entry.suffix.lower() in {".pdf", ".zip"}
    )
    assert 1 <= len(pdfs) <= 10, f"expected 1-10 pdf/zip fixtures, got {len(pdfs)}"
    for pdf in pdfs:
        assert pdf.read_bytes()[:5] == b"%PDF-", f"{pdf.name} is not a PDF"


def test_dry_run_with_smoke_fixtures() -> None:
    completed = _run(
        "--api", "http://localhost:8000",
        "--email", "a@b.c",
        "--password", "x",
        "--files", str(SMOKE_FIXTURES),
        "--dry-run",
    )
    assert completed.returncode == 0, completed.stderr
    assert "Smoke plan" in completed.stdout


def test_pipeline_failure_policy() -> None:
    smoke = _load_smoke_module()
    # Terminal failed/cancelled/rejected items warn by default ...
    for status in ("failed", "cancelled", "rejected"):
        assert smoke.pipeline_failure_is_fatal(
            status, timed_out=False, require_clean=False
        ) is False
        # ... and fail only with --require-clean.
        assert smoke.pipeline_failure_is_fatal(
            status, timed_out=False, require_clean=True
        ) is True
    # Timeouts stay fatal either way; completed never fails here.
    assert smoke.pipeline_failure_is_fatal(
        "failed", timed_out=True, require_clean=False
    ) is True
    assert smoke.pipeline_failure_is_fatal(
        "completed", timed_out=False, require_clean=True
    ) is False


@pytest.mark.parametrize("poll_items", [[], [{"application_id": 1, "status": "failed"}]])
def test_live_smoke_does_not_forget_accepted_uploads(monkeypatch, capsys, poll_items):
    import requests

    smoke = _load_smoke_module()

    class Response:
        status_code = 200

        def __init__(self, payload):
            self.payload = payload

        def json(self):
            return self.payload

    class Session:
        headers = {}

        def post(self, url, **kwargs):
            if url.endswith("/auth/login"):
                return Response({"token": "synthetic"})
            return Response({"batch_id": "test", "items": [
                {"application_id": 1, "filename": "loan-a.pdf", "status": "queued"},
                {"application_id": 2, "filename": "loan-b.pdf", "status": "queued"},
            ]})

        def get(self, url, **kwargs):
            return Response({"items": poll_items})

    clock = iter(range(100))
    monkeypatch.setattr(requests, "Session", Session)
    monkeypatch.setattr(smoke.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(smoke.time, "sleep", lambda _: None)
    result = smoke.main([
        "--api", "http://example.test", "--email", "a@b.c", "--password", "x",
        "--files", str(SMOKE_FIXTURES), "--timeout", "2",
    ])
    assert result == 1
    assert "timeout: loan-b.pdf still queued" in capsys.readouterr().out
