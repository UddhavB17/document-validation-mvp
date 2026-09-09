import { z } from "zod";
import { evidenceProxyOcrJsonUrl, evidenceProxyPageImageUrl, evidenceProxyPdfUrl } from "./evidenceProxy";
export { normalizeDocumentType } from "./documentType";

// The API module owns two concerns: validating backend payloads and exposing
// the small set of requests used by the frontend. Keeping both here makes the
// request/response contract easy to find when adding a new screen.

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

// --- ws-d auth: in-memory bearer token (set once by lib/auth.ts) ---
// The JWT lives in an httpOnly cookie, so page code cannot read it directly.
// lib/auth.ts loads it once via GET /api/session — which verifies the cookie
// against backend GET /auth/me and returns the current DB role — and
// registers a getter here; every backend request below carries the token as
// `Authorization: Bearer …`.
type AuthTokenProvider = () => string | null;
let authTokenProvider: AuthTokenProvider | null = null;

export function setAuthTokenProvider(provider: AuthTokenProvider | null) {
  authTokenProvider = provider;
}

function authHeaders(): Record<string, string> {
  const token = authTokenProvider?.() ?? null;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function handleUnauthorized(status: number) {
  if (typeof window === "undefined" || status !== 401 || window.location.pathname === "/login") return;
  void fetch("/api/session", { method: "DELETE" }).finally(() => {
    window.location.assign("/login");
  });
}

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

export const anomalyEvidenceObjectSchema = z.object({
  page: z.number().nullable().optional(),
  bbox: z.tuple([z.number(), z.number(), z.number(), z.number()]).nullable().optional(),
  text: nullableString,
});

// The review API returns validation rows verbatim, so evidence_json arrives
// as an object, a raw TEXT string, or null. Keep this a plain union (no
// preprocess/transform effects): effect wrappers degrade to `unknown` when
// inferred through react-query's generics. Callers narrow with
// parseAnomalyEvidence below.
export const anomalyEvidenceSchema = z
  .union([anomalyEvidenceObjectSchema, z.string()])
  .nullable()
  .optional();

function safeJsonParse(raw: string): unknown {
  try {
    return JSON.parse(raw) as unknown;
  } catch {
    return null;
  }
}

/** Narrow an anomaly's evidence_json (object | string | null) to an object. */
export function parseAnomalyEvidence(value: unknown): z.infer<typeof anomalyEvidenceObjectSchema> | null {
  const raw = typeof value === "string" ? safeJsonParse(value) : value;
  const parsed = anomalyEvidenceObjectSchema.safeParse(raw);
  return parsed.success ? parsed.data : null;
}

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
  evidence_json: anomalyEvidenceSchema,
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
    handleUnauthorized(response.status);
    const detailPayload =
      typeof payload === "object" && payload !== null && "detail" in payload ? payload.detail : payload;
    const detail = typeof detailPayload === "string" ? detailPayload : JSON.stringify(detailPayload);
    throw new ApiError(detail || "Request failed", response.status);
  }
  return schema.parse(payload);
}

async function getJsonResponse<T>(path: string, schema: z.ZodType<T>): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, { headers: { ...authHeaders() } });
  return parseApiResponse(response, schema);
}

async function postJsonResponse<T>(path: string, body: unknown, schema: z.ZodType<T>): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(body),
  });
  return parseApiResponse(response, schema);
}

async function patchJsonResponse<T>(path: string, body: unknown, schema: z.ZodType<T>): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(body),
  });
  return parseApiResponse(response, schema);
}

