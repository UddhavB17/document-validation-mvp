# Application 93 (Loan ID: RJ000030677) Verification Comparison Report

This document contains all the ground-truth values from the company database JSON dump contrasted against the values extracted via OCR from the loan package documents.

## 1. Application-Level Core Parameters

Below is the comparison of the core loan metadata specified in the system JSON dump versus the values parsed from documents (e.g. Sanction Letter, CAM, Loan Agreement):

| Parameter | System expected (JSON Dump) | Extracted from OCR / CAM | Status |
| --- | --- | --- | --- |
| Loan ID / App Number | `RJ000030677` | `RJ000030677` | ✅ Match |
| Sanction Amount | `1200000` | `1200000` | ✅ Match |
| Loan Amount | `1200000` | `1200000` | ✅ Match |
| Rate of Interest (ROI) | `23.000000` | `23.0` | ✅ Match |
| Tenure (Months) | `120` | `120` | ✅ Match |
| EMI | `25626` | `25626` | ✅ Match |
| Installment Count | `120` | `120` | ✅ Match |
| Branch | `JAIPUR 5` | `JAIPUR 5` | ✅ Match |
| Product Type | `LAP` | `N/A` | ❌ Mismatch |
| Case Type | `Normal Case` | `N/A` | ❌ Mismatch |

## 2. Applicant Demographic Comparisons

Demographic fields compared on a per-person basis (Primary Applicant & Co-applicants).

### Profile: Neeraj Sharma (PRIMARY)

| Field | Expected Value (JSON Dump) | Extracted (OCR Observed) | Status | Details |
| --- | --- | --- | --- | --- |
| Applicant Name | `Neeraj Sharma` | `Neeraj Sharma` | ❌ Mismatch | Applicant Name does not match the trusted JSON/database dump. |
| PAN Number | `GJPPS9903E` | `GJPPS9903E` | ✅ Match | Match |
| Date of Birth | `01-December-1980` | `1980-12-01` | ✅ Match | Match |
| Phone Number | `9024602047` | `9024602047` | ✅ Match | Match |
| Address (Permanent) | `S/O Prem Shankar, 33,JYOTIBA FULE NAGAR, JAISINGHPURA KHOR, LALWAS.,JAIPUR, RAJASTHAN,Khojpur,Jaipur,Rajasthan,India,302027` | `बाग, (राज)` | ❌ Mismatch | Address does not match the Aadhaar address for primary. |
| Pin Code | `302027` | `302027` | ✅ Match | Match |
| Aadhaar Last 4 | `0272` | `0272` | ✅ Match | Match |
| Gender | `MALE` | `MALE` | ✅ Match | Match |
| Father's Name | `Prem Shankar` | `Prem Shankar` | ✅ Match | Match |

### Profile: Rita  Sharma (COAPPLICANT)

| Field | Expected Value (JSON Dump) | Extracted (OCR Observed) | Status | Details |
| --- | --- | --- | --- | --- |
| Applicant Name | `Rita  Sharma` | `Rita Sharma` | ✅ Match | Match |
| PAN Number | `GGCPS0526R` | `GGCPS0526R` | ✅ Match | Match |
| Date of Birth | `01-May-1986` | `1986-05-01` | ✅ Match | Match |
| Phone Number | `6367817651` | `6367817651` | ✅ Match | Match |
| Address (Permanent) | `W/O Niraj Sharma,33,jyotiba fule nagar,,jaisingh pura khor,Jaisinghpura Shekhawatan,Amber,,Jaisinghpura,,,Jaipur,Rajasthan,India,302027` | `बाग, (राज)` | ✅ Match | Match |
| Pin Code | `302027` | `302027` | ✅ Match | Match |
| Aadhaar Last 4 | `1130` | `1130` | ✅ Match | Match |
| Gender | `FEMALE` | `MALE` | ✅ Match | Match |
| Father's Name | `Niraj Sharma` | `Prem Shankar` | ✅ Match | Match |

