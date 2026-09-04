import database.db as db
from database.db import get_connection, init_db
from services.automatic_document_index import build_automatic_document_index
from services.company_data_provider import CompanyReferenceData, LocalJsonCompanyDataProvider
from services.document_index_provider import (
    ManualDocumentIndexProvider,
    compose_verification_manifest,
)
from services.field_extractor import extract_fields
from services.field_verification import verify_name
from services.mapped_verification import compare_processed_pages, run_mapped_verification
from services.reviewer import build_reviewer_summary, load_reviewer_summary
from services.verification_manifest import VerificationManifest


def _anomaly_text(anomalies: list[dict]) -> str:
    return repr(anomalies)


class _FakeDocument:
    def __init__(self, pages: int) -> None:
        self.pages = [object() for _ in range(pages)]

    def __len__(self) -> int:
        return len(self.pages)

    def __getitem__(self, index: int):
        return self.pages[index]

    def close(self) -> None:
        return None


class _DigitalPage:
    def __init__(self, text: str) -> None:
        self.text = text

    def get_text(self) -> str:
        return self.text


def test_shared_pipeline_comparison_matches_case_insensitive_name_and_classifies_source() -> None:
    pages = [
        {
            "page_number": 1,
            "page_type": "digital",
            "is_readable": True,
            "ocr_text": (
                "INCOME TAX DEPARTMENT\nNAME\nRAMESH KUMAR\nPermanent Account Number ABCDE1234F"
            ),
            "ocr_confidence": None,
            "document_type": "PAN",
            "classification_confidence": 0.98,
            "extracted_fields": {
                "applicant_name": "RAMESH KUMAR",
                "pan_number": "ABCDE1234F",
                "_structured_llm_classification": {
                    "document_type": "PAN",
                    "confidence": 0.99,
                },
            },
        }
    ]
    manifest = {
        "loan_id": "MAP-SHARED",
        "reference_data": {
            "primary": {
                "applicant_name": "Ramesh Kumar",
                "pan_number": "ABCDE1234F",
            }
        },
        "documents": [
            {
                "source_document_id": "file-0001",
                "applicant_role": "primary",
                "document_type": "PAN",
                "pages": [1],
            }
        ],
    }

    result = compare_processed_pages(
        pages,
        manifest,
        source_documents=[
            {
                "source_document_id": "file-0001",
                "original_filename": "Applicant/KYC/pan.pdf",
                "internal_page_start": 1,
                "internal_page_end": 1,
            }
        ],
    )

    assert result["anomalies"] == []
    assert result["checked_fields"] == 2
    assert result["matched_fields"] == 2
    assert result["source_classifications"] == [
        {
            "source_document_id": "file-0001",
            "original_filename": "Applicant/KYC/pan.pdf",
            "pages": [1],
            "provided_person_ids": ["primary"],
            "predicted_person_id": "primary",
            "owner_detection_method": "extracted_identity",
            "provided_document_types": ["PAN"],
            "predicted_document_type": "PAN",
            "document_type_votes": {"PAN": 1},
        }
    ]


def test_shared_comparison_recovers_labeled_dob_from_raw_ocr(monkeypatch) -> None:
    monkeypatch.setattr(
        "services.mapped_verification.extract_fields",
        lambda _document_type, _text: {"dob": None},
    )
    pages = [
        {
            "page_number": 67,
            "page_type": "scanned",
            "is_readable": True,
            "ocr_text": (
                "UNION OF INDIA Driving Licence\n"
                "Date of Birth\nBlood Group\nUnknown\n28/11/1994\n"
                "Name\nKULDEEP SINGH"
            ),
            "ocr_confidence": 0.93,
            "document_type": "Driving License",
            "classification_confidence": 1.0,
            "extracted_fields": {"dob": None},
        }
    ]
    manifest = {
        "reference_data": {
            "coapplicant_2": {"date_of_birth": "28-November-1994"},
        },
        "documents": [
            {
                "source_document_id": "dl-1",
                "applicant_role": "coapplicant_2",
                "document_type": "Driving License",
                "pages": [67],
                "expected_fields": {"date_of_birth": "28-November-1994"},
            }
        ],
    }

    result = compare_processed_pages(pages, manifest)

    assert result["anomalies"] == []
    assert result["checked_fields"] == 1
    assert result["matched_fields"] == 1
    assert pages[0]["extracted_fields"]["dob"] == "28/11/1994"
    recovery = pages[0]["extracted_fields"]["_trusted_candidate_recovery"]["date_of_birth"]
    assert recovery["resolution_method"] == "trusted_candidate_match"
    assert recovery["anchor"] == "date_of_birth_label"
    assert recovery["original_values"] == []


