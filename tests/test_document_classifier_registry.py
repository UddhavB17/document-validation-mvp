import pytest

from services.document_classifier import classify_page


def test_fuzzy_ocr_noisy_heading_classified() -> None:
    text = "Sancfion Lefter\nSanctioned Amount Rs 500000\nTenure 60 months"
    result = classify_page(text)
    assert result["document_type"] == "Sanction Letter"
    assert result["confidence"] >= 0.75


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Family Court Divorce Decree dissolution of marriage", "Divorce Decree"),
        ("Certificate of Marriage Registrar of Marriages Bride Groom", "Marriage Certificate"),
        ("Death Certificate date of death deceased registrar", "Death Certificate"),
        ("GST Registration Certificate GSTIN 27ABCDE1234F1Z5", "GST Certificate"),
        ("Board Resolution resolved that board of directors authorised signatory", "Board Resolution"),
        ("No Objection Certificate NOC from previous lender", "NOC"),
        ("TransUnion CIBIL Credit Information Report CIBIL Score Control Number", "CIBIL Report"),
        ("CRIF High Mark Credit Information Report Credit Score", "CRIF Report"),
    ],
)
def test_expanded_registry_document_types(text: str, expected: str) -> None:
    assert classify_page(text)["document_type"] == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("MGNREGA Job Card National Rural Employment Guarantee Job Card Number 123", "MNREGA Job Card"),
        ("National Population Register NPR Letter issued to resident", "NPR Letter"),
        ("FORM 97 Declaration in lieu of PAN Form No 97", "Form 97"),
        ("Pension Payment Order PPO Number 12345 Pensioner Name", "Pension Payment Order"),
        ("List of Documents LOD original documents held by lender", "List of Documents"),
        ("FI Approval Field Investigation Approval negative FI approved", "FI Approval Letter"),
    ],
)
def test_new_printed_checklist_document_types_are_classified(text: str, expected: str) -> None:
    assert classify_page(text)["document_type"] == expected


def test_unmatched_page_still_unknown() -> None:
    text = "Random narrative page about lunch plans and weather with no loan-file signals."
    result = classify_page(text)
    assert result["document_type"] == "None"
    assert result["confidence"] == 0.0
