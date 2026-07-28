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
  if (["CLEAN", "verified", "verified_with_override"].includes(status)) {
    return "text-emerald-700";
  }
  if (["CRITICAL", "pipeline_failed", "incomplete"].includes(status)) {
    return "text-red-700";
  }
  if (["NEEDS_REVIEW", "processing", "ocr_completed"].includes(status)) {
    return "text-amber-700";
  }
  return "text-slate-700";
}