def test_shared_comparison_replaces_noisy_name_and_address_when_ocr_has_trusted_values(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "services.mapped_verification.extract_fields",
        lambda _document_type, _text: {
            "applicant_name": "APPLICATION DETAILS",
            "address": "DATE OF BIRTH BLOOD GROUP UNKNOWN",
        },
    )
    pages = [
        {
            "page_number": 3,
            "page_type": "scanned",
            "is_readable": True,
            "ocr_text": (
                "Application Form\nApplicant Name\nRAMESH KUMAR\n"
                "Permanent Address\n12 Market Road\nDelhi 110001\n"
                "Mobile Number\n9876543210"
            ),
            "ocr_confidence": 0.96,
            "document_type": "Application Form",
            "classification_confidence": 0.98,
            "extracted_fields": {
                "applicant_name": "APPLICATION DETAILS",
                "address": "DATE OF BIRTH BLOOD GROUP UNKNOWN",
            },
        }
    ]
    expected = {
        "applicant_name": "Ramesh Kumar",
        "address": "12 Market Road Delhi 110001",
    }
    manifest = {
        "reference_data": {"primary": expected},
        "documents": [
            {
                "source_document_id": "form-1",
                "applicant_role": "primary",
                "document_type": "Application Form",
                "pages": [3],
                "expected_fields": expected,
            }
        ],
    }

    result = compare_processed_pages(pages, manifest)

    assert result["anomalies"] == []
    assert result["checked_fields"] == 2
    assert result["matched_fields"] == 2
    fields = pages[0]["extracted_fields"]
    assert fields["applicant_name"] == "RAMESH KUMAR"
    assert fields["address"] == "12 Market Road Delhi 110001"
    assert fields["_trusted_candidate_recovery"]["address"]["original_values"] == [
        "DATE OF BIRTH BLOOD GROUP UNKNOWN"
    ]


def test_shared_comparison_does_not_hide_wrong_owner_with_trusted_recovery(monkeypatch) -> None:
    monkeypatch.setattr(
        "services.mapped_verification.extract_fields",
        lambda _document_type, _text: {"applicant_name": "SITA KUMAR"},
    )
    pages = [
        {
            "page_number": 4,
            "page_type": "digital",
            "is_readable": True,
            "ocr_text": "Application Form\nApplicant Name\nRAMESH KUMAR\nCo-applicant SITA KUMAR",
            "ocr_confidence": 1.0,
            "document_type": "Application Form",
            "classification_confidence": 0.99,
            "extracted_fields": {"applicant_name": "SITA KUMAR"},
        }
    ]
    manifest = {
        "reference_data": {
            "primary": {"applicant_name": "Ramesh Kumar"},
            "coapplicant_1": {"applicant_name": "Sita Kumar"},
        },
        "documents": [
            {
                "source_document_id": "form-2",
                "applicant_role": "primary",
                "document_type": "Application Form",
                "pages": [4],
                "expected_fields": {"applicant_name": "Ramesh Kumar"},
            }
        ],
    }

    result = compare_processed_pages(pages, manifest)

    assert pages[0]["extracted_fields"]["applicant_name"] == "SITA KUMAR"
    assert "_trusted_candidate_recovery" not in pages[0]["extracted_fields"]
    assert [item["rule_id"] for item in result["anomalies"]] == ["INDEX_MAPPING_SUSPECTED"]


def test_shared_comparison_requires_a_field_label_before_trusted_recovery(monkeypatch) -> None:
    monkeypatch.setattr(
        "services.mapped_verification.extract_fields",
        lambda _document_type, _text: {"applicant_name": None},
    )
    pages = [
        {
            "page_number": 5,
            "page_type": "digital",
            "is_readable": True,
            "ocr_text": "This declaration was witnessed by Ramesh Kumar and signed below.",
            "ocr_confidence": 1.0,
            "document_type": "Application Form",
            "classification_confidence": 0.99,
            "extracted_fields": {"applicant_name": None},
        }
    ]
    manifest = {
        "reference_data": {"primary": {"applicant_name": "Ramesh Kumar"}},
        "documents": [
            {
                "source_document_id": "form-3",
                "applicant_role": "primary",
                "document_type": "Application Form",
                "pages": [5],
                "expected_fields": {"applicant_name": "Ramesh Kumar"},
            }
        ],
    }

    result = compare_processed_pages(pages, manifest)

    assert pages[0]["extracted_fields"]["applicant_name"] is None
    assert "_trusted_candidate_recovery" not in pages[0]["extracted_fields"]
    assert [item["rule_id"] for item in result["anomalies"]] == ["APPLICANT_NAME_NOT_FOUND"]


def test_mapped_cersai_uses_debtor_pan_over_wrong_provided_person() -> None:
    text = """Debtor Based Search Report
Search Criteria Entered
Name of the Debtor
SITA KUMAR
PAN
FGHIJ5678K
Search Output Details
Applicant RAMESH KUMAR PAN ABCDE1234F
"""
    pages = [
        {
            "page_number": 1,
            "page_type": "digital",
            "is_readable": True,
            "ocr_text": text,
            "ocr_confidence": 1.0,
            "document_type": "CERSAI Report",
            "classification_confidence": 0.98,
            "extracted_fields": extract_fields("CERSAI Report", text),
        }
    ]
    manifest = {
        "reference_data": {
            "primary": {"applicant_name": "Ramesh Kumar", "pan_number": "ABCDE1234F"},
            "coapplicant_1": {"applicant_name": "Sita Kumar", "pan_number": "FGHIJ5678K"},
        },
        "documents": [
            {
                "source_document_id": "cersai-1",
                # Deliberately wrong: debtor evidence must override this mapping.
                "applicant_role": "primary",
                "document_type": "CERSAI Report",
                "pages": [1],
            }
        ],
    }

    result = compare_processed_pages(pages, manifest)

    assert pages[0]["person_id"] == "coapplicant_1"
    assert pages[0]["extracted_fields"]["_provided_mapping"]["provided_person_id"] == "primary"
    assert result["anomalies"] == []
    assert result["checked_fields"] == 2
    assert result["matched_fields"] == 2