### Profile: Kuldeep  KULDEEP (COAPPLICANT)

| Field | Expected Value (JSON Dump) | Extracted (OCR Observed) | Status | Details |
| --- | --- | --- | --- | --- |
| Applicant Name | `Kuldeep  KULDEEP` | `KULDEEP KULDEEP` | ✅ Match | Match |
| PAN Number | `EFRPK6071R` | `EFRPK6071R` | ✅ Match | Match |
| Date of Birth | `02-January-1992` | `1992-01-02` | ✅ Match | Match |
| Phone Number | `7339904623` | `7339904623` | ✅ Match | Match |
| Address (Permanent) | `S/O Prem Shankar,33,jyotiba fule nagar,,Jaisinghpura Shekhawatan,Amber,Jaisingh Pura Khor,,Jaisinghpura,,,Jaipur,Rajasthan,India,302027` | `बाग, (राज)` | ✅ Match | Match |
| Pin Code | `302027` | `302027` | ✅ Match | Match |
| Aadhaar Last 4 | `0649` | `0649` | ✅ Match | Match |
| Gender | `MALE` | `MALE` | ✅ Match | Match |
| Father's Name | `Prem Shankar` | `Prem Shankar` | ✅ Match | Match |

## 3. Detailed Validation Results (90 Anomalies)

These are the exact validation warnings and demographic mismatches flagged by the consistency and verification rules when comparing OCR text blocks to the expected JSON schema values.

