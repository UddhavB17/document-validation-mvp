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

    assert [item["auto_mapping"]["source_document_id"] for item in result["documents"]] == [
        "file-0001",
        "file-0002",
    ]
    assert all(item["source_document_id"].startswith("file-000") for item in result["documents"])


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


def test_strong_deterministic_type_wins_over_disagreeing_llm_advice() -> None:
    page = _page(
        10,
        "CAM",
        {
            "loan_amount": "450000",
            "_structured_llm_classification": {
                "document_type": "Loan Agreement",
                "confidence": 0.99,
            },
        },
    )
    page["classification_confidence"] = 1.0

    result = build_automatic_document_index(
        [page],
        {"primary": {"applicant_name": "Suthar Anupkumar", "loan_amount": "450000"}},
    )

    assert result["documents"][0]["document_type"] == "CAM"


def test_weak_inherited_type_yields_to_high_confidence_structured_advice() -> None:
    page = _page(
        10,
        "Application Form",
        {
            "pan_number": "ABCDE1234F",
            "_structured_llm_classification": {
                "document_type": "PAN",
                "confidence": 0.99,
            },
        },
    )
    page["classification_confidence"] = 0.70
    page["detection_method"] = "sandwich_smoothed"

    result = build_automatic_document_index(
        [page],
        {"primary": {"applicant_name": "Ramesh Kumar", "pan_number": "ABCDE1234F"}},
    )

    assert result["documents"][0]["document_type"] == "PAN"


def test_unsupported_llm_agreement_guess_does_not_override_spreadsheet_context() -> None:
    page = _page(
        467,
        "Application Form",
        {
            "_structured_llm_classification": {
                "document_type": "Loan Agreement",
                "confidence": 0.999,
            },
        },
    )
    page["classification_confidence"] = 0.58
    page["detection_method"] = "inherited"
    page["ocr_text"] = (
        "Workbook: case.xlsx | Sheet: CFA | Columns 9-10 | Rows 1-33\n"
        "=IFERROR(ROUNDDOWN(IF(E11>0, =E30+(C36-E36) =C84+F90"
    )

    result = build_automatic_document_index(
        [page],
        {"primary": {"applicant_name": "Ramesh Kumar"}},
    )

    assert result["documents"][0]["document_type"] == "Application Form"


def test_non_person_scoped_document_does_not_raise_owner_unresolved() -> None:
    result = build_automatic_document_index(
        [_page(1, "NOC", {"status": "issued"})],
        {
            "primary": {"applicant_name": "Ramesh Kumar"},
            "coapplicant_1": {"applicant_name": "Sita Kumar"},
        },
    )

    assert result["anomalies"] == []
    assert result["documents"][0]["document_type"] == "NOC"


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


def test_explicit_name_outweighs_reused_phone_for_owner_resolution() -> None:
    result = build_automatic_document_index(
        [_page(1, "CRIF Report", {"applicant_name": "Radha Bai", "phone_number": "9000000002"})],
        {
            "coapplicant_1": {"applicant_name": "Unkar Lal", "phone_number": "9000000002"},
            "coapplicant_2": {"applicant_name": "Radha Bai", "phone_number": "9000000003"},
        },
    )
    assert result["documents"][0]["applicant_role"] == "coapplicant_2"


def test_full_aadhaar_number_matches_trusted_last_four_for_owner_resolution() -> None:
    result = build_automatic_document_index(
        [_page(1, "Aadhaar", {"aadhaar_number": "999988880003"})],
        {
            "coapplicant_1": {"applicant_name": "Unkar Lal", "aadhaar_last4": "0002"},
            "coapplicant_2": {"applicant_name": "Radha Bai", "aadhaar_last4": "0003"},
        },
    )
    assert result["anomalies"] == []
    assert result["documents"][0]["applicant_role"] == "coapplicant_2"


def test_weak_smoothed_unknown_name_does_not_resolve_owner() -> None:
    weak = _page(
        31,
        "CRIF Report",
        {
            "applicant_name": "MEHAR BASTI SEMALI BAKHATA",
            "_identity_extraction_reliable": False,
            "_classification": {
                "raw_document_type": "Unknown",
                "detection_method": "sandwich_smoothed",
            },
        },
        detected=30,
    )
    weak["detection_method"] = "sandwich_smoothed"
    result = build_automatic_document_index(
        [weak],
        {
            "primary": {"applicant_name": "Peeru Lal"},
            "coapplicant_1": {"applicant_name": "Unkar Lal"},
        },
    )

    assert result["documents"] == []
    assert result["anomalies"][0]["rule_id"] == "AUTO_OWNER_UNRESOLVED"


