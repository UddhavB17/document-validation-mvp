import { Anomaly } from "@/lib/api";

export type ActiveTab = "overview" | "extracted" | "anomalies" | "checklist" | "logs" | "downloads";

export type EvidenceSelection = {
  anomaly: Anomaly;
  pageNumber: number;
  allPageNumbers?: number[];
};
