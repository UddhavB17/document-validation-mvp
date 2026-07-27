from pathlib import Path

import database.db as db
from database.db import get_connection, init_db
from services.mapped_verification import compare_processed_pages, run_mapped_verification
from services.field_verification import verify_name
from services.reviewer import build_reviewer_summary, load_reviewer_summary
from services.verification_manifest import VerificationManifest
from services.company_data_provider import CompanyReferenceData, LocalJsonCompanyDataProvider
from services.document_index_provider import ManualDocumentIndexProvider, compose_verification_manifest


class _FakeDocument:
    def __init__(self, pages: int) -> None:
        self.pages = [object() for _ in range(pages)]

    def __len__(self) -> int:
        return len(self.pages)

    def __getitem__(self, index: int):
        return self.pages[index]

    def close(self) -> None:
        return None


class _DigitalPage:
    def __init__(self, text: str) -> None:
        self.text = text

    def get_text(self) -> str:
        return self.text


def test_shared_pipeline_comparison_matches_case_insensitive_name_and_classifies_source() -> None:
    pages = [{
        "page_number": 1,
        "page_type": "digital",
        "is_readable": True,
        "ocr_text": (
            "INCOME TAX DEPARTMENT\nNAME\nRAMESH KUMAR\n"
            "Permanent Account Number ABCDE1234F"
        ),
        "ocr_confidence": None,
        "document_type": "PAN",
        "classification_confidence": 0.98,
        "extracted_fields": {
            "applicant_name": "RAMESH KUMAR",
            "pan_number": "ABCDE1234F",
            "_structured_llm_classification": {
                "document_type": "PAN",
                "confidence": 0.99,
            },
        },
    }]
    manifest = {
        "loan_id": "MAP-SHARED",
        "reference_data": {
            "primary": {
                "applicant_name": "Ramesh Kumar",
                "pan_number": "ABCDE1234F",
            }
        },
        "documents": [{
            "source_document_id": "file-0001",
            "applicant_role": "primary",
            "document_type": "PAN",
            "pages": [1],
        }],
    }

    result = compare_processed_pages(
        pages,
        manifest,
        source_documents=[{
            "source_document_id": "file-0001",
            "original_filename": "Applicant/KYC/pan.pdf",
            "internal_page_start": 1,
            "internal_page_end": 1,
        }],
    )

    assert result["anomalies"] == []
    assert result["checked_fields"] == 2
    assert result["matched_fields"] == 2
    assert result["source_classifications"] == [{
        "source_document_id": "file-0001",
        "original_filename": "Applicant/KYC/pan.pdf",
        "pages": [1],
        "provided_person_ids": ["primary"],
        "predicted_person_id": "primary",
        "owner_detection_method": "extracted_identity",
        "provided_document_types": ["PAN"],
        "predicted_document_type": "PAN",
        "document_type_votes": {"PAN": 1},
    }]


def test_loan_level_field_checks_run_once_across_fragments() -> None:
    pages = [
        {
            "page_number": 1,
            "page_type": "digital",
            "is_readable": True,
            "ocr_text": "Loan Agreement page 1",
            "document_type": "Loan Agreement",
            "extracted_fields": {},
        },
        {
            "page_number": 2,
            "page_type": "digital",
            "is_readable": True,
            "ocr_text": "Loan Agreement Borrower RAMESH KUMAR Loan Amount 500000",
            "document_type": "Loan Agreement",
            "extracted_fields": {"borrower_name": "RAMESH KUMAR", "loan_amount": "500000"},
        },
        {
            "page_number": 3,
            "page_type": "digital",
            "is_readable": True,
            "ocr_text": "Loan Agreement continuation",
            "document_type": "Loan Agreement",
            "extracted_fields": {},
        },
    ]
    result = compare_processed_pages(
        pages,
        {
            "loan_id": "MAP-LA",
            "reference_data": {
                "primary": {"applicant_name": "Ramesh Kumar", "loan_amount": "500000"},
            },
            "documents": [
                {
                    "source_document_id": "la-1",
                    "applicant_role": "primary",
                    "document_type": "Loan Agreement",
                    "pages": [1],
                },
                {
                    "source_document_id": "la-2",
                    "applicant_role": "primary",
                    "document_type": "Loan Agreement",
                    "pages": [2],
                },
                {
                    "source_document_id": "la-3",
                    "applicant_role": "primary",
                    "document_type": "Loan Agreement",
                    "pages": [3],
                },
            ],
        },
    )

    assert result["anomalies"] == []
    assert result["checked_fields"] == 2
    assert result["matched_fields"] == 2


