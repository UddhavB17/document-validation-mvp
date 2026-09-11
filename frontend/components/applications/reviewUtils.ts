import type { ApplicationReview } from "@/lib/api";

// Pure display helpers shared by the application review tabs. These helpers
// keep formatting and review-specific labels out of the data-fetching layer.

export const rejectionReasons = {
  "Document missing": "Please resubmit with the missing document(s) listed above.",
  "Name mismatch": "Name on submitted document does not match application records. Please verify and resubmit.",
  "Scan unclear": "Scan quality is too low to verify. Please rescan and resubmit.",
  "Statement outdated": "Bank statement is outside the allowed recency window. Please upload a recent statement.",
  "Wrong applicant": "Document appears to belong to a different applicant. Please verify and resubmit.",
  "Signature missing": "Required signature is missing. Please upload a signed copy.",
} as const;

export const statusLabels = {
  match: "Match",
  mismatch: "Mismatch",
  attention: "Attention",
} as const;

export type ReviewErrorPresentation = {
  title: string;
  message: string;
};

export function getReviewErrorPresentation(error: unknown, applicationId: number): ReviewErrorPresentation {
  const status = getErrorStatus(error);
  if (status === 404) {
    return {
      title: "Application not found",
      message: `Application ${applicationId} does not exist or is no longer available in the review service.`,
    };
  }
  if (isSchemaError(error)) {
    return {
      title: "Review data could not be read",
      message: "The API returned application data in an unexpected shape. Retry the request; if it persists, check the backend and frontend versions together.",
    };
  }
  if (status !== null) {
    return {
      title: "Review API error",
      message: `The review API returned HTTP ${status}. Retry the request and check the local API health if it continues.`,
    };
  }
  return {
    title: "Unable to load application review",
    message: error instanceof Error && error.message
      ? error.message
      : "The application review could not be loaded. Retry the request and check the local API health if it continues.",
  };
}

export function displayValue(value: unknown, maxLength = 220): string {
  if (value === null || value === undefined || value === "") {
    return "-";
  }
  let text: string;
  if (typeof value === "string") {
    text = value;
  } else {
    try {
      text = JSON.stringify(value);
    } catch {
      text = String(value);
    }
  }
  if (!text) {
    return "-";
  }
  return text.length > maxLength ? `${text.slice(0, maxLength - 3)}...` : text;
}

export function isSensitiveFieldName(fieldName: string): boolean {
  return /(?:pan|aadhaar|aadhar|account(?:_number|_no| number| no)?|ifsc|phone|mobile)/i.test(fieldName);
}

export function maskSensitiveValue(value: unknown): string {
  const text = displayValue(value, 160);
  if (text === "-") {
    return text;
  }
  const compact = text.replace(/\s+/g, "");
  if (compact.length <= 4) {
    return "••••";
  }
  return `•••• •••• ${compact.slice(-4)}`;
}

export function isProcessingIssue(status: unknown, error: unknown): boolean {
  if (typeof error === "string" && error.trim()) {
    return true;
  }
  const normalized = String(status ?? "").toLowerCase().replace(/\s+/g, "_");
  return !["completed", "complete", "success", "ok", "processed", "done"].includes(normalized);
}

function getErrorStatus(error: unknown): number | null {
  if (typeof error === "object" && error !== null && "status" in error) {
    const status = (error as { status?: unknown }).status;
    return typeof status === "number" ? status : null;
  }
  return null;
}

function isSchemaError(error: unknown): boolean {
  return error instanceof Error && (error.name === "ZodError" || error.name === "ValidationError");
}

export function averagePageTime(pageEvents: ApplicationReview["page_events"]): number {
  const pageDurations = pageEvents
    .map((page) => page.elapsed_seconds)
    .filter((duration): duration is number => typeof duration === "number");
  if (pageDurations.length === 0) {
    return 0;
  }
  return pageDurations.reduce((total, duration) => total + duration, 0) / pageDurations.length;
}

export function summarizePublicFields(fields: Record<string, unknown> | undefined): string {
  if (!fields || Object.keys(fields).length === 0) {
    return "-";
  }
  const visibleFields = Object.fromEntries(
    Object.entries(fields).filter(([key, value]) => !key.startsWith("_") && value !== null && value !== undefined && value !== ""),
  );
  if (Object.keys(visibleFields).length === 0) {
    return "-";
  }
  return displayValue(visibleFields, 220);
}

export function formatLlmDocument(fields: Record<string, unknown> | undefined): string {
  if (!fields) {
    return "-";
  }
  const structuredClassification = fields._structured_llm_classification;
  if (!isRecord(structuredClassification)) {
    return "-";
  }
  const documentType = String(structuredClassification.document_type || "").trim();
  if (!documentType) {
    return "-";
  }
  const confidence = structuredClassification.confidence;
  if (typeof confidence === "number") {
    return `${documentType} (${Math.round(confidence * 100)}%)`;
  }
  return documentType;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function getSeverityBadgeColor(severity: string | null | undefined): string {
  if (severity === "HIGH") {
    return "bg-rose-100 text-rose-800 border-rose-200 border";
  }
  if (severity === "MEDIUM") {
    return "bg-amber-100 text-amber-800 border-amber-200 border";
  }
  return "bg-slate-100 text-slate-800 border-slate-200 border";
}
