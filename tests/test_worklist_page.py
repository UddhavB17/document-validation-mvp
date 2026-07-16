from views.reviewer_view import _filter_applications, get_result_state


def test_worklist_filters_separate_auto_clean_from_reviewer_verified() -> None:
    applications = [
        {"loan_id": "A", "status": "processing"},
        {"loan_id": "B", "status": "CLEAN"},
        {"loan_id": "C", "status": "verified"},
        {"loan_id": "D", "status": "verified_with_override"},
        {"loan_id": "E", "status": "CRITICAL"},
    ]

    assert [item["loan_id"] for item in _filter_applications(applications, "Pending")] == ["A"]
    assert [item["loan_id"] for item in _filter_applications(applications, "Auto Clean")] == ["B"]
    assert [item["loan_id"] for item in _filter_applications(applications, "Verified")] == ["C", "D"]
    assert [item["loan_id"] for item in _filter_applications(applications, "Needs Review")] == ["E"]


def test_result_state_blocks_processing_and_failed_statuses() -> None:
    assert get_result_state("processing") == "processing"
    assert get_result_state("ocr_completed") == "processing"
    assert get_result_state("pipeline_failed") == "failed"
    assert get_result_state("CLEAN") == "ready"
    assert get_result_state("NEEDS_REVIEW") == "ready"
    assert get_result_state("verified") == "ready"