def test_asset_based_cersai_has_no_applicant_or_pan_contract() -> None:
    text = """Asset Based Search Report
Search Criteria Entered
Asset Category
Immovable
Survey Number
42
Search Output Details
Co-Applicant SITA KUMAR PAN FGHIJ5678K
"""
    pages = [
        {
            "page_number": 145,
            "page_type": "digital",
            "is_readable": True,
            "ocr_text": text,
            "ocr_confidence": 1.0,
            "document_type": "CERSAI Report",
            "classification_confidence": 1.0,
            "extracted_fields": extract_fields("CERSAI Report", text),
        },
        {
            "page_number": 146,
            "page_type": "digital",
            "is_readable": True,
            "ocr_text": "--- End Of Report --- CERSAI",
            "ocr_confidence": 1.0,
            "document_type": "CERSAI Report",
            "classification_confidence": 1.0,
            "extracted_fields": {},
        },
    ]
    manifest = {
        "reference_data": {
            "primary": {"applicant_name": "Ramesh Kumar", "pan_number": "ABCDE1234F"},
            "coapplicant_1": {"applicant_name": "Sita Kumar", "pan_number": "FGHIJ5678K"},
        },
        "documents": [
            {
                "source_document_id": "file-0022",
                # A stale/default mapping must not turn an asset search into a
                # primary-applicant identity document.
                "applicant_role": "primary",
                "document_type": "CERSAI Report",
                "pages": [145, 146],
            }
        ],
    }

    result = compare_processed_pages(
        pages,
        manifest,
        source_documents=[
            {
                "source_document_id": "file-0022",
                "original_filename": "CERSAI_For_Asset_Based_Search.pdf",
                "internal_page_start": 145,
                "internal_page_end": 146,
            }
        ],
    )

    assert result["anomalies"] == []
    assert result["checked_fields"] == 0
    assert result["matched_fields"] == 0
    assert all(page["person_id"] is None for page in pages)
    assert all(page["applicant_role"] is None for page in pages)
    assert all(
        page["extracted_fields"]["_ownership"]["document_scope"] == "loan_level" for page in pages
    )
    assert result["source_classifications"][0]["provided_person_ids"] == []
    assert result["source_classifications"][0]["predicted_person_id"] is None
    assert "CERSAI Report" not in result["people_verification"]["primary"]["documents"]


def test_multipage_bank_statement_does_not_require_name_on_continuation_pages() -> None:
    pages = [
        {
            "page_number": 47,
            "page_type": "digital",
            "is_readable": True,
            "ocr_text": "Bank Statement\nTransaction Date Narration Debit Credit Balance",
            "document_type": "Bank Statement",
            "extracted_fields": {},
        },
        {
            "page_number": 48,
            "page_type": "digital",
            "is_readable": True,
            "ocr_text": "Bank Statement continuation\nTransaction Date Narration Debit Credit Balance",
            "document_type": "Bank Statement",
            "extracted_fields": {},
        },
    ]
    result = compare_processed_pages(
        pages,
        {
            "reference_data": {"primary": {"applicant_name": "Ramesh Kumar"}},
            "documents": [
                {
                    "source_document_id": "statement-1",
                    "applicant_role": "primary",
                    "document_type": "Bank Statement",
                    "pages": [47, 48],
                }
            ],
        },
    )

    assert not any(item["rule_id"] == "APPLICANT_NAME_NOT_FOUND" for item in result["anomalies"])


def test_cam_uses_requested_amount_and_cross_page_sanction_table() -> None:
    pages = [
        {
            "page_number": 101,
            "page_type": "digital",
            "is_readable": True,
            "ocr_text": """CREDIT APPROVAL MEMO
APPLICATION DETAILS
Requested Loan Amount
275000.00
""",
            "document_type": "CAM",
            "classification_confidence": 0.99,
            "extracted_fields": {"requested_amount": "275000"},
        },
        {
            "page_number": 106,
            "page_type": "digital",
            "is_readable": True,
            "ocr_text": """CREDIT APPROVAL MEMO
Sanction Loan Amount
Sanction Tenure
Advance EMI
Sanction Rate
Sanction EMI
Sanction Date
Sanction Remarks
Username
275000.000000
60
-
26.00
8,234.00
20-June-2026
Approved
msfc1063
""",
            "document_type": "CAM",
            "classification_confidence": 0.99,
            "extracted_fields": {},
        },
    ]
    manifest = {
        "reference_data": {
            "primary": {"loan_amount": "275000", "sanction_amount": "275000"},
        },
        "documents": [
            {
                "source_document_id": "cam-1",
                "applicant_role": "primary",
                "document_type": "CAM",
                "pages": [101, 106],
                "expected_fields": {"loan_amount": "275000", "sanction_amount": "275000"},
            }
        ],
    }

    result = compare_processed_pages(pages, manifest)

    assert result["anomalies"] == []
    assert result["checked_fields"] == 2
    assert result["matched_fields"] == 2


def test_aadhaar_address_comparison_includes_separate_relationship_fields() -> None:
    pages = [
        {
            "page_number": 241,
            "page_type": "digital",
            "is_readable": True,
            "ocr_text": "DigiLocker verified e-Aadhaar\nS/O: Unkar Lal\nAddress\nSemli Bakhta 326502",
            "document_type": "Aadhaar",
            "classification_confidence": 0.99,
            "extracted_fields": {
                "relationship_qualifier": "S/O",
                "related_person_name": "Unkar Lal",
                "address": "mehar basti, semli bakhta, Semlibakta, Jhalawar, Rajasthan, 326502",
            },
        }
    ]
    manifest = {
        "reference_data": {"primary": {"address": "S/O: Unkar Lal"}},
        "documents": [
            {
                "source_document_id": "aadhaar-1",
                "applicant_role": "primary",
                "document_type": "Aadhaar",
                "pages": [241],
                "expected_fields": {"address": "S/O: Unkar Lal"},
            }
        ],
    }

    result = compare_processed_pages(pages, manifest)

    assert result["anomalies"] == []
    assert result["checked_fields"] == 1
    assert result["matched_fields"] == 1


