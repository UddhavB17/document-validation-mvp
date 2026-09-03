import { z } from "zod";
export { normalizeDocumentType } from "./documentType";

// The API module owns two concerns: validating backend payloads and exposing
// the small set of requests used by the frontend. Keeping both here makes the
// request/response contract easy to find when adding a new screen.

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

// Shared schema pieces used by several response shapes.
const nullableString = z.string().nullable().optional();
const dynamicFieldsSchema = z.record(z.unknown());
const nullableValue = z.union([z.string(), z.number()]).nullable().optional();

// ZIP preparation and upload responses.
export const zipDocumentSchema = z.object({
  source_document_id: z.string(),
  original_filename: z.string(),
  file_type: z.string(),
  source_size_bytes: z.number(),
  page_count: z.number(),
  internal_page_start: z.number(),
  internal_page_end: z.number(),
  worksheets: z.array(z.string()).nullable().optional(),
});

export const zipProgressEventSchema = z.object({
  stage: z.string().nullable().optional(),
  message: z.string().nullable().optional(),
  processed_files: z.number().nullable().optional(),
  total_files: z.number().nullable().optional(),
  current_file: nullableString,
  elapsed_seconds: z.number().nullable().optional(),
  timestamp: nullableString,
});

export const zipPreparationProgressSchema = z.object({
  package_id: z.string(),
  status: z.string(),
  stage: nullableString,
  message: nullableString,
  processed_files: z.number().optional(),
  total_files: z.number().optional(),
  current_file: nullableString,
  total_pages: z.number().optional(),
  documents: z.array(zipDocumentSchema).optional(),
  verify_url: nullableString,
  error: nullableString,
  events: z.array(zipProgressEventSchema).optional(),
});

export const zipPackageUploadResponseSchema = z.object({
  package_id: z.string(),
  status: z.string(),
  progress_url: z.string(),
  verify_url: z.string().optional(),
  total_files: z.number().optional(),
  total_pages: z.number().optional(),
  documents: z.array(zipDocumentSchema).optional(),
});

export type ZipDocument = z.infer<typeof zipDocumentSchema>;
export type ZipPreparationProgress = z.infer<typeof zipPreparationProgressSchema>;
export type ZipPackageUploadResponse = z.infer<typeof zipPackageUploadResponseSchema>;

// Core upload, processing, worklist, and review responses.
export const healthSchema = z.object({
  status: z.string(),
  version: z.string().optional(),
});

export const uploadResponseSchema = z.object({
  application_id: z.number(),
  job_id: z.number().optional(),
  loan_id: z.string(),
  status: z.string(),
  pipeline_status: z.string(),
  progress_url: z.string().optional(),
  total_pages: z.number().optional(),
  digital_pages: z.number().optional(),
  scanned_pages: z.number().optional(),
  mapped_pages: z.array(z.number()).optional(),
  documents_found: z.array(z.string()).optional(),
  documents_missing: z.array(z.string()).optional(),
  anomaly_count: z.number().optional(),
});

export const pageEventSchema = z.object({
  page_number: z.number().nullable().optional(),
  total_pages: z.number().nullable().optional(),
  page_type: nullableString,
  document_type: nullableString,
  status: z.string().nullable().optional(),
  elapsed_seconds: z.number().nullable().optional(),
  error: nullableString,
  extracted_fields: dynamicFieldsSchema.optional(),
  completed_at: nullableString,
});

export const progressSchema = z.object({
  application_id: z.number().optional(),
  stage: z.string().optional(),
  total_pages: z.number().optional(),
  digital_pages: z.number().optional(),
  scanned_pages: z.number().optional(),
  processed_pages: z.number().optional(),
  last_processed_page: z.number().nullable().optional(),
  current_page: z.number().nullable().optional(),
  percentage: z.number().nullable().optional(),
  status: z.string().optional(),
  operational_status: z.string().optional(),
  is_stale: z.boolean().optional(),
  retryable: z.boolean().optional(),
  message: nullableString,
  error: nullableString,
  eta_seconds: z.number().nullable().optional(),
  completed_pages: z.array(pageEventSchema).optional(),
});