async function deleteJsonResponse<T>(path: string, schema: z.ZodType<T>): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: "DELETE",
    headers: { ...authHeaders() },
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
    const response = await fetch(`${API_BASE_URL}/upload`, { method: "POST", headers: { ...authHeaders() }, body: formData });
    return parseApiResponse(response, uploadResponseSchema);
  },
  uploadMapped: async (payload: { manifest?: string; caseType: "Normal Case" | "BT Case"; file: File }) => {
    const formData = new FormData();
    if (payload.manifest !== undefined) {
      formData.append("manifest", payload.manifest);
    }
    formData.append("case_type", payload.caseType);
    formData.append("file", payload.file);
    const response = await fetch(`${API_BASE_URL}/upload/mapped`, { method: "POST", headers: { ...authHeaders() }, body: formData });
    return parseApiResponse(response, uploadResponseSchema);
  },
  uploadPartnerJson: (payload: unknown) => postJsonResponse("/upload/json", payload, uploadResponseSchema),
  prepareZipPackage: async (file: File) => {
    const formData = new FormData();
    formData.append("file", file);
    const response = await fetch(`${API_BASE_URL}/upload/package?background=true`, {
      method: "POST",
      headers: { ...authHeaders() },
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
      headers: { ...authHeaders() },
      body: formData,
    });
    return parseApiResponse(response, uploadResponseSchema);
  },
  createDecision: (payload: { application_id: number; decision: string; reviewer_note: string }) =>
    postJsonResponse("/decision", payload, decisionSchema),
  undoDecision: (decisionId: number) => postJsonResponse(`/decision/${decisionId}/undo`, {}, decisionSchema),
  reprocessApplication: (applicationId: number) =>
    postJsonResponse(`/review/applications/${applicationId}/reprocess`, {}, reprocessResponseSchema),
  // Evidence URLs go through the same-origin proxy
  // (frontend/app/api/evidence/[...path]/route.ts), which forwards the
  // dmef_session cookie as the backend bearer token. Direct backend URLs
  // cannot carry the in-memory token from <img>/<a> subresources (401).
  sourcePdfUrl: (applicationId: number, pageNumber?: number) =>
    evidenceProxyPdfUrl(applicationId, pageNumber),
  sourcePageImageUrl: (applicationId: number, pageNumber: number, highlight?: string) =>
    evidenceProxyPageImageUrl(applicationId, pageNumber, highlight),
  ocrJsonUrl: (applicationId: number) => evidenceProxyOcrJsonUrl(applicationId),
  uploadBatch: async (files: File[]) => {
    const formData = new FormData();
    for (const file of files) {
      formData.append("files", file);
    }
    const response = await fetch(`${API_BASE_URL}/upload/batch`, { method: "POST", headers: { ...authHeaders() }, body: formData });
    return parseApiResponse(response, batchUploadResponseSchema);
  },
  batchStatus: (batchId: string) => getJsonResponse(`/upload/batch/${batchId}`, batchStatusSchema),
};

// --- ws-c batch ---
export const batchItemSchema = z.object({
  filename: z.string(),
  application_id: z.number().nullable().optional(),
  job_id: z.number().nullable().optional(),
  status: z.string(),
  reason: nullableString,
});

export const batchUploadResponseSchema = z.object({
  batch_id: z.string(),
  items: z.array(batchItemSchema),
});

export const batchStatusItemSchema = z.object({
  application_id: z.number(),
  filename: z.string(),
  status: z.string(),
  attempt: z.number(),
  max_attempts: z.number().optional().default(3),
  failure_reason: nullableString,
  progress_percentage: z.number().nullable().optional(),
  review_ready: z.boolean(),
});

export const batchStatusSchema = z.object({
  batch_id: z.string(),
  items: z.array(batchStatusItemSchema),
});

export type BatchItemUpload = z.infer<typeof batchItemSchema>;
export type BatchUploadResponse = z.infer<typeof batchUploadResponseSchema>;
export type BatchItem = z.infer<typeof batchStatusItemSchema>;
export type BatchStatus = z.infer<typeof batchStatusSchema>;

// --- ws-d auth ---
export const authUserSchema = z.object({
  id: z.number(),
  email: z.string(),
  display_name: z.string(),
  role: z.string(),
});

export const loginResponseSchema = z.object({
  token: z.string(),
  user: authUserSchema,
});

export const sessionResponseSchema = z.object({
  token: z.string(),
  role: z.string(),
});

export const adminUserSchema = z.object({
  id: z.number(),
  email: z.string(),
  display_name: z.string(),
  role: z.string(),
  is_active: z.boolean(),
  created_at: z.string(),
});

export type AuthUser = z.infer<typeof authUserSchema>;
export type LoginResponse = z.infer<typeof loginResponseSchema>;
export type AdminUser = z.infer<typeof adminUserSchema>;

export async function loginRequest(email: string, password: string): Promise<LoginResponse> {
  return postJsonResponse("/auth/login", { email, password }, loginResponseSchema);
}

// --- ws-g gemini + llm ---
const llmProvidersSchema = z.object({
  providers: z.array(z.string()),
  current_provider: z.string(),
  current_model: z.string(),
  gemini_models: z.array(z.string()),
  costs: z.array(z.object({
    model: z.string(),
    calls: z.number(),
    tokens_in: z.number(),
    tokens_out: z.number(),
    usd: z.number(),
  })),
});

