// Small display-only formatters shared by tables, metrics, and review panels.

const POSITIVE_STATUSES = new Set(["CLEAN", "verified", "verified_with_override"]);
const NEGATIVE_STATUSES = new Set(["CRITICAL", "pipeline_failed", "incomplete"]);
const IN_PROGRESS_STATUSES = new Set(["NEEDS_REVIEW", "processing", "ocr_completed"]);

export function asText(value: unknown): string {
  if (value === null || value === undefined || value === "") {
    return "-";
  }
  if (typeof value === "object") {
    return JSON.stringify(value);
  }
  return String(value);
}

export function formatNumber(value: unknown): string {
  if (typeof value !== "number") {
    return "-";
  }
  return value.toLocaleString("en-IN");
}

export function formatSeconds(value: unknown): string {
  if (typeof value !== "number") {
    return "-";
  }
  return `${value.toFixed(2)}s`;
}

export function statusTone(status: string): string {
  if (POSITIVE_STATUSES.has(status)) {
    return "text-emerald-700";
  }
  if (NEGATIVE_STATUSES.has(status)) {
    return "text-red-700";
  }
  if (IN_PROGRESS_STATUSES.has(status)) {
    return "text-amber-700";
  }
  return "text-slate-700";
}
