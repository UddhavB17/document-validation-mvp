"""Trusted evidence may resolve metadata but must never replace OCR values."""

from services.automatic_document_index import build_automatic_document_index
from services.evidence_resolution import resolve_trusted_evidence


def _page(
    number: int,
    text: str,
    *,
    document_type: str = "Unknown",
    confidence: float = 0.0,
    detected: int | None = None,
    fields: dict | None = None,
) -> dict:
    return {
        "page_number": number,
        "page_type": "digital",
        "is_readable": True,
        "ocr_text": text,
        "document_type": document_type,
        "classification_confidence": confidence,
        "detected_page_number": number if detected is None else detected,
        "extracted_fields": fields or {},
    }


def test_unknown_pan_page_is_promoted_and_owner_resolved_without_value_replacement() -> None:
    pages = [_page(
        1,
        "Income Tax Department\nPermanent Account Number\nTSTAA0001T\nName\nOCR CAPTURE",
        fields={"applicant_name": "OCR CAPTURE"},
    )]
    trusted = {
        "primary": {
            "applicant_name": "Trusted Display Name",
            "pan_number": "TSTAA0001T",
        }
    }

    result = resolve_trusted_evidence(pages, trusted)

    assert pages[0]["document_type"] == "PAN"
    assert pages[0]["person_id"] == "primary"
    assert pages[0]["extracted_fields"]["pan_number"] == "TSTAA0001T"
    assert pages[0]["extracted_fields"]["applicant_name"] == "OCR CAPTURE"
    assert pages[0]["extracted_fields"]["_evidence_resolution"]["trusted_values_replaced"] is False
    assert result["mode"] == "merged_pdf"


def test_pan_inside_application_form_does_not_turn_form_into_pan_card() -> None:
    pages = [_page(
        1,
        "Loan Application Form\nApplicant Details\nPAN Number: TSTAA0001T",
        document_type="Application Form",
        confidence=0.91,
    )]

    resolve_trusted_evidence(
        pages,
        {"primary": {"applicant_name": "Test Person", "pan_number": "TSTAA0001T"}},
    )

    assert pages[0]["document_type"] == "Application Form"


def test_merged_aadhaar_front_and_back_use_front_identifier_not_relation_name() -> None:
    pages = [
        _page(
            1,
            "UIDAI Aadhaar\nName: Card Holder\n9999 8888 7777",
            document_type="Aadhaar",
            confidence=0.94,
            fields={"applicant_name": "Card Holder", "aadhaar_number": "999988887777"},
        ),
        _page(
            2,
            "Address: W/O Relation Person, Test District 400001",
            document_type="Aadhaar",
            confidence=0.72,
            fields={"address": "W/O Relation Person, Test District 400001", "pin_code": "400001"},
        ),
    ]
    trusted = {
        "primary": {"applicant_name": "Relation Person"},
        "coapplicant_1": {"applicant_name": "Card Holder", "aadhaar_last4": "7777"},
    }

    resolve_trusted_evidence(pages, trusted)

    assert pages[0]["person_id"] == "coapplicant_1"
    assert pages[1]["person_id"] == "coapplicant_1"
    assert pages[0]["extracted_fields"]["_evidence_resolution"]["document_id"] == pages[1]["extracted_fields"]["_evidence_resolution"]["document_id"]


def test_aadhaar_back_relation_name_alone_does_not_resolve_cardholder() -> None:
    pages = [_page(
        1,
        "Address: W/O Relation Person, Test District 400001",
        document_type="Aadhaar",
        confidence=0.90,
        fields={"address": "W/O Relation Person, Test District 400001"},
    )]
    trusted = {
        "primary": {"applicant_name": "Relation Person"},
        "coapplicant_1": {"applicant_name": "Different Card Holder"},
    }

    resolve_trusted_evidence(pages, trusted)

    assert pages[0].get("person_id") is None
    assert pages[0]["extracted_fields"]["_evidence_resolution"]["resolved_person_id"] is None


def test_aadhaar_back_inverse_wife_relationship_resolves_unique_holder() -> None:
    pages = [_page(
        1,
        "Address: W/O Relation Person, Test District 400001",
        document_type="Aadhaar",
        confidence=0.90,
        fields={"address": "W/O Relation Person, Test District 400001"},
    )]
    trusted = {
        "primary": {"applicant_name": "Relation Person"},
        "coapplicant_1": {
            "applicant_name": "Card Holder",
            "relationship_qualifier": "W/O",
            "husband_name": "Relation Person",
        },
    }

    resolve_trusted_evidence(pages, trusted)

    assert pages[0]["person_id"] == "coapplicant_1"
    evidence = pages[0]["extracted_fields"]["_evidence_resolution"]["owner_evidence"]
    assert "relationship:w/o:primary" in evidence


def test_zip_application_form_builds_individual_records_across_all_pages() -> None:
    pages = [
        _page(
            1,
            "Loan Application Form\nAPPLICANT KYC DETAILS\nTest Applicant\nXXXXXXXX0001\nTSTAA0001T",
            document_type="Application Form",
            confidence=0.92,
        ),
        _page(
            2,
            "CO-APPLICANT KYC DETAILS\nTest Coapplicant\nXXXXXXXX0002\nTSTBB0002T",
            document_type="Application Form",
            confidence=0.90,
            detected=1,
        ),
    ]
    trusted = {
        "primary": {"applicant_name": "Test Applicant", "pan_number": "TSTAA0001T"},
        "coapplicant_1": {"applicant_name": "Test Coapplicant", "pan_number": "TSTBB0002T"},
    }
    sources = [{
        "source_document_id": "file-0001",
        "original_filename": "application-form.pdf",
        "internal_page_start": 1,
        "internal_page_end": 2,
    }]

    result = resolve_trusted_evidence(pages, trusted, source_documents=sources)
    records = pages[0]["extracted_fields"]["person_records"]

    assert result["mode"] == "zip"
    assert {record.get("_resolved_person_id") for record in records} == {"primary", "coapplicant_1"}
    assert result["groups"][0]["person_record_count"] == 2

    index = build_automatic_document_index(pages, trusted, source_documents=sources)
    assert index["documents"][0]["auto_mapping"]["multi_person_document"] is True


