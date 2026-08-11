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


def test_sanction_boilerplate_is_not_treated_as_legal_clearance() -> None:
    pages = [
        {
            "page_number": 101,
            "document_type": "Sanction Letter",
            "page_type": "digital",
            "classification_confidence": 1.0,
            "ocr_text": "events of default under the agreement and enforcement of security",
        }
    ]

    anomalies = run_checks(pages, {}, {}, "LAP")

    assert any(anomaly["rule_id"] == "MISSING_DOC_S37" for anomaly in anomalies)
    assert not any(anomaly["rule_id"] == "STATUS_CHECK_S37" for anomaly in anomalies)


def test_legal_otc_pdd_approval_email_satisfies_clearance_and_status() -> None:
    pages = [
        {
            "page_number": 511,
            "document_type": "OTC PDD Document",
            "page_type": "digital",
            "classification_confidence": 1.0,
            "ocr_text": (
                "Subject: Re: Request legal OTC/PDD approval for the case\n"
                "App No: 30765\nFrom: Chief Operating Officer\nok\nThanks & regards"
            ),
            "extracted_fields": {},
        }
    ]

    anomalies = run_checks(pages, {}, {}, "LAP")

    assert not any(anomaly["rule_id"] == "MISSING_DOC_S37" for anomaly in anomalies)
    assert not any(anomaly["rule_id"] in {"STATUS_CHECK_S37", "STATUS_UNVERIFIABLE_S37"} for anomaly in anomalies)


def test_generic_otc_pdd_inventory_is_not_legal_clearance() -> None:
    pages = [
        {
            "page_number": 512,
            "document_type": "OTC PDD Document",
            "page_type": "digital",
            "classification_confidence": 1.0,
            "ocr_text": "OTC/PDD inventory: tax receipt received; mortgage deed pending",
            "extracted_fields": {},
        }
    ]

    anomalies = run_checks(pages, {}, {}, "LAP")

    assert any(anomaly["rule_id"] == "MISSING_DOC_S37" for anomaly in anomalies)


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


def test_disbursal_continuation_dates_do_not_trigger_bank_period_check() -> None:
    pages = [
        _confident_page(1, "Application Form"),
        _confident_page(2, "Loan Agreement"),
        _confident_page(
            3,
            "Bank Statement",
            ocr_text=(
                "In case the transaction is related to a Balance Transfer, the eligible amount "
                "shall be based on the Foreclosure Letter or Statement of Account submitted by "
                "the customer at the time of disbursement. Yours faithfully."
            ),
            extracted_fields={
                "statement_period_start": "2026-07-31",
                "statement_period_end": "2026-07-31",
            },
        ),
    ]

    anomalies = run_checks(pages, {}, {}, "LAP")

    assert not any(item["rule_id"] == "PERIOD_CHECK_S17" for item in anomalies)


def test_missing_pan() -> None:
    anomalies = run_checks([], {}, {}, "LAP")
    assert any(anomaly["rule_id"] == "MISSING_DOC_S7" for anomaly in anomalies)


def test_temporarily_excluded_physical_items_are_not_reviewed() -> None:
    ai_snos = {item["s_no"] for item in get_ai_checkable_items("LAP")}
    manual_snos = {item["s_no"] for item in get_human_review_items("LAP")}

    assert 1 in ai_snos
    assert 1 not in manual_snos
    assert 24 not in manual_snos
    assert 41 in manual_snos

    anomalies = run_checks([], {}, {}, "LAP")
    assert any(anomaly["rule_id"] == "MISSING_DOC_S1" for anomaly in anomalies)
    assert any(anomaly["rule_id"] == "MISSING_DOC_S7" for anomaly in anomalies)
    assert not any(anomaly.get("s_no") in {13, 19} for anomaly in anomalies)


def test_manual_only_items_do_not_become_factual_missing_document_anomalies() -> None:
    anomalies = run_checks(
        [_confident_page(1, "Application Form")],
        {"loan_amount": 450000},
        {"loan_amount": 450000},
        "LAP",
    )

    assert not any(
        anomaly.get("s_no") in {13, 19}
        and str(anomaly.get("rule_id") or "").startswith("MISSING_DOC")
        for anomaly in anomalies
    )


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


def test_stamp_date_check_is_temporarily_disabled() -> None:
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

    assert not any(anomaly["rule_id"] == "DATE_CHECK_S33" for anomaly in anomalies)


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


def test_amount_condition_boundaries_from_printed_checklist() -> None:
    pages = [
        _confident_page(1, "Application Form"),
        _confident_page(2, "Bank Statement"),
        _confident_page(3, "CRIF Report", person_id="primary"),
    ]
    common = {"people": {"primary": {"role": "primary"}}, "kyc_details_checked": True}

    for amount, s_no, expected_missing in [
        (999999, 28, False),
        (1000000, 28, True),
        (1499999, 23, False),
        (1500000, 23, True),
        (2000000, 39, False),
        (2000001, 39, True),
    ]:
        system_data = {**common, "loan_amount": amount}
        anomalies = run_checks(pages, system_data, system_data, "LAP")
        is_missing = any(
            item.get("s_no") == s_no and item["rule_id"].startswith("MISSING_DOC")
            for item in anomalies
        )
        assert is_missing is expected_missing


