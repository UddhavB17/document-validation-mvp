import { Anomaly } from "@/lib/api";

export type CaseTab = "review" | "extracted" | "checklist" | "processing" | "files";

// Legacy values remain part of the route contract so old bookmarked links can
// be normalized by the case route without breaking callers that still import
// this type.
export type LegacyCaseTab = "overview" | "anomalies" | "logs" | "downloads";
export type ActiveTab = CaseTab | LegacyCaseTab;

export type EvidenceSelection = {
  anomaly: Anomaly;
  pageNumber: number;
  allPageNumbers?: number[];
};
