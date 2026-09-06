"""PDF input preparation and unsupported-input handling."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import fitz

from services.paths import job_work_dir
from services.pipeline.page_details import _build_db_data_fields, _is_starting_json_db_page
from services.text_extractor import extract_digital_text


def job_source_dir(job_id: int | str) -> Path:
    """Working directory for one job under ``DMEF_JOB_WORK_DIR``."""
    return job_work_dir() / f"job-{job_id}"


def prepare_job_source(application_id: int, job_id: int | str) -> Path:
    """Download the application source PDF from the object store.

    The ``source`` (falling back to ``normalized_pdf``) key is read from
    ``object_refs`` and staged at
    ``DMEF_JOB_WORK_DIR/job-{job_id}/source.pdf``. Callers hand the returned
    path to the existing pipeline code and delete the directory (via
    :func:`cleanup_job_source`) when the pipeline returns, success or failure.
    """
    from services.storage import get_store
    from services.storage.refs import get_ref

    ref = get_ref("applications", application_id, "source") or get_ref(
        "applications", application_id, "normalized_pdf"
    )
    if ref is None:
        raise FileNotFoundError(
            f"No source object recorded for application {application_id}"
        )
    target_dir = job_source_dir(job_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / "source.pdf"
    store = get_store()
    target.write_bytes(store.get(str(ref["storage_key"])))
    return target


def prepare_intake_source(package_id: str, job_id: int | str) -> Path:
    """Download an intake normalized PDF from the object store.

    ZIP/package intake artifacts recorded via ``_store_intake_package`` live
    under ``object_refs`` with ``owner_table='intake_packages'``. The
    ``normalized_pdf`` key is staged at
    ``DMEF_JOB_WORK_DIR/job-{job_id}/source.pdf`` so package jobs resolve the
    same way as single-file uploads.
    """
    from services.storage import get_store
    from services.storage.refs import get_ref

    ref = get_ref("intake_packages", package_id, "normalized_pdf")
    if ref is None:
        raise FileNotFoundError(
            f"No normalized PDF recorded for intake package {package_id}"
        )
    target_dir = job_source_dir(job_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / "source.pdf"
    store = get_store()
    target.write_bytes(store.get(str(ref["storage_key"])))
    return target


def resolve_job_source(
    application_id: int,
    hint_path: str | Path | None,
    job_id: int | str,
    package_id: str | None = None,
) -> Path:
    """Return a local PDF path for the pipeline, preferring the store.

    When the store holds a ``source``/``normalized_pdf`` key it is downloaded
    to the job work dir and that staged path is returned. Store download
    failures propagate (never fall back to a deleted hint path). Only when no
    store reference exists at all is ``hint_path`` (legacy staged file)
    returned; when neither exists ``FileNotFoundError`` is raised.
    """
    from services.storage.refs import get_ref

    ref = get_ref("applications", application_id, "source") or get_ref(
        "applications", application_id, "normalized_pdf"
    )
    if ref is not None:
        # Durable source of truth is the object store. Propagate download
        # errors so callers never hash a deleted upload work dir.
        return prepare_job_source(application_id, job_id)
    if package_id:
        intake_ref = get_ref("intake_packages", package_id, "normalized_pdf")
        if intake_ref is not None:
            return prepare_intake_source(package_id, job_id)
    if hint_path is not None:
        return Path(hint_path)
    raise FileNotFoundError(
        f"No source PDF available for application {application_id}"
    )


def cleanup_job_source(path: str | Path | None) -> None:
    """Delete ``DMEF_JOB_WORK_DIR``-scoped pipeline inputs.

    Only directories inside the configured job work dir are removed, so
    legacy paths (``data/uploads``, test tmp dirs) are never deleted here.
    """
    if path is None:
        return
    candidate = Path(path)
    if candidate.is_dir():
        root = candidate
    else:
        root = candidate.parent
    try:
        work_root = job_work_dir().resolve()
    except Exception:
        return
    try:
        resolved = root.resolve()
    except Exception:
        return
    if resolved == work_root or work_root in resolved.parents:
        shutil.rmtree(resolved, ignore_errors=True)



def _mapped_ground_truth(
    manifest: dict[str, Any],
    system_data: dict[str, Any] | None,
) -> dict[str, Any]:
    """Flatten primary trusted data for checklist/report compatibility."""
    reference_data = manifest.get("reference_data") or {}
    primary = reference_data.get("primary") if isinstance(reference_data, dict) else {}
    primary = primary if isinstance(primary, dict) else {}
    return {
        **{
            key: value
            for key, value in manifest.items()
            if key not in {"documents", "reference_data"}
        },
        **(system_data or {}),
        **primary,
        "loan_id": manifest.get("loan_id") or (system_data or {}).get("loan_id"),
        "product_type": manifest.get("product_type")
        or (system_data or {}).get("product_type")
        or "LAP",
        "reference_data": reference_data,
    }


def _extract_digital_text_by_page(pdf_path: Path) -> dict[int, str]:
    doc = fitz.open(pdf_path)
    try:
        return {
            page_number: text
            for page_number, page in enumerate(doc, start=1)
            if (text := extract_digital_text(page))
        }
    finally:
        doc.close()


def _checklist_processing_metadata(progress_snapshot: dict[str, Any]) -> dict[str, int]:
    completed_pages = progress_snapshot.get("completed_pages") or []
    ocr_time_ms = int(
        sum(float(page.get("elapsed_seconds") or 0) for page in completed_pages) * 1000
    )
    return {
        "ocr_time_ms": ocr_time_ms,
        "classification_time_ms": 0,
        "narration_time_ms": 0,
    }


def _build_unsupported_page_records(
    page_structure: list[dict[str, Any]],
    digital_text_by_page: dict[int, str],
) -> list[dict[str, Any]]:
    pages: list[dict[str, Any]] = []
    for page_info in page_structure:
        page_number = int(page_info["page_number"])
        page_type = page_info["page_type"]
        text = digital_text_by_page.get(page_number, "")
        is_db_data = page_type == "digital" and _is_starting_json_db_page(
            page_number=page_number, text=text
        )
        document_type = "DB Data" if is_db_data else "Unknown"
        pages.append(
            {
                "page_number": page_number,
                "page_type": page_type,
                "image_path": page_info.get("image_path"),
                "is_readable": bool(text),
                "ocr_text": text,
                "ocr_confidence": None,
                "document_type": document_type,
                "classification_confidence": 1.0 if is_db_data else 0.0,
                "detection_method": "db_data" if is_db_data else "unknown",
                "detected_page_number": page_number if is_db_data else None,
                "extracted_fields": _build_db_data_fields(page_number=page_number, text=text)
                if is_db_data
                else {},
            }
        )
    return pages