def test_unknown_condition_is_review_not_silent_skip() -> None:
    anomalies = run_checks([], {}, {}, "LAP")
    assert any(item["rule_id"] == "APPLICABILITY_UNKNOWN_S23" for item in anomalies)
    assert any(item["rule_id"] == "APPLICABILITY_UNKNOWN_S41" for item in anomalies)


def test_pdc_count_changes_with_nach_registration() -> None:
    five_pdcs = [_confident_page(index, "PDC") for index in range(1, 6)]
    registered = {"nach_registered": True}
    anomalies = run_checks(five_pdcs, registered, registered, "LAP")
    assert not any(item.get("s_no") == 41 and item["rule_id"].startswith("MISSING_DOC") for item in anomalies)

    unregistered = {"nach_registered": False}
    anomalies = run_checks(five_pdcs, unregistered, unregistered, "LAP")
    assert any(
        item.get("s_no") == 41
        and item["rule_id"].startswith("MISSING_DOC")
        and "10" in str(item.get("expected_value"))
        for item in anomalies
    )


def test_pdc_count_uses_explicit_nach_status_from_banking_approval() -> None:
    pages = [
        _confident_page(
            1,
            "Bank Statement",
            extracted_fields={"nach_status": "done"},
        ),
        _confident_page(
            2,
            "PDC",
            extracted_fields={
                "cheque_numbers": ["000001", "000002", "000003", "000004", "000005"]
            },
        ),
    ]
    anomalies = run_checks(pages, {}, {}, "LAP")
    assert not any(item.get("s_no") == 41 for item in anomalies)
    assert not any(item.get("s_no") == 42 for item in anomalies)


def test_ach_not_registered_requires_approval_bsv_and_three_nach_forms() -> None:
    pages = [
        _confident_page(1, "ACH Approval Document"),
        _confident_page(2, "Bank Signature Verification"),
        _confident_page(3, "NACH Form"),
        _confident_page(4, "NACH Form"),
    ]
    system_data = {"nach_registered": False}
    anomalies = run_checks(pages, system_data, system_data, "LAP")
    assert any(
        item.get("s_no") == 42
        and item.get("document_type") == "NACH Form"
        and "3" in str(item.get("expected_value"))
        for item in anomalies
    )

    pages.append(_confident_page(5, "NACH Form"))
    anomalies = run_checks(pages, system_data, system_data, "LAP")
    assert not any(item.get("s_no") == 42 and item["rule_id"].startswith("MISSING_DOC") for item in anomalies)


def test_negative_or_referred_fi_requires_approval_letter() -> None:
    pages = [_confident_page(1, "FI Report")]
    negative = {"loan_amount": 1500000, "fi_report_status": "negative"}
    anomalies = run_checks(pages, negative, negative, "LAP")
    assert any(
        item.get("s_no") == 23 and item.get("document_type") == "FI Approval Letter"
        for item in anomalies
    )

    positive = {"loan_amount": 1500000, "fi_report_status": "positive"}
    anomalies = run_checks(pages, positive, positive, "LAP")
    assert not any(
        item.get("s_no") == 23 and item.get("document_type") == "FI Approval Letter"
        for item in anomalies
    )


def test_utility_bill_age_is_not_cross_checked() -> None:
    old_date = (datetime.now() - timedelta(days=75)).date().isoformat()
    pages = [
        _confident_page(1, "Utility Bill", extracted_fields={"bill_date": old_date}),
        _confident_page(2, "Application Form"),
    ]
    anomalies = run_checks(pages, {}, {}, "LAP")
    assert not any(
        item["rule_id"] in {"DATE_CHECK_S6", "FIELD_VALUE_MISSING_S6"}
        for item in anomalies
    )


def test_coapplicant_presence_and_match_verifies_against_correct_person() -> None:
    """Ensure that a co-applicant's PAN is matched against their own reference data, not the primary applicant's."""
    pages = [
        _confident_page(
            1,
            "PAN Card",
            person_id="coapplicant_1",
            extracted_fields={"pan_number": "TSTBB0002T"},
        ),
        _confident_page(2, "Application Form"),
    ]

    system_data = {
        "pan_number": "TSTAA0001T",  # primary PAN
        "applicant_name": "Peeru Lal",
        "reference_data": {
            "primary": {
                "person_id": "primary",
                "applicant_name": "Peeru Lal",
                "pan_number": "TSTAA0001T",
            },
            "coapplicant_1": {
                "person_id": "coapplicant_1",
                "applicant_name": "Unkar Lal",
                "pan_number": "TSTBB0002T",
            },
        },
    }

    # If the fix works:
    # 1. It checks the coapplicant_1 page against coapplicant_1 reference PAN ("TSTBB0002T") and finds a MATCH.
    # 2. No FIELD_MISMATCH anomaly should be produced.
    anomalies = run_checks(pages, system_data, system_data, "LAP")
    mismatch_anomalies = [
        item for item in anomalies if item.get("rule_id", "").startswith("FIELD_MISMATCH")
    ]
    assert not mismatch_anomalies, f"Found unexpected mismatch anomalies: {mismatch_anomalies}"
