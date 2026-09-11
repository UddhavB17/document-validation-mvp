import json

import pytest

from services.company_dump_adapter import convert_company_database_dump
from services.verification_manifest import VerificationManifest

RAW_DUMP = """
Loan Application: RJ900000001
--- START RAW DATABASE JSON DUMP ---
{
"applicantdetails": {
"loanId": 90001,
"entityName": "Veeru Lal",
"mobileNo": “9876543210,
"dob": "18-May-1994"
},
"applicantkyc": {
"entityName": "Veeru Lal",
"panNumber": "ABCDE1234F",
"aadhaarNumber": "XXXXXXXX1234”
},
"camdetails": {
"loanId": 90001,
"applicantname": "Veeru Lal",
"branch": "JHALAWAR",
"sanctionamount": "275000",
"tenure": 60,
"emiamount": "8234"
},
"coapplicantdetails": [
{
"entityName": "Ambar Lal",
"mobileNo": "9123456789",
"dob": "05-June-1961"
},
{
"entityName": "Sudha Bai",
"dob": "01-January-1962",
"husbandName": "Ambar Lal",
"relationshipQualifier": "W/O"
}
],
"coapplicantkyc": [
{"entityName": "Ambar Lal", "aadhaarNumber": "XXXXXXXX0002"},
{"entityName": "Sudha Bai", "aadhaarNumber": "********0003"}
]
}
--- END RAW DATABASE JSON DUMP ---
"""


def test_converts_malformed_company_dump_to_automatic_manifest() -> None:
    manifest = convert_company_database_dump(RAW_DUMP)

    assert manifest["loan_id"] == "RJ900000001"
    assert manifest["branch"] == "JHALAWAR"
    assert manifest["document_index"] == []
    assert list(manifest["people"]) == ["primary", "coapplicant_1", "coapplicant_2"]
    assert manifest["people"]["primary"] == {
        "role": "primary",
        "date_of_birth": "18-May-1994",
        "phone_number": "9876543210",
        "pan_number": "ABCDE1234F",
        "aadhaar_last4": "1234",
        "applicant_name": "Veeru Lal",
        "loan_amount": "275000",
        "tenure": 60,
        "emi": "8234",
    }
    assert manifest["people"]["coapplicant_1"]["aadhaar_last4"] == "0002"
    assert manifest["people"]["coapplicant_2"]["aadhaar_last4"] == "0003"
    assert manifest["people"]["coapplicant_2"]["husband_name"] == "Ambar Lal"
    assert manifest["people"]["coapplicant_2"]["relationship_qualifier"] == "W/O"
    assert manifest["conversion_warnings"]


def test_converts_valid_database_json_object() -> None:
    manifest = convert_company_database_dump(
        {
            "applicantdetails": {
                "loanId": 42,
                "entityName": "Ramesh Kumar",
                "dob": "01-January-1990",
            },
            "camdetails": {
                "loanId": 42,
                "loanamount": "500000",
                "loginDate": "17-August-2026",
            },
        }
    )

    assert manifest["loan_id"] == "42"
    assert manifest["application_date"] == "17-August-2026"
    assert manifest["people"]["primary"]["applicant_name"] == "Ramesh Kumar"
    assert manifest["people"]["primary"]["loan_amount"] == "500000"


@pytest.mark.parametrize("serialized", [False, True])
def test_json_string_punctuation_preserves_people_and_trusted_fields(serialized: bool) -> None:
    payload = {
        "applicantdetails": {
            "loanId": 42,
            "fieldRemarks": "Review } note",
            "entityName": "Primary One",
            "mobileNo": "9000000001",
            "address": 'House "A", Block [2]',
        },
        "coapplicantdetails": [
            {"entityName": "Alice One", "fieldRemarks": "Review { note"},
            {"entityName": "Bob Two", "mobileNo": "9000000002"},
        ],
    }

    manifest = convert_company_database_dump(json.dumps(payload) if serialized else payload)

    assert list(manifest["people"]) == ["primary", "coapplicant_1", "coapplicant_2"]
    primary = manifest["people"]["primary"]
    assert primary["phone_number"] == "9000000001"
    assert primary["field_remarks"] == "Review } note"
    assert primary["address"] == 'House "A", Block [2]'
    assert manifest["people"]["coapplicant_1"]["applicant_name"] == "Alice One"
    assert manifest["people"]["coapplicant_2"]["applicant_name"] == "Bob Two"
    assert manifest["people"]["coapplicant_2"]["phone_number"] == "9000000002"


