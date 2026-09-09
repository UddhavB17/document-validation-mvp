"""Workdir lifetime for ``run_pipeline`` (direct/offline and worker runs).

Direct runs without a job id must render page images into a unique temporary
directory under ``DMEF_JOB_WORK_DIR`` — never into the caller's output dir —
and remove it on success and on failure, leaving the source PDF and the
output dir intact. Worker runs keep the stable ``{root}/{job_id}`` dir.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import database.db as db
from database.db import get_connection, init_db


def _create_application_pdf(path: Path) -> None:
    fitz = pytest.importorskip("fitz")
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text(
        (72, 72),
        "Loan Application Form\n"
        "Applicant Name: Ramesh Kumar\n"
        "Loan Amount: Rs. 500000\n"
        "Product Type: LAP\n"
        "Address: 12 Market Road Delhi\n"
        "This digital page contains enough selectable text for processing.",
    )
    doc.save(path)
    doc.close()


@pytest.fixture
def pipeline_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "dmef.db")
    monkeypatch.setenv("DMEF_STORAGE_BACKEND", "local")
    monkeypatch.setenv("DMEF_LOCAL_STORE_DIR", str(tmp_path / "store"))
    work_root = tmp_path / "jobs"
    output_dir = tmp_path / "processed"
    monkeypatch.setenv("DMEF_JOB_WORK_DIR", str(work_root))
    monkeypatch.setenv("PAGE_OUTPUT_DIR", str(tmp_path / "pagedir"))
    import services.report_generator as report_generator

    monkeypatch.setattr(report_generator, "REPORTS_DIR", tmp_path / "reports")
    init_db()
    return {"work_root": work_root, "output_dir": output_dir, "tmp": tmp_path}


def _insert_application(pdf_path: Path) -> int:
    with get_connection() as connection:
        row = connection.execute(
            """
            INSERT INTO applications (loan_id, applicant_name, product_type, branch)
            VALUES (?, ?, ?, ?)
            RETURNING id
            """,
            ("LAP-WORKDIR-001", "Ramesh Kumar", "LAP", "Delhi"),
        ).fetchone()
        application_id = int(row["id"])
        connection.execute(
            """
            INSERT INTO uploaded_files (
                application_id, file_path, original_filename, file_size_kb,
                total_pages, digital_pages, scanned_pages
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (application_id, str(pdf_path), "application.pdf", 1.0, 0, 0, 0),
        )
    return application_id


def _spy_on_renders(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    import services.pipeline.orchestrator as orchestrator
    from services.pdf_processor import process_pdf_structure as real_process

    seen: list[Path] = []

    def spy(pdf_path, image_output_dir, *args, **kwargs):
        seen.append(Path(image_output_dir))
        return real_process(pdf_path, image_output_dir, *args, **kwargs)

    monkeypatch.setattr(orchestrator, "process_pdf_structure", spy)
    return seen


def _pngs_under(path: Path) -> list[Path]:
    if not path.exists():
        return []
    return sorted(path.rglob("*.png"))


def _prepare_output_dir(output_dir: Path) -> Path:
    """Pre-existing caller dir with a sentinel; runs must leave it intact."""
    output_dir.mkdir(parents=True, exist_ok=True)
    sentinel = output_dir / "caller-sentinel.txt"
    sentinel.write_text("caller data", encoding="utf-8")
    return sentinel


def test_no_job_run_uses_temp_workdir_and_cleans_up(
    pipeline_env: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    from services.pipeline import run_pipeline

    work_root = pipeline_env["work_root"]
    output_dir = pipeline_env["output_dir"]
    sentinel = _prepare_output_dir(output_dir)
    pdf_path = pipeline_env["tmp"] / "application.pdf"
    _create_application_pdf(pdf_path)
    application_id = _insert_application(pdf_path)
    seen = _spy_on_renders(monkeypatch)

    result = run_pipeline(
        pdf_path,
        application_id,
        output_dir=output_dir,
        system_data={
            "loan_id": "LAP-WORKDIR-001",
            "applicant_name": "Ramesh Kumar",
            "product_type": "LAP",
            "branch": "Delhi",
        },
        product_type="LAP",
        generate_llm_summary=False,
    )

    assert result["pipeline_status"] == "completed"
    # Real rendering happened, but into the temp work dir, not the output dir.
    assert len(seen) == 1
    work_dir = seen[0].parent
    assert work_dir.parent == work_root
    assert work_dir.name.startswith("offline-")
    assert work_dir != output_dir
    assert not work_dir.exists()  # cleaned up on success
    assert list(work_root.iterdir()) == []  # nothing left behind
    assert _pngs_under(output_dir) == []  # no durable page images
    assert pdf_path.exists()  # source PDF untouched
    assert sentinel.read_text(encoding="utf-8") == "caller data"  # output intact


def test_no_job_run_cleans_up_on_failure(
    pipeline_env: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    import services.pipeline.orchestrator as orchestrator
    from services.pipeline import run_pipeline

    work_root = pipeline_env["work_root"]
    output_dir = pipeline_env["output_dir"]
    sentinel = _prepare_output_dir(output_dir)
    pdf_path = pipeline_env["tmp"] / "application.pdf"
    _create_application_pdf(pdf_path)
    application_id = _insert_application(pdf_path)
    seen = _spy_on_renders(monkeypatch)

    def explode(*_args, **_kwargs):
        raise RuntimeError("simulated persist failure")

    monkeypatch.setattr(orchestrator, "_save_pages", explode)

    with pytest.raises(RuntimeError, match="simulated persist failure"):
        run_pipeline(
            pdf_path,
            application_id,
            output_dir=output_dir,
            system_data={"loan_id": "LAP-WORKDIR-001"},
            product_type="LAP",
            generate_llm_summary=False,
        )

    # Rendering really started (images on disk mid-run) yet everything was
    # removed by the finally cleanup.
    assert len(seen) == 1
    assert seen[0].parent.parent == work_root
    assert list(work_root.iterdir()) == []
    assert _pngs_under(output_dir) == []
    assert pdf_path.exists()
    assert sentinel.read_text(encoding="utf-8") == "caller data"


def test_job_run_keeps_stable_per_job_workdir(
    pipeline_env: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Worker behaviour is preserved: ``{root}/{job_id}``, removed after."""
    from services.pipeline import run_pipeline

    work_root = pipeline_env["work_root"]
    output_dir = pipeline_env["output_dir"]
    pdf_path = pipeline_env["tmp"] / "application.pdf"
    _create_application_pdf(pdf_path)
    application_id = _insert_application(pdf_path)
    seen = _spy_on_renders(monkeypatch)
    with get_connection() as connection:
        job_id = int(
            connection.execute(
                """
                INSERT INTO pipeline_jobs (application_id, job_type, status, created_at)
                VALUES (?, ?, ?, ?)
                RETURNING id
                """,
                (application_id, "pdf_pipeline", "running", "2026-09-04 12:00:00"),
            ).fetchone()["id"]
        )

    result = run_pipeline(
        pdf_path,
        application_id,
        output_dir=output_dir,
        system_data={"loan_id": "LAP-WORKDIR-001"},
        product_type="LAP",
        generate_llm_summary=False,
        job_id=job_id,
    )

    assert result["pipeline_status"] == "completed"
    assert len(seen) == 1
    assert seen[0].parent == work_root / str(job_id)
    assert not (work_root / str(job_id)).exists()
    assert _pngs_under(output_dir) == []
    assert pdf_path.exists()