export type LlmProviders = z.infer<typeof llmProvidersSchema>;

const spendMonthSchema = z.object({
  month: z.string(),
  units: z.number(),
  free_units: z.number(),
  billable_units: z.number(),
  usd: z.number(),
});

const spendSchema = z.object({
  currency: z.string(),
  llm: z.object({ calls: z.number(), usd: z.number() }),
  vision: z.object({
    units_total: z.number(),
    free_units: z.number(),
    billable_units: z.number(),
    price_per_1k_usd: z.number(),
    free_units_monthly: z.number(),
    usd: z.number(),
    by_month: z.array(spendMonthSchema),
  }),
  total_usd: z.number(),
});

export type SpendSummary = z.infer<typeof spendSchema>;

export const llmApi = {
  providers: () => getJsonResponse("/settings/llm/providers", llmProvidersSchema),
  spend: () => getJsonResponse("/admin/spend", spendSchema),
};

export async function fetchCurrentUser(): Promise<AuthUser> {
  return getJsonResponse("/auth/me", authUserSchema);
}

// --- ws-e ops ui ---
// Operations payload (contracts §5). Everything a non-technical user sees
// comes from GET /ops/applications/{id}: at most 5 findings, bilingual
// strings, normalized bboxes. No rule ids, no OCR text, no JSON dumps.
const opsTextSchema = z.object({
  en: z.string(),
  hi: z.string(),
});

// Contracts §5 status vocabulary; legacy reviewer values fold to needs_review.
function mapOpsStatusValue(value: unknown): string {
  const normalized = String(value ?? "").trim().toLowerCase();
  return normalized === "clean" || normalized === "processing" || normalized === "failed" ? normalized : "needs_review";
}

export const opsStatusSchema = z.preprocess(
  mapOpsStatusValue,
  z.enum(["needs_review", "clean", "processing", "failed"]),
);

// Contracts §11 finding codes, priority order.
const OPS_FINDING_CODES = [
  "NAME_MISMATCH",
  "ID_MISMATCH",
  "ADDRESS_MISMATCH",
  "MISSING_DOCUMENT",
  "BANK_STATEMENT_OLD",
  "PAGE_UNREADABLE",
  "OCR_FAILED",
  "DATA_MISSING",
  "PROCESSING_ERROR",
] as const;

// Display strings stay lenient: null/missing becomes "" so one empty field cannot fail the whole parse.
const opsDisplayStringSchema = z.preprocess((value: unknown) => value ?? "", z.string());

const opsBboxSchema = z.tuple([z.number(), z.number(), z.number(), z.number()]);

export const opsEvidenceSchema = z.object({
  page: z.number(),
  bbox: opsBboxSchema.nullable(),
  text: z.string(),
});

export const opsFindingSchema = z.object({
  code: z
    .string()
    .refine((value) => (OPS_FINDING_CODES as readonly string[]).includes(value), { message: "Unknown finding code" }),
  severity: z.enum(["HIGH", "MEDIUM", "LOW"]),
  title: opsTextSchema,
  detail: opsTextSchema,
  pages: z.array(z.number()),
  evidence: opsEvidenceSchema.nullable(),
});

export const opsPageToVerifySchema = z.object({
  page: z.number(),
  document: opsTextSchema,
  problem: opsTextSchema,
});

export const opsChecklistRowSchema = z.object({
  s_no: z.number(),
  description: z.string(),
  status: z.enum(["FOUND", "MISSING", "NOT_CHECKED"]),
  pages: z.array(z.number()),
});

export const opsChecklistSchema = z.object({
  total: z.number(),
  found: z.number(),
  missing: z.number(),
  not_checked: z.number(),
  rows: z.array(opsChecklistRowSchema),
});

export const opsProcessingSchema = z.object({
  stage: z.string().nullable().optional(),
  percentage: z.number().nullable().optional(),
  attempt: z.number().nullable().optional(),
  failure_reason: z.string().nullable().optional(),
});

export const opsApplicationSchema = z.object({
  application_id: z.number(),
  loan_id: opsDisplayStringSchema,
  applicant_name: opsDisplayStringSchema,
  status: opsStatusSchema,
  processing: opsProcessingSchema,
  summary: opsTextSchema,
  top_findings: z.array(opsFindingSchema).max(5),
  pages_to_verify: z.array(opsPageToVerifySchema),
  checklist: opsChecklistSchema,
});

