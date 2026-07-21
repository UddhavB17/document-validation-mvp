from services.company_dump_adapter import convert_company_database_dump


RAW_DUMP = """
Loan Application: RJ000028546
--- START RAW DATABASE JSON DUMP ---
{
"applicantdetails": {
"loanId": 28546,
"entityName": "Peeru Lal",
"mobileNo": “9876543210,
"dob": "18-May-1994"
},
"applicantkyc": {
"entityName": "Peeru Lal",
"panNumber": "ABCDE1234F",
"aadhaarNumber": "XXXXXXXX1234”
},
"camdetails": {
"loanId": 28546,
"applicantname": "Peeru Lal",
"branch": "JHALAWAR",
"sanctionamount": "275000",
"tenure": 60,
"emiamount": "8234"
},
"coapplicantdetails": [
{
"entityName": "Unkar Lal",
"mobileNo": "9123456789",
"dob": "05-June-1961"
},
{
"entityName": "Radha Bai",
"dob": "01-January-1962"
}
],
"coapplicantkyc": [
{"entityName": "Unkar Lal", "aadhaarNumber": "XXXXXXXX7326"},
{"entityName": "Radha Bai", "aadhaarNumber": "********1187"}
]
}
--- END RAW DATABASE JSON DUMP ---
"""


def test_converts_malformed_company_dump_to_automatic_manifest() -> None:
    manifest = convert_company_database_dump(RAW_DUMP)

    assert manifest["loan_id"] == "RJ000028546"
    assert manifest["branch"] == "JHALAWAR"
    assert manifest["document_index"] == []
    assert list(manifest["people"]) == ["primary", "coapplicant_1", "coapplicant_2"]
    assert manifest["people"]["primary"] == {
        "role": "primary",
        "date_of_birth": "18-May-1994",
        "phone_number": "9876543210",
        "pan_number": "ABCDE1234F",
        "aadhaar_last4": "1234",
        "applicant_name": "Peeru Lal",
        "loan_amount": "275000",
        "tenure": 60,
        "emi": "8234",
    }
    assert manifest["people"]["coapplicant_1"]["aadhaar_last4"] == "7326"
    assert manifest["people"]["coapplicant_2"]["aadhaar_last4"] == "1187"
    assert manifest["conversion_warnings"]


def test_converts_valid_database_json_object() -> None:
    manifest = convert_company_database_dump({
        "applicantdetails": {
            "loanId": 42,
            "entityName": "Ramesh Kumar",
            "dob": "01-January-1990",
        },
        "camdetails": {"loanId": 42, "loanamount": "500000"},
    })

    assert manifest["loan_id"] == "42"
    assert manifest["people"]["primary"]["applicant_name"] == "Ramesh Kumar"
    assert manifest["people"]["primary"]["loan_amount"] == "500000"