def test_mapped_verification_rejects_address_like_applicant_name_candidate() -> None:
    pages = [
        {
            "page_number": 1,
            "page_type": "digital",
            "is_readable": True,
            "ocr_text": "Application Form\nApplicant Name\nSemali Bakhata",
            "document_type": "Application Form",
            "classification_confidence": 0.98,
            "extracted_fields": {"applicant_name": "Semali Bakhata"},
        }
    ]
    manifest = {
        "reference_data": {"primary": {"applicant_name": "Peeru Lal"}},
        "documents": [
            {
                "source_document_id": "file-0001",
                "applicant_role": "primary",
                "document_type": "Application Form",
                "pages": [1],
            }
        ],
    }

    result = compare_processed_pages(pages, manifest)

    assert pages[0]["extracted_fields"]["applicant_name"] is None
    assert not any(item["rule_id"] == "APPLICANT_NAME_MISMATCH" for item in result["anomalies"])
    assert not any("NAME_EXTRACTION" in item["rule_id"] for item in result["anomalies"])
    assert "Semali Bakhata" not in _anomaly_text(result["anomalies"])


def test_pan_mapped_to_property_deed_suppresses_third_party_name_evidence() -> None:
    pages = [
        {
            "page_number": 1,
            "page_type": "scanned",
            "is_readable": True,
            "ocr_text": (
                "Endorsement of Execution\n"
                "Name: MOHAN LAL Age: 40\n"
                "The lease deed or allotment order issued by the Gram Panchayat"
            ),
            "ocr_confidence": 0.84,
            "document_type": "PAN",
            "classification_confidence": 0.65,
            "detection_method": "inherited",
            "extracted_fields": {"applicant_name": "MOHAN LAL", "dob": "40"},
        }
    ]
    manifest = {
        "reference_data": {
            "coapplicant_1": {
                "applicant_name": "Unkar Lal",
                "date_of_birth": "05-June-1961",
            }
        },
        "documents": [
            {
                "source_document_id": "auto-0001-pan",
                "applicant_role": "coapplicant_1",
                "document_type": "PAN",
                "pages": [1],
            }
        ],
    }

    result = compare_processed_pages(pages, manifest)

    text = _anomaly_text(result["anomalies"])
    assert "MOHAN LAL" not in text
    assert not any("APPLICANT_NAME_MISMATCH" in item["rule_id"] for item in result["anomalies"])
    assert not any("DATE_OF_BIRTH_MISMATCH" in item["rule_id"] for item in result["anomalies"])


def test_zip_source_application_form_is_verified_as_one_merged_document() -> None:
    pages = [
        {
            "page_number": 1,
            "page_type": "digital",
            "is_readable": True,
            "ocr_text": "Application Form\nApplicant Name\nSemali Bakhata",
            "document_type": "Unknown",
            "classification_confidence": 0.0,
            "extracted_fields": {"applicant_name": "Semali Bakhata"},
        },
        {
            "page_number": 2,
            "page_type": "digital",
            "is_readable": True,
            "ocr_text": "Application Form\nMobile Number\n9000000001",
            "document_type": "Application Form",
            "classification_confidence": 0.91,
            "extracted_fields": {"phone_number": "9000000001"},
        },
        {
            "page_number": 3,
            "page_type": "digital",
            "is_readable": True,
            "ocr_text": "CO-APPLICANT KYC DETAILS\nPAN\nTSTAA0001T",
            "document_type": "Unknown",
            "classification_confidence": 0.0,
            "extracted_fields": {"pan_number": "TSTAA0001T"},
        },
    ]
    reference_data = {
        "primary": {
            "applicant_name": "Peeru Lal",
            "phone_number": "9000000001",
            "pan_number": "TSTAA0001T",
        }
    }
    source_documents = [
        {
            "source_document_id": "file-0001",
            "original_filename": "Applicant/application-form.pdf",
            "file_type": "pdf",
            "page_count": 3,
            "internal_page_start": 1,
            "internal_page_end": 3,
        }
    ]
    automatic_index = build_automatic_document_index(
        pages,
        reference_data,
        source_documents=source_documents,
    )

    assert automatic_index["documents"][0]["document_type"] == "Application Form"
    assert automatic_index["documents"][0]["pages"] == [1, 2, 3]
    assert (
        automatic_index["documents"][0]["auto_mapping"]["detection_method"]
        == "zip_source_document_classification"
    )

    result = compare_processed_pages(
        pages,
        {"reference_data": reference_data, "documents": automatic_index["documents"]},
        source_documents=source_documents,
    )

    assert result["checked_fields"] >= 3
    assert result["matched_fields"] >= 2
    assert not any(
        item["severity"] == "HIGH" and "APPLICANT_NAME" in item["rule_id"]
        for item in result["anomalies"]
    )
    assert pages[0]["extracted_fields"]["applicant_name"] is None
    assert not any("NAME_EXTRACTION" in item["rule_id"] for item in result["anomalies"])
    assert "Semali Bakhata" not in _anomaly_text(result["anomalies"])
    name_not_found = next(
        item for item in result["anomalies"] if item["rule_id"] == "APPLICANT_NAME_NOT_FOUND"
    )
    assert name_not_found["source_filename"] == "Applicant/application-form.pdf"
    assert name_not_found["source_segment"] == "1-3"


