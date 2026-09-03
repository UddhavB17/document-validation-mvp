import type { WorklistItem } from "@/lib/api";

export type WorklistClassification = "review" | "processing" | "recovery" | "closed";
export type WorklistFilter = WorklistClassification | "all";

const CLOSED_CASE_STATES = new Set(["verified", "verified_with_override", "incomplete"]);
const COMPLETED_PIPELINE_STATES = new Set(["completed", "completed_with_warnings"]);
const PROCESSING_STATES = new Set([
  "not_started",
  "queued",
  "processing",
  "pause_requested",
  "paused",
  "uploaded",
  "ocr_completed",
  "classified",
  "mapping",
  "mapped",
  "extracting",
]);
const RECOVERY_STATES = new Set(["failed", "pipeline_failed", "stale", "cancelled", "unsupported_input"]);

export function classifyWorklistItem(item: WorklistItem): WorklistClassification {
  const processingState = String(item.pipeline_status ?? "").toLowerCase();
  const caseState = String(item.status ?? "").toLowerCase();

  // Retryable pipeline failures are recovery work, even when the case also
  // carries business issues. They must never enter the reviewer queue.
  if (item.pipeline_retryable || RECOVERY_STATES.has(processingState)) return "recovery";
  if (CLOSED_CASE_STATES.has(caseState)) return "closed";
  if (COMPLETED_PIPELINE_STATES.has(processingState)) return "review";
  if (PROCESSING_STATES.has(processingState)) return "processing";
  // Unknown pipeline states are not safe to action; surface them for recovery.
  return "recovery";
}

export function matchesWorklistFilter(item: WorklistItem, filter: WorklistFilter): boolean {
  return filter === "all" || classifyWorklistItem(item) === filter;
}

export function isActionableReviewItem(item: WorklistItem): boolean {
  return classifyWorklistItem(item) === "review";
}

export function rankWorklistItem(item: WorklistItem): number {
  const state = classifyWorklistItem(item);
  if (state === "recovery") return 0;
  if (state === "processing") return 3;
  if (state === "closed") return 4;
  const caseState = String(item.status ?? "").toLowerCase();
  if (caseState === "critical") return 1;
  if (caseState === "needs_review") return 2;
  return 3;
}

function timestamp(value: string): number {
  const result = new Date(value).getTime();
  return Number.isNaN(result) ? Number.MAX_SAFE_INTEGER : result;
}

export function sortWorklistItems(items: readonly WorklistItem[], sort: "priority" | "received_asc" | "received_desc"): WorklistItem[] {
  return [...items].sort((left, right) => {
    if (sort === "priority") {
      const priorityDifference = rankWorklistItem(left) - rankWorklistItem(right);
      if (priorityDifference !== 0) return priorityDifference;
    } else {
      const receivedDifference = timestamp(left.created_at) - timestamp(right.created_at);
      if (receivedDifference !== 0) return sort === "received_asc" ? receivedDifference : -receivedDifference;
    }
    const tieBreakDifference = timestamp(left.created_at) - timestamp(right.created_at);
    return tieBreakDifference !== 0 ? tieBreakDifference : left.id - right.id;
  });
}

export function getActionableReviewItems(items: readonly WorklistItem[], search = ""): WorklistItem[] {
  const query = search.trim().toLowerCase();
  const filtered = items.filter((item) => {
    if (!isActionableReviewItem(item)) return false;
    if (!query) return true;
    return [item.loan_id, item.applicant_name, item.product_type, item.status, item.pipeline_status]
      .some((value) => String(value ?? "").toLowerCase().includes(query));
  });
  return sortWorklistItems(filtered, "priority");
}
