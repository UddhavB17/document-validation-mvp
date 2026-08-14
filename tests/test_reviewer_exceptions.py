from services.reviewer import (
    build_reviewer_summary,
    collapse_for_reviewer,
    compute_final_status,
    split_reviewer_anomalies,
    summarize_for_display,
)


def test_trusted_mismatch_suppresses_redundant_cross_document_item() -> None:
    anomalies = [
        {
            "rule_id": "TRUSTED_APPLICANT_NAME_MISMATCH",
            "severity": "HIGH",
            "person_id": "coapplicant_1",
            "page_number": 10,
        },
        {
            "rule_id": "CROSS_DOCUMENT_APPLICANT_NAME_MISMATCH",
            "severity": "HIGH",
            "person_id": "coapplicant_1",
            "page_number": 10,
        },
    ]
    result = collapse_for_reviewer(anomalies)
    assert [item["rule_id"] for item in result] == ["TRUSTED_APPLICANT_NAME_MISMATCH"]


def test_collapses_repeated_unclassified_pages() -> None:
    anomalies = [
        {
            "rule_id": "UNCLASSIFIED_PAGE",
            "severity": "LOW",
            "page_number": page,
            "reason": "Page could not be classified",
        }
        for page in range(1, 116)
    ]
    collapsed = collapse_for_reviewer(anomalies)
    assert len(collapsed) == 1
    assert collapsed[0]["rule_id"] == "UNCLASSIFIED_PAGE_SUMMARY"
    assert collapsed[0]["collapsed_count"] == 115


def test_collapses_auto_owner_and_field_not_found_noise() -> None:
    anomalies = (
        [
            {
                "rule_id": "AUTO_OWNER_UNRESOLVED",
                "severity": "MEDIUM",
                "page_number": page,
                "document_type": "Bank Statement",
            }
            for page in range(1, 21)
        ]
        + [
            {
                "rule_id": "LOAN_AMOUNT_NOT_FOUND",
                "severity": "MEDIUM",
                "page_number": page,
                "document_type": "Loan Agreement",
            }
            for page in range(30, 60)
        ]
        + [{"rule_id": "MISSING_DOC_S7", "severity": "HIGH", "reason": "PAN missing"}]
    )
    collapsed = collapse_for_reviewer(anomalies)
    assert len(collapsed) == 3
    assert {item["rule_id"] for item in collapsed} == {
        "MISSING_DOC_S7",
        "AUTO_OWNER_UNRESOLVED_SUMMARY",
        "LOAN_AMOUNT_NOT_FOUND_SUMMARY",
    }


def test_keeps_high_severity_checklist_items() -> None:
    anomalies = [
        {"rule_id": "MISSING_DOC_S7", "severity": "HIGH", "reason": "PAN missing"},
        {"rule_id": "UNCLASSIFIED_PAGE", "severity": "LOW", "page_number": 4, "reason": "Unknown"},
        {"rule_id": "UNCLASSIFIED_PAGE", "severity": "LOW", "page_number": 5, "reason": "Unknown"},
    ]
    collapsed = collapse_for_reviewer(anomalies)
    assert len(collapsed) == 2
    assert collapsed[0]["rule_id"] == "MISSING_DOC_S7"


def test_compute_final_status_ignores_low_noise_only() -> None:
    anomalies = [
        {"rule_id": "LOW_OCR_CONFIDENCE", "severity": "LOW", "page_number": 1},
        {"rule_id": "LOW_OCR_CONFIDENCE", "severity": "LOW", "page_number": 2},
    ]
    assert compute_final_status(anomalies) == "NEEDS_REVIEW"


def test_summarize_for_display_counts() -> None:
    anomalies = [{"rule_id": "MISSING_DOC_S1", "severity": "HIGH"}] + [
        {"rule_id": "UNREADABLE_PAGE", "severity": "MEDIUM", "page_number": i} for i in range(10)
    ]
    summary = summarize_for_display(anomalies)
    assert summary["raw_count"] == 11
    assert summary["reviewer_count"] == 2
    assert summary["high_count"] == 1


def test_separates_business_exceptions_from_processing_warnings() -> None:
    business, processing = split_reviewer_anomalies(
        [
            {"rule_id": "MISSING_DOC_S7", "severity": "HIGH"},
            {"rule_id": "PAN_NUMBER_MISMATCH", "severity": "HIGH"},
            {"rule_id": "LOW_OCR_CONFIDENCE_SUMMARY", "severity": "LOW"},
            {"rule_id": "PAGE_PROCESSING_ERROR", "severity": "MEDIUM"},
        ]
    )

    assert [item["rule_id"] for item in business] == ["MISSING_DOC_S7", "PAN_NUMBER_MISMATCH"]
    assert [item["rule_id"] for item in processing] == [
        "LOW_OCR_CONFIDENCE_SUMMARY",
        "PAGE_PROCESSING_ERROR",
    ]


def test_reviewer_does_not_merge_mismatches_for_different_people() -> None:
    anomalies = [
        {
            "rule_id": "TRUSTED_PHONE_NUMBER_MISMATCH",
            "severity": "HIGH",
            "person_id": "primary",
            "page_number": 10,
            "document_type": "Application Form",
        },
        {
            "rule_id": "TRUSTED_PHONE_NUMBER_MISMATCH",
            "severity": "HIGH",
            "person_id": "coapplicant_1",
            "page_number": 11,
            "document_type": "CRIF Report",
        },
    ]

    collapsed = collapse_for_reviewer(anomalies)

    assert len(collapsed) == 2
    assert {item["person_id"] for item in collapsed} == {"primary", "coapplicant_1"}


