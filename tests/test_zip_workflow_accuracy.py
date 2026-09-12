"""Fixed-evidence ZIP regressions: source context must survive cached processing."""

from copy import deepcopy
from zipfile import ZipFile

import fitz
import pytest

from services.automatic_document_index import build_automatic_document_index
from services.evidence_resolution import resolve_trusted_evidence
from services.mapped_verification import compare_processed_pages
from services.pipeline.page_processing import _build_page_records
from services.zip_package import normalize_zip_package


@pytest.fixture(autouse=True)
def no_provider_calls(monkeypatch):
    monkeypatch.setattr(
        "services.pipeline.page_processing.create_llm_classifier_budget", lambda: None
    )


def _page(number, document_type, text="", detected=1):
    return {
        "page_number": number,
        "page_type": "digital",
        "document_type": document_type,
        "classification_confidence": 0.95 if document_type != "Unknown" else 0.0,
        "ocr_text": text,
        "is_readable": True,
        "detection_method": "detected" if number == detected else "unknown",
        "detected_page_number": detected,
        "extracted_fields": {},
    }


def _sources():
    return [
        {
            "source_document_id": f"file-{number:04d}",
            "original_filename": f"source-{number}.pdf",
            "internal_page_start": number,
            "internal_page_end": number,
        }
        for number in range(1, 4)
    ]


def test_resumed_zip_restores_source_boundaries_before_smoothing():
    # Database checkpoint rows do not contain top-level source_document_id.
    # An unrelated source between two statements must never become a statement.
    checkpoints = [
        _page(1, "Bank Statement", "Account Statement Debit Credit Balance"),
        _page(2, "Unknown", "Unidentified attachment"),
        _page(3, "Bank Statement", "Account Statement Debit Credit Balance", detected=3),
    ]
    original = deepcopy(checkpoints)
    pages = _build_page_records(
        [{"page_number": n, "page_type": "digital"} for n in range(1, 4)],
        {},
        source_documents=_sources(),
        checkpoint_pages=checkpoints,
    )
    assert [page["document_type"] for page in pages] == [
        "Bank Statement",
        "Unknown",
        "Bank Statement",
    ]
    assert [page["source_document_id"] for page in pages] == ["file-0001", "file-0002", "file-0003"]
    assert checkpoints == original


def test_cached_refresh_derives_boundaries_from_source_inventory(monkeypatch):
    monkeypatch.setattr(
        "services.pipeline.page_processing.classify_page_text",
        lambda *args, **kwargs: ({"document_type": "None", "confidence": 0.0}, {"source": "rules"}),
    )
    checkpoints = [
        _page(1, "Bank Statement", "Account Statement Debit Credit Balance"),
        _page(2, "Unknown", "Continuation details"),
    ]
    # First checkpoint is strong cached evidence, second belongs to a new file.
    checkpoints[0]["meta"] = {
        "_classification": {
            "source": "llm",
            "llm_document_type": "Bank Statement",
            "llm_confidence": 0.95,
        }
    }
    pages = _build_page_records(
        [{"page_number": n, "page_type": "digital"} for n in (1, 2)],
        {},
        source_documents=_sources()[:2],
        checkpoint_pages=checkpoints,
        refresh_cached_ocr=True,
    )
    assert pages[0]["document_type"] == "Bank Statement"
    assert pages[1]["document_type"] == "Unknown"
    assert pages[1]["source_document_id"] == "file-0002"


@pytest.mark.parametrize("cached", [False, True])
def test_zip_and_merged_pdf_preserve_same_borrowers_and_real_discrepancy(tmp_path, cached):
    # Synthetic benchmark: identical page text, two borrowers, one deliberate
    # DOB discrepancy. Packaging must change neither the owner nor the finding.
    texts = [
        "INCOME TAX DEPARTMENT\nGOVT. OF INDIA\nNAME\nRAVI KUMAR\nFATHER NAME\n"
        "RAM KUMAR\nDATE OF BIRTH\n01/01/1980\nPermanent Account Number\nTSTPA7009Z",
        "INCOME TAX DEPARTMENT\nGOVT. OF INDIA\nNAME\nRITA SHARMA\nFATHER NAME\n"
        "MOHAN SHARMA\nDATE OF BIRTH\n02/02/1982\nPermanent Account Number\nTSTPB7010Z",
    ]
    archive_path = tmp_path / "original-documents.zip"
    with ZipFile(archive_path, "w") as archive:
        for n, text in enumerate(texts, start=1):
            with fitz.open() as document:
                document.new_page().insert_text((72, 72), text)
                archive.writestr(f"card-{n}.pdf", document.tobytes())
    normalized = normalize_zip_package(archive_path, tmp_path / "package")
    assert [
        (s["internal_page_start"], s["internal_page_end"]) for s in normalized["documents"]
    ] == [(1, 1), (2, 2)]
    with fitz.open(normalized["normalized_pdf_path"]) as document:
        fixed_text = {n + 1: page.get_text() for n, page in enumerate(document)}
    people = {
        "primary": {
            "applicant_name": "RAVI KUMAR",
            "pan_number": "TSTPA7009Z",
            "date_of_birth": "1980-01-01",
        },
        "coapplicant_1": {
            "applicant_name": "RITA SHARMA",
            "pan_number": "TSTPB7010Z",
            "date_of_birth": "1983-02-02",
        },
    }
    for source_documents in (None, normalized["documents"]):
        structure = [
            {"page_number": n, "page_type": "digital", "is_readable": True} for n in fixed_text
        ]
        pages = _build_page_records(structure, fixed_text, source_documents=source_documents)
        if cached:
            # Match the saved checkpoint shape: private metadata survives, but
            # source context is restored from the ZIP inventory on resume.
            checkpoints = [
                {k: v for k, v in p.items() if not k.startswith("source_")} for p in pages
            ]
            pages = _build_page_records(
                structure,
                fixed_text,
                source_documents=source_documents,
                checkpoint_pages=checkpoints,
            )
        resolve_trusted_evidence(pages, people, source_documents=source_documents)
        index = build_automatic_document_index(pages, people, source_documents=source_documents)
        assert [
            (d["document_type"], d["pages"], d["applicant_role"]) for d in index["documents"]
        ] == [("PAN", [1], "primary"), ("PAN", [2], "coapplicant_1")]
        result = compare_processed_pages(
            pages,
            {"reference_data": people, "documents": index["documents"]},
            source_documents=source_documents,
        )
        assert [
            (a["rule_id"], a["person_id"], a["expected_value"], a["found_value"])
            for a in result["anomalies"]
        ] == [("DATE_OF_BIRTH_MISMATCH", "coapplicant_1", "1983-02-02", "1982-02-02")]
        assert [p["ocr_text"] for p in pages] == list(fixed_text.values())