def test_zip_member_multi_page_pdf_is_one_document_candidate() -> None:
    pages = [
        _page(1, "Application Form", {"applicant_name": "Peeru Lal"}),
        _page(2, "Application Form", {"pan_number": "TSTAA0001T"}, detected=1),
    ]
    result = build_automatic_document_index(
        pages,
        {"primary": {"applicant_name": "Peeru Lal", "pan_number": "TSTAA0001T"}},
        source_documents=[{
            "source_document_id": "file-0001",
            "original_filename": "application-form.pdf",
            "internal_page_start": 1,
            "internal_page_end": 2,
        }],
    )

    assert len(result["documents"]) == 1
    assert result["documents"][0]["auto_mapping"]["source_document_id"] == "file-0001"
    assert result["documents"][0]["source_document_id"].startswith("file-0001#")
    assert result["documents"][0]["pages"] == [1, 2]


def test_zip_member_with_multiple_document_types_is_split() -> None:
    pages = [
        _page(1, "PAN", {"applicant_name": "Peeru Lal", "pan_number": "ABCDE1234F"}),
        _page(2, "Aadhaar", {"applicant_name": "Peeru Lal", "aadhaar_number": "1234 5678 9012"}),
        _page(3, "Aadhaar", {"address": "Rajasthan"}, detected=2),
    ]
    result = build_automatic_document_index(
        pages,
        {"primary": {"applicant_name": "Peeru Lal", "pan_number": "ABCDE1234F"}},
        source_documents=[{
            "source_document_id": "file-0001",
            "original_filename": "kyc-pack.pdf",
            "internal_page_start": 1,
            "internal_page_end": 3,
        }],
    )

    assert [(item["document_type"], item["pages"]) for item in result["documents"]] == [
        ("PAN", [1]),
        ("Aadhaar", [2, 3]),
    ]
    assert all(item["auto_mapping"]["source_document_id"] == "file-0001" for item in result["documents"])


def test_detected_bureau_appendix_remains_with_subject_page_in_same_source() -> None:
    first = _page(1, "CRIF Report", {"applicant_name": "Mosmee Meena"})
    first["ocr_text"] = (
        "CRIF High Mark Credit Information Report Consumer Name Mosmee Meena Credit Score"
    )
    appendix = _page(2, "CRIF Report", {})
    appendix["ocr_text"] = (
        "Account Information Payment History Overdue High Mark Credit Member Asset Classification"
    )
    result = build_automatic_document_index(
        [first, appendix],
        {"coapplicant_3": {"applicant_name": "Mosmee Meena"}},
        source_documents=[{
            "source_document_id": "file-0001",
            "original_filename": "credit_score.pdf",
            "internal_page_start": 1,
            "internal_page_end": 2,
        }],
    )

    assert result["anomalies"] == []
    assert len(result["documents"]) == 1
    assert result["documents"][0]["pages"] == [1, 2]
    assert result["documents"][0]["applicant_role"] == "coapplicant_3"


def test_repeated_aadhaar_heading_does_not_split_front_and_back_in_same_source() -> None:
    front = _page(
        19,
        "Aadhaar",
        {
            "applicant_name": "Tika Ram Meena",
            "aadhaar_number": "111122223333",
            "date_of_birth": "1992-12-02",
        },
    )
    back = _page(20, "Aadhaar", {"address": "Village Deoli Tonk 304023"})
    result = build_automatic_document_index(
        [front, back],
        {
            "coapplicant_1": {
                "applicant_name": "Tika Ram Meena",
                "aadhaar_number": "111122223333",
            },
            "coapplicant_2": {"applicant_name": "Radha Bai"},
        },
        source_documents=[{
            "source_document_id": "file-0007",
            "original_filename": "Co-Applicant/KYC/aadhaar.pdf",
            "internal_page_start": 19,
            "internal_page_end": 20,
        }],
    )

    assert result["anomalies"] == []
    assert result["documents"][0]["pages"] == [19, 20]
    assert result["documents"][0]["applicant_role"] == "coapplicant_1"


def test_two_strongly_different_aadhaar_ids_still_split_in_same_source() -> None:
    first = _page(
        1,
        "Aadhaar",
        {"applicant_name": "Tika Ram Meena", "aadhaar_number": "111122223333"},
    )
    second = _page(
        2,
        "Aadhaar",
        {"applicant_name": "Radha Bai", "aadhaar_number": "999988887777"},
    )
    result = build_automatic_document_index(
        [first, second],
        {
            "coapplicant_1": {
                "applicant_name": "Tika Ram Meena",
                "aadhaar_number": "111122223333",
            },
            "coapplicant_2": {
                "applicant_name": "Radha Bai",
                "aadhaar_number": "999988887777",
            },
        },
        source_documents=[{
            "source_document_id": "file-0001",
            "internal_page_start": 1,
            "internal_page_end": 2,
        }],
    )

    assert [item["pages"] for item in result["documents"]] == [[1], [2]]