export const worklistItemSchema = z.object({
  id: z.number(),
  loan_id: z.string(),
  applicant_name: nullableString,
  product_type: nullableString,
  status: z.string(),
  created_at: z.string(),
  issues: z.number(),
  reviewer_issues: z.number(),
  business_issues: z.number(),
  processing_warnings: z.number(),
  pipeline_status: z.string(),
  pipeline_retryable: z.boolean(),
});

export const worklistSchema = z.object({
  items: z.array(worklistItemSchema),
});

export const activitySchema = z.object({
  total: z.number(),
  accepted: z.number(),
  overridden: z.number(),
  sent_back: z.number(),
  rows: z.array(
    z.object({
      id: z.number(),
      application_id: z.number(),
      loan_id: z.string(),
      decision: z.string(),
      decided_at: z.string(),
    }),
  ),
});

export const decisionSchema = z.object({
  id: z.number().optional(),
  decision_id: z.number().optional(),
  application_id: z.number(),
  decision: z.string(),
  reviewer_note: nullableString,
  decided_at: nullableString,
  new_status: nullableString,
  previous_status: nullableString,
  restored_status: nullableString,
});

// Settings responses share this shape; the update response adds a status.
const settingSchemaShape = {
  config_key: z.string(),
  config_value: z.string(),
  value_type: z.string(),
  category: z.string(),
  label: nullableString,
  description: nullableString,
  is_secret: z.boolean().optional(),
  has_value: z.boolean().optional(),
};

export const settingSchema = z.object(settingSchemaShape);

export const settingUpdateResponseSchema = z.object({
  status: z.string(),
  ...settingSchemaShape,
});

export const checklistRowSchema = z.object({
  s_no: z.number().nullable().optional(),
  status: z.string(),
  description: z.string(),
  document_types: z.string(),
  pages: z.string(),
});

export const anomalySchema = z.object({
  id: z.number().optional(),
  application_id: z.number().optional(),
  rule_id: nullableString,
  s_no: z.number().nullable().optional(),
  severity: nullableString,
  document_type: nullableString,
  expected_value: nullableString,
  found_value: nullableString,
  page_number: z.number().nullable().optional(),
  reason: nullableString,
  status: nullableString,
  created_at: nullableString,
  collapsed_page_numbers: z.array(z.number()).optional(),
});

export const applicationSchema = z.object({
  id: z.number().optional(),
  loan_id: nullableString,
  applicant_name: nullableString,
  coapplicant_name: nullableString,
  product_type: nullableString,
  branch: nullableString,
  status: nullableString,
  llm_summary: nullableString,
  created_at: nullableString,
  updated_at: nullableString,
  // These fields are present in some persisted application payloads, but are
  // not required by the upload route.
  purpose: nullableValue,
  property_address: nullableValue,
  loan_amount: nullableValue,
  roi: nullableValue,
  tenure: nullableValue,
  emi: nullableValue,
  case_type: nullableString,
});

export const uploadedFileSchema = z.object({
  id: z.number().optional(),
  application_id: z.number().optional(),
  file_path: nullableString,
  original_filename: nullableString,
  file_size_kb: z.number().nullable().optional(),
  total_pages: z.number().nullable().optional(),
  digital_pages: z.number().nullable().optional(),
  scanned_pages: z.number().nullable().optional(),
  uploaded_at: nullableString,
});

export const groundTruthSchema = z.object({
  id: z.number().optional(),
  application_id: z.number().optional(),
  applicant_name: nullableString,
  pan_number: nullableString,
  loan_amount: nullableString,
  phone: nullableString,
  address: nullableString,
  product_type: nullableString,
  raw_json: nullableString,
  extracted_at: nullableString,
  roi: nullableValue,
  tenure: nullableValue,
  emi: nullableValue,
});

