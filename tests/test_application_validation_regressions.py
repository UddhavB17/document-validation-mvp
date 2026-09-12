"""Regressions from comparing merged-PDF validation with the local ZIP run."""

import pytest

import database.db as db
from services.automatic_document_index import build_automatic_document_index
from services.consistency_checks import _matches
from services.field_extractor import extract_fields
from services.field_verification import verify_address
from services.person_names import is_person_name_candidate
from services.pipeline.classification import (
    _assign_sequential_document_type,
    _smooth_page_classifications,
)
from services.pipeline.page_processing import _refresh_page_from_cached_ocr
from services.pipeline.persistence import _load_page_checkpoints, _save_pages


@pytest.mark.parametrize(
    ("previous", "detected", "text"),
    [
        (
            "CRIF Report",
            "CIBIL Report",
            "CIBIL COMBO REPORT\nCONSUMER NAME: SAMPLE KUMAR\nScore 633",
        ),
        (
            "CIBIL Report",
            "CRIF Report",
            "Credit Information™Report\nPROV2\nFor SAMPLE KUMAR\nCHM Ref #:\nCRIF HM Score(S): 510",
        ),
        (
            "Loan Agreement",
            "Bank Statement",
            "Statement of INDIAN BANK Account No: XXXXX12345 for the period (From: 22-01-2026 To: 21-07-2026)\nCUSTOMER NAME\nSample Kumar\nKYC COMPLIANCE\nFacility UNKNOWN\nTransactions Debit Credit Balance",
        ),
        (
            "Bank Statement",
            "Bank Statement",
            "PATRON LEASING & FINANCE PVT. LTD.\nLoan Account Statement for : LAP0000123 (Mr SAMPLE KUMAR)\nLoan Detail:\nDebit Credit Balance",
        ),
    ],
)
def test_explicit_document_cover_ends_previous_run(previous, detected, text):
    result = _assign_sequential_document_type(
        page_number=6,
        text=text,
        classification={"document_type": detected, "confidence": 0.97},
        current_type=previous,
        current_confidence=1.0,
        current_detected_page=1,
    )
    assert result["document_type"] == detected
    assert result["detected_page_number"] == 6
    assert result["detection_method"] == "detected"


def test_shared_father_does_not_hide_a_different_full_address():
    expected = "S/O Ram Kumar, 33 Jyotiba Nagar, Jaipur Rajasthan 302027"
    observed = "S/O Ram Kumar, Bikrampur Khojpur Kasganj Uttar Pradesh 207245"
    assert not _matches("address", observed, expected)
    assert not verify_address(observed, expected).match
    assert _matches("address", observed, "S/O Ram Kumar")
    assert verify_address(observed, "S/O Ram Kumar").match


def test_lender_statement_uses_named_subject_in_title():
    fields = extract_fields(
        "Bank Statement",
        "Loan Account Statement for : LAP0000123 (Mr SAMPLE KUMAR)\n"
        "Loan Detail:\nApplication No:\nAPP123\n"
        "Customer Detail:\n# Name\nType\nGender/Age\n"
        "1 SAMPLE KUMAR\nBorrower\nDebit Credit Balance",
    )
    assert fields["account_holder_name"] == "SAMPLE KUMAR"
    assert not is_person_name_candidate("Loan Detail")


def test_final_provenance_survives_an_earlier_ocr_meta_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "provenance.db")
    db.init_db()
    with db.get_connection() as connection:
        application_id = connection.execute(
            "INSERT INTO applications (loan_id) VALUES (?) RETURNING id", ("META-TEST",)
        ).fetchone()["id"]
    page = {
        "page_number": 1,
        "page_type": "digital",
        "document_type": "PAN",
        "meta": {"_classification": {"source": "rules"}, "_ownership": {"person_id": "unassigned"}},
        "extracted_fields": {
            "applicant_name": "Sample Kumar",
            "_ownership": {"person_id": "coapplicant_1", "evidence": ["document_index"]},
            "_document_extraction": {"document_id": "doc-6"},
        },
    }
    _save_pages(application_id, [page])
    restored = _load_page_checkpoints(application_id)[0]
    persisted = restored["meta"]
    assert persisted["_ownership"]["person_id"] == "coapplicant_1"
    assert persisted["_document_extraction"]["document_id"] == "doc-6"
    assert persisted["_classification"] == {"source": "rules"}
    assert "applicant_name" not in persisted
    assert restored["extracted_fields"]["_ownership"]["person_id"] == "coapplicant_1"