def test_imports_explicit_submission_date_from_company_loan_section() -> None:
    payload = {
        "applicantdetails": {"loanId": 42, "entityName": "Test Applicant"},
        "loanclientdetails": {"loanApplicationSubmittedDate": "24-July-2026"},
        "loanlogindetails": {"loginDate": "23-July-2026"},
    }
    assert convert_company_database_dump(payload)["application_date"] == "24-July-2026"
    del payload["loanclientdetails"]
    assert convert_company_database_dump(payload)["application_date"] == "23-July-2026"
    del payload["loanlogindetails"]
    assert not convert_company_database_dump(payload).get("application_date")


def test_converts_single_object_coapplicant_sections() -> None:
    manifest = convert_company_database_dump(
        {
            "applicantdetails": {
                "loanId": 90002,
                "entityName": "Sutar Ajaykumar",
            },
            "coapplicantdetails": {
                "entityName": "Bharatiben Ajaykumar Sutar",
                "mobileNo": "9876543210",
            },
            "coapplicantkyc": {
                "entityName": "Bharatiben Ajaykumar Sutar",
                "panNumber": "TSTPA1053Z",
                "aadhaarNumber": "XXXXXXXX8196",
            },
        }
    )

    assert manifest["people"]["coapplicant_1"] == {
        "role": "coapplicant",
        "phone_number": "9876543210",
        "pan_number": "TSTPA1053Z",
        "aadhaar_last4": "8196",
        "applicant_name": "Bharatiben Ajaykumar Sutar",
    }


def test_imports_singleton_guarantor_with_identity_kyc_address() -> None:
    manifest = convert_company_database_dump(
        {
            "applicantdetails": {
                "loanId": 9001,
                "entityName": "Synthetic Primary One",
                "mobileNo": "9000000001",
                "dob": "01-January-1990",
            },
            "camdetails": {"loanId": 9001, "branch": "SYNTHETIC-BRANCH"},
            "guarantordetails": {
                "entityType": "Guarantor",
                # Doubled space must still bind to single-space KYC/address.
                "entityName": "Synthetic  Guarantor One",
                "mobileNo": "9000000002",
                "fatherName": "Synthetic Father One",
                "dob": "02-February-1985",
            },
            "guarantorkyc": {
                "entityType": "Guarantor",
                "entityName": "Synthetic Guarantor One",
                "panNumber": "TSTPA7013Z",
                "aadhaarNumber": "XXXXXXXX4321",
            },
            "guarantoraddressdetails": {
                "entityType": "Guarantor",
                "entityName": "Synthetic Guarantor One",
                "address": "12 Synthetic Street",
                "addressSubType": "Permanent",
                "pincode": "300001",
            },
        }
    )

    assert list(manifest["people"]) == ["primary", "guarantor_1"]
    guarantor = manifest["people"]["guarantor_1"]
    assert guarantor["role"] == "guarantor"
    assert guarantor["applicant_name"].replace("  ", " ") == "Synthetic Guarantor One"
    assert guarantor["phone_number"] == "9000000002"
    assert guarantor["date_of_birth"] == "02-February-1985"
    assert guarantor["pan_number"] == "TSTPA7013Z"
    assert guarantor["aadhaar_last4"] == "4321"
    assert guarantor["address"] == "12 Synthetic Street"
    assert guarantor["pin_code"] == "300001"
    assert guarantor["father_name"] == "Synthetic Father One"
    # Contract must accept the new role/ID without document remapping.
    VerificationManifest(**manifest)