export const opsWorklistItemSchema = z.object({
  application_id: z.number(),
  loan_id: opsDisplayStringSchema.optional(),
  applicant_name: opsDisplayStringSchema.optional(),
  status: opsStatusSchema,
  findings_count: z.number(),
  updated_at: z.string().nullable().optional(),
});

export const opsWorklistSchema = z.object({
  applications: z.array(opsWorklistItemSchema),
});

// Application processing status (contracts §8, ≤ 5 KB). The lightweight
// GET /review/applications/{id}/status nests progress under `progress`
// (routes/review_pages.py: stage, percentage, completed_pages, total_pages)
// plus the latest job row. The ops header bar reads progress.percentage
// from here while in-flight; extra keys are ignored.
const statusProgressSchema = z
  .object({
    stage: z.string().nullable().optional(),
    percentage: z.number().nullable().optional(),
    completed_pages: z.number().nullable().optional(),
    total_pages: z.number().nullable().optional(),
  })
  .passthrough();

const statusJobSchema = z
  .object({
    id: z.number().nullable().optional(),
    status: z.string().nullable().optional(),
    attempt: z.number().nullable().optional(),
    failure_reason: z.string().nullable().optional(),
  })
  .passthrough();

export const applicationStatusSchema = z
  .object({
    application_id: z.number().optional(),
    status: z.string(),
    progress: statusProgressSchema.nullable().optional(),
    updated_at: z.string().nullable().optional(),
    job: statusJobSchema.nullable().optional(),
  })
  .passthrough();

export type AnomalyEvidence = z.infer<typeof anomalyEvidenceSchema>;
export type OpsText = z.infer<typeof opsTextSchema>;
export type OpsEvidence = z.infer<typeof opsEvidenceSchema>;
export type OpsFinding = z.infer<typeof opsFindingSchema>;
export type OpsPageToVerify = z.infer<typeof opsPageToVerifySchema>;
export type OpsChecklistRow = z.infer<typeof opsChecklistRowSchema>;
export type OpsChecklist = z.infer<typeof opsChecklistSchema>;
export type OpsApplication = z.infer<typeof opsApplicationSchema>;
export type OpsWorklistItem = z.infer<typeof opsWorklistItemSchema>;
export type OpsWorklist = z.infer<typeof opsWorklistSchema>;
export type ApplicationStatus = z.infer<typeof applicationStatusSchema>;

// Admin user management (ws-d endpoints in routes/admin_users.py).
export const adminUserListSchema = z.object({
  users: z.array(adminUserSchema),
});

export async function adminListUsersRequest(): Promise<z.infer<typeof adminUserListSchema>> {
  return getJsonResponse("/admin/users", adminUserListSchema);
}

export async function adminCreateUserRequest(payload: {
  email: string;
  display_name: string;
  role: string;
  password: string;
}): Promise<AdminUser> {
  return postJsonResponse("/admin/users", payload, adminUserSchema);
}

export async function adminUpdateUserRequest(
  userId: number,
  payload: { display_name?: string; role?: string; is_active?: boolean },
): Promise<AdminUser> {
  return patchJsonResponse(`/admin/users/${userId}`, payload, adminUserSchema);
}

export async function adminResetPasswordRequest(userId: number, newPassword: string): Promise<void> {
  await postJsonResponse(`/admin/users/${userId}/password`, { new_password: newPassword }, z.object({}));
}

export async function adminDeleteUserRequest(userId: number): Promise<void> {
  await deleteJsonResponse(`/admin/users/${userId}`, z.object({}));
}

export async function fetchOpsApplication(applicationId: number): Promise<OpsApplication> {
  // The ops schemas use z.preprocess for legacy-status mapping and null
  // coercion. That is runtime-correct, but this toolchain infers preprocessed
  // fields as unknown through the response generic (see the note on
  // anomalyEvidenceSchema above), so the schema is asserted to its own
  // inferred output type here. The assertion cannot drift: OpsApplication is
  // derived from this same schema.
  return getJsonResponse(
    `/ops/applications/${applicationId}`,
    opsApplicationSchema as z.ZodType<OpsApplication>,
  );
}

export async function fetchOpsWorklist(): Promise<OpsWorklist> {
  // Same preprocess note as fetchOpsApplication.
  return getJsonResponse("/ops/worklist", opsWorklistSchema as z.ZodType<OpsWorklist>);
}

export async function fetchApplicationStatus(applicationId: number): Promise<ApplicationStatus> {
  return getJsonResponse(`/review/applications/${applicationId}/status`, applicationStatusSchema);
}
