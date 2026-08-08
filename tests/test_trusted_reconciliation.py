from services.trusted_reconciliation import build_trusted_reconciliation


def _page(number: int, document_type: str, person_id: str, **fields) -> dict:
    return {
        "page_number": number,
        "document_type": document_type,
        "page_type": "digital",
        "classification_confidence": 0.99,
        "person_id": person_id,
        "extracted_fields": fields,
    }


def test_reconciliation_exposes_matches_conflicts_gaps_and_database_only_fields() -> None:
    trusted = {
        "loan_amount": "500000",
        "emi": "12000",
        "workflow_note": "maker approved",
        "people": {
            "primary": {
                "applicant_name": "Ramesh Kumar",
                "pan_number": "ABCDE1234F",
                "account_number": "123456789012",
                "qualification": "Graduate",
            }
        },
    }
    pages = [
        _page(1, "Application Form", "primary", applicant_name="Ramesh Kumar", loan_amount="500000"),
        _page(2, "PAN", "primary", pan_number="ABCDE1234F"),
        _page(3, "Bank Statement", "primary", account_number="999999999012"),
        _page(4, "Loan Agreement", "primary", loan_amount="600000"),
    ]

    result = build_trusted_reconciliation(pages, trusted)
    statuses = {
        (item.get("person_id"), item["field"]): item["status"]
        for item in result["fields"]
    }

    assert statuses[(None, "loan_amount")] == "MATCH_WITH_CONFLICTS"
    assert statuses[(None, "emi")] == "NOT_OBSERVED"
    assert statuses[(None, "workflow_note")] == "NOT_CHECKABLE"
    assert statuses[("primary", "pan_number")] == "MATCH"
    assert statuses[("primary", "account_number")] == "MATCH"
    assert statuses[("primary", "qualification")] == "NOT_OBSERVED"
    assert result["summary"]["checked_fields"] == 4
