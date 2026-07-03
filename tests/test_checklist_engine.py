from datetime import datetime, timedelta

from services.checklist_engine import (
    check_date_range,
    check_field_match,
    check_presence_any,
    evaluate_checklist,
    run_checks,
)
from services.checklist_service import get_ai_checkable_items, get_human_review_items


def test_evaluate_checklist_flags_missing_documents() -> None:
    checklist = {"required_documents": ["PAN", "Aadhaar"]}
    extracted_documents = {"PAN": {}}

    assert evaluate_checklist(checklist, extracted_documents) == [
        {"document": "Aadhaar", "issue": "missing"}
    ]


def test_presence_any_passes_with_aadhaar() -> None:
    result = check_presence_any([{"document_type": "Aadhaar"}], ["Aadhaar", "Voter ID"])
    assert result["passed"] is True


def test_technical_report_satisfies_technical_clearance_presence() -> None:
    pages = [
        {
            "page_number": 490,
            "document_type": "Technical Report",
            "page_type": "digital",
            "classification_confidence": 1.0,
            "ocr_text": "MS FINCAP PVT. LTD. TECHNICAL VALUATION",
        }
    ]

    anomalies = run_checks(pages, {}, {}, "LAP")

    assert not any(anomaly["rule_id"] == "MISSING_DOC_S38" for anomaly in anomalies)


def test_legal_title_evidence_satisfies_legal_clearance_presence() -> None:
    pages = [
        {
            "page_number": 82,
            "document_type": "Sanction Letter",
            "page_type": "digital",
            "classification_confidence": 1.0,
            "ocr_text": "property has a clear, marketable, and unencumbered title for security",
        }
    ]

    anomalies = run_checks(pages, {}, {}, "LAP")

    assert not any(anomaly["rule_id"] == "MISSING_DOC_S37" for anomaly in anomalies)


def test_presence_any_fails_when_none_found() -> None:
    result = check_presence_any([{"document_type": "Bank Statement"}], ["Aadhaar", "Voter ID"])
    assert result["passed"] is False


def test_field_match_loan_amount_exact() -> None:
    assert check_field_match({"loan_amount": "500000"}, {"loan_amount": "500000"}, ["loan_amount"]) == []


def test_field_match_loan_amount_mismatch() -> None:
    result = check_field_match({"loan_amount": "600000"}, {"loan_amount": "500000"}, ["loan_amount"])
    assert result[0]["field"] == "loan_amount"


def test_field_match_pan_case_insensitive() -> None:
    assert check_field_match({"pan_number": "abcde1234f"}, {"pan_number": "ABCDE1234F"}, ["pan_number"]) == []


def test_date_range_bank_stmt_recent() -> None:
    recent = (datetime.now() - timedelta(days=30)).date().isoformat()
    assert check_date_range({"statement_period_end": recent}, 3)["passed"] is True


def test_date_range_bank_stmt_old() -> None:
    old = (datetime.now() - timedelta(days=180)).date().isoformat()
    assert check_date_range({"statement_period_end": old}, 3)["passed"] is False


def test_missing_pan() -> None:
    anomalies = run_checks([], {}, {}, "LAP")
    assert any(anomaly["rule_id"] == "MISSING_DOC_S7" for anomaly in anomalies)


def test_physical_only_items_are_manual_review_not_ai_missing() -> None:
    ai_snos = {item["s_no"] for item in get_ai_checkable_items("LAP")}
    manual_snos = {item["s_no"] for item in get_human_review_items("LAP")}

    assert 1 not in ai_snos
    assert 1 in manual_snos
    assert 24 in manual_snos
    assert 41 in manual_snos

    anomalies = run_checks([], {}, {}, "LAP")
    assert not any(anomaly["rule_id"] == "MISSING_DOC_S1" for anomaly in anomalies)
    assert any(anomaly["rule_id"] == "MISSING_DOC_S7" for anomaly in anomalies)


def test_run_checks_flags_non_loan_document_instead_of_missing_docs() -> None:
    pages = [
        {"page_number": 1, "document_type": "Unknown", "page_type": "digital", "is_readable": True},
        {"page_number": 2, "document_type": "Unknown", "page_type": "digital", "is_readable": True},
        {"page_number": 3, "document_type": "Unknown", "page_type": "digital", "is_readable": True},
        {"page_number": 4, "document_type": "Unknown", "page_type": "digital", "is_readable": True},
        {"page_number": 5, "document_type": "Unknown", "page_type": "digital", "is_readable": True},
    ]
    anomalies = run_checks(pages, {}, {}, "LAP")
    assert len(anomalies) == 1
    assert anomalies[0]["rule_id"] == "UNSUPPORTED_DOCUMENT_TYPE"


def test_single_noisy_expected_match_still_flags_non_loan_document() -> None:
    pages = [
        {
            "page_number": 1,
            "document_type": "PAN",
            "page_type": "scanned",
            "is_readable": True,
            "ocr_confidence": 0.95,
            "classification_confidence": 0.95,
        },
        {"page_number": 2, "document_type": "Unknown", "page_type": "scanned", "is_readable": True},
        {"page_number": 3, "document_type": "Unknown", "page_type": "scanned", "is_readable": True},
        {"page_number": 4, "document_type": "Unknown", "page_type": "scanned", "is_readable": True},
        {"page_number": 5, "document_type": "Unknown", "page_type": "scanned", "is_readable": True},
    ]

    anomalies = run_checks(pages, {}, {}, "LAP")

    assert len(anomalies) == 1
    assert anomalies[0]["rule_id"] == "UNSUPPORTED_DOCUMENT_TYPE"


def test_low_confidence_document_does_not_satisfy_presence() -> None:
    pages = [
        {
            "page_number": 1,
            "document_type": "PAN",
            "page_type": "scanned",
            "is_readable": True,
            "ocr_confidence": 0.40,
            "classification_confidence": 0.95,
        },
        {"page_number": 2, "document_type": "Application Form", "page_type": "digital", "classification_confidence": 0.95},
        {"page_number": 3, "document_type": "Bank Statement", "page_type": "digital", "classification_confidence": 0.95},
    ]

    anomalies = run_checks(pages, {}, {}, "LAP")

    assert any(anomaly["rule_id"] == "MISSING_DOC_S7" for anomaly in anomalies)