def test_aadhaar_front_and_back_are_verified_as_one_document_set() -> None:
    pages = [
        {
            "page_number": 1,
            "page_type": "digital",
            "is_readable": True,
            "ocr_text": "Aadhaar Name: RADHA BAI Date of Birth: 01-01-1962",
            "document_type": "Aadhaar",
            "extracted_fields": {"applicant_name": "RADHA BAI", "dob": "1962-01-01"},
        },
        {
            "page_number": 2,
            "page_type": "scanned",
            "is_readable": True,
            "ocr_text": "Address: W/O Ukar Lal Rajasthan 326502",
            "document_type": "Aadhaar",
            "extracted_fields": {"address": "W/O Ukar Lal Rajasthan 326502", "pin_code": "326502"},
        },
    ]
    result = compare_processed_pages(
        pages,
        {
            "reference_data": {
                "coapplicant_2": {
                    "applicant_name": "Radha Bai",
                    "date_of_birth": "1962-01-01",
                    "address": "W/O Ukar Lal Rajasthan 326502",
                    "pin_code": "326502",
                }
            },
            "documents": [
                {"source_document_id": "front", "applicant_role": "coapplicant_2", "document_type": "Aadhaar", "pages": [1]},
                {"source_document_id": "back", "applicant_role": "coapplicant_2", "document_type": "Aadhaar", "pages": [2]},
            ],
        },
    )
    assert result["anomalies"] == []
    assert result["checked_fields"] == 4
    assert result["matched_fields"] == 4


