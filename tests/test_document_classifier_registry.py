import pytest

from services.document_classifier import classify_page, document_type_config


def test_fuzzy_ocr_noisy_heading_classified() -> None:
    text = "Sancfion Lefter\nSanctioned Amount Rs 500000\nTenure 60 months"
    result = classify_page(text)
    assert result["document_type"] == "Sanction Letter"
    assert result["confidence"] >= 0.75


def test_co_borrower_personal_details_page_is_an_application_form() -> None:
    text = (
        "Co-Borrower\nIndividual/Sole Proprietor\nCo-Applicant\nPersonal Details\n"
        "Name (Mr/Mrs./Ms./Dr) SAMPLE PERSON\nRelationship with Applicant SELF\n"
        "Date of Birth\nPAN/GIR Number\nContact Details\nCurrent Res Address\n"
        "PIN 302027\nPermanent Resi. Address\nBusiness Constitution\n"
    )
    assert classify_page(text)["document_type"] == "Application Form"


def test_personal_details_heading_requires_application_context() -> None:
    assert classify_page("Personal Details\nName: Sample Person")["document_type"] != (
        "Application Form"
    )
    assert (
        classify_page(
            "Loan Agreement\nBorrower and lender\nPersonal Details\n"
            "Co-applicant shall comply with repayment covenants."
        )["document_type"]
        == "Loan Agreement"
    )


def test_application_kyc_table_on_continuation_page_is_classifiable() -> None:
    text = "Office address\n" * 30 + (
        "APPLICANT KYC DETAILS\nAPPLICANT NAME\nआवेदक का नाम\n"
        "AADHAAR\nआधार\nPAN\nपैन कार्ड\nVOTER ID\nDRIVING LICENCE\n"
        "Sample Person\nXXXXXXXX1234\nABCDE1234F\nNot Provided\n"
    )
    result = classify_page(text)
    assert result["document_type"] == "Application Form"
    assert result["confidence"] >= 0.65


def test_kyc_policy_reference_is_not_an_application_table() -> None:
    result = classify_page(
        "KYC policy\nCheck applicant KYC details including Aadhaar, PAN and voter ID."
    )
    assert result["document_type"] != "Application Form"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Family Court Divorce Decree dissolution of marriage", "Divorce Decree"),
        ("Certificate of Marriage Registrar of Marriages Bride Groom", "Marriage Certificate"),
        ("Death Certificate date of death deceased registrar", "Death Certificate"),
        ("GST Registration Certificate GSTIN 27ABCDE1234F1Z5", "GST Certificate"),
        (
            "Board Resolution resolved that board of directors authorised signatory",
            "Board Resolution",
        ),
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
        (
            "MGNREGA Job Card National Rural Employment Guarantee Job Card Number 123",
            "MNREGA Job Card",
        ),
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
    utility = classify_page(
        "Jaipur Vidyut Vitran Nigam Limited विद्युत bill month due date consumer no"
    )
    assert utility["document_type"] == "Utility Bill"


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


@pytest.mark.parametrize(
    "heading",
    [
        "आवासीय भूमि का पट्टा",
        "आबादी भूमि का पट्टा",
    ],
)
def test_residential_patta_headings_are_property_document(heading: str) -> None:
    text = f"{heading}\nग्राम पंचायत रामपुरा\nपट्टा संख्या 142\nआवंटी का नाम Sample Person\n"
    assert classify_page(text)["document_type"] == "Property Document"


def test_sanction_condition_requiring_patta_remains_sanction_letter() -> None:
    text = (
        "Sanction Letter\n"
        "Sanctioned Amount Rs 500000\n"
        "Tenure 60 months\n"
        "Terms and conditions of loan\n"
        "Please submit आवासीय भूमि का पट्टा before disbursement"
    )
    assert classify_page(text)["document_type"] == "Sanction Letter"


def test_genuine_sale_deed_still_property_document() -> None:
    text = "Sale Deed\nSurvey Number 123\nPlot No 45"
    assert classify_page(text)["document_type"] == "Property Document"


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
