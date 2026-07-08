// Generated from database.models.ChecklistVerificationResponse.
// Regenerate with scripts/export_checklist_types.py after schema changes.

export type ChecklistStatus = "verified" | "needs_review" | "missing" | "unknown";
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
  verified: number;
  needs_review: number;
  missing: number;
  unknown: number;
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
