from pages.worklist_page import _filter_applications


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
