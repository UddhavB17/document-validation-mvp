from services.legal_party_identity import legal_party_birth_dates


def _page(text: str, **overrides) -> dict:
    page = {
        "page_number": 152,
        "document_type": "Property Document",
        "page_type": "scanned",
        "is_readable": True,
        "ocr_confidence": 0.9769,
        "classification_confidence": 0.95,
        "ocr_text": text,
    }
    page.update(overrides)
    return page


def _trusted_person() -> dict:
    return {
        "coapplicant_2": {
            "applicant_name": "SAMPLE PERSON",
            "date_of_birth": "1977-08-09",
            "aadhaar_last4": "1234",
        }
    }


def _first_party_text() -> str:
    return '''MEMORANDUM BY DEPOSIT OF TITLE DEEDS
This Memorandum is made between the parties.
Smt. SAMPLE PERSON W/o Sh. SOME PERSON (DOB-01.01.1978) R/o Modelplace
Modeltown Raj. 302001 (Aadhar No. XXXX XXXX 1234) hereinafter referred as
"THE FIRST PARTIES/OWNERS".
IN WITNESS whereof the first parties/owners executed this Memorandum in the terms and conditions mentioned above.
Smt. SAMPLE PERSON W/o Sh. SOME PERSON (DOB-01.01.1978) R/o Modelplace
Modeltown Raj. 302001 (Aadhar No. XXXX XXXX 1234
(THE FIRST PARTIES/OWNERS):
(Authorized Person and on behalf of lender)
Sh. OFFICER NAME (DOB-02.02.1970)'''


def test_extracts_dob_from_first_party_identity_and_ignores_page_owner() -> None:
    observations = legal_party_birth_dates(
        [_page(_first_party_text(), person_id="primary")], _trusted_person()
    )

    assert observations == [
        {
            "person_id": "coapplicant_2",
            "field": "date_of_birth",
            "value": "1978-01-01",
            "document_type": "Property Document",
            "page_number": 152,
            "ocr_text": _first_party_text(),
            "page_type": "scanned",
        }
    ]


def test_does_not_extract_witness_or_lender_dob() -> None:
    text = '''MEMORANDUM BY DEPOSIT OF TITLE DEEDS
IN WITNESS whereof
Smt. SAMPLE PERSON W/o Sh. SOME PERSON (DOB-01.01.1978) R/o Modelplace
Modeltown Raj. 302001 (Aadhar No. XXXX XXXX 1234)
"THE FIRST PARTIES/OWNERS"
'''

    assert legal_party_birth_dates([_page(text)], _trusted_person()) == []


def test_does_not_use_ambiguous_trusted_last_four_match() -> None:
    people = {
        **_trusted_person(),
        "coapplicant_3": {
            "applicant_name": "SAMPLE PERSON",
            "date_of_birth": "1978-01-01",
            "aadhaar_number": "999999991234",
        },
    }

    assert legal_party_birth_dates([_page(_first_party_text())], people) == []


def test_rejects_low_quality_or_non_memo_pages_even_with_matching_owner() -> None:
    text = _first_party_text()
    poor = _page(text, ocr_confidence=0.72)
    wrong_type = _page(text, document_type="Sanction Letter", person_id="coapplicant_2")

    assert legal_party_birth_dates([poor, wrong_type], _trusted_person()) == []


def test_accepts_high_confidence_digital_page_without_ocr_score() -> None:
    page = _page(
        _first_party_text(),
        page_type="digital",
        ocr_confidence=None,
        classification_confidence=0.85,
    )

    assert legal_party_birth_dates([page], _trusted_person())[0]["value"] == "1978-01-01"


def test_requires_formatted_first_party_marker_and_masked_aadhaar() -> None:
    no_marker = (
        _first_party_text()
        .replace('"THE FIRST PARTIES/OWNERS"', "the first parties/owners")
        .replace("(THE FIRST PARTIES/OWNERS):", "the first parties/owners")
    )
    no_mask = _first_party_text().replace("XXXX XXXX 1234", "1111 2222 1234")

    assert legal_party_birth_dates([_page(no_marker)], _trusted_person()) == []
    assert legal_party_birth_dates([_page(no_mask)], _trusted_person()) == []