export const pageSchema = z.object({
  id: z.number().optional(),
  application_id: z.number().optional(),
  page_number: z.number().nullable().optional(),
  page_type: nullableString,
  image_path: nullableString,
  // SQLite returns INTEGER 0/1 for this BOOLEAN column.
  is_readable: z.union([z.boolean(), z.number().int().min(0).max(1)]).nullable().optional(),
  ocr_text: nullableString,
  ocr_confidence: z.number().nullable().optional(),
  document_type: nullableString,
  classification_confidence: z.number().nullable().optional(),
  detection_method: nullableString,
  detected_page_number: z.number().nullable().optional(),
  extracted_fields: dynamicFieldsSchema.optional(),
});

export const reviewDocumentTypeSchema = z.union([z.string(), z.array(z.string())]).nullable().optional();
export type ReviewDocumentType = z.infer<typeof reviewDocumentTypeSchema>;

export const reviewItemSchema = z.object({
  s_no: z.union([z.number(), z.string()]).nullable().optional(),
  page_number: z.number().nullable().optional(),
  person_id: nullableString,
  matched_person_id: nullableString,
  document_type: reviewDocumentTypeSchema,
  field: nullableString,
  category: nullableString,
  description: nullableString,
  status: nullableString,
  severity: nullableString,
  reason: nullableString,
  expected_masked: nullableString,
  extracted_masked: nullableString,
  collapsed_count: z.number().nullable().optional(),
});

export const reviewerSummarySchema = z.object({
  overall_status: z.string(),
  message: z.string(),
  recommendation: z.string(),
  total_pages: z.number(),
  checked_fields: z.number(),
  matched_fields: z.number(),
  anomaly_count: z.number(),
  raw_anomaly_count: z.number(),
  severity_counts: z.object({
    high: z.number(),
    medium: z.number(),
    low: z.number(),
  }),
  pages_to_review: z.array(z.number()),
  review_items: z.array(reviewItemSchema),
  note: nullableString,
});

const comparisonStatusSchema = z.enum(["match", "mismatch", "attention"]);

export const fieldComparisonSchema = z.object({
  field_name: z.string(),
  label: z.string(),
  expected_value: z.string().nullable(),
  extracted_value: z.string().nullable(),
  status: comparisonStatusSchema,
  source_pages: z.array(z.number()),
});

export const applicantComparisonSchema = z.object({
  applicant_role: z.enum(["primary", "co_applicant", "guarantor"]),
  applicant_label: z.string(),
  person_name: z.string(),
  fields: z.array(fieldComparisonSchema),
});

export const comparisonMatrixSchema = z.object({
  core_parameters: z.array(fieldComparisonSchema),
  applicants: z.array(applicantComparisonSchema),
});

export const relationshipNodeSchema = z.object({
  id: z.string(),
  name: z.string(),
  role: z.enum(["primary", "co_applicant", "guarantor", "family_member"]),
  relation_to_primary: z.string().nullable(),
  status: z.enum(["match", "mismatch", "attention", "n/a"]),
});

export const reviewDocumentSchema = z.object({
  name: z.string(),
  type: z.string(),
  // The review route returns a display range such as "1–3", not a count.
  pages: z.string(),
  status: z.string(),
  firstPage: z.number(),
});