def test_passbook_unique_account_match_makes_missing_name_non_blocking() -> None:
    pages = [
        {
            "page_number": 61,
            "page_type": "digital",
            "is_readable": True,
            "ocr_text": (
                "PASSBOOK\nAccount Number: 222233334444\nIFSC: PUNB0001234\nAccount particulars"
            ),
            "document_type": "Passbook",
            "classification_confidence": 0.98,
            "extracted_fields": {
                "account_number": "222233334444",
                "ifsc": "PUNB0001234",
            },
        }
    ]
    reference_data = {
        "primary": {
            "applicant_name": "Kala Singh",
            "account_number": "111122223333",
        },
        "coapplicant_1": {
            "applicant_name": "Seeta Seeta",
            "account_number": "222233334444",
            "ifsc": "PUNB0001234",
        },
    }

    result = compare_processed_pages(
        pages,
        {
            "reference_data": reference_data,
            "documents": [
                {
                    "source_document_id": "passbook-1",
                    "applicant_role": "coapplicant_1",
                    "document_type": "Passbook",
                    "pages": [61],
                }
            ],
        },
    )

    assert result["checked_fields"] == 2
    assert result["matched_fields"] == 2
    assert not any(item["rule_id"] == "APPLICANT_NAME_NOT_FOUND" for item in result["anomalies"])


def test_passbook_account_match_does_not_hide_conflicting_holder_name() -> None:
    pages = [
        {
            "page_number": 61,
            "page_type": "digital",
            "is_readable": True,
            "ocr_text": (
                "PASSBOOK\nAccount Number: 222233334444\n"
                "IFSC: PUNB0001234\nAccount Holder: Another Person"
            ),
            "document_type": "Passbook",
            "classification_confidence": 0.98,
            "extracted_fields": {
                "account_holder_name": "Another Person",
                "account_number": "222233334444",
                "ifsc": "PUNB0001234",
            },
        }
    ]

    result = compare_processed_pages(
        pages,
        {
            "reference_data": {
                "coapplicant_1": {
                    "applicant_name": "Seeta Seeta",
                    "account_number": "222233334444",
                    "ifsc": "PUNB0001234",
                },
            },
            "documents": [
                {
                    "source_document_id": "passbook-1",
                    "applicant_role": "coapplicant_1",
                    "document_type": "Passbook",
                    "pages": [61],
                }
            ],
        },
    )

    assert any(item["rule_id"] == "APPLICANT_NAME_MISMATCH" for item in result["anomalies"])


def test_passbook_shared_account_does_not_replace_holder_identity() -> None:
    pages = [
        {
            "page_number": 61,
            "page_type": "digital",
            "is_readable": True,
            "ocr_text": "PASSBOOK\nAccount Number: 222233334444\nIFSC: PUNB0001234",
            "document_type": "Passbook",
            "classification_confidence": 0.98,
            "extracted_fields": {
                "account_number": "222233334444",
                "ifsc": "PUNB0001234",
            },
        }
    ]

    result = compare_processed_pages(
        pages,
        {
            "reference_data": {
                "primary": {
                    "applicant_name": "Kala Singh",
                    "account_number": "222233334444",
                },
                "coapplicant_1": {
                    "applicant_name": "Seeta Seeta",
                    "account_number": "222233334444",
                    "ifsc": "PUNB0001234",
                },
            },
            "documents": [
                {
                    "source_document_id": "joint-passbook-1",
                    "applicant_role": "coapplicant_1",
                    "document_type": "Passbook",
                    "pages": [61],
                }
            ],
        },
    )

    assert any(item["rule_id"] == "APPLICANT_NAME_NOT_FOUND" for item in result["anomalies"])


def test_loan_level_field_checks_run_once_across_fragments() -> None:
    pages = [
        {
            "page_number": 1,
            "page_type": "digital",
            "is_readable": True,
            "ocr_text": "Loan Agreement page 1",
            "document_type": "Loan Agreement",
            "extracted_fields": {},
        },
        {
            "page_number": 2,
            "page_type": "digital",
            "is_readable": True,
            "ocr_text": "Loan Agreement Borrower RAMESH KUMAR Loan Amount 500000",
            "document_type": "Loan Agreement",
            "extracted_fields": {"borrower_name": "RAMESH KUMAR", "loan_amount": "500000"},
        },
        {
            "page_number": 3,
            "page_type": "digital",
            "is_readable": True,
            "ocr_text": "Loan Agreement continuation",
            "document_type": "Loan Agreement",
            "extracted_fields": {},
        },
    ]
    result = compare_processed_pages(
        pages,
        {
            "loan_id": "MAP-LA",
            "reference_data": {
                "primary": {"applicant_name": "Ramesh Kumar", "loan_amount": "500000"},
            },
            "documents": [
                {
                    "source_document_id": "la-1",
                    "applicant_role": "primary",
                    "document_type": "Loan Agreement",
                    "pages": [1],
                },
                {
                    "source_document_id": "la-2",
                    "applicant_role": "primary",
                    "document_type": "Loan Agreement",
                    "pages": [2],
                },
                {
                    "source_document_id": "la-3",
                    "applicant_role": "primary",
                    "document_type": "Loan Agreement",
                    "pages": [3],
                },
            ],
        },
    )

    assert result["anomalies"] == []
    assert result["checked_fields"] == 2
    assert result["matched_fields"] == 2


