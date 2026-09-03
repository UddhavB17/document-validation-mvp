import { DocumentFieldSchema } from "./types";

export const ALL_FIELD_SCHEMAS = {
  pan: { label: "PAN Card", fields: ["pan_number", "applicant_name", "dob"] },
  aadhaar: { label: "Aadhaar Card", fields: ["aadhaar_number", "applicant_name", "dob", "address", "pin_code"] },
  voter_id: { label: "Voter ID", fields: ["voter_id_number", "applicant_name", "dob", "address"] },
  driving_license: { label: "Driving License", fields: ["dl_number", "applicant_name", "dob", "validity_date", "is_expired"] },
  sanction_letter: { label: "Sanction Letter / KFS", fields: ["loan_amount", "tenure", "emi", "roi", "applicant_name"] },
  loan_agreement: { label: "Loan Agreement", fields: ["loan_amount", "tenure", "emi", "roi", "borrower_name", "agreement_date"] },
  cibil_report: { label: "CIBIL Report", fields: ["credit_score", "applicant_name", "report_date"] },
  crif_report: { label: "CRIF Report", fields: ["credit_score", "applicant_name", "report_date"] },
  bank_statement: { label: "Bank Statement", fields: ["account_holder_name", "account_number", "ifsc"] },
  passbook: { label: "Passbook", fields: ["account_holder_name", "account_number", "ifsc"] },
  cheque: { label: "Cheque / Cancelled Cheque", fields: ["account_holder_name", "account_number", "cheque_number", "ifsc", "is_cancelled"] },
  salary_slip: { label: "Salary Slip", fields: ["applicant_name", "salary_month", "net_salary"] },
  stamp_duty: { label: "Stamp Duty", fields: ["stamp_duty_amount", "stamp_paper_number", "first_party", "second_party"] },
  insurance_consent: { label: "Insurance Consent", fields: ["is_consent_given", "premium_amount"] },
  clearance_report: { label: "Clearance Report (CERSAI)", fields: ["search_result", "debtor_name", "pan_number"] },
  nach_form: { label: "NACH Form", fields: ["account_number", "ifsc", "mandate_limit"] },
  utility_bill: { label: "Utility Bill", fields: ["applicant_name", "address", "pin_code"] },
  application_form: { label: "Application Form", fields: ["applicant_name", "pan_number", "aadhaar_number", "date_of_birth", "phone_number", "address", "pin_code", "loan_amount"] },
} satisfies Record<string, DocumentFieldSchema>;
