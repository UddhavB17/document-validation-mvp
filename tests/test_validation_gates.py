from services.field_extractor import extract_fields
from services.validation_gates import (
    attach_field_provenance,
    compatible_field_for_document,
    field_reliable_for_validation,
    has_bank_statement_anchor,
)


def test_statement_period_fields_alone_are_not_a_bank_statement_anchor() -> None:
    assert not has_bank_statement_anchor(
        "Bank Statement",
        {
            "statement_period_start": "2026-07-31",
            "statement_period_end": "2026-07-31",
        },
    )


def test_account_identifier_can_anchor_a_bank_statement() -> None:
    assert has_bank_statement_anchor(
        "Bank Statement Account No. 123456789012",
        {},
    )


def test_transaction_column_signature_can_anchor_a_bank_statement() -> None:
    assert has_bank_statement_anchor(
        "Account Statement\nDate Narration Debit Credit Balance",
        {},
    )


def test_lender_statement_with_dr_cr_columns_is_a_bank_statement_anchor() -> None:
    assert has_bank_statement_anchor(
        "Customer's Statement of Account\n"
        "Name\nDAYARAM DEENA\nLoan Account No.\n221205302480415\n"
        "Date Particulars Dr. Cr. Balance",
        {"account_holder_name": "DAYARAM DEENA"},
    )


def test_repayment_schedule_continuation_is_not_a_bank_statement() -> None:
    assert not has_bank_statement_anchor(
        "Due Date Principal Interest Instalment Balance\n31/08/2026 2500 750 3250 447500",
        {
            "statement_period_start": "2026-08-31",
            "statement_period_end": "2027-08-31",
        },
    )


def test_disbursal_continuation_is_not_a_bank_statement() -> None:
    assert not has_bank_statement_anchor(
        "Foreclosure Letter or Statement of Account submitted by the customer at the time of disbursement",
        {
            "statement_period_start": "2026-07-31",
            "statement_period_end": "2026-07-31",
        },
    )


def test_insurer_local_application_id_is_not_loan_validation_evidence() -> None:
    page = {
        "ocr_text": (
            "Care Health Insurance Limited IRDAI Registration No. 148\n"
            "Group Care 360 Application Form\n"
            "Proposer Nominee Policy Sum Insured Premium\n"
            "Application No: 0030705"
        ),
        "extracted_fields": {"application_number": "0030705"},
    }

    assert not compatible_field_for_document("Insurance Form", "application_number", page)


def test_insurance_form_keeps_explicit_loan_account_id_as_validation_evidence() -> None:
    page = {
        "ocr_text": (
            "Care Health Insurance Limited IRDAI Registration No. 148\n"
            "Group Care 360 Application Form\n"
            "Proposer Nominee Policy Sum Insured Premium\n"
            "Loan Account No: 5000090002\nApplication No: 0030705"
        ),
        "extracted_fields": {"application_number": "5000090002"},
    }

    assert compatible_field_for_document("Insurance Form", "application_number", page)


def test_cached_page_counter_is_not_reliable_address_evidence() -> None:
    page = {
        "document_type": "Application Form",
        "classification_confidence": 0.99,
        "ocr_text": "PERMANENT ADDRESS\nPage 2 of 128",
        "extracted_fields": {"permanent_address": "Page 2 of 128"},
    }

    assert not field_reliable_for_validation(
        page,
        "permanent_address",
        "Page 2 of 128",
        expected_document_type="Application Form",
    )


def _synth_bbox(x0: float, y0: float, x1: float, y1: float) -> dict:
    return {
        "vertices": [
            {"x": x0, "y": y0},
            {"x": x1, "y": y0},
            {"x": x1, "y": y1},
            {"x": x0, "y": y1},
        ]
    }


def _synth_region(text: str, confidence, x0: float, y0: float, x1: float, y1: float) -> dict:
    region: dict = {"text": text, "bounding_box": _synth_bbox(x0, y0, x1, y1)}
    if confidence is not None:
        region["confidence"] = confidence
    return region


def _synth_page_via_public_path(
    body_conf,
    *,
    split_pin: bool = False,
    layout_current: str | None = None,
    layout_permanent: str | None = None,
) -> dict:
    current_value = "12 Synthetic Nagar Example Road Delhi 110001"
    permanent_value = "44 Synthetic Vas Example Lane Jaipur 302001"
    layout_current_value = layout_current if layout_current is not None else current_value
    layout_permanent_value = layout_permanent if layout_permanent is not None else permanent_value
    text = (
        "Application Form\n"
        f"Current Resi. Address: {current_value}\n"
        f"Permanent Resi. Address: {permanent_value}\n"
    )
    regions: list[dict] = [
        _synth_region("Current Resi Address", 0.98, 39, 457, 114, 464),
        _synth_region("Permanent Resi Address", 0.98, 39, 600, 114, 607),
        _synth_region("Unrelated High Value", 0.99, 10, 100, 50, 110),
        _synth_region("Mobile 9876543210", 0.99, 330, 453, 450, 470),
    ]
    if split_pin:
        current_body = layout_current_value.replace(" 110001", "").replace("110001", "").strip()
        permanent_body = layout_permanent_value.replace(" 302001", "").replace("302001", "").strip()
        current_pin = "110001" if "110001" in layout_current_value else "110001"
        permanent_pin = "302001" if "302001" in layout_permanent_value else "302001"
        regions += [
            _synth_region(current_body, body_conf, 133, 453, 308, 470),
            _synth_region(current_pin, 0.99, 221, 497, 343, 508),
            _synth_region(permanent_body, body_conf, 133, 596, 308, 613),
            _synth_region(permanent_pin, 0.99, 221, 640, 343, 651),
        ]
    else:
        regions += [
            _synth_region(layout_current_value, body_conf, 133, 453, 308, 470),
            _synth_region(layout_permanent_value, body_conf, 133, 596, 308, 613),
        ]
    fields = extract_fields(
        "Application Form", text, structured_content={"layout_regions": regions}
    )
    page = {
        "page_number": 1,
        "document_type": "Application Form",
        "classification_confidence": 0.95,
        "ocr_confidence": 0.95,
        "ocr_text": text,
        "extracted_fields": fields,
    }
    attach_field_provenance(page)
    return page


