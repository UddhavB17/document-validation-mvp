from services.reviewer import compute_final_status, file_severity_for_error_count


def test_file_severity_thresholds_are_inclusive_at_lower_boundaries() -> None:
    assert file_severity_for_error_count(0) == "CLEAN"
    assert file_severity_for_error_count(1) == "LOW"
    assert file_severity_for_error_count(9) == "LOW"
    assert file_severity_for_error_count(10) == "MEDIUM"
    assert file_severity_for_error_count(29) == "MEDIUM"
    assert file_severity_for_error_count(30) == "HIGH"
    assert file_severity_for_error_count(49) == "HIGH"
    assert file_severity_for_error_count(50) == "CRITICAL"


def test_file_status_counts_processing_and_business_errors_together() -> None:
    anomalies = [
        {"rule_id": "PAN_NUMBER_MISMATCH", "severity": "HIGH"},
        {"rule_id": "PAGE_PROCESSING_ERROR", "severity": "MEDIUM"},
    ]
    assert compute_final_status(anomalies) == "LOW"


def test_file_status_ignores_only_dismissed_errors() -> None:
    anomalies = [
        {"rule_id": "PAN_NUMBER_MISMATCH", "severity": "HIGH", "status": "dismissed_by_llm"},
        {"rule_id": "PAGE_PROCESSING_ERROR", "severity": "MEDIUM"},
    ]
    assert compute_final_status(anomalies) == "LOW"