def test_binds_multiple_guarantors_despite_reordered_sections() -> None:
    manifest = convert_company_database_dump(
        {
            "applicantdetails": {"loanId": 9002, "entityName": "Synthetic Primary Two"},
            "coapplicantdetails": {
                "entityName": "Synthetic Coapplicant Two",
                "mobileNo": "9000000010",
            },
            "coapplicantkyc": {
                "entityName": "Synthetic Coapplicant Two",
                "panNumber": "TSTPA7007Z",
            },
            "guarantordetails": [
                {
                    "entityType": "Guarantor",
                    "entityName": "Synthetic Guarantor Alpha",
                    "mobileNo": "9000000003",
                },
                {
                    "entityType": "Guarantor",
                    "entityName": "Synthetic Guarantor Beta",
                    "mobileNo": "9000000004",
                },
            ],
            # KYC order is intentionally reversed relative to details.
            "guarantorkyc": [
                {
                    "entityType": "Guarantor",
                    "entityName": "Synthetic Guarantor Beta",
                    "panNumber": "TSTPA7006Z",
                },
                {
                    "entityType": "Guarantor",
                    "entityName": "Synthetic Guarantor Alpha",
                    "panNumber": "TSTPA7004Z",
                },
            ],
            # Address order is also reversed; binding must use names, not position.
            "guarantoraddressdetails": [
                {
                    "entityType": "Guarantor",
                    "entityName": "Synthetic Guarantor Beta",
                    "address": "99 Beta Road",
                    "pincode": "300002",
                },
                {
                    "entityType": "Guarantor",
                    "entityName": "Synthetic Guarantor Alpha",
                    "address": "11 Alpha Road",
                    "pincode": "300003",
                },
            ],
        }
    )

    assert list(manifest["people"]) == [
        "primary",
        "coapplicant_1",
        "guarantor_1",
        "guarantor_2",
    ]
    assert manifest["people"]["coapplicant_1"]["role"] == "coapplicant"
    assert manifest["people"]["coapplicant_1"]["pan_number"] == "TSTPA7007Z"
    first = manifest["people"]["guarantor_1"]
    second = manifest["people"]["guarantor_2"]
    assert first["applicant_name"] == "Synthetic Guarantor Alpha"
    assert first["pan_number"] == "TSTPA7004Z"
    assert first["phone_number"] == "9000000003"
    assert first["address"] == "11 Alpha Road"
    assert second["applicant_name"] == "Synthetic Guarantor Beta"
    assert second["pan_number"] == "TSTPA7006Z"
    assert second["phone_number"] == "9000000004"
    assert second["address"] == "99 Beta Road"


def test_ignores_missing_and_placeholder_guarantor_sections() -> None:
    manifest = convert_company_database_dump(
        {
            "applicantdetails": {"loanId": 9003, "entityName": "Synthetic Primary Three"},
            "guarantordetails": {"entityName": "NA", "mobileNo": "-"},
            "guarantorkyc": {"entityName": "none"},
            "guarantoraddressdetails": [],
            "witnessdetails": [{"entityName": "Synthetic Witness One"}],
            "incomesummary": {"entityName": "Synthetic Witness One"},
        }
    )
    assert list(manifest["people"]) == ["primary"]

    manifest_without_sections = convert_company_database_dump(
        {"applicantdetails": {"loanId": 9003, "entityName": "Synthetic Primary Three"}}
    )
    assert list(manifest_without_sections["people"]) == ["primary"]