def test_cibil_combo_reports_for_different_borrowers_are_not_merged():
    pages = [
        {
            "page_number": n,
            "detected_page_number": n,
            "document_type": "CIBIL Report",
            "classification_confidence": 1.0,
            "ocr_text": f"CIBIL COMBO REPORT\nCONSUMER NAME:\n{name}\nCONTROL NUMBER:\n{n}",
            "extracted_fields": {"applicant_name": name, "cibil_score": score},
        }
        for n, name, score in [(1, "Ravi Kumar", "591"), (2, "Rita Sharma", "633")]
    ]
    index = build_automatic_document_index(
        pages,
        {
            "primary": {"applicant_name": "Ravi Kumar"},
            "coapplicant_1": {"applicant_name": "Rita Sharma"},
        },
    )
    assert [(d["applicant_role"], d["pages"]) for d in index["documents"]] == [
        ("primary", [1]),
        ("coapplicant_1", [2]),
    ]


def test_smoothing_preserves_explicit_kfs_inside_agreement_packet():
    pages = [
        {"page_number": 1, "document_type": "Loan Agreement", "extracted_fields": {}},
        {
            "page_number": 2,
            "document_type": "KFS",
            "extracted_fields": {},
            "ocr_text": "Borrower and lender agree.\nKEY FACT STATEMENT (KFS)\nPART 1 Interest Rate Fees Charges\nSanctioned Loan Amount",
        },
        {"page_number": 3, "document_type": "Loan Agreement", "extracted_fields": {}},
    ]
    assert _smooth_page_classifications(pages, None, 3)[1]["document_type"] == "KFS"


def test_bank_period_uses_explicit_header_not_first_page_transactions():
    fields = extract_fields(
        "Bank Statement",
        "Statement of INDIAN BANK Account No: XXXXX12345 for the period "
        "(From: 22-01-2026 To: 21-07-2026)\n"
        "TRANSACTIONS\nTransaction Date\nDebit Credit Balance\n22-01-2026\n25-01-2026",
    )
    assert fields["statement_period_start"] == "2026-01-22"
    assert fields["statement_period_end"] == "2026-07-21"


def test_kfs_disbursement_question_is_not_an_agreement_heading():
    result = _assign_sequential_document_type(
        page_number=2,
        text="1.\nDisbursement in Stages or 100% upfront.\n2.\n"
        "If It is stage wise, mention the clause of the\n"
        "loan agreement having relevant details.\nLoan Terms (Months)\n"
        "Frequency Of EPIs\nInterest rate\n120\n23.00 Fixed",
        classification={"document_type": "Loan Agreement", "confidence": 1.0},
        current_type="KFS",
        current_confidence=1.0,
        current_detected_page=1,
    )
    assert result["document_type"] == "KFS"


def test_pan_birth_date_survives_damaged_english_label():
    fields = extract_fields(
        "PAN",
        "INCOME TAX DEPARTMENT\nPermanent Account Number Card\n"
        "ABCDE1234F\nName\nSAMPLE KUMAR\nजन्म की रीख (Dote\n22/12/1979",
    )
    assert fields["dob"] == "1979-12-22"


@pytest.mark.parametrize(
    ("cached_type", "cached_source", "rule_type", "rule_confidence", "expected"),
    [
        ("Gift Deed", "llm", "None", 0.0, "Gift Deed"),
        ("Gift Deed", "llm", "PAN", 1.0, "PAN"),
        ("Aadhaar", "llm", "None", 0.0, "Unknown"),
        ("Gift Deed", "rules", "None", 0.0, "Unknown"),
    ],
)
def test_cached_refresh_retains_accepted_model_evidence_without_overriding_rules(
    monkeypatch, cached_type, cached_source, rule_type, rule_confidence, expected
):
    monkeypatch.setattr(
        "services.pipeline.page_processing.classify_page_text",
        lambda *_args, **_kwargs: (
            {"document_type": rule_type, "confidence": rule_confidence},
            {"source": "rules"},
        ),
    )
    checkpoint = {
        "page_number": 1,
        "page_type": "digital",
        "document_type": cached_type,
        "ocr_text": "The donor transfers this property to the donee.",
        "extracted_fields": {},
        "meta": {
            "_classification": {
                "source": cached_source,
                "llm_document_type": cached_type,
                "llm_confidence": 0.9,
            }
        },
    }
    refreshed = _refresh_page_from_cached_ocr(
        checkpoint,
        current_type="Unknown",
        current_confidence=0.0,
        current_detected_page=None,
        source_documents=[],
    )
    assert refreshed["document_type"] == expected
    assert refreshed["ocr_text"] == checkpoint["ocr_text"]
    if expected == "Gift Deed":
        assert refreshed["meta"]["_classification"]["cached_llm_reused"] is True
