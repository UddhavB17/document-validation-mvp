"""Dry-run tests for scripts/smoke_batch.py (owned by ws-j-deploy-smoke).

``--dry-run`` validates arguments and prints the plan without any network
I/O, so these tests never need credentials, docker, or a live API.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "smoke_batch.py"


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