def _application() -> int:
    init_db()
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO applications (loan_id, applicant_name, product_type, branch)
            VALUES ('MAP-001', 'Ramesh Kumar', 'LAP', 'Delhi')
            """
        )
        return int(cursor.lastrowid)


def test_mapped_verification_uses_mapping_and_flags_pan_mismatch(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "mapped.db")
    monkeypatch.setattr("services.mapped_verification.open_pdf", lambda _path: _FakeDocument(20))
    monkeypatch.setattr(
        "services.mapped_verification.convert_page_to_image",
        lambda _page, output: str(output),
    )
    monkeypatch.setattr(
        "services.mapped_verification.run_ocr_on_page",
        lambda path: {
            "ocr_text": (
                "Name: Ramesh Kumar\nPermanent Account Number ZZZZZ9999Z"
                if "page_14" in path
                else "Name: Ramesh Kumar\n1234 5678 9012"
            ),
            "is_readable": True,
            "confidence": 0.96,
        },
    )
    application_id = _application()

    result = run_mapped_verification(
        tmp_path / "loan.pdf",
        application_id,
        {
            "loan_id": "MAP-001",
            "reference_data": {
                "aadhaar_number": "123456789012",
                "pan_number": "ABCDE1234F",
            },
            "documents": [
                {
                    "document_type": "Aadhaar",
                    "pages": [12],
                    "expected_fields": {"aadhaar_number": "123456789012"},
                },
                {
                    "document_type": "PAN",
                    "pages": [14],
                    "expected_fields": {"pan_number": "ABCDE1234F"},
                },
            ],
        },
        output_dir=tmp_path / "processed",
    )

    assert result["mapped_pages_processed"] == 2
    assert result["checked_fields"] == 2
    assert result["matched_fields"] == 1
    assert [item["rule_id"] for item in result["anomalies"]] == ["PAN_NUMBER_MISMATCH"]
    assert result["reviewer_summary"]["overall_status"] == "HIGH_RISK"
    assert result["reviewer_summary"]["pages_to_review"] == [14]
    assert result["reviewer_summary"]["review_items"][0]["expected_masked"] == "******234F"
    assert load_reviewer_summary(application_id) == result["reviewer_summary"]


def test_mapped_verification_uses_embedded_text_without_running_ocr(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "digital.db")
    document = _FakeDocument(1)
    document.pages[0] = _DigitalPage(
        "INCOME TAX DEPARTMENT\nName: Ramesh Kumar\n"
        "Permanent Account Number ABCDE1234F\nDigital PAN document"
    )
    monkeypatch.setattr("services.mapped_verification.open_pdf", lambda _path: document)

    def must_not_run(*_args, **_kwargs):
        raise AssertionError("Digital mapped pages must not be rendered or sent to PaddleOCR")

    monkeypatch.setattr("services.mapped_verification.convert_page_to_image", must_not_run)
    monkeypatch.setattr("services.mapped_verification.run_ocr_on_page", must_not_run)
    application_id = _application()

    result = run_mapped_verification(
        tmp_path / "digital.pdf",
        application_id,
        {
            "loan_id": "MAP-DIGITAL",
            "reference_data": {"pan_number": "ABCDE1234F"},
            "documents": [
                {
                    "document_type": "PAN",
                    "pages": [1],
                    "expected_fields": {"pan_number": "ABCDE1234F"},
                }
            ],
        },
        output_dir=tmp_path / "processed",
    )

    assert result["matched_fields"] == 1
    assert result["digital_pages_processed"] == 1
    assert result["ocr_pages_processed"] == 0
    with get_connection() as connection:
        page = connection.execute(
            """
            SELECT page_type, image_path, detection_method, ocr_confidence
            FROM pages WHERE application_id = ?
            """,
            (application_id,),
        ).fetchone()
    assert dict(page) == {
        "page_type": "digital",
        "image_path": None,
        "detection_method": "provided_mapping_embedded_text",
        "ocr_confidence": 1.0,
    }


def test_reviewer_summary_escalates_many_high_risk_anomalies() -> None:
    anomalies = [
        {
            "rule_id": f"RULE_{number}",
            "severity": "HIGH",
            "page_number": number,
            "reason": "Critical difference",
        }
        for number in (2, 4, 6)
    ]
    summary = build_reviewer_summary(
        total_pages=30,
        anomalies=anomalies,
        checked_fields=5,
        matched_fields=2,
    )

    assert summary["overall_status"] == "FULL_MANUAL_REVIEW"
    assert summary["pages_to_review"] == [2, 4, 6]
    assert "Completely check" in summary["recommendation"]


def test_reviewer_summary_is_clean_without_anomalies() -> None:
    summary = build_reviewer_summary(
        total_pages=10,
        anomalies=[],
        checked_fields=4,
        matched_fields=4,
    )
    assert summary["overall_status"] == "CLEAN"
    assert summary["pages_to_review"] == []


def test_manifest_normalizes_multi_person_contract_and_legacy_contract() -> None:
    current = VerificationManifest.model_validate({
        "loan_id": "MAP-MULTI",
        "people": {
            "primary": {"applicant_name": "Ramesh", "pan_number": "ABCDE1234F"},
            "coapplicant_1": {"applicant_name": "Sita", "pan_number": "FGHIJ5678K"},
        },
        "document_index": [
            {"person_id": "primary", "document_type": "PAN", "pages": [1]},
            {"person_id": "coapplicant_1", "document_type": "PAN", "pages": [2]},
        ],
    })
    assert sorted(current.people) == ["coapplicant_1", "primary"]
    assert current.pipeline_payload()["documents"][1]["applicant_role"] == "coapplicant_1"

    legacy = VerificationManifest.model_validate({
        "loan_id": "MAP-LEGACY",
        "reference_data": {"pan_number": "ABCDE1234F"},
        "documents": [{"document_type": "PAN", "pages": [1]}],
    })
    assert legacy.people["primary"].pan_number == "ABCDE1234F"


def test_manifest_allows_required_document_without_pages_for_missing_check() -> None:
    manifest = VerificationManifest.model_validate({
        "loan_id": "MAP-MISSING",
        "people": {"primary": {"applicant_name": "Ramesh"}},
        "document_index": [
            {"person_id": "primary", "document_type": "PAN", "pages": [1]},
            {"person_id": "primary", "document_type": "Utility Bill", "pages": [], "required": True},
        ],
    })

    assert manifest.document_index[1].pages == []


def test_manifest_allows_automatic_document_identification_without_index() -> None:
    manifest = VerificationManifest.model_validate({
        "loan_id": "MAP-AUTO",
        "people": {"primary": {"applicant_name": "Ramesh Kumar"}},
    })

    assert manifest.document_index == []
    assert manifest.pipeline_payload()["documents"] == []


def test_company_data_and_manual_index_compose_without_pipeline_changes() -> None:
    reference = LocalJsonCompanyDataProvider({
        "loan_id": "MAP-COMPOSE",
        "people": {"primary": {"pan_number": "ABCDE1234F"}},
    }).get_reference_data("MAP-COMPOSE")
    assert isinstance(reference, CompanyReferenceData)
    index = ManualDocumentIndexProvider([
        {"person_id": "primary", "document_type": "PAN", "pages": [3]}
    ]).get_document_index("unused.pdf")

    manifest = compose_verification_manifest(reference, index)

    assert manifest.loan_id == "MAP-COMPOSE"
    assert manifest.document_index[0].pages == [3]
    assert manifest.pipeline_payload()["reference_data"]["primary"]["pan_number"] == "ABCDE1234F"


def test_manifest_rejects_unknown_person_and_conflicting_page_assignment() -> None:
    import pytest

    with pytest.raises(ValueError, match="unknown people"):
        VerificationManifest.model_validate({
            "loan_id": "MAP-BAD-PERSON",
            "people": {"primary": {}},
            "document_index": [
                {"person_id": "coapplicant_1", "document_type": "PAN", "pages": [1]}
            ],
        })

    with pytest.raises(ValueError, match="conflicting mappings"):
        VerificationManifest.model_validate({
            "loan_id": "MAP-BAD-PAGE",
            "people": {"primary": {}, "coapplicant_1": {}},
            "document_index": [
                {"person_id": "primary", "document_type": "PAN", "pages": [1]},
                {"person_id": "coapplicant_1", "document_type": "PAN", "pages": [1]},
            ],
        })


def test_multi_person_verification_checks_every_distinct_occurrence_and_wrong_owner(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "multi.db")
    monkeypatch.setattr("services.mapped_verification.open_pdf", lambda _path: _FakeDocument(4))
    monkeypatch.setattr(
        "services.mapped_verification.convert_page_to_image",
        lambda _page, output: str(output),
    )
    page_text = {
        "page_1": "Name: Ramesh Kumar\n1111 2222 3333",
        "page_2": "Name: Ramesh Kumar\n1111 2222 9999",
        "page_3": "Name: Ramesh Kumar\nABCDE1234F",
        # Co-applicant page accidentally contains the primary applicant's PAN.
        "page_4": "Name: Ramesh Kumar\nABCDE1234F",
    }

    def fake_ocr(path: str) -> dict:
        text = next(value for key, value in page_text.items() if key in path)
        return {"ocr_text": text, "is_readable": True, "confidence": 0.95}

    monkeypatch.setattr("services.mapped_verification.run_ocr_on_page", fake_ocr)
    application_id = _application()
    manifest = VerificationManifest.model_validate({
        "loan_id": "MAP-MULTI",
        "people": {
            "primary": {
                "applicant_name": "Ramesh Kumar",
                "aadhaar_number": "111122223333",
                "pan_number": "ABCDE1234F",
            },
            "coapplicant_1": {
                "applicant_name": "Sita Kumar",
                "pan_number": "FGHIJ5678K",
            },
        },
        "document_index": [
            {
                "person_id": "primary", "document_type": "Aadhaar", "pages": [1, 2],
                "expected_fields": {"aadhaar_number": "111122223333"},
            },
            {
                "person_id": "primary", "document_type": "PAN", "pages": [3],
                "expected_fields": {"pan_number": "ABCDE1234F"},
            },
            {
                "person_id": "coapplicant_1", "document_type": "PAN", "pages": [4],
                "expected_fields": {"pan_number": "FGHIJ5678K"},
            },
        ],
    })

    result = run_mapped_verification(
        tmp_path / "loan.pdf",
        application_id,
        manifest.pipeline_payload(),
        output_dir=tmp_path / "processed",
    )

    assert result["checked_fields"] == 4
    assert result["matched_fields"] == 2
    assert {(item["rule_id"], item["page_number"]) for item in result["anomalies"]} == {
        ("AADHAAR_NUMBER_MISMATCH", 2),
        ("INDEX_MAPPING_SUSPECTED", 4),
    }
    suspected = next(item for item in result["anomalies"] if item["page_number"] == 4)
    assert suspected["person_id"] == "coapplicant_1"
    assert suspected["matched_person_id"] == "primary"
    assert result["people_verification"]["primary"]["status"] == "NEEDS_REVIEW"
    assert result["people_verification"]["coapplicant_1"]["status"] == "NEEDS_REVIEW"
    assert result["reviewer_summary"]["pages_to_review"] == [2, 4]


def test_mapped_verification_flags_missing_required_document_and_checks_utility_bill(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "missing.db")
    monkeypatch.setattr("services.mapped_verification.open_pdf", lambda _path: _FakeDocument(2))
    monkeypatch.setattr(
        "services.mapped_verification.convert_page_to_image",
        lambda _page, output: str(output),
    )
    monkeypatch.setattr(
        "services.mapped_verification.run_ocr_on_page",
        lambda _path: {
            "ocr_text": (
                "Electricity Bill\nConsumer Name: Ramesh Kumar\nService Address\n"
                "12 Market Road\nDelhi 110001"
            ),
            "is_readable": True,
            "confidence": 0.94,
        },
    )
    application_id = _application()
    manifest = VerificationManifest.model_validate({
        "loan_id": "MAP-MISSING",
        "people": {
            "primary": {
                "applicant_name": "Ramesh Kumar",
                "address": "12 Market Road Delhi",
                "pin_code": "110001",
            }
        },
        "document_index": [
            {"person_id": "primary", "document_type": "Utility Bill", "pages": [1]},
            {"person_id": "primary", "document_type": "PAN", "pages": [], "required": True},
        ],
    })

    result = run_mapped_verification(
        tmp_path / "loan.pdf",
        application_id,
        manifest.pipeline_payload(),
        output_dir=tmp_path / "processed",
    )

    assert result["mapped_pages_processed"] == 1
    assert result["checked_fields"] == 3
    assert result["matched_fields"] == 3
    assert [item["rule_id"] for item in result["anomalies"]] == ["DOCUMENT_MISSING"]
    assert result["anomalies"][0]["document_type"] == "PAN"
    assert result["people_verification"]["primary"]["documents"]["Utility Bill"]["status"] == "MATCH"
    assert result["people_verification"]["primary"]["documents"]["PAN"]["status"] == "NEEDS_REVIEW"


def test_name_match_ignores_missing_ocr_whitespace() -> None:
    assert verify_name("PEERULAL", "Peeru Lal").match is True
