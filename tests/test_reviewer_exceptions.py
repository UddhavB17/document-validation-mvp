from services.reviewer import (
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
