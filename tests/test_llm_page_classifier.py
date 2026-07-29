import pytest
from services.llm_page_classifier import _parse_classifier_response, normalize_llm_document_type


def test_parse_classifier_response_toon():
    # Valid TOON response
    toon_resp = """
document_type: "PAN Card"
confidence: 0.95
reason: "Contains tax department headers and standard PAN format."
"""
    parsed = _parse_classifier_response(toon_resp)
    assert parsed is not None
    assert parsed.get("document_type") == "PAN Card"
    assert parsed.get("confidence") == 0.95
    assert "tax department" in parsed.get("reason", "")

    # TOON response inside a code block
    fenced_resp = """
```toon
document_type: "Aadhaar"
confidence: 0.8
reason: "UIDAI header detected."
```
"""
    parsed = _parse_classifier_response(fenced_resp)
    assert parsed is not None
    assert parsed.get("document_type") == "Aadhaar"
    assert parsed.get("confidence") == 0.8


def test_normalize_llm_document_type():
    # Exact match case insensitivity
    assert normalize_llm_document_type("pan card") == "PAN Card"
    assert normalize_llm_document_type("aadhaar") == "Aadhaar"

    # Alias / Substring normalization
    assert normalize_llm_document_type("PAN") == "PAN Card"
    assert normalize_llm_document_type("Aadhar Card") == "Aadhaar"
    assert normalize_llm_document_type("Aadhaar Card") == "Aadhaar"
    assert normalize_llm_document_type("bank account statement") == "Bank Statement"
    assert normalize_llm_document_type("pass book") == "Passbook"
    assert normalize_llm_document_type("cancelled cheque") == "Cheque"
    assert normalize_llm_document_type("electricity bill") == "Utility Bill"
    assert normalize_llm_document_type("cibil report page") == "CIBIL Report"
    assert normalize_llm_document_type("crif check") == "CRIF Report"
    assert normalize_llm_document_type("cersai search page") == "CERSAI Report"
    assert normalize_llm_document_type("Form 97") == "Form 97"
    assert normalize_llm_document_type("form 60 declaration") == "Form 97"

    # Broad ambiguous words must NOT hijack classification
    assert normalize_llm_document_type("statement") == "None"
    assert normalize_llm_document_type("bill") == "None"
    assert normalize_llm_document_type("agreement") == "None"

    # None cases
    assert normalize_llm_document_type("random document") == "None"
    assert normalize_llm_document_type("") == "None"
    assert normalize_llm_document_type(None) == "None"


def test_form_97_llm_prediction_requires_literal_evidence():
    from services.llm_page_classifier import llm_prediction_has_evidence

    assert llm_prediction_has_evidence(
        "Form 97",
        "FORM 97 Declaration in lieu of PAN Form No. 97",
    )
    assert not llm_prediction_has_evidence(
        "Form 97",
        "Account Type: TWO-WHEELER LOAN Credit Grantor repayment schedule",
    )
    assert not llm_prediction_has_evidence(
        "Form 97",
        "INDIA NON JUDICIAL FIVE HUNDRED RUPEES stamp paper RAJASTHAN",
    )
    assert llm_prediction_has_evidence(
        "Utility Bill",
        "Jaipur Vidyut Vitran Nigam Limited bill month due date",
    )
