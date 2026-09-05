import type { ReactNode } from "react";

export type ReviewStateKind = "case" | "processing" | "decision";

const CASE_STATE_LABELS: Record<string, string> = {
  CLEAN: "Clean",
  CRITICAL: "Critical",
  NEEDS_REVIEW: "Needs review",
  incomplete: "Docs requested",
  verified: "Verified",
  verified_with_override: "Verified with override",
};

const PROCESSING_STATE_LABELS: Record<string, string> = {
  cancelled: "Cancelled",
  completed: "Completed",
  completed_with_warnings: "Completed with warnings",
  failed: "Failed",
  not_started: "Not started",
  pause_requested: "Pause requested",
  paused: "Paused",
  processing: "Processing",
  queued: "Queued",
  stale: "Out of date",
};

const DECISION_LABELS: Record<string, string> = {
  ACCEPT: "Accepted",
  OVERRIDE: "Override",
  REQUEST_DOCS: "Docs requested",
};

export function humanizeReviewState(value: string | null | undefined, kind: ReviewStateKind = "case"): string {
  const normalized = String(value ?? "").trim();
  if (!normalized) {
    return "Unknown";
  }

  const labels = kind === "processing" ? PROCESSING_STATE_LABELS : kind === "decision" ? DECISION_LABELS : CASE_STATE_LABELS;
  return labels[normalized] ?? labels[normalized.toUpperCase()] ?? normalized.replace(/[_-]+/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function formatReviewTimestamp(value: string | null | undefined): string {
  if (!value) {
    return "—";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("en-IN", {
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    month: "short",
    year: "numeric",
  }).format(date);
}

export function formatExceptionSummary(businessIssues: number, processingWarnings: number): string {
  const summary: string[] = [];
  if (businessIssues > 0) {
    summary.push(`${businessIssues} exception${businessIssues === 1 ? "" : "s"}`);
  }
  if (processingWarnings > 0) {
    summary.push(`${processingWarnings} processing warning${processingWarnings === 1 ? "" : "s"}`);
  }
  return summary.length > 0 ? summary.join(" · ") : "No exceptions";
}

export function ReviewStateBadge({ status, kind }: { status: string; kind: ReviewStateKind }) {
  const normalized = status.toLowerCase();
  const tone = getStateTone(normalized, kind);
  const label = humanizeReviewState(status, kind);
  return (
    <span className={`stamp ${tone} select-none`} aria-label={`${kind} state: ${label}`}>
      {label}
    </span>
  );
}

export function ExceptionSummary({ businessIssues, processingWarnings }: { businessIssues: number; processingWarnings: number }) {
  const summary = formatExceptionSummary(businessIssues, processingWarnings);
  const hasBusinessIssues = businessIssues > 0;
  const hasProcessingWarnings = processingWarnings > 0;
  const tone = hasBusinessIssues ? "text-[#AF3B2E]" : hasProcessingWarnings ? "text-[#A0701C]" : "text-[#1F7A5C]";

  return (
    <span className={`text-[12px] font-semibold leading-5 ${tone}`}>
      {summary}
    </span>
  );
}

export function InlineCount({ label, value, children }: { label: string; value: number; children?: ReactNode }) {
  return (
    <div className="flex items-baseline gap-2 border-l border-[#E1E5EB] pl-4 first:border-l-0 first:pl-0">
      <dt className="text-[11px] font-bold uppercase tracking-[0.08em] text-[#5C6B7A]">{label}</dt>
      <dd className="font-mono text-lg font-semibold text-[#16202E]">{value}</dd>
      {children}
    </div>
  );
}

function getStateTone(status: string, kind: ReviewStateKind): "match" | "attention" | "mismatch" {
  if (kind === "processing") {
    if (["failed", "stale"].includes(status)) {
      return "mismatch";
    }
    if (["completed", "not_started"].includes(status)) {
      return "match";
    }
    return "attention";
  }

  if (kind === "decision") {
    return status === "accept" ? "match" : ["override", "request_docs"].includes(status) ? "attention" : "mismatch";
  }

  if (["clean", "verified"].includes(status)) {
    return "match";
  }
  if (["critical"].includes(status)) {
    return "mismatch";
  }
  return "attention";
}
