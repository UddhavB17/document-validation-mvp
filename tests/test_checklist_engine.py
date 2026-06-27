from services.checklist_engine import evaluate_checklist


def test_evaluate_checklist_flags_missing_documents() -> None:
    checklist = {"required_documents": ["PAN", "Aadhaar"]}
    extracted_documents = {"PAN": {}}

    assert evaluate_checklist(checklist, extracted_documents) == [
        {"document": "Aadhaar", "issue": "missing"}
    ]