def test_omits_masked_invalid_guarantor_identifiers() -> None:
    manifest = convert_company_database_dump(
        {
            "applicantdetails": {"loanId": 9004, "entityName": "Synthetic Primary Four"},
            "guarantordetails": {
                "entityType": "Guarantor",
                "entityName": "Synthetic Guarantor Gamma",
                "mobileNo": "123",
                "dob": "not-a-date",
            },
            "guarantorkyc": {
                "entityType": "Guarantor",
                "entityName": "Synthetic Guarantor Gamma",
                "panNumber": "INVALID",
                "aadhaarNumber": "XXXXXX",
            },
            "guarantoraddressdetails": {
                "entityType": "Guarantor",
                "entityName": "Synthetic Guarantor Gamma",
                "address": "7 Gamma Lane",
                "pincode": "12",
            },
        }
    )

    guarantor = manifest["people"]["guarantor_1"]
    assert guarantor["role"] == "guarantor"
    assert "phone_number" not in guarantor
    assert "pan_number" not in guarantor
    assert "aadhaar_number" not in guarantor
    assert "aadhaar_last4" not in guarantor
    assert "date_of_birth" not in guarantor
    assert "pin_code" not in guarantor
    # Valid address text is still kept even when exact identifiers are dropped.
    assert guarantor["address"] == "7 Gamma Lane"


def test_never_attaches_nonmatching_kyc_address_to_another_person() -> None:
    manifest = convert_company_database_dump(
        {
            "applicantdetails": {"loanId": 9005, "entityName": "Synthetic Primary Five"},
            "guarantordetails": {
                "entityType": "Guarantor",
                "entityName": "Synthetic Guarantor Delta",
                "mobileNo": "9000000005",
            },
            "guarantorkyc": {
                "entityType": "Guarantor",
                "entityName": "Synthetic Guarantor Epsilon",
                "panNumber": "TSTPA7008Z",
                "aadhaarNumber": "XXXXXXXX5678",
            },
            "guarantoraddressdetails": {
                "entityType": "Guarantor",
                "entityName": "Synthetic Guarantor Epsilon",
                "address": "5 Epsilon Court",
                "pincode": "300005",
            },
        }
    )

    assert list(manifest["people"]) == ["primary", "guarantor_1", "guarantor_2"]
    first = manifest["people"]["guarantor_1"]
    second = manifest["people"]["guarantor_2"]
    assert first["applicant_name"] == "Synthetic Guarantor Delta"
    assert first["phone_number"] == "9000000005"
    assert "pan_number" not in first
    assert "address" not in first
    assert second["applicant_name"] == "Synthetic Guarantor Epsilon"
    assert second["pan_number"] == "TSTPA7008Z"
    assert second["aadhaar_last4"] == "5678"
    assert second["address"] == "5 Epsilon Court"


def test_keeps_same_name_cross_role_persons_separate() -> None:
    manifest = convert_company_database_dump(
        {
            "applicantdetails": {
                "loanId": 9006,
                "entityName": "Synthetic Same Name",
                "mobileNo": "9000000006",
            },
            "applicantkyc": {
                "entityName": "Synthetic Same Name",
                "panNumber": "TSTPA7011Z",
            },
            "guarantordetails": {
                "entityType": "Guarantor",
                "entityName": "Synthetic Same Name",
                "mobileNo": "9000000007",
            },
            "guarantorkyc": {
                "entityType": "Guarantor",
                "entityName": "Synthetic Same Name",
                "panNumber": "TSTPA7010Z",
            },
            "guarantoraddressdetails": {
                "entityType": "Guarantor",
                "entityName": "Synthetic Same Name",
                "address": "7 Guarantor Lane",
                "pincode": "300007",
            },
        }
    )

    primary = manifest["people"]["primary"]
    guarantor = manifest["people"]["guarantor_1"]
    assert primary["phone_number"] == "9000000006"
    assert primary["pan_number"] == "TSTPA7011Z"
    assert "address" not in primary
    assert guarantor["role"] == "guarantor"
    assert guarantor["phone_number"] == "9000000007"
    assert guarantor["pan_number"] == "TSTPA7010Z"
    assert guarantor["address"] == "7 Guarantor Lane"
