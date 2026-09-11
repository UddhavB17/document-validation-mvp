import { Anomaly } from "@/lib/api";

export type CaseTab = "review" | "extracted" | "checklist" | "processing" | "files";

export type EvidenceSelection = {
  anomaly: Anomaly;
  pageNumber: number | null;
  allPageNumbers?: number[];
  decisionTaskIds?: string[];
};