| Page | Document Type | Rule / Severity | Expected Value | Found Value | Flagged Reason |
| --- | --- | --- | --- | --- | --- |
| 16 | Aadhaar | **ADDRESS_MISMATCH**<br>_(MEDIUM)_ | S/O Prem Shankar, 33,JYOTIBA FULE NAGAR, JAISINGHPURA KHOR, LALWAS.,JAIPUR, RAJASTHAN,Khojpur,Jaipur,Rajasthan,India,302027 | बाग, (राज) | address value missing |
| 16 | Aadhaar | **ADDRESS_MISMATCH**<br>_(MEDIUM)_ | S/O Prem Shankar, 33,JYOTIBA FULE NAGAR, JAISINGHPURA KHOR, LALWAS., JAIPUR, RAJASTHAN, 302027, Jaipur, Rajasthan, India, 302027, Khojpur | बाग, (राज) | address value missing |
| 48 | Loan Agreement | **APPLICANT_NAME_NOT_FOUND**<br>_(MEDIUM)_ | Neeraj Sharma | N/A | Expected field was not found with sufficient confidence. |
| 116 | Loan Agreement | **APPLICANT_NAME_NOT_FOUND**<br>_(MEDIUM)_ | Rita  Sharma | N/A | Expected field was not found with sufficient confidence. |
| 612 | NACH Form | **APPLICANT_NAME_NOT_FOUND**<br>_(MEDIUM)_ | Neeraj Sharma | N/A | Expected field was not found with sufficient confidence. |
| 39 | Application Form | **APPLICATION_REGIONAL_LANGUAGE_UNVERIFIED**<br>_(MEDIUM)_ | Second language other than Hindi | Devanagari script; exact language is ambiguous | Devanagari may be Hindi, Haryanvi, Bhojpuri, Maithili, Magahi, or another language. Verify the printed language declaration or configure application_form_languages. |
| 672 | Aadhaar | **CROSS_DOCUMENT_ADDRESS_MISMATCH**<br>_(MEDIUM)_ | S/O Prem Shankar, 33,JYOTIBA FULE NAGAR, JAISINGHPURA KHOR, LALWAS.,JAIPUR, RAJASTHAN,Khojpur,Jaipur,Rajasthan,India,302027 (CAM) | GOVERNANCE DIVISION 4th FLOOR ELECTRONICS NIKETAN 6,ST=Delhi,L=South Delhi,postalCode=110003,OU=NATIONAL E GOVERNANCE DEPARTMENT,O=DIGITAL INDIA (Aadhaar) | Address is inconsistent across documents for primary. |
| 53 | Loan Agreement | **CROSS_DOCUMENT_ROI_MISMATCH**<br>_(MEDIUM)_ | 23.0 (CAM) | 6.0 (Loan Agreement) | Roi is inconsistent across documents for primary. |
| 39 | Application Form | **PIN_CODE_NOT_FOUND**<br>_(MEDIUM)_ | 302027 | N/A | Expected field was not found with sufficient confidence. |
| 16 | Aadhaar | **TRUSTED_ADDRESS_MISMATCH**<br>_(MEDIUM)_ | S/O Prem Shankar, 33,JYOTIBA FULE NAGAR, JAISINGHPURA KHOR, LALWAS.,JAIPUR, RAJASTHAN,Khojpur,Jaipur,Rajasthan,India,302027 | बाग, (राज) | Address does not match the trusted JSON/database dump. |
| 671 | Aadhaar | **TRUSTED_ADDRESS_MISMATCH**<br>_(MEDIUM)_ | S/O Prem Shankar, 33,JYOTIBA FULE NAGAR, JAISINGHPURA KHOR, LALWAS.,JAIPUR, RAJASTHAN,Khojpur,Jaipur,Rajasthan,India,302027 | bikrampur,Khojpur,Kasganj,Khojpur,K asganj,Uttar Pradesh,207245 | Address does not match the trusted JSON/database dump. |
| 672 | Aadhaar | **TRUSTED_ADDRESS_MISMATCH**<br>_(MEDIUM)_ | S/O Prem Shankar, 33,JYOTIBA FULE NAGAR, JAISINGHPURA KHOR, LALWAS.,JAIPUR, RAJASTHAN,Khojpur,Jaipur,Rajasthan,India,302027 | GOVERNANCE DIVISION 4th FLOOR ELECTRONICS NIKETAN 6,ST=Delhi,L=South Delhi,postalCode=110003,OU=NATIONAL E GOVERNANCE DEPARTMENT,O=DIGITAL INDIA | Address does not match the trusted JSON/database dump. |
| 53 | Loan Agreement | **TRUSTED_ROI_MISMATCH**<br>_(MEDIUM)_ | 23.000000 | 6.0 | Roi does not match the trusted JSON/database dump. |
| 196 | Loan Agreement | **TRUSTED_ROI_MISMATCH**<br>_(MEDIUM)_ | 23.000000 | 6.0 | Roi does not match the trusted JSON/database dump. |
| 330 | Loan Agreement | **TRUSTED_ROI_MISMATCH**<br>_(MEDIUM)_ | 23.000000 | 6.0 | Roi does not match the trusted JSON/database dump. |
| None | KYC OSV Mark | **APPLICABILITY_UNKNOWN_S2**<br>_(LOW)_ | Physical OSV evidence is required when KYC is not digitally verified in Graviton | Required system value not supplied | Could not determine whether checklist item 2 applies. |
| None | Udyam Certificate / GST Certificate / Shop Establishment Certificate | **APPLICABILITY_UNKNOWN_S31**<br>_(LOW)_ | Required for SENP/SEP customers or when business proof is marked applicable | Required system value not supplied | Could not determine whether checklist item 31 applies. |
| None | Salary Slip / Income Tax Return / Assessed Income Document | **APPLICABILITY_UNKNOWN_S34**<br>_(LOW)_ | Required when assessed-income documents are called for by credit policy | Required system value not supplied | Could not determine whether checklist item 34 applies. |
| None | Insurance Consent Letter | **APPLICABILITY_UNKNOWN_S35**<br>_(LOW)_ | Required when insurance tenure is shorter than loan tenure | Required system value not supplied | Could not determine whether checklist item 35 applies. |
| None | PDC | **APPLICABILITY_UNKNOWN_S41**<br>_(LOW)_ | Five PDCs when ACH/NACH is registered; ten when it is not registered | Required system value not supplied | Could not determine whether checklist item 41 applies. |
| None | ACH Approval Document / NACH Form | **APPLICABILITY_UNKNOWN_S42**<br>_(LOW)_ | Required only when ACH/NACH is not registered | Required system value not supplied | Could not determine whether checklist item 42 applies. |
| 565 | Life Insurance Form | **AUTO_OWNER_UNRESOLVED**<br>_(LOW)_ | Automatic person assignment | N/A | The document type was identified, but no applicant identity matched trusted data. |
| 579 | Bank Statement | **AUTO_OWNER_UNRESOLVED**<br>_(LOW)_ | Automatic person assignment | N/A | The document type was identified, but no applicant identity matched trusted data. |
| 624 | Life Insurance Form | **AUTO_OWNER_UNRESOLVED**<br>_(LOW)_ | Automatic person assignment | N/A | The document type was identified, but no applicant identity matched trusted data. |
| 625 | Property Insurance Form | **AUTO_OWNER_UNRESOLVED**<br>_(LOW)_ | Automatic person assignment | N/A | The document type was identified, but no applicant identity matched trusted data. |
| 626 | Property Insurance Form | **AUTO_OWNER_UNRESOLVED**<br>_(LOW)_ | Automatic person assignment | N/A | The document type was identified, but no applicant identity matched trusted data. |
| 627 | Insurance Form | **AUTO_OWNER_UNRESOLVED**<br>_(LOW)_ | Automatic person assignment | N/A | The document type was identified, but no applicant identity matched trusted data. |
| 628 | Insurance Form | **AUTO_OWNER_UNRESOLVED**<br>_(LOW)_ | Automatic person assignment | N/A | The document type was identified, but no applicant identity matched trusted data. |
| 655 | Voter ID | **AUTO_OWNER_UNRESOLVED**<br>_(LOW)_ | Automatic person assignment | N/A | The document type was identified, but no applicant identity matched trusted data. |
| 656 | Voter ID | **AUTO_OWNER_UNRESOLVED**<br>_(LOW)_ | Automatic person assignment | N/A | The document type was identified, but no applicant identity matched trusted data. |
| 8 | Stamp Duty | **LOW_OCR_CONFIDENCE**<br>_(LOW)_ | Confidence above 70% | 67% confidence | OCR confidence below acceptable threshold |
| 9 | Stamp Duty | **LOW_OCR_CONFIDENCE**<br>_(LOW)_ | Confidence above 70% | 67% confidence | OCR confidence below acceptable threshold |
| 12 | Property Document | **LOW_OCR_CONFIDENCE**<br>_(LOW)_ | Confidence above 70% | 69% confidence | OCR confidence below acceptable threshold |
| 17 | Unknown | **LOW_OCR_CONFIDENCE**<br>_(LOW)_ | Confidence above 70% | 66% confidence | OCR confidence below acceptable threshold |
| 625 | Property Insurance Form | **LOW_OCR_CONFIDENCE**<br>_(LOW)_ | Confidence above 70% | 64% confidence | OCR confidence below acceptable threshold |
| 626 | Property Insurance Form | **LOW_OCR_CONFIDENCE**<br>_(LOW)_ | Confidence above 70% | 65% confidence | OCR confidence below acceptable threshold |
| 627 | Insurance Form | **LOW_OCR_CONFIDENCE**<br>_(LOW)_ | Confidence above 70% | 70% confidence | OCR confidence below acceptable threshold |
| 497 | Technical Report | **STATUS_UNVERIFIABLE_S38**<br>_(LOW)_ | clear / cleared / positive / approved | No explicit clearance status field on valuation/report pages | Technical clearance status must be cleared before disbursement (status not explicitly extractable; manual review) |
| None | KYC System Check | **SYSTEM_VALUE_UNKNOWN_S11**<br>_(LOW)_ | kyc_details_checked=true | System value not supplied | KYC details checked in system |
| 657 | Aadhaar | **TRUSTED_PERSON_SCOPE_MISSING**<br>_(LOW)_ | Automatic person assignment | N/A | The ZIP contains guarantor documents, but trusted JSON has no guarantor person record. Their values were not compared to primary. |
| 658 | PAN | **TRUSTED_PERSON_SCOPE_MISSING**<br>_(LOW)_ | Automatic person assignment | N/A | The ZIP contains guarantor documents, but trusted JSON has no guarantor person record. Their values were not compared to primary. |
| 659 | Aadhaar | **TRUSTED_PERSON_SCOPE_MISSING**<br>_(LOW)_ | Automatic person assignment | N/A | The ZIP contains guarantor documents, but trusted JSON has no guarantor person record. Their values were not compared to primary. |
| 661 | CRIF Report | **TRUSTED_PERSON_SCOPE_MISSING**<br>_(LOW)_ | Automatic person assignment | N/A | The ZIP contains guarantor documents, but trusted JSON has no guarantor person record. Their values were not compared to primary. |
| 664 | CIBIL Report | **TRUSTED_PERSON_SCOPE_MISSING**<br>_(LOW)_ | Automatic person assignment | N/A | The ZIP contains guarantor documents, but trusted JSON has no guarantor person record. Their values were not compared to primary. |
| 17 | Unknown | **UNCLASSIFIED_PAGE**<br>_(LOW)_ | Known document type | Unknown | Page could not be classified |
| 18 | Unknown | **UNCLASSIFIED_PAGE**<br>_(LOW)_ | Known document type | Unknown | Page could not be classified |
| 171 | Unknown | **UNCLASSIFIED_PAGE**<br>_(LOW)_ | Known document type | Unknown | Page could not be classified |
| 172 | Unknown | **UNCLASSIFIED_PAGE**<br>_(LOW)_ | Known document type | Unknown | Page could not be classified |
| 180 | Unknown | **UNCLASSIFIED_PAGE**<br>_(LOW)_ | Known document type | Unknown | Page could not be classified |
| 181 | Unknown | **UNCLASSIFIED_PAGE**<br>_(LOW)_ | Known document type | Unknown | Page could not be classified |
| 314 | Unknown | **UNCLASSIFIED_PAGE**<br>_(LOW)_ | Known document type | Unknown | Page could not be classified |
| 315 | Unknown | **UNCLASSIFIED_PAGE**<br>_(LOW)_ | Known document type | Unknown | Page could not be classified |
| 448 | Unknown | **UNCLASSIFIED_PAGE**<br>_(LOW)_ | Known document type | Unknown | Page could not be classified |
| 449 | Unknown | **UNCLASSIFIED_PAGE**<br>_(LOW)_ | Known document type | Unknown | Page could not be classified |
| 547 | Unknown | **UNCLASSIFIED_PAGE**<br>_(LOW)_ | Known document type | Unknown | Page could not be classified |
| 548 | Unknown | **UNCLASSIFIED_PAGE**<br>_(LOW)_ | Known document type | Unknown | Page could not be classified |
| 549 | Unknown | **UNCLASSIFIED_PAGE**<br>_(LOW)_ | Known document type | Unknown | Page could not be classified |
| 550 | Unknown | **UNCLASSIFIED_PAGE**<br>_(LOW)_ | Known document type | Unknown | Page could not be classified |
| 551 | Unknown | **UNCLASSIFIED_PAGE**<br>_(LOW)_ | Known document type | Unknown | Page could not be classified |
| 552 | Unknown | **UNCLASSIFIED_PAGE**<br>_(LOW)_ | Known document type | Unknown | Page could not be classified |
| 553 | Unknown | **UNCLASSIFIED_PAGE**<br>_(LOW)_ | Known document type | Unknown | Page could not be classified |
| 564 | Unknown | **UNCLASSIFIED_PAGE**<br>_(LOW)_ | Known document type | Unknown | Page could not be classified |
| 566 | Unknown | **UNCLASSIFIED_PAGE**<br>_(LOW)_ | Known document type | Unknown | Page could not be classified |
| 567 | Unknown | **UNCLASSIFIED_PAGE**<br>_(LOW)_ | Known document type | Unknown | Page could not be classified |
| 568 | Unknown | **UNCLASSIFIED_PAGE**<br>_(LOW)_ | Known document type | Unknown | Page could not be classified |
| 613 | Unknown | **UNCLASSIFIED_PAGE**<br>_(LOW)_ | Known document type | Unknown | Page could not be classified |
| 614 | Unknown | **UNCLASSIFIED_PAGE**<br>_(LOW)_ | Known document type | Unknown | Page could not be classified |
| 615 | Unknown | **UNCLASSIFIED_PAGE**<br>_(LOW)_ | Known document type | Unknown | Page could not be classified |
| 616 | Unknown | **UNCLASSIFIED_PAGE**<br>_(LOW)_ | Known document type | Unknown | Page could not be classified |
| 629 | Unknown | **UNCLASSIFIED_PAGE**<br>_(LOW)_ | Known document type | Unknown | Page could not be classified |
| 16 | Aadhaar | **AADHAAR_ADDRESS_MISMATCH**<br>_(HIGH)_ | GOVERNANCE DIVISION 4th FLOOR ELECTRONICS NIKETAN 6,ST=Delhi,L=South Delhi,postalCode=110003,OU=NATIONAL E GOVERNANCE DEPARTMENT,O=DIGITAL INDIA | बाग, (राज) | Address does not match the Aadhaar address for primary. |
| 26 | CAM | **AADHAAR_ADDRESS_MISMATCH**<br>_(HIGH)_ | GOVERNANCE DIVISION 4th FLOOR ELECTRONICS NIKETAN 6,ST=Delhi,L=South Delhi,postalCode=110003,OU=NATIONAL E GOVERNANCE DEPARTMENT,O=DIGITAL INDIA | S/O Prem Shankar, 33,JYOTIBA FULE NAGAR, JAISINGHPURA KHOR, LALWAS.,JAIPUR, RAJASTHAN,Khojpur,Jaipur,Rajasthan,India,302027 | Address does not match the Aadhaar address for primary. |
| 40 | Application Form | **AADHAAR_ADDRESS_MISMATCH**<br>_(HIGH)_ | GOVERNANCE DIVISION 4th FLOOR ELECTRONICS NIKETAN 6,ST=Delhi,L=South Delhi,postalCode=110003,OU=NATIONAL E GOVERNANCE DEPARTMENT,O=DIGITAL INDIA | S/O Prem Shankar, 33,JYOTIBA FULE NAGAR, Khojpur, Page 2 of 132 | Address does not match the Aadhaar address for primary. |
| 183 | Application Form | **AADHAAR_ADDRESS_MISMATCH**<br>_(HIGH)_ | GOVERNANCE DIVISION 4th FLOOR ELECTRONICS NIKETAN 6,ST=Delhi,L=South Delhi,postalCode=110003,OU=NATIONAL E GOVERNANCE DEPARTMENT,O=DIGITAL INDIA | S/O Prem Shankar, 33,JYOTIBA FULE NAGAR, Khojpur, Page 2 of 132 | Address does not match the Aadhaar address for primary. |
| 316 | Application Form | **AADHAAR_ADDRESS_MISMATCH**<br>_(HIGH)_ | GOVERNANCE DIVISION 4th FLOOR ELECTRONICS NIKETAN 6,ST=Delhi,L=South Delhi,postalCode=110003,OU=NATIONAL E GOVERNANCE DEPARTMENT,O=DIGITAL INDIA | S/O Prem Shankar, 33,JYOTIBA FULE NAGAR, Khojpur, Page 2 of 132, Jaipur, Rajasthan, India, 302027 | Address does not match the Aadhaar address for primary. |
| 317 | Application Form | **AADHAAR_ADDRESS_MISMATCH**<br>_(HIGH)_ | GOVERNANCE DIVISION 4th FLOOR ELECTRONICS NIKETAN 6,ST=Delhi,L=South Delhi,postalCode=110003,OU=NATIONAL E GOVERNANCE DEPARTMENT,O=DIGITAL INDIA | S/O Prem Shankar, 33,JYOTIBA FULE NAGAR, Khojpur, Page 2 of 132 | Address does not match the Aadhaar address for primary. |
| 671 | Aadhaar | **AADHAAR_ADDRESS_MISMATCH**<br>_(HIGH)_ | GOVERNANCE DIVISION 4th FLOOR ELECTRONICS NIKETAN 6,ST=Delhi,L=South Delhi,postalCode=110003,OU=NATIONAL E GOVERNANCE DEPARTMENT,O=DIGITAL INDIA | bikrampur,Khojpur,Kasganj,Khojpur,K asganj,Uttar Pradesh,207245 | Address does not match the Aadhaar address for primary. |
| 639 | Bank Statement | **CROSS_DOCUMENT_ACCOUNT_NUMBER_MISMATCH**<br>_(HIGH)_ | 8153638019 (CAM) | 30536 (Bank Statement) | Account Number is inconsistent across documents for primary. |
| 494 | Bank Statement | **CROSS_DOCUMENT_APPLICANT_NAME_MISMATCH**<br>_(HIGH)_ | Neeraj Sharma (Aadhaar) | Loan Detail (Bank Statement) | Applicant Name is inconsistent across documents for primary. |
| 644 | Bank Statement | **CROSS_DOCUMENT_APPLICANT_NAME_MISMATCH**<br>_(HIGH)_ | RITA SHARMA (PAN) | Govind Yadav (Bank Statement) | Applicant Name is inconsistent across documents for coapplicant_1. |
| 494 | Bank Statement | **CROSS_DOCUMENT_APPLICATION_NUMBER_MISMATCH**<br>_(HIGH)_ | RJ000030677 (CAM) | APJPR00351 (Bank Statement) | Application Number is inconsistent across documents for primary. |
| 639 | Bank Statement | **CROSS_DOCUMENT_IFSC_MISMATCH**<br>_(HIGH)_ | IDIB000J525 (CAM) | RMGB0000001 (Bank Statement) | Ifsc is inconsistent across documents for primary. |
| 650 | CERSAI Report | **CROSS_DOCUMENT_PAN_NUMBER_MISMATCH**<br>_(HIGH)_ | GJPPS9903E (CAM) | AAECC5770G (CERSAI Report) | Pan Number is inconsistent across documents for primary. |
| 53 | Loan Agreement | **FIELD_MISMATCH_S12**<br>_(HIGH)_ | 23.000000 | 6.0 | Loan document field mismatch: roi |
| 494 | Bank Statement | **TRUSTED_APPLICANT_NAME_MISMATCH**<br>_(HIGH)_ | Neeraj Sharma | Loan Detail | Applicant Name does not match the trusted JSON/database dump. |
| 644 | Bank Statement | **TRUSTED_APPLICANT_NAME_MISMATCH**<br>_(HIGH)_ | Rita  Sharma | Govind Yadav | Applicant Name does not match the trusted JSON/database dump. |
| 494 | Bank Statement | **TRUSTED_APPLICATION_NUMBER_MISMATCH**<br>_(HIGH)_ | RJ000030677 | APJPR00351 | Application Number does not match the trusted JSON/database dump. |
| 650 | CERSAI Report | **TRUSTED_PAN_NUMBER_MISMATCH**<br>_(HIGH)_ | GJPPS9903E | AAECC5770G | Pan Number does not match the trusted JSON/database dump. |
| 671 | Aadhaar | **TRUSTED_PIN_CODE_MISMATCH**<br>_(HIGH)_ | 302027 | 207245 | Pin Code does not match the trusted JSON/database dump. |
| 672 | Aadhaar | **TRUSTED_PIN_CODE_MISMATCH**<br>_(HIGH)_ | 302027 | 110003 | Pin Code does not match the trusted JSON/database dump. |