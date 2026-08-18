import pytest

from services.document_classifier import classify_page, document_type_config


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


def test_form_97_not_inferred_from_unrelated_loan_pages() -> None:
    from services.document_classifier import load_document_type_registry

    load_document_type_registry.cache_clear()
    samples = [
        "Account Type: TWO-WHEELER LOAN Credit Grantor: XXXX Account #: xxxx Lender Type: PRB",
        "भारत INDIA NON JUDICIAL FIVE HUNDRED RUPEES RAJASTHAN stamp paper AG 841430",
        "Jaipur Vidyut Vitran Nigam Limited bill month due date consumer no 2106320",
        "The loan will be disbursed subject to Facility Agreement Borrower Lender repayment",
    ]
    for text in samples:
        result = classify_page(text)
        assert result["document_type"] != "Form 97", text


def test_form_60_instruction_inside_application_form_is_not_form_97() -> None:
    text = (
        "Individual / Sole Proprietor\n"
        "Applicant Personal Details\n"
        "PAN/GIR Number (if not available, please fill up Form 60/61 as applicable)\n"
        "Contact Details\n"
        "Current Residence Address\n"
        "Preferred Mailing Address\n"
    )

    result = classify_page(text)

    assert result["document_type"] != "Form 97"


@pytest.mark.parametrize("title", ["FORM 97", "FORM NO. 60"])
def test_form_97_or_form_60_opening_title_remains_classifiable(title: str) -> None:
    result = classify_page(f"{title}\nDeclaration in lieu of PAN")

    assert result["document_type"] == "Form 97"


def test_stamp_and_utility_pages_classify_correctly() -> None:
    from services.document_classifier import load_document_type_registry

    load_document_type_registry.cache_clear()
    stamp = classify_page("INDIA NON JUDICIAL FIVE HUNDRED RUPEES stamp paper RAJASTHAN")
    assert stamp["document_type"] == "Stamp Duty"
    utility = classify_page("Jaipur Vidyut Vitran Nigam Limited विद्युत bill month due date consumer no")
    assert utility["document_type"] == "Utility Bill"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "Unique Identification Authority of India Aadhaar Letter "
            "XXXX XXXX 1234 Secure QR Code",
            "Aadhaar",
        ),
        (
            "REPUBLIC OF INDIA PASSPORT Ministry of External Affairs "
            "P<INDKUMAR<<RAVI A1234567",
            "Passport",
        ),
        (
            "Election Commission of India e-EPIC Elector Photo Identity Card ABC1234567",
            "Voter ID",
        ),
        (
            "FORM OF DRIVING LICENCE Transport Department DL No RJ14 2020 1234567 "
            "Date of Issue 01/01/2020",
            "Driving License",
        ),
        (
            "UDYAM REGISTRATION CERTIFICATE Ministry of Micro Small and Medium Enterprises "
            "UDYAM-RJ-12-1234567",
            "Udyam Certificate",
        ),
        (
            "GUMASTA CERTIFICATE Registration of Establishment under the Shops and "
            "Establishments Act Registration No RJ-123",
            "Shop Establishment Certificate",
        ),
        (
            "FIELD INVESTIGATION REPORT Applicant Name Ravi Kumar Verification Status Positive "
            "Visit Date 01/08/2026",
            "FI Report",
        ),
        (
            "CRIME CHECK REPORT Subject Name Ravi Kumar Report Status No Adverse Record "
            "Approved by Credit",
            "Crime Check Report",
        ),
    ],
)
def test_refined_document_formats_classify(text: str, expected: str) -> None:
    assert classify_page(text)["document_type"] == expected


def test_multi_cheque_scan_is_classified_as_pdc_sheet() -> None:
    text = (
        "A/C Payee Rupees IFSC HDFC0001234 Cheque No 000001 000001 123456789\n"
        "Account Payee Rupees IFSC HDFC0001234 Cheque No 000002 000002 123456789"
    )

    assert classify_page(text)["document_type"] == "PDC"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("લોન કરાર ઉધારકર્તા લોનદાતા ડિફોલ્ટ અને ચુકવણીની શરતો", "Loan Agreement"),
        ("સ્ટેમ્પ ડ્યુટી બિન ન્યાયિક ગુજરાત પ્રમાણપત્ર", "Stamp Duty"),
        ("ગ્રાહક અરજી ફોર્મ અરજદારની વિગતો સહ અરજદાર સરનામું", "Application Form"),
        ("વીજળી બિલ ગ્રાહક નંબર બાકી તારીખ ચુકવવાની રકમ", "Utility Bill"),
        ("નોંધાયેલ વેચાણ દસ્તાવેજ મિલકત સર્વે નંબર પ્લોટ નંબર ચતુઃસીમા", "Property Document"),
    ],
)
def test_gujarati_document_signals_are_preserved_and_classified(text: str, expected: str) -> None:
    assert classify_page(text)["document_type"] == expected


def test_end_use_letter_beats_generic_application_form_terms() -> None:
    result = classify_page(
        "END-USE LETTER FROM THE BORROWER\nApplication date 23-July-2026\n"
        "Applicant Mobile Number\nThe said Loan is for the purpose of: Business Use\n"
        "I/We confirm this is a valid & legal purpose"
    )
    assert result["document_type"] == "End-Use Letter"


def test_acceptance_profile_panel_is_not_unknown() -> None:
    result = classify_page(
        "Applicant Entity Name Profile Image\nCo-Applicant Entity Name Profile Image\n"
        "Guarantor Entity Name Profile Image\nThanks & Regards\nMS Fincap Pvt Ltd"
    )
    assert result["document_type"] == "Acceptance Letter"


def test_sanction_conditions_are_not_property_document_from_generic_property_words() -> None:
    result = classify_page(
        "Sanction Conditions\nTerms and conditions of loan\n"
        "The property security documents must be self-attested before disbursement"
    )
    assert result["document_type"] != "Property Document"


def test_unmatched_page_still_unknown() -> None:
    text = "Random narrative page about lunch plans and weather with no loan-file signals."
    result = classify_page(text)
    assert result["document_type"] == "None"
    assert result["confidence"] == 0.0


def test_registry_ocr_routes_are_validated_and_default_safe() -> None:
    assert document_type_config("PAN").ocr_route == "fast"
    assert document_type_config("Bank Statement").has_tabular_data is True
    assert document_type_config("Utility Bill").ocr_route == "structured"
    assert document_type_config("Future Unconfigured Type").ocr_route == "structured"
