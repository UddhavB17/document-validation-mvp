import type { ChecklistVerificationResponse } from "../generated/checklistTypes";

export const checklistMock: ChecklistVerificationResponse = {
  loan_file_id: "LAP-APPLICATION-31",
  summary: {
    total: 44,
    verified: 38,
    needs_review: 4,
    missing: 1,
    unknown: 1,
    not_applicable: 0,
  },
  processing_metadata: {
    ocr_time_ms: 76420,
    classification_time_ms: 18200,
    narration_time_ms: 2300,
  },
  items: [
    {
      item_number: 1,
      document_name: "Application Form",
      status: "verified",
      confidence: "high",
      confidence_detail: "matched 1 of 1 expected page(s); lowest classification confidence 96%",
      extracted_fields: {
        applicant_name: "Amit Sharma",
        loan_amount: "2500000",
      },
      extraction_source: "deterministic",
      narration: null,
      flagged_reason: null,
    },
    {
      item_number: 7,
      document_name: "PAN",
      status: "needs_review",
      confidence: "medium",
      confidence_detail: "PAN number differs from digital application form; expected TSTAA0001T, found TSTAA0009T",
      extracted_fields: {
        applicant_name: "Amit Sharma",
        pan_number: "TSTAA0009T",
      },
      extraction_source: "deterministic",
      narration: "needs_review was assigned because the extracted PAN number TSTAA0009T does not match the digital application value TSTAA0001T.",
      flagged_reason: "pan_number_mismatch",
    },
    {
      item_number: 19,
      document_name: "Bank Statement",
      status: "missing",
      confidence: "low",
      confidence_detail: "matched 0 of 1 expected page(s)",
      extracted_fields: {},
      extraction_source: "deterministic",
      narration: "missing was assigned because no confident Bank Statement page was found for this checklist item.",
      flagged_reason: "missing_doc_s19",
    },
    {
      item_number: 26,
      document_name: "CERSAI",
      status: "unknown",
      confidence: "low",
      confidence_detail: "no deterministic checklist rule could verify this item",
      extracted_fields: {
        search_reference_number: "MHL12345",
      },
      extraction_source: "llm_fallback",
      narration: "unknown was assigned because the page was handled through fallback extraction and requires manual confirmation before checklist approval.",
      flagged_reason: "manual_review_required",
    },
  ],
};
