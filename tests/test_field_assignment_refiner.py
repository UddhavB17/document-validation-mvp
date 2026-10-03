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


def test_statement_counterparties_do_not_become_holder_evidence(monkeypatch) -> None:
    from services.field_extractor import extract_fields
    from services.person_ownership import identity_observations

    monkeypatch.setenv("ENABLE_LLM_FIELD_ASSIGNMENT", "true")

    def unexpected_llm(**_kwargs):
        raise AssertionError("Missing statement holders must not be guessed")

    monkeypatch.setattr(field_assignment_refiner, "_assign_with_llm", unexpected_llm)
    header = "Bank: Test Bank\nAccount Number: XXXX1234\n"
    transactions = (
        "TRANSACTIONS\nTransaction Date\n24/07/2026\nNarration\n"
        "Customer Name: Other Person\nUPI/TEST0000001/9876543210\n"
        "PAN ABCDE1234F\n"
    )
    fields = extract_fields("Bank Statement", header + transactions)
    refined = refine_field_assignments(
        document_type="Bank Statement", ocr_text=header + transactions, extracted_fields=fields
    )
    assert refined["account_holder_name"] is None
    assert refined["ifsc"] is None
    assert refined["pan_number"] is None
    assert refined["statement_period_end"] == "2026-07-24"
    refined["_generic_evidence"] = {"phone_numbers": ["9876543210"], "pan_numbers": ["ABCDE1234F"]}
    identity = identity_observations(
        [
            {
                "document_type": "Bank Statement",
                "ocr_text": header + transactions,
                "extracted_fields": refined,
            }
        ]
    )
    assert identity["phone_number"] == []
    assert identity["pan_number"] == []
    assert identity["applicant_name"] == []

    profile = header + "Customer Name: Actual Holder\nIFSC: REAL0000001\nPAN: TSTPA7022Z\n"
    fields = extract_fields("Bank Statement", profile + transactions)
    assert fields["account_holder_name"] == "Actual Holder"
    assert fields["ifsc"] == "REAL0000001"
    assert fields["pan_number"] == "TSTPA7022Z"


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
        "Professionally qualified Mobile 9000001027 Business Constitution 335027"
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
        extracted_fields={"pin_code": "'110003'", "related_person_name": "'Geeta'"},
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
            "Co-Applicant SUDHA BAI PAN TSTCC0003T"
        ),
        extracted_fields={"cersai_search_type": "asset_based", "applicant_name": None},
    )

    assert result["applicant_name"] is None


def test_parse_field_assignment_accepts_json_and_fenced_json() -> None:
    raw = '{"fields": {"applicant_name": "Veeru Lal"}, "reason": "ok", "confidence": 0.9}'
    assert _parse_toon_object(raw)["fields"]["applicant_name"] == "Veeru Lal"
    fenced = "```json\n" + raw + "\n```"
    assert _parse_toon_object(fenced)["fields"]["applicant_name"] == "Veeru Lal"
    prose = "Here is the result:\n" + raw + "\nThanks"
    assert _parse_toon_object(prose)["fields"]["applicant_name"] == "Veeru Lal"


def test_parse_field_assignment_still_accepts_toon() -> None:
    toon = "fields:\n  applicant_name: Veeru Lal\nreason: clear name\nconfidence: 0.91\n"
    assert _parse_toon_object(toon)["fields"]["applicant_name"] == "Veeru Lal"