def test_merged_application_form_aggregates_contiguous_pages() -> None:
    pages = [
        _page(
            10,
            "Loan Application Form\nAPPLICANT KYC DETAILS\nTest Applicant\nXXXXXXXX0001\nTSTAA0001T",
            document_type="Application Form",
            confidence=0.92,
        ),
        _page(
            11,
            "CO-APPLICANT KYC DETAILS\nTest Coapplicant\nXXXXXXXX0002\nTSTBB0002T",
            document_type="Application Form",
            confidence=0.88,
            detected=10,
        ),
    ]
    trusted = {
        "primary": {"applicant_name": "Test Applicant", "pan_number": "TSTAA0001T"},
        "coapplicant_1": {"applicant_name": "Test Coapplicant", "pan_number": "TSTBB0002T"},
    }

    result = resolve_trusted_evidence(pages, trusted)

    assert len(result["groups"]) == 1
    assert result["groups"][0]["pages"] == [10, 11]
    assert result["groups"][0]["multi_person_document"] is True
    assert result["groups"][0]["person_record_count"] == 2


def test_intrinsic_inference_abstains_on_kyc_checklist_page() -> None:
    from services.evidence_resolution import infer_document_type_from_evidence

    text = (
        "KYC Verification Sheet\n"
        "Aadhaar Card: 2345 1234 1234 (Unique Identification Authority of India)\n"
        "PAN Card: TSTAA0001T\nVoter ID: ABC1234567\nDriving License: RJ14 2011\n"
    )
    assert infer_document_type_from_evidence(text) is None


def test_intrinsic_aadhaar_inference_ignores_phone_numbers() -> None:
    from services.evidence_resolution import infer_document_type_from_evidence

    # A 91-prefixed mobile number must not count as an Aadhaar number even
    # next to an authority phrase quoted in a form.
    text = "Contact: 919374200200\nRegistered with Unique Identification Authority of India"
    result = infer_document_type_from_evidence(text)
    assert result is None or result["document_type"] != "Aadhaar"


def test_low_confidence_group_type_is_not_promoted_to_unknown_pages() -> None:
    from services.evidence_resolution import _resolve_group

    pages = [
        _page(1, "faint text", document_type="Driving License", confidence=0.2),
        _page(2, "more faint text", document_type="Unknown", confidence=0.0),
    ]
    _resolve_group({"document_id": "doc-1", "pages": pages}, {})
    assert pages[1]["document_type"] == "Unknown"


def test_confident_group_type_still_fills_unknown_pages() -> None:
    from services.evidence_resolution import _resolve_group

    pages = [
        _page(1, "statement of account", document_type="Bank Statement", confidence=0.9),
        _page(2, "txn rows", document_type="Unknown", confidence=0.0),
    ]
    _resolve_group({"document_id": "doc-2", "pages": pages}, {})
    assert pages[1]["document_type"] == "Bank Statement"


def test_zip_role_absent_from_trusted_stays_unassigned_through_index() -> None:
    pages = [_page(
        1,
        "Income Tax Department\nPermanent Account Number\nSXPPS4453F\nSUTHAR AARATIBEN ANUPKUMAR",
        document_type="PAN",
        confidence=0.95,
        fields={
            "applicant_name": "SUTHAR AARATIBEN ANUPKUMAR",
            "pan_number": "SXPPS4453F",
        },
    )]
    source = [{
        "source_document_id": "file-1",
        "original_filename": "Co-Applicant/KYC/PAN.pdf",
        "file_type": "pdf",
        "internal_page_start": 1,
        "internal_page_end": 1,
    }]
    trusted = {"primary": {"role": "primary", "applicant_name": "Suthar Anupkumar", "pan_number": "TSTAA0001T"}}

    resolve_trusted_evidence(pages, trusted, source_documents=source)
    assert pages[0].get("person_id") in {None, "unassigned"}
    assert pages[0].get("source_filename") == "Co-Applicant/KYC/PAN.pdf"
    evidence = pages[0]["extracted_fields"]["_evidence_resolution"]["owner_evidence"]
    assert "source_role_not_in_trusted_data" in evidence

    index = build_automatic_document_index(pages, trusted, source_documents=source)
    assert not index["documents"]
    assert index["anomalies"][0]["rule_id"] == "TRUSTED_PERSON_SCOPE_MISSING"
    assert index["anomalies"][0]["person_role"] == "coapplicant"


def test_cached_generic_application_is_overridden_by_insurance_semantics() -> None:
    pages = [_page(
        1,
        """Application Form - Group Care 360 Scheme
Underwritten by Care Health Insurance Limited IRDAI
Proposer Details Nominee Details Details of Person to be Insured
Policy Tenure Sum Insured Total Premium
""",
        document_type="Application Form",
        confidence=1.0,
        fields={"application_number": "0030705"},
    )]
    resolve_trusted_evidence(
        pages,
        {"primary": {"application_number": "GJ000030765"}},
    )
    assert pages[0]["document_type"] == "Insurance Form"
    assert pages[0]["extracted_fields"]["_evidence_resolution"]["document_type_changed"] is True