def test_auto_document_type_low_confidence_is_one_processing_warning() -> None:
    anomalies = [
        {
            "rule_id": "AUTO_DOCUMENT_TYPE_LOW_CONFIDENCE",
            "severity": "LOW",
            "page_number": page,
            "document_type": "Application Form",
        }
        for page in (4, 9, 12)
    ]

    collapsed = collapse_for_reviewer(anomalies)
    business, processing = split_reviewer_anomalies(collapsed)

    assert business == []
    assert len(processing) == 1
    assert processing[0]["rule_id"] == "AUTO_DOCUMENT_TYPE_LOW_CONFIDENCE_SUMMARY"
    assert processing[0]["collapsed_count"] == 3


def test_exact_duplicate_anomalies_do_not_inflate_bucket_count() -> None:
    first = {
        "rule_id": "UNCLASSIFIED_PAGE",
        "severity": "LOW",
        "page_number": 1,
        "reason": "Unknown",
    }
    second = {**first, "page_number": 2}

    collapsed = collapse_for_reviewer([first, dict(first), second])

    assert len(collapsed) == 1
    assert collapsed[0]["collapsed_count"] == 2
    assert collapsed[0]["collapsed_page_numbers"] == [1, 2]


def test_missing_trusted_person_scope_collapses_separately_by_role() -> None:
    anomalies = [
        {
            "rule_id": "TRUSTED_PERSON_SCOPE_MISSING",
            "severity": "MEDIUM",
            "person_role": "coapplicant",
            "page_number": page,
        }
        for page in (20, 21)
    ] + [
        {
            "rule_id": "TRUSTED_PERSON_SCOPE_MISSING",
            "severity": "MEDIUM",
            "person_role": "guarantor",
            "page_number": 30,
        }
    ]

    collapsed = collapse_for_reviewer(anomalies)

    assert len(collapsed) == 2
    assert {item.get("person_role") for item in collapsed} == {"coapplicant", "guarantor"}
    coapplicant = next(item for item in collapsed if item.get("person_role") == "coapplicant")
    assert coapplicant["rule_id"] == "TRUSTED_PERSON_SCOPE_MISSING_SUMMARY"
    assert coapplicant["collapsed_count"] == 2

    business, processing = split_reviewer_anomalies(collapsed)
    assert len(business) == 2
    assert processing == []


def test_repayment_total_checks_collapse_with_contributing_evidence() -> None:
    schedule_check = {
        "rule_id": "REPAYMENT_SCHEDULE_TOTAL_MISMATCH",
        "severity": "HIGH",
        "page_number": 36,
        "document_type": "Repayment Schedule",
        "expected_value": "INR 1,135,219.00 (KFS/facility summary)",
        "found_value": "INR 862,250.18 (sum of EMI column)",
        "reason": "Schedule total differs from the stated repayment total.",
    }
    summary_check = {
        "rule_id": "REPAYMENT_SUMMARY_TOTAL_MISMATCH",
        "severity": "HIGH",
        "page_number": 36,
        "document_type": "Repayment Schedule",
        "expected_value": "Loan + interest = INR 450,000.00",
        "found_value": "Stated total repayment = INR 1,135,219.00",
        "reason": "KFS summary is internally inconsistent.",
    }

    collapsed = collapse_for_reviewer([schedule_check, summary_check])

    assert len(collapsed) == 1
    item = collapsed[0]
    assert item["rule_id"] == "REPAYMENT_SCHEDULE_TOTAL_MISMATCH_SUMMARY"
    assert item["contributing_rule_ids"] == [
        "REPAYMENT_SCHEDULE_TOTAL_MISMATCH",
        "REPAYMENT_SUMMARY_TOTAL_MISMATCH",
    ]
    assert [evidence["expected_value"] for evidence in item["contributing_evidence"]] == [
        schedule_check["expected_value"],
        summary_check["expected_value"],
    ]

    reviewer = build_reviewer_summary(total_pages=40, anomalies=[schedule_check, summary_check])
    assert reviewer["anomaly_count"] == 1
    assert reviewer["review_items"][0]["contributing_rule_ids"] == item["contributing_rule_ids"]
    assert len(reviewer["review_items"][0]["contributing_evidence"]) == 2


def test_build_summary_found_value_with_multiple_pages() -> None:
    anomalies = [
        {
            "rule_id": "UNCLASSIFIED_PAGE",
            "severity": "LOW",
            "page_number": 1,
            "found_value": "Statement Header",
        },
        {
            "rule_id": "UNCLASSIFIED_PAGE",
            "severity": "LOW",
            "page_number": 2,
            "found_value": "Statement Header",
        },
        {
            "rule_id": "UNCLASSIFIED_PAGE",
            "severity": "LOW",
            "page_number": 3,
            "found_value": "Salary Details",
        },
    ]

    collapsed = collapse_for_reviewer(anomalies)
    assert len(collapsed) == 1
    assert collapsed[0]["found_value"] == "Page 1: 'Statement Header'\nPage 2: 'Statement Header'\nPage 3: 'Salary Details'"