def test_low_layout_body_is_not_reliable_via_public_path() -> None:
    page = _synth_page_via_public_path(0.40)
    fields = page["extracted_fields"]
    # Identical text fallback is preserved as source value, but capped low.
    assert fields["current_address"] == "12 Synthetic Nagar Example Road Delhi 110001"
    assert fields["permanent_address"] == "44 Synthetic Vas Example Lane Jaipur 302001"
    for field in ("current_address", "permanent_address"):
        provenance = fields["_field_provenance"][field]
        assert provenance["field_confidence"] < 0.60
        assert not field_reliable_for_validation(page, field, fields[field])


def test_high_layout_body_remains_reliable_via_public_path() -> None:
    page = _synth_page_via_public_path(0.95)
    fields = page["extracted_fields"]
    for field in ("current_address", "permanent_address"):
        assert fields["_field_provenance"][field]["field_confidence"] >= 0.60
        assert field_reliable_for_validation(page, field, fields[field])


def test_high_pin_and_labels_do_not_inflate_low_body_via_public_path() -> None:
    page = _synth_page_via_public_path(0.40, split_pin=True)
    fields = page["extracted_fields"]
    for field in ("current_address", "permanent_address"):
        assert fields["_field_provenance"][field]["field_confidence"] == 0.40
        assert not field_reliable_for_validation(page, field, fields[field])


def test_text_only_extraction_uses_page_confidence() -> None:
    text = (
        "Application Form\n"
        "Current Resi. Address: 12 Synthetic Nagar Example Road Delhi 110001\n"
        "Permanent Resi. Address: 44 Synthetic Vas Example Lane Jaipur 302001\n"
    )
    fields = extract_fields("Application Form", text)
    assert "_address_region_evidence" not in fields
    page = {
        "page_number": 1,
        "document_type": "Application Form",
        "classification_confidence": 0.95,
        "ocr_confidence": 0.95,
        "ocr_text": text,
        "extracted_fields": fields,
    }
    attach_field_provenance(page)
    for field in ("current_address", "permanent_address"):
        assert field_reliable_for_validation(page, field, fields[field])


def test_changed_accepted_value_does_not_inherit_old_confidence() -> None:
    page = _synth_page_via_public_path(0.70)
    fields = page["extracted_fields"]
    # Simulate a later correction/recovery changing the value: new value must not inherit old.
    fields["current_address"] = "77 Changed Nagar New Road Delhi 110001"
    fields["permanent_address"] = "78 Changed Vas New Lane Jaipur 302001"
    attach_field_provenance(page)
    for field in ("current_address", "permanent_address"):
        assert fields["_field_provenance"][field]["field_confidence"] == 0.95
        assert field_reliable_for_validation(page, field, fields[field])


def test_zero_body_confidence_is_not_missing_via_public_path() -> None:
    page = _synth_page_via_public_path(0.0)
    fields = page["extracted_fields"]
    assert fields["current_address"] == "12 Synthetic Nagar Example Road Delhi 110001"
    for field in ("current_address", "permanent_address"):
        assert fields["_field_provenance"][field]["field_confidence"] == 0.0
        assert not field_reliable_for_validation(page, field, fields[field])


def test_absent_body_confidence_keeps_page_confidence_via_public_path() -> None:
    page = _synth_page_via_public_path(None)
    fields = page["extracted_fields"]
    assert "_address_region_evidence" not in fields
    for field in ("current_address", "permanent_address"):
        assert fields["_field_provenance"][field]["field_confidence"] == 0.95
        assert field_reliable_for_validation(page, field, fields[field])


def test_distinct_text_fallback_does_not_inherit_rejected_confidence() -> None:
    page = _synth_page_via_public_path(
        0.40,
        layout_current="99 Different Road Other Town 110001",
        layout_permanent="88 Other Vas Elsewhere City 302001",
    )
    fields = page["extracted_fields"]
    # Text fallback is distinct from the rejected layout candidate, so it keeps page confidence.
    assert fields["current_address"] == "12 Synthetic Nagar Example Road Delhi 110001"
    assert fields["permanent_address"] == "44 Synthetic Vas Example Lane Jaipur 302001"
    for field in ("current_address", "permanent_address"):
        assert fields["_field_provenance"][field]["field_confidence"] == 0.95
        assert field_reliable_for_validation(page, field, fields[field])


def test_missing_body_with_pin_attaches_no_evidence_via_public_path() -> None:
    page = _synth_page_via_public_path(None, split_pin=True)
    fields = page["extracted_fields"]
    assert fields["current_address"] == "12 Synthetic Nagar Example Road Delhi 110001"
    assert fields["permanent_address"] == "44 Synthetic Vas Example Lane Jaipur 302001"
    assert "_address_region_evidence" not in fields
    for field in ("current_address", "permanent_address"):
        assert fields["_field_provenance"][field]["field_confidence"] == 0.95
        assert field_reliable_for_validation(page, field, fields[field])
