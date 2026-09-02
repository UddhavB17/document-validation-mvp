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

export function averagePageTime(pageEvents: ApplicationReview["page_events"]): number {
  const pageDurations = pageEvents
    .map((page) => page.elapsed_seconds)
    .filter((duration): duration is number => typeof duration === "number");
  if (pageDurations.length === 0) {
    return 0;
  }
  return pageDurations.reduce((total, duration) => total + duration, 0) / pageDurations.length;
}

export function summarizeFields(fields: Record<string, unknown> | undefined): string {
  if (!fields || Object.keys(fields).length === 0) {
    return "-";
  }
  const visibleFields = Object.fromEntries(Object.entries(fields).filter(([key, value]) => !key.startsWith("_") && value));
  const text = JSON.stringify(Object.keys(visibleFields).length ? visibleFields : fields);
  return text.length > 160 ? `${text.slice(0, 157)}...` : text;
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
