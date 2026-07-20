from services.checklist_engine import run_checks
from services.checklist_output import build_checklist_verification_response


def test_build_checklist_verification_response_counts_statuses() -> None:
    pages = [
        {
            "page_number": 1,
            "document_type": "PAN",
            "page_type": "digital",
            "classification_confidence": 0.96,
            "extracted_fields": {"pan_number": "BCXPL9010K"},
        }
    ]
    anomalies = [{"rule_id": "MISSING_DOC_S19", "s_no": 19, "reason": "Bank statement missing"}]

    result = build_checklist_verification_response(
        loan_file_id="LAP-1",
        pages=pages,
        anomalies=anomalies,
        product_type="LAP",
    )

    assert result.summary.total == 44
    assert result.summary.verified >= 1
    assert result.summary.missing >= 1

    pan_item = next(item for item in result.items if item.item_number == 7)
    assert pan_item.status == "verified"
    assert pan_item.confidence == "high"
    assert pan_item.extracted_fields["pan_number"] == "BCXPL9010K"

    bank_item = next(item for item in result.items if item.item_number == 19)
    assert bank_item.status == "missing"
    assert bank_item.flagged_reason == "missing_doc_s19"


def test_llm_fallback_source_is_tagged_from_page_fields() -> None:
    pages = [
        {
            "page_number": 1,
            "document_type": "PAN",
            "page_type": "digital",
            "classification_confidence": 0.90,
            "extracted_fields": {
                "pan_number": "BCXPL9010K",
                "_llm_field_extraction": {"status": "fields_extracted"},
            },
        }
    ]

    result = build_checklist_verification_response(
        loan_file_id="LAP-1",
        pages=pages,
        anomalies=[],
        product_type="LAP",
    )

    pan_item = next(item for item in result.items if item.item_number == 7)
    assert pan_item.extraction_source == "llm_fallback"


def test_false_condition_is_reported_as_not_applicable() -> None:
    result = build_checklist_verification_response(
        loan_file_id="LAP-1",
        pages=[],
        anomalies=[],
        product_type="LAP",
        system_data={"loan_amount": 1000000},
    )

    technical_item = next(item for item in result.items if item.item_number == 39)
    assert technical_item.status == "not_applicable"
    assert result.summary.not_applicable >= 1


def test_system_flag_can_verify_kyc_checklist_row() -> None:
    result = build_checklist_verification_response(
        loan_file_id="LAP-1",
        pages=[],
        anomalies=[],
        product_type="LAP",
        system_data={"kyc_details_checked": True},
    )

    kyc_item = next(item for item in result.items if item.item_number == 11)
    assert kyc_item.status == "verified"
    assert kyc_item.extracted_fields["kyc_details_checked"] == "True"


def test_complete_applicability_data_leaves_no_unknown_checklist_rows() -> None:
    system_data = {
        "loan_amount": 500000,
        "people": {"primary": {"role": "primary"}},
        "kyc_verified_in_graviton": True,
        "kyc_details_checked": True,
        "identity_mismatch_present": False,
        "vernacular_required": False,
        "manual_loan_agreement": False,
        "bt_undertaking_required": False,
        "internal_bt_topup_consent_required": False,
        "case_type": "fresh",
        "has_guarantor": False,
        "business_proof_required": False,
        "nach_registered": True,
        "assessed_income_documents_required": False,
        "insurance_consent_required": False,
    }
    anomalies = run_checks([], system_data, system_data, "LAP")
    result = build_checklist_verification_response(
        loan_file_id="LAP-1",
        pages=[],
        anomalies=anomalies,
        product_type="LAP",
        system_data=system_data,
    )

    assert len(result.items) == 44
    assert result.summary.unknown == 0