export const applicationReviewSchema = z.object({
  application: applicationSchema,
  uploaded_file: uploadedFileSchema,
  ground_truth: groundTruthSchema,
  anomalies: z.array(anomalySchema),
  pages: z.array(pageSchema),
  page_events: z.array(pageEventSchema),
  documents_found: z.array(z.string()),
  document_pages: z.record(z.array(z.number())),
  documents_missing: z.array(z.string().nullable()),
  summary: z.object({
    raw_count: z.number(),
    reviewer_count: z.number(),
    high_count: z.number(),
    medium_count: z.number().optional(),
    low_count: z.number().optional(),
    reviewer_anomalies: z.array(anomalySchema),
    business_count: z.number(),
    processing_warning_count: z.number(),
    business_anomalies: z.array(anomalySchema),
    processing_warnings: z.array(anomalySchema),
  }),
  reviewer_summary: reviewerSummarySchema.nullable(),
  manual_review_items: z.array(reviewItemSchema),
  checklist: z.object({
    total: z.number(),
    found: z.number(),
    missing: z.number(),
    not_checked: z.number(),
    rows: z.array(checklistRowSchema),
  }),
  ai_checklist: z.object({
    passed: z.number(),
    total: z.number(),
  }),
  latest_decision: decisionSchema.nullable(),
  progress: progressSchema.nullable(),
  comparison_matrix: comparisonMatrixSchema.optional(),
  relationships: z.array(relationshipNodeSchema).optional(),
  documents: z.array(reviewDocumentSchema).optional(),
});

export const reprocessResponseSchema = z.object({
  application_id: z.number(),
  job_id: z.number(),
  status: z.string(),
  pipeline_status: z.string(),
  previous_pipeline_status: z.string(),
});

export type Health = z.infer<typeof healthSchema>;
export type UploadResponse = z.infer<typeof uploadResponseSchema>;
export type Progress = z.infer<typeof progressSchema>;
export type WorklistItem = z.infer<typeof worklistItemSchema>;
export type Activity = z.infer<typeof activitySchema>;
export type Decision = z.infer<typeof decisionSchema>;
export type Setting = z.infer<typeof settingSchema>;
export type SettingUpdateResponse = z.infer<typeof settingUpdateResponseSchema>;
export type ApplicationReview = z.infer<typeof applicationReviewSchema>;
export type Anomaly = z.infer<typeof anomalySchema>;
export type ChecklistRow = z.infer<typeof checklistRowSchema>;
export type ApplicantComparison = z.infer<typeof applicantComparisonSchema>;
export type FieldComparison = z.infer<typeof fieldComparisonSchema>;
export type RelationshipNode = z.infer<typeof relationshipNodeSchema>;
export type ReviewDocument = z.infer<typeof reviewDocumentSchema>;
export type ReviewItem = z.infer<typeof reviewItemSchema>;
export type ZipProgressEvent = z.infer<typeof zipProgressEventSchema>;

// Transport errors are normalized before a response is parsed by its Zod schema.
export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
  }
}

async function parseApiResponse<T>(response: Response, schema: z.ZodType<T>): Promise<T> {
  const text = await response.text();
  let payload: unknown = {};
  try {
    payload = text ? JSON.parse(text) : {};
  } catch {
    throw new ApiError(text || "Backend returned a non-JSON response", response.status);
  }
  if (!response.ok) {
    const detailPayload = getApiErrorDetail(payload);
    const detail = typeof detailPayload === "string" ? detailPayload : JSON.stringify(detailPayload);
    throw new ApiError(detail || "Request failed", response.status);
  }
  return schema.parse(payload);
}

function getApiErrorDetail(payload: unknown): unknown {
  if (typeof payload === "object" && payload !== null && "detail" in payload) {
    return payload.detail;
  }
  return payload;
}

