import { Anomaly } from "@/lib/api";

export type ActiveTab = "checklist" | "anomalies" | "logs" | "all_items" | "downloads";

export type EvidenceSelection = {
  anomaly: Anomaly;
  pageNumber: number;
  allPageNumbers?: number[];
};

export const rejectionReasons = {
  "Document missing": "Please resubmit with the missing document(s) listed above.",
  "Name mismatch": "Name on submitted document does not match application records. Please verify and resubmit.",
  "Scan unclear": "Scan quality is too low to verify. Please rescan and resubmit.",
  "Statement outdated": "Bank statement is outside the allowed recency window. Please upload a recent statement.",
  "Wrong applicant": "Document appears to belong to a different applicant. Please verify and resubmit.",
  "Signature missing": "Required signature is missing. Please upload a signed copy.",
} as const;

export const severityBadgeColors = {
  HIGH: "bg-red-100 text-red-800 border border-red-200",
  MEDIUM: "bg-amber-100 text-amber-800 border border-amber-200",
  LOW: "bg-blue-50 text-blue-700 border border-blue-200",
  INFO: "bg-slate-100 text-slate-700 border border-slate-200",
} as const;

export function getSeverityBadgeColor(severity: string | null | undefined) {
  const clean = String(severity ?? "INFO").toUpperCase();
  return severityBadgeColors[clean as keyof typeof severityBadgeColors] ?? severityBadgeColors.INFO;
}
