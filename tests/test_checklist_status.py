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
    assert not any(
        str(anomaly.get("rule_id", "")).startswith("FIELD_MISMATCH") for anomaly in anomalies
    )


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
