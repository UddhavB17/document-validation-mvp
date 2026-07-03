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
    ],
)
def test_expanded_registry_document_types(text: str, expected: str) -> None:
    assert classify_page(text)["document_type"] == expected


def test_unmatched_page_still_unknown() -> None:
    text = "Random narrative page about lunch plans and weather with no loan-file signals."
    result = classify_page(text)
    assert result["document_type"] == "None"
    assert result["confidence"] == 0.0
