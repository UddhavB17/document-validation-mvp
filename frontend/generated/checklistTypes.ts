// Generated from database.models.ChecklistVerificationResponse.
// Regenerate with scripts/export_checklist_types.py after schema changes.

export type ChecklistStatus = "required_and_present" | "required_and_missing" | "not_applicable" | "not_evaluated_by_engine" | "manual_review";
export type OcrStatus = "success" | "failed" | "no_text_extracted" | "not_applicable";
export type ChecklistConfidence = "high" | "medium" | "low";
export type ChecklistExtractionSource = "deterministic" | "llm_fallback";

export interface ChecklistItem {
  item_number: number;
  document_name: string;
  status: ChecklistStatus;
  confidence: ChecklistConfidence;
  confidence_detail: string;
  extracted_fields: Record<string, string | null>;
  extraction_source: ChecklistExtractionSource;
  narration?: string | null;
  flagged_reason?: string | null;
}

export interface ChecklistSummary {
  total: number;
  required_and_present: number;
  required_and_missing: number;
  not_applicable: number;
  not_evaluated_by_engine: number;
  manual_review: number;
}

export interface ChecklistProcessingMetadata {
  ocr_time_ms: number;
  classification_time_ms: number;
  narration_time_ms: number;
}

export interface ChecklistVerificationResponse {
  loan_file_id: string;
  summary: ChecklistSummary;
  items: ChecklistItem[];
  processing_metadata: ChecklistProcessingMetadata;
}
