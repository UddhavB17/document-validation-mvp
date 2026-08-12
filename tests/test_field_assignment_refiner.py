import services.field_assignment_refiner as field_assignment_refiner
from services.field_assignment_refiner import _parse_toon_object, refine_field_assignments


def test_bank_table_labels_are_not_accepted_as_customer_values(monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_LLM_FIELD_ASSIGNMENT", "false")
    result = refine_field_assignments(
        document_type="Bank Statement",
        ocr_text="A/C HOLDER NAME A/C NUMEBER ACCOUNT TYPE खाता प्रकार",
        extracted_fields={
            "account_holder_name": "A/C NUMEBER",
            "account_type": "खाता प्रकार",
        },
    )
    assert result["account_holder_name"] is None
    assert result["account_type"] is None


def test_table_column_headings_are_not_accepted_as_names(monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_LLM_FIELD_ASSIGNMENT", "false")
    for value in ("Source", "Financer", "Issuing Authority", "Ration Card", "PHONE NO"):
        result = refine_field_assignments(
            document_type="Aadhaar",
            ocr_text=value,
            extracted_fields={"applicant_name": value},
        )
        assert result["applicant_name"] is None


def test_noisy_permanent_address_is_removed(monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_LLM_FIELD_ASSIGNMENT", "false")
    noisy_address = (
        "Driving License No Graduate Postgraduate Aadhaar No 641 "
        "Professionally qualified Mobile 8690456870 Business Constitution 335027"
    )

    result = refine_field_assignments(
        document_type="Application Form",
        ocr_text=noisy_address,
        extracted_fields={"permanent_address": noisy_address},
    )

    assert result["permanent_address"] is None
    assert result["_field_assignment"]["deterministic_changes"]["permanent_address"]["reason"] == (
        "label_or_placeholder_value"
    )


def test_page_counter_address_is_removed(monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_LLM_FIELD_ASSIGNMENT", "false")

    result = refine_field_assignments(
        document_type="Application Form",
        ocr_text="PERMANENT ADDRESS\nPage 2 of 128",
        extracted_fields={"permanent_address": "Page 2 of 128"},
    )

    assert result["permanent_address"] is None
    assert result["_field_assignment"]["deterministic_changes"]["permanent_address"]["reason"] == (
        "label_or_placeholder_value"
    )


def test_signed_aadhaar_xml_appendix_never_calls_llm_or_keeps_public_fields(monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_LLM_FIELD_ASSIGNMENT", "true")

    def unexpected_llm_call(**_kwargs):
        raise AssertionError("verification appendix must not be sent to the LLM")

    monkeypatch.setattr(field_assignment_refiner, "_assign_with_llm", unexpected_llm_call)
    result = refine_field_assignments(
        document_type="Aadhaar",
        ocr_text=(
            "Digitally signed e-Aadhaar XML\n"
            '<UidData uid="xxxxxxxx1641"><Poa pc="335027"/></UidData>\n'
            "CN=DS DIGITAL INDIA CORPORATION 3,postalCode=110003"
        ),
        extracted_fields={"pin_code": "'110003'", "related_person_name": "'Seeta'"},
    )

    assert result == {"_aadhaar_verification_appendix": True}


def test_cersai_never_uses_generic_llm_to_choose_a_debtor(monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_LLM_FIELD_ASSIGNMENT", "true")

    def unexpected_llm_call(**_kwargs):
        raise AssertionError("CERSAI debtor identity must come from Search Criteria")

    monkeypatch.setattr(field_assignment_refiner, "_assign_with_llm", unexpected_llm_call)
    result = refine_field_assignments(
        document_type="CERSAI Report",
        ocr_text=(
            "Asset Based Search Report\nSearch Criteria Entered\n"
            "Asset Category\nImmovable\nSearch Output Details\n"
            "Co-Applicant RADHA BAI PAN TSTCC0003T"
        ),
        extracted_fields={"cersai_search_type": "asset_based", "applicant_name": None},
    )

    assert result["applicant_name"] is None


def test_parse_field_assignment_accepts_json_and_fenced_json() -> None:
    raw = '{"fields": {"applicant_name": "Peeru Lal"}, "reason": "ok", "confidence": 0.9}'
    assert _parse_toon_object(raw)["fields"]["applicant_name"] == "Peeru Lal"
    fenced = "```json\n" + raw + "\n```"
    assert _parse_toon_object(fenced)["fields"]["applicant_name"] == "Peeru Lal"
    prose = "Here is the result:\n" + raw + "\nThanks"
    assert _parse_toon_object(prose)["fields"]["applicant_name"] == "Peeru Lal"


def test_parse_field_assignment_still_accepts_toon() -> None:
    toon = (
        "fields:\n"
        "  applicant_name: Peeru Lal\n"
        "reason: clear name\n"
        "confidence: 0.91\n"
    )
    assert _parse_toon_object(toon)["fields"]["applicant_name"] == "Peeru Lal"
