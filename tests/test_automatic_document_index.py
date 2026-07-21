from services.automatic_document_index import build_automatic_document_index


def _page(number: int, document_type: str, fields: dict, *, detected: int | None = None) -> dict:
    return {
        "page_number": number,
        "document_type": document_type,
        "classification_confidence": 0.92,
        "detected_page_number": number if detected is None else detected,
        "extracted_fields": fields,
    }


def test_builds_contiguous_index_and_infers_people() -> None:
    pages = [
        _page(1, "PAN", {"applicant_name": "PEERU LAL", "pan_number": "ABCDE1234F"}),
        _page(2, "Aadhaar", {"applicant_name": "Unkar Lal", "dob": "05/06/1961"}),
        _page(3, "Aadhaar", {"address": "Semli Bakhta Rajasthan"}, detected=2),
    ]
    result = build_automatic_document_index(
        pages,
        {
            "primary": {"applicant_name": "Peeru Lal", "pan_number": "ABCDE1234F"},
            "coapplicant_1": {"applicant_name": "Unkar Lal", "date_of_birth": "05-June-1961"},
        },
    )

    assert result["anomalies"] == []
    assert [(item["document_type"], item["pages"], item["applicant_role"]) for item in result["documents"]] == [
        ("PAN", [1], "primary"),
        ("Aadhaar", [2, 3], "coapplicant_1"),
    ]
    assert result["unclassified_pages"] == []


def test_respects_zip_source_boundaries_for_same_document_type() -> None:
    pages = [
        _page(1, "PAN", {"applicant_name": "Ramesh Kumar"}),
        _page(2, "PAN", {"applicant_name": "Ramesh Kumar"}, detected=1),
    ]
    result = build_automatic_document_index(
        pages,
        {"primary": {"applicant_name": "Ramesh Kumar"}},
        source_documents=[
            {"source_document_id": "file-0001", "internal_page_start": 1, "internal_page_end": 1},
            {"source_document_id": "file-0002", "internal_page_start": 2, "internal_page_end": 2},
        ],
    )

    assert [item["source_document_id"] for item in result["documents"]] == ["file-0001", "file-0002"]


def test_does_not_guess_kyc_owner_when_multiple_people_have_no_matching_identity() -> None:
    result = build_automatic_document_index(
        [_page(4, "PAN", {"pan_number": "ZZZZZ9999Z"})],
        {
            "primary": {"applicant_name": "Ramesh Kumar", "pan_number": "ABCDE1234F"},
            "coapplicant_1": {"applicant_name": "Sita Kumar", "pan_number": "FGHIJ5678K"},
        },
    )

    assert result["documents"] == []
    assert result["anomalies"][0]["rule_id"] == "AUTO_OWNER_UNRESOLVED"
    assert result["unclassified_pages"] == [4]


def test_loan_level_docs_skip_owner_noise_and_still_index() -> None:
    pages = [
        _page(1, "Loan Agreement", {"some_clause": "x"}),
        _page(2, "Loan Agreement", {"some_clause": "y"}, detected=1),
        _page(3, "Sanction Letter", {"loan_amount": "100000"}),
    ]
    result = build_automatic_document_index(
        pages,
        {
            "primary": {"applicant_name": "Ramesh Kumar"},
            "coapplicant_1": {"applicant_name": "Sita Kumar"},
        },
    )

    assert result["anomalies"] == []
    assert len(result["documents"]) == 2
    assert all(item["applicant_role"] == "primary" for item in result["documents"])


def test_aggregates_loan_agreement_fragments_within_same_source() -> None:
    pages = [
        _page(1, "Loan Agreement", {}),
        _page(2, "Loan Agreement", {}, detected=2),  # false "new document" heading
        _page(3, "Loan Agreement", {}, detected=3),
    ]
    result = build_automatic_document_index(
        pages,
        {"primary": {"applicant_name": "Ramesh Kumar"}},
        source_documents=[
            {"source_document_id": "file-0001", "internal_page_start": 1, "internal_page_end": 3},
        ],
    )

    assert len(result["documents"]) == 1
    assert result["documents"][0]["pages"] == [1, 2, 3]