def test_aadhaar_front_and_back_are_verified_as_one_document_set() -> None:
    pages = [
        {
            "page_number": 1,
            "page_type": "digital",
            "is_readable": True,
            "ocr_text": "Aadhaar Name: RADHA BAI Date of Birth: 01-01-1962",
            "document_type": "Aadhaar",
            "extracted_fields": {"applicant_name": "RADHA BAI", "dob": "1962-01-01"},
        },
        {
            "page_number": 2,
            "page_type": "scanned",
            "is_readable": True,
            "ocr_text": "Address: W/O Ukar Lal Rajasthan 326502",
            "document_type": "Aadhaar",
            "extracted_fields": {"address": "W/O Ukar Lal Rajasthan 326502", "pin_code": "326502"},
        },
    ]
    result = compare_processed_pages(
        pages,
        {
            "reference_data": {
                "coapplicant_2": {
                    "applicant_name": "Radha Bai",
                    "date_of_birth": "1962-01-01",
                    "address": "W/O Ukar Lal Rajasthan 326502",
                    "pin_code": "326502",
                }
            },
            "documents": [
                {
                    "source_document_id": "front",
                    "applicant_role": "coapplicant_2",
                    "document_type": "Aadhaar",
                    "pages": [1],
                },
                {
                    "source_document_id": "back",
                    "applicant_role": "coapplicant_2",
                    "document_type": "Aadhaar",
                    "pages": [2],
                },
            ],
        },
    )
    assert result["anomalies"] == []
    assert result["checked_fields"] == 4
    assert result["matched_fields"] == 4


