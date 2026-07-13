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


def _confident_page(page_number: int, document_type: str, **extra) -> dict:
    return {
        "page_number": page_number,
        "document_type": document_type,
        "page_type": "digital",
        "classification_confidence": 0.99,
        **extra,
    }


def test_pan_is_required_for_each_borrower() -> None:
    pages = [
        _confident_page(1, "PAN", person_id="primary", extracted_fields={"pan_number": "ABCDE1234F"}),
        _confident_page(2, "Application Form"),
        _confident_page(3, "Bank Statement"),
    ]
    system_data = {
        "people": {
            "primary": {"applicant_name": "A", "pan_number": "ABCDE1234F"},
            "coapplicant_1": {"applicant_name": "B", "pan_number": "FGHIJ5678K"},
        }
    }

    anomalies = run_checks(pages, system_data, system_data, "LAP")

    assert any(
        anomaly["s_no"] == 7 and anomaly.get("person_id") == "coapplicant_1"
        for anomaly in anomalies
    )
    assert not any(
        anomaly["s_no"] == 7 and anomaly.get("person_id") == "primary"
        for anomaly in anomalies
    )


def test_cibil_is_required_per_borrower_only_above_five_lakh() -> None:
    pages = [
        _confident_page(1, "CRIF Report", person_id="primary"),
        _confident_page(2, "CRIF Report", person_id="coapplicant_1"),
        _confident_page(3, "CIBIL Report", person_id="primary"),
        _confident_page(4, "Application Form"),
        _confident_page(5, "Bank Statement"),
    ]
    system_data = {
        "loan_amount": "600000",
        "people": {"primary": {}, "coapplicant_1": {}},
    }

    anomalies = run_checks(pages, system_data, system_data, "LAP")

    assert any(
        anomaly["s_no"] == 15
        and anomaly.get("document_type") == "CIBIL Report"
        and anomaly.get("person_id") == "coapplicant_1"
        for anomaly in anomalies
    )

    below_threshold = {**system_data, "loan_amount": "500000"}
    anomalies = run_checks(pages, below_threshold, below_threshold, "LAP")
    assert not any(
        anomaly["s_no"] == 15 and anomaly.get("document_type") == "CIBIL Report"
        for anomaly in anomalies
    )


def test_kfs_and_sanction_letter_are_both_required() -> None:
    pages = [
        _confident_page(1, "Sanction Letter"),
        _confident_page(2, "Application Form"),
        _confident_page(3, "Bank Statement"),
    ]

    anomalies = run_checks(pages, {}, {}, "LAP")

    assert any(
        anomaly["s_no"] == 21 and anomaly.get("document_type") == "KFS"
        for anomaly in anomalies
    )


def test_stamp_date_must_not_be_after_disbursement() -> None:
    pages = [
        _confident_page(1, "Stamp Duty", extracted_fields={"stamp_date": "2026-07-20"}),
        _confident_page(2, "Application Form"),
        _confident_page(3, "Bank Statement"),
    ]

    anomalies = run_checks(
        pages,
        {"disbursement_date": "2026-07-15"},
        {"disbursement_date": "2026-07-15"},
        "LAP",
    )

    assert any(anomaly["rule_id"] == "DATE_CHECK_S33" for anomaly in anomalies)


def test_two_positive_technical_reports_must_be_distinct() -> None:
    pages = [
        _confident_page(
            1, "Technical Report", source_document_id="report-a",
            extracted_fields={"report_status": "positive"},
        ),
        _confident_page(
            2, "Technical Report", source_document_id="report-a",
            extracted_fields={"report_status": "positive"},
        ),
        _confident_page(3, "Application Form"),
        _confident_page(4, "Bank Statement"),
    ]
    system_data = {"loan_amount": "2500000"}

    anomalies = run_checks(pages, system_data, system_data, "LAP")
    assert any(anomaly["rule_id"] == "COUNT_STATUS_CHECK_S39" for anomaly in anomalies)

    pages[1]["source_document_id"] = "report-b"
    anomalies = run_checks(pages, system_data, system_data, "LAP")
    assert not any(anomaly["rule_id"] == "COUNT_STATUS_CHECK_S39" for anomaly in anomalies)


def test_present_legal_report_with_pending_status_needs_review() -> None:
    pages = [
        _confident_page(1, "Legal Clearance Report", extracted_fields={"clearance_status": "pending"}),
        _confident_page(2, "Application Form"),
        _confident_page(3, "Bank Statement"),
    ]

    anomalies = run_checks(pages, {}, {}, "LAP")

    assert any(anomaly["rule_id"] == "STATUS_CHECK_S37" for anomaly in anomalies)