async function getJsonResponse<T>(path: string, schema: z.ZodType<T>): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`);
  return parseApiResponse(response, schema);
}

async function postJsonResponse<T>(path: string, body: unknown, schema: z.ZodType<T>): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return parseApiResponse(response, schema);
}

async function patchJsonResponse<T>(path: string, body: unknown, schema: z.ZodType<T>): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return parseApiResponse(response, schema);
}

// Public request methods. Endpoint paths and payload field names stay aligned
// with the backend contract; callers should not build these requests directly.
export const api = {
  health: () => getJsonResponse("/health", healthSchema),
  worklist: () => getJsonResponse("/review/worklist", worklistSchema),
  activityToday: () => getJsonResponse("/review/activity/today", activitySchema),
  settings: () => getJsonResponse("/settings", z.array(settingSchema)),
  updateSetting: (configKey: string, configValue: string, clearSecret = false) =>
    patchJsonResponse(
      `/settings/${configKey}`,
      { config_value: configValue, clear_secret: clearSecret },
      settingUpdateResponseSchema,
    ),
  applicationReview: (applicationId: number) => getJsonResponse(`/review/applications/${applicationId}`, applicationReviewSchema),
  progress: (applicationId: number) => getJsonResponse(`/upload/${applicationId}/progress`, progressSchema),
  uploadPdf: async (payload: {
    loanId: string;
    applicantName: string;
    coapplicantName?: string;
    productType: string;
    branch: string;
    caseType: "Normal Case" | "BT Case";
    applicationDate: string;
    file: File;
  }) => {
    const formData = new FormData();
    formData.append("loan_id", payload.loanId);
    formData.append("applicant_name", payload.applicantName);
    formData.append("coapplicant_name", payload.coapplicantName ?? "");
    formData.append("product_type", payload.productType);
    formData.append("branch", payload.branch);
    formData.append("case_type", payload.caseType);
    formData.append("application_date", payload.applicationDate);
    formData.append("file", payload.file);
    const response = await fetch(`${API_BASE_URL}/upload`, { method: "POST", body: formData });
    return parseApiResponse(response, uploadResponseSchema);
  },
  uploadMapped: async (payload: { manifest?: string; caseType: "Normal Case" | "BT Case"; file: File }) => {
    const formData = new FormData();
    if (payload.manifest !== undefined) {
      formData.append("manifest", payload.manifest);
    }
    formData.append("case_type", payload.caseType);
    formData.append("file", payload.file);
    const response = await fetch(`${API_BASE_URL}/upload/mapped`, { method: "POST", body: formData });
    return parseApiResponse(response, uploadResponseSchema);
  },
  uploadPartnerJson: (payload: unknown) => postJsonResponse("/upload/json", payload, uploadResponseSchema),
  prepareZipPackage: async (file: File) => {
    const formData = new FormData();
    formData.append("file", file);
    const response = await fetch(`${API_BASE_URL}/upload/package?background=true`, {
      method: "POST",
      body: formData,
    });
    return parseApiResponse(response, zipPackageUploadResponseSchema);
  },
  getZipPreparationProgress: (packageId: string) =>
    getJsonResponse(`/upload/package/${packageId}/preparation`, zipPreparationProgressSchema),
  verifyZipPackage: async (packageId: string, manifest: string, caseType: "Normal Case" | "BT Case") => {
    const formData = new FormData();
    formData.append("manifest", manifest);
    formData.append("case_type", caseType);
    const response = await fetch(`${API_BASE_URL}/upload/package/${packageId}/verify`, {
      method: "POST",
      body: formData,
    });
    return parseApiResponse(response, uploadResponseSchema);
  },
  createDecision: (payload: { application_id: number; decision: string; reviewer_note: string }) =>
    postJsonResponse("/decision", payload, decisionSchema),
  undoDecision: (decisionId: number) => postJsonResponse(`/decision/${decisionId}/undo`, {}, decisionSchema),
  reprocessApplication: (applicationId: number) =>
    postJsonResponse(`/review/applications/${applicationId}/reprocess`, {}, reprocessResponseSchema),
  sourcePdfUrl: (applicationId: number, pageNumber?: number) => {
    const base = `${API_BASE_URL}/review/applications/${applicationId}/source-pdf`;
    return pageNumber ? `${base}#page=${pageNumber}&zoom=page-width` : base;
  },
  sourcePageImageUrl: (applicationId: number, pageNumber: number, highlight?: string) => {
    const base = `${API_BASE_URL}/review/applications/${applicationId}/source-page/${pageNumber}`;
    return highlight ? `${base}?highlight=${encodeURIComponent(highlight)}` : base;
  },
  ocrJsonUrl: (applicationId: number) => `${API_BASE_URL}/review/applications/${applicationId}/ocr-json`,
};
