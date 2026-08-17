from services.checklist_engine import check_presence_min_count, run_checks
from services.checklist_status import build_checklist_status
from services.checklist_service import get_all_checklist_items


def test_presence_min_count_requires_two_pages() -> None:
    pages = [{"document_type": "Technical Report", "page_number": 10}]
    result = check_presence_min_count(pages, "Technical Report", 2)
    assert result["passed"] is False

    pages.append({"document_type": "Technical Report", "page_number": 11})
    result = check_presence_min_count(pages, "Technical Report", 2)
    assert result["passed"] is True


def test_run_checks_flags_missing_pan_presence_only() -> None:
    anomalies = run_checks([], {}, {}, "LAP")
    assert any(anomaly["rule_id"] == "MISSING_DOC_S7" for anomaly in anomalies)
    assert not any(str(anomaly.get("rule_id", "")).startswith("FIELD_MISMATCH") for anomaly in anomalies)


def test_build_checklist_status_marks_missing_items() -> None:
    items = get_all_checklist_items("LAP")
    rows = build_checklist_status(
        items,
        pages=[{"document_type": "Application Form", "page_number": 1}],
        anomalies=[{"rule_id": "MISSING_DOC_S7", "s_no": 7}],
    )
    app_row = next(row for row in rows if row["s_no"] == 1)
    pan_row = next(row for row in rows if row["s_no"] == 7)
    assert app_row["status"] == "FOUND"
    assert pan_row["status"] == "MISSING"


def test_build_checklist_status_does_not_mark_unmatched_items_found() -> None:
    items = get_all_checklist_items("LAP")
    rows = build_checklist_status(
        items,
        pages=[{"document_type": "Unknown", "page_number": 1}],
        anomalies=[{"rule_id": "UNSUPPORTED_DOCUMENT_TYPE", "s_no": None}],
    )

    assert all(row["status"] != "FOUND" for row in rows)
    assert all(row["status"] == "NOT_CHECKED" for row in rows)


def test_build_checklist_status_requires_confident_match() -> None:
    items = get_all_checklist_items("LAP")
    rows = build_checklist_status(
        items,
        pages=[
            {
                "document_type": "PAN",
                "page_number": 1,
                "page_type": "scanned",
                "ocr_confidence": 0.40,
                "classification_confidence": 0.95,
            }
        ],
        anomalies=[{"rule_id": "MISSING_DOC_S7", "s_no": 7}],
    )

    pan_row = next(row for row in rows if row["s_no"] == 7)
    assert pan_row["status"] == "MISSING"
    assert pan_row["pages"] == "-"


def test_manual_and_hybrid_items_are_not_reported_as_found() -> None:
    items = get_all_checklist_items("LAP")
    pages = [
        {"document_type": "Loan Agreement", "page_number": 1, "classification_confidence": 0.99},
        {"document_type": "Life Insurance Form", "page_number": 2, "classification_confidence": 0.99},
        {"document_type": "Property Insurance Form", "page_number": 3, "classification_confidence": 0.99},
    ]

    rows = build_checklist_status(items, pages=pages, anomalies=[])
    by_number = {row["s_no"]: row for row in rows}

    assert by_number[20]["status"] == "NOT_CHECKED"
    assert by_number[22]["status"] == "NOT_CHECKED"


def test_pdc_shortfall_beats_document_presence_in_reviewer_status() -> None:
    items = get_all_checklist_items("LAP")
    rows = build_checklist_status(
        items,
        pages=[{"document_type": "PDC", "page_number": 1, "classification_confidence": 0.99}],
        anomalies=[{"rule_id": "MISSING_DOC_S41", "s_no": 41}],
        system_data={"nach_registered": False},
    )

    assert next(row for row in rows if row["s_no"] == 41)["status"] == "MISSING"


def test_accuracy_anomaly_prevents_found_status() -> None:
    items = get_all_checklist_items("LAP")
    rows = build_checklist_status(
        items,
        pages=[
            {"document_type": "Bank Statement", "page_number": 1, "classification_confidence": 0.99}
        ],
        anomalies=[{"rule_id": "PERIOD_COVERAGE_S17", "s_no": 17}],
    )

    assert next(row for row in rows if row["s_no"] == 17)["status"] == "NEEDS_REVIEW"