def _application() -> int:
    init_db()
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO applications (loan_id, applicant_name, product_type, branch)
            VALUES ('MAP-001', 'Ramesh Kumar', 'LAP', 'Delhi')
            """
        )
        return int(cursor.lastrowid)


def test_mapped_verification_uses_mapping_and_flags_pan_mismatch(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "mapped.db")
    monkeypatch.setattr("services.mapped_verification.open_pdf", lambda _path: _FakeDocument(20))
    monkeypatch.setattr(
        "services.mapped_verification.convert_page_to_image",
        lambda _page, output: str(output),
    )
    monkeypatch.setattr(
        "services.mapped_verification.run_ocr_on_page",
        lambda path: {
            "ocr_text": (
                "Name: Ramesh Kumar\nPermanent Account Number ZZZZZ9999Z"
                if "page_14" in path
                else "Name: Ramesh Kumar\n1234 5678 9012"
            ),
            "is_readable": True,
            "confidence": 0.96,
        },
    )
    application_id = _application()

    result = run_mapped_verification(
        tmp_path / "loan.pdf",
        application_id,
        {
            "loan_id": "MAP-001",
            "reference_data": {
                "aadhaar_number": "123456789012",
                "pan_number": "ABCDE1234F",
            },
            "documents": [
                {
                    "document_type": "Aadhaar",
                    "pages": [12],
                    "expected_fields": {"aadhaar_number": "123456789012"},
                },
                {
                    "document_type": "PAN",
                    "pages": [14],
                    "expected_fields": {"pan_number": "ABCDE1234F"},
                },
            ],
        },
        output_dir=tmp_path / "processed",
    )

    assert result["mapped_pages_processed"] == 2
    assert result["checked_fields"] == 2
    assert result["matched_fields"] == 1
    assert [item["rule_id"] for item in result["anomalies"]] == ["PAN_NUMBER_MISMATCH"]
    assert result["reviewer_summary"]["overall_status"] == "HIGH_RISK"
    assert result["reviewer_summary"]["pages_to_review"] == [14]
    assert result["reviewer_summary"]["review_items"][0]["expected_masked"] == "******234F"
    assert load_reviewer_summary(application_id) == result["reviewer_summary"]


def test_mapped_verification_uses_embedded_text_without_running_ocr(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "digital.db")
    document = _FakeDocument(1)
    document.pages[0] = _DigitalPage(
        "INCOME TAX DEPARTMENT\nName: Ramesh Kumar\n"
        "Permanent Account Number ABCDE1234F\nDigital PAN document"
    )
    monkeypatch.setattr("services.mapped_verification.open_pdf", lambda _path: document)

    def must_not_run(*_args, **_kwargs):
        raise AssertionError("Digital mapped pages must not be rendered or sent to an OCR API")

    monkeypatch.setattr("services.mapped_verification.convert_page_to_image", must_not_run)
    monkeypatch.setattr("services.mapped_verification.run_ocr_on_page", must_not_run)
    application_id = _application()

    result = run_mapped_verification(
        tmp_path / "digital.pdf",
        application_id,
        {
            "loan_id": "MAP-DIGITAL",
            "reference_data": {"pan_number": "ABCDE1234F"},
            "documents": [
                {
                    "document_type": "PAN",
                    "pages": [1],
                    "expected_fields": {"pan_number": "ABCDE1234F"},
                }
            ],
        },
        output_dir=tmp_path / "processed",
    )

    assert result["matched_fields"] == 1
    assert result["digital_pages_processed"] == 1
    assert result["ocr_pages_processed"] == 0
    with get_connection() as connection:
        page = connection.execute(
            """
            SELECT page_type, detection_method, ocr_confidence
            FROM pages WHERE application_id = ?
            """,
            (application_id,),
        ).fetchone()
    # Diet: pages no longer carries image_path (ws-a data diet).
    assert dict(page) == {
        "page_type": "digital",
        "detection_method": "provided_mapping_embedded_text",
        "ocr_confidence": 1.0,
    }


def test_reviewer_summary_escalates_many_high_risk_anomalies() -> None:
    anomalies = [
        {
            "rule_id": f"RULE_{number}",
            "severity": "HIGH",
            "page_number": number,
            "reason": "Critical difference",
        }
        for number in (2, 4, 6)
    ]
    summary = build_reviewer_summary(
        total_pages=30,
        anomalies=anomalies,
        checked_fields=5,
        matched_fields=2,
    )

    assert summary["overall_status"] == "FULL_MANUAL_REVIEW"
    assert summary["pages_to_review"] == [2, 4, 6]
    assert "Completely check" in summary["recommendation"]


def test_reviewer_summary_is_clean_without_anomalies() -> None:
    summary = build_reviewer_summary(
        total_pages=10,
        anomalies=[],
        checked_fields=4,
        matched_fields=4,
    )
    assert summary["overall_status"] == "CLEAN"
    assert summary["pages_to_review"] == []


def test_manifest_normalizes_multi_person_contract_and_legacy_contract() -> None:
    current = VerificationManifest.model_validate(
        {
            "loan_id": "MAP-MULTI",
            "people": {
                "primary": {"applicant_name": "Ramesh", "pan_number": "ABCDE1234F"},
                "coapplicant_1": {"applicant_name": "Sita", "pan_number": "FGHIJ5678K"},
            },
            "document_index": [
                {"person_id": "primary", "document_type": "PAN", "pages": [1]},
                {"person_id": "coapplicant_1", "document_type": "PAN", "pages": [2]},
            ],
        }
    )
    assert sorted(current.people) == ["coapplicant_1", "primary"]
    assert current.pipeline_payload()["documents"][1]["applicant_role"] == "coapplicant_1"

    legacy = VerificationManifest.model_validate(
        {
            "loan_id": "MAP-LEGACY",
            "reference_data": {"pan_number": "ABCDE1234F"},
            "documents": [{"document_type": "PAN", "pages": [1]}],
        }
    )
    assert legacy.people["primary"].pan_number == "ABCDE1234F"


def test_manifest_allows_required_document_without_pages_for_missing_check() -> None:
    manifest = VerificationManifest.model_validate(
        {
            "loan_id": "MAP-MISSING",
            "people": {"primary": {"applicant_name": "Ramesh"}},
            "document_index": [
                {"person_id": "primary", "document_type": "PAN", "pages": [1]},
                {
                    "person_id": "primary",
                    "document_type": "Utility Bill",
                    "pages": [],
                    "required": True,
                },
            ],
        }
    )

    assert manifest.document_index[1].pages == []


def test_manifest_allows_automatic_document_identification_without_index() -> None:
    manifest = VerificationManifest.model_validate(
        {
            "loan_id": "MAP-AUTO",
            "people": {"primary": {"applicant_name": "Ramesh Kumar"}},
        }
    )

    assert manifest.document_index == []
    assert manifest.pipeline_payload()["documents"] == []


def test_company_data_and_manual_index_compose_without_pipeline_changes() -> None:
    reference = LocalJsonCompanyDataProvider(
        {
            "loan_id": "MAP-COMPOSE",
            "people": {"primary": {"pan_number": "ABCDE1234F"}},
        }
    ).get_reference_data("MAP-COMPOSE")
    assert isinstance(reference, CompanyReferenceData)
    index = ManualDocumentIndexProvider(
        [{"person_id": "primary", "document_type": "PAN", "pages": [3]}]
    ).get_document_index("unused.pdf")

    manifest = compose_verification_manifest(reference, index)

    assert manifest.loan_id == "MAP-COMPOSE"
    assert manifest.document_index[0].pages == [3]
    assert manifest.pipeline_payload()["reference_data"]["primary"]["pan_number"] == "ABCDE1234F"


def test_manifest_rejects_unknown_person_and_conflicting_page_assignment() -> None:
    import pytest

    with pytest.raises(ValueError, match="unknown people"):
        VerificationManifest.model_validate(
            {
                "loan_id": "MAP-BAD-PERSON",
                "people": {"primary": {}},
                "document_index": [
                    {"person_id": "coapplicant_1", "document_type": "PAN", "pages": [1]}
                ],
            }
        )

    with pytest.raises(ValueError, match="conflicting mappings"):
        VerificationManifest.model_validate(
            {
                "loan_id": "MAP-BAD-PAGE",
                "people": {"primary": {}, "coapplicant_1": {}},
                "document_index": [
                    {"person_id": "primary", "document_type": "PAN", "pages": [1]},
                    {"person_id": "coapplicant_1", "document_type": "PAN", "pages": [1]},
                ],
            }
        )


def test_multi_person_verification_checks_every_distinct_occurrence_and_wrong_owner(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "multi.db")
    monkeypatch.setattr("services.mapped_verification.open_pdf", lambda _path: _FakeDocument(4))
    monkeypatch.setattr(
        "services.mapped_verification.convert_page_to_image",
        lambda _page, output: str(output),
    )
    page_text = {
        "page_1": "Name: Ramesh Kumar\n1111 2222 3333",
        "page_2": "Name: Ramesh Kumar\n1111 2222 9999",
        "page_3": "Name: Ramesh Kumar\nABCDE1234F",
        # Co-applicant page accidentally contains the primary applicant's PAN.
        "page_4": "Name: Ramesh Kumar\nABCDE1234F",
    }

    def fake_ocr(path: str) -> dict:
        text = next(value for key, value in page_text.items() if key in path)
        return {"ocr_text": text, "is_readable": True, "confidence": 0.95}

    monkeypatch.setattr("services.mapped_verification.run_ocr_on_page", fake_ocr)
    application_id = _application()
    manifest = VerificationManifest.model_validate(
        {
            "loan_id": "MAP-MULTI",
            "people": {
                "primary": {
                    "applicant_name": "Ramesh Kumar",
                    "aadhaar_number": "111122223333",
                    "pan_number": "ABCDE1234F",
                },
                "coapplicant_1": {
                    "applicant_name": "Sita Kumar",
                    "pan_number": "FGHIJ5678K",
                },
            },
            "document_index": [
                {
                    "person_id": "primary",
                    "document_type": "Aadhaar",
                    "pages": [1, 2],
                    "expected_fields": {"aadhaar_number": "111122223333"},
                },
                {
                    "person_id": "primary",
                    "document_type": "PAN",
                    "pages": [3],
                    "expected_fields": {"pan_number": "ABCDE1234F"},
                },
                {
                    "person_id": "coapplicant_1",
                    "document_type": "PAN",
                    "pages": [4],
                    "expected_fields": {"pan_number": "FGHIJ5678K"},
                },
            ],
        }
    )

    result = run_mapped_verification(
        tmp_path / "loan.pdf",
        application_id,
        manifest.pipeline_payload(),
        output_dir=tmp_path / "processed",
    )

    assert result["checked_fields"] == 4
    assert result["matched_fields"] == 2
    assert {(item["rule_id"], item["page_number"]) for item in result["anomalies"]} == {
        ("AADHAAR_NUMBER_MISMATCH", 2),
        ("INDEX_MAPPING_SUSPECTED", 4),
    }
    suspected = next(item for item in result["anomalies"] if item["page_number"] == 4)
    assert suspected["person_id"] == "coapplicant_1"
    assert suspected["matched_person_id"] == "primary"
    assert result["people_verification"]["primary"]["status"] == "NEEDS_REVIEW"
    assert result["people_verification"]["coapplicant_1"]["status"] == "NEEDS_REVIEW"
    assert result["reviewer_summary"]["pages_to_review"] == [2, 4]


def test_mapped_verification_flags_missing_required_document_and_checks_utility_bill(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "missing.db")
    monkeypatch.setattr("services.mapped_verification.open_pdf", lambda _path: _FakeDocument(2))
    monkeypatch.setattr(
        "services.mapped_verification.convert_page_to_image",
        lambda _page, output: str(output),
    )
    monkeypatch.setattr(
        "services.mapped_verification.run_ocr_on_page",
        lambda _path: {
            "ocr_text": (
                "Electricity Bill\nConsumer Name: Ramesh Kumar\nService Address\n"
                "12 Market Road\nDelhi 110001"
            ),
            "is_readable": True,
            "confidence": 0.94,
        },
    )
    application_id = _application()
    manifest = VerificationManifest.model_validate(
        {
            "loan_id": "MAP-MISSING",
            "people": {
                "primary": {
                    "applicant_name": "Ramesh Kumar",
                    "address": "12 Market Road Delhi",
                    "pin_code": "110001",
                }
            },
            "document_index": [
                {"person_id": "primary", "document_type": "Utility Bill", "pages": [1]},
                {"person_id": "primary", "document_type": "PAN", "pages": [], "required": True},
            ],
        }
    )

    result = run_mapped_verification(
        tmp_path / "loan.pdf",
        application_id,
        manifest.pipeline_payload(),
        output_dir=tmp_path / "processed",
    )

    assert result["mapped_pages_processed"] == 1
    assert result["checked_fields"] == 0
    assert result["matched_fields"] == 0
    assert [item["rule_id"] for item in result["anomalies"]] == ["DOCUMENT_MISSING"]
    assert result["anomalies"][0]["document_type"] == "PAN"
    assert (
        result["people_verification"]["primary"]["documents"]["Utility Bill"]["status"]
        == "NOT_CHECKED"
    )
    assert result["people_verification"]["primary"]["documents"]["PAN"]["status"] == "NEEDS_REVIEW"


def test_name_match_ignores_missing_ocr_whitespace() -> None:
    assert verify_name("PEERULAL", "Peeru Lal").match is True


def test_mapped_name_and_address_accept_trusted_indian_variants() -> None:
    from services.mapped_verification import _mapped_field_matches

    person = {
        "applicant_name": "Suthar Anupkumar",
        "father_name": "Chetanbhai Mohanlal Suthar",
        "permanent_address": "MODIVAS HARNIYAV AHMEDABAD 382435",
        "communication_address": "B 402 PANDIT DINDAYAL 2 HATHIJAN AHMEDABAD 382445",
    }
    assert _mapped_field_matches(
        "applicant_name",
        "ANUPKUMAR CHETANBHAI SUTHAR",
        person["applicant_name"],
        person,
    )
    assert _mapped_field_matches(
        "address",
        "B-402 PANDIT DINDAYAL-2 HATHIJAN AHMEDABAD 382445",
        person["permanent_address"],
        person,
    )
