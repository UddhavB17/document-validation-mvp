import { z } from "zod";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

const nullableString = z.string().nullable().optional();
const recordSchema = z.record(z.unknown());

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
  extracted_fields: recordSchema.optional(),
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

export const checklistRowSchema = z.object({
  s_no: z.number().nullable().optional(),
  status: z.string(),
  description: z.string(),
  document_types: z.string(),
  pages: z.string(),
  reason: z.string().nullable().optional(),
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

export const applicationReviewSchema = z.object({
  application: recordSchema,
  uploaded_file: recordSchema,
  ground_truth: recordSchema,
  anomalies: z.array(anomalySchema),
  pages: z.array(recordSchema),
  page_events: z.array(pageEventSchema),
  documents_found: z.array(z.string()),
  document_pages: z.record(z.array(z.number())),
  documents_missing: z.array(z.string().nullable()),
  summary: z.object({
    raw_count: z.number(),
    reviewer_count: z.number(),
    high_count: z.number(),
    reviewer_anomalies: z.array(anomalySchema),
    business_count: z.number(),
    processing_warning_count: z.number(),
    business_anomalies: z.array(anomalySchema),
    processing_warnings: z.array(anomalySchema),
  }),
  reviewer_summary: recordSchema.nullable(),
  manual_review_items: z.array(recordSchema),
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
  comparison_matrix: z.any().optional(),
  relationships: z.any().optional(),
  documents: z.any().optional(),
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
export type ApplicationReview = z.infer<typeof applicationReviewSchema>;
export type Anomaly = z.infer<typeof anomalySchema>;

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
  }
}

async function parseResponse<T>(response: Response, schema: z.ZodType<T>): Promise<T> {
  const text = await response.text();
  let payload: unknown = {};
  try {
    payload = text ? JSON.parse(text) : {};
  } catch {
    throw new ApiError(text || "Backend returned a non-JSON response", response.status);
  }
  if (!response.ok) {
    const errorPayload = payload as { detail?: unknown };
    const detail = typeof errorPayload.detail === "string" ? errorPayload.detail : JSON.stringify(errorPayload.detail ?? payload);
    throw new ApiError(detail || "Request failed", response.status);
  }
  return schema.parse(payload);
}

async function getJson<T>(path: string, schema: z.ZodType<T>): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`);
  return parseResponse(response, schema);
}

async function postJson<T>(path: string, body: unknown, schema: z.ZodType<T>): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return parseResponse(response, schema);
}

export const api = {
  health: () => getJson("/health", healthSchema),
  worklist: () => getJson("/review/worklist", worklistSchema),
  activityToday: () => getJson("/review/activity/today", activitySchema),
  applicationReview: (applicationId: number) => getJson(`/review/applications/${applicationId}`, applicationReviewSchema),
  progress: (applicationId: number) => getJson(`/upload/${applicationId}/progress`, progressSchema),
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
    return parseResponse(response, uploadResponseSchema);
  },
  uploadMapped: async (payload: { manifest?: string; caseType: "Normal Case" | "BT Case"; file: File }) => {
    const formData = new FormData();
    if (payload.manifest !== undefined) {
      formData.append("manifest", payload.manifest);
    }
    formData.append("case_type", payload.caseType);
    formData.append("file", payload.file);
    const response = await fetch(`${API_BASE_URL}/upload/mapped`, { method: "POST", body: formData });
    return parseResponse(response, uploadResponseSchema);
  },
  uploadPartnerJson: (payload: unknown) => postJson("/upload/json", payload, uploadResponseSchema),
  prepareZipPackage: async (file: File) => {
    const formData = new FormData();
    formData.append("file", file);
    const response = await fetch(`${API_BASE_URL}/upload/package?background=true`, {
      method: "POST",
      body: formData,
    });
    return parseResponse(response, zipPackageUploadResponseSchema);
  },
  getZipPreparationProgress: (packageId: string) =>
    getJson(`/upload/package/${packageId}/preparation`, zipPreparationProgressSchema),
  verifyZipPackage: async (packageId: string, manifest: string, caseType: "Normal Case" | "BT Case") => {
    const formData = new FormData();
    formData.append("manifest", manifest);
    formData.append("case_type", caseType);
    const response = await fetch(`${API_BASE_URL}/upload/package/${packageId}/verify`, {
      method: "POST",
      body: formData,
    });
    return parseResponse(response, uploadResponseSchema);
  },
  createDecision: (payload: { application_id: number; decision: string; reviewer_note: string }) =>
    postJson("/decision", payload, decisionSchema),
  undoDecision: (decisionId: number) => postJson(`/decision/${decisionId}/undo`, {}, decisionSchema),
  reprocessApplication: (applicationId: number) =>
    postJson(`/review/applications/${applicationId}/reprocess`, {}, reprocessResponseSchema),
  sourcePdfUrl: (applicationId: number, pageNumber?: number) => {
    const base = `${API_BASE_URL}/review/applications/${applicationId}/source-pdf`;
    return pageNumber ? `${base}#page=${pageNumber}&zoom=page-width` : base;
  },
  sourcePageImageUrl: (applicationId: number, pageNumber: number, highlight?: string) => {
    const base = `${API_BASE_URL}/review/applications/${applicationId}/source-page/${pageNumber}`;
    return highlight ? `${base}?highlight=${encodeURIComponent(highlight)}` : base;
  },
  ocrJsonUrl: (applicationId: number) => `${API_BASE_URL}/review/applications/${applicationId}/ocr-json`,
  summaryReportUrl: (applicationId: number) => `${API_BASE_URL}/review/applications/${applicationId}/summary-report`,
};
