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
