"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { InfoMessage } from "@/components/Message";
import { Anomaly, ApplicationReview } from "@/lib/api";
import { buildExceptionTaskId, buildManualTaskId } from "@/lib/decisionPolicy";
import { asText } from "@/lib/format";

import {
  getReviewTaskState,
  getReviewIssueState,
  REVIEW_STATE_EVENT,
  type ReviewIssueState,
} from "./sessionState";

export type IssueGroupId =
  | "decision-blockers"
  | "business-exceptions"
  | "manual-checks"
  | "processing-quality";

export interface ReviewIssue {
  key: string;
  anomaly: Anomaly;
  group: IssueGroupId;
  pages: number[];
  decisionTaskIds: string[];
}

export const ISSUE_GROUPS: ReadonlyArray<{
  id: IssueGroupId;
  label: string;
  description: string;
  tone: string;
}> = [
  {
    id: "decision-blockers",
    label: "Decision blockers",
    description: "High-risk business exceptions that should be checked before a decision.",
    tone: "border-rose-200 bg-rose-50/60",
  },
  {
    id: "business-exceptions",
    label: "Other business exceptions",
    description: "Business-rule differences that need reviewer judgment.",
    tone: "border-amber-200 bg-amber-50/60",
  },
  {
    id: "manual-checks",
    label: "Required manual checks",
    description: "Checklist items that cannot be confirmed automatically.",
    tone: "border-violet-200 bg-violet-50/60",
  },
  {
    id: "processing-quality",
    label: "Processing quality",
    description: "OCR, classification, or page-quality limits that affect confidence.",
    tone: "border-sky-200 bg-sky-50/60",
  },
];

const GROUP_ORDER = new Map(ISSUE_GROUPS.map((group, index) => [group.id, index]));
const SEVERITY_ORDER: Record<string, number> = { HIGH: 0, MEDIUM: 1, LOW: 2, INFO: 3 };
const DECISION_BLOCKER_RULES = new Set([
  "AADHAAR_NUMBER_MISMATCH",
  "PAN_NUMBER_MISMATCH",
  "DATE_OF_BIRTH_MISMATCH",
  "UNSUPPORTED_DOCUMENT_TYPE",
]);

export function getAffectedPages(anomaly: Anomaly): number[] {
  const pages = anomaly.collapsed_page_numbers?.length
    ? anomaly.collapsed_page_numbers
    : typeof anomaly.page_number === "number"
      ? [anomaly.page_number]
      : [];

  return [...new Set(pages.filter((page) => Number.isFinite(page) && page > 0))].sort((a, b) => a - b);
}

export function getReviewIssueKey(applicationId: number, anomaly: Anomaly): string {
  const identity = [
    anomaly.id ?? "",
    anomaly.rule_id ?? "",
    anomaly.document_type ?? "",
    anomaly.page_number ?? "",
    anomaly.collapsed_page_numbers?.join(",") ?? "",
    anomaly.reason ?? "",
    String(anomaly.expected_value ?? "").slice(0, 400),
    String(anomaly.found_value ?? "").slice(0, 400),
  ].join("|");

  let hash = 2166136261;
  for (let index = 0; index < identity.length; index += 1) {
    hash ^= identity.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return `dmef:${applicationId}:${(hash >>> 0).toString(16)}`;
}

export function formatPageRange(pages: number[], maxSegments = 4): string {
  const normalizedPages = [...new Set(pages.filter((page) => Number.isFinite(page) && page > 0))].sort((a, b) => a - b);
  if (normalizedPages.length === 0) return "-";

  const ranges: string[] = [];
  let start = normalizedPages[0];
  let end = normalizedPages[0];
  for (const page of normalizedPages.slice(1)) {
    if (page === end + 1) {
      end = page;
      continue;
    }
    ranges.push(start === end ? String(start) : `${start}–${end}`);
    start = page;
    end = page;
  }
  ranges.push(start === end ? String(start) : `${start}–${end}`);

  if (ranges.length <= maxSegments) return ranges.join(", ");
  return `${ranges.slice(0, maxSegments).join(", ")} +${ranges.length - maxSegments} more ranges`;
}

function conciseReason(anomaly: Anomaly): string {
  const reason = String(anomaly.reason ?? anomaly.rule_id ?? "Review exception")
    .replace(/\s+/g, " ")
    .trim();
  return reason.length > 150 ? `${reason.slice(0, 147)}…` : reason;
}

export function isDecisionBlocker(anomaly: Anomaly): boolean {
  const ruleId = String(anomaly.rule_id ?? "").replace(/_SUMMARY$/, "").toUpperCase();
  return String(anomaly.severity ?? "").toUpperCase() === "HIGH"
    || DECISION_BLOCKER_RULES.has(ruleId)
    || ruleId.startsWith("MISSING_");
}

function makeManualCheckAnomaly(
  item: ApplicationReview["manual_review_items"][number],
  index: number,
): Anomaly {
  const pageNumber = typeof item.page_number === "number" ? item.page_number : undefined;
  return {
    rule_id: `MANUAL_CHECK_${item.s_no ?? index + 1}`,
    severity: String(item.severity ?? "MEDIUM").toUpperCase(),
    document_type: item.document_type ?? item.description ?? "Manual checklist item",
    expected_value: item.expected_masked ?? "Manual confirmation",
    found_value: item.extracted_masked,
    page_number: pageNumber,
    reason: item.reason ?? item.description ?? "Manual verification required",
    collapsed_page_numbers: pageNumber ? [pageNumber] : undefined,
  };
}

function makeManualPageReviewAnomaly(data: ApplicationReview): Anomaly | null {
  const pages = data.reviewer_summary?.pages_to_review ?? [];
  if (pages.length === 0) return null;
  const firstPage = [...pages].sort((a, b) => a - b)[0];
  return {
    rule_id: "MANUAL_PAGE_REVIEW",
    severity: data.reviewer_summary?.overall_status === "FULL_MANUAL_REVIEW" ? "HIGH" : "MEDIUM",
    document_type: "Loan file",
    expected_value: "Manual verification",
    found_value: `${pages.length} page(s) flagged for review`,
    page_number: firstPage,
    collapsed_page_numbers: pages,
    reason: "Reviewer summary identifies pages requiring manual verification",
  };
}

export function buildReviewIssues(data: ApplicationReview, applicationId: number): ReviewIssue[] {
  const issues: ReviewIssue[] = [];
  const seen = new Set<string>();

  const add = (anomaly: Anomaly, group: IssueGroupId, decisionTaskIds: string[] = []) => {
    const key = getReviewIssueKey(applicationId, anomaly);
    if (seen.has(key)) return;
    seen.add(key);
    issues.push({ key, anomaly, group, pages: getAffectedPages(anomaly), decisionTaskIds });
  };

  for (const anomaly of data.summary.business_anomalies) {
    add(anomaly, isDecisionBlocker(anomaly) ? "decision-blockers" : "business-exceptions", [buildExceptionTaskId(anomaly)]);
  }
  for (const anomaly of data.summary.processing_warnings) {
    add(anomaly, "processing-quality");
  }

  if (data.manual_review_items.length > 0) {
    data.manual_review_items.forEach((item, index) => add(makeManualCheckAnomaly(item, index), "manual-checks", [buildManualTaskId(item.s_no, item.description, index)]));
  } else {
    const manualPageReview = makeManualPageReviewAnomaly(data);
    if (manualPageReview) add(manualPageReview, "manual-checks");
  }

  return issues.sort((left, right) => {
    const groupOrder = (GROUP_ORDER.get(left.group) ?? 99) - (GROUP_ORDER.get(right.group) ?? 99);
    if (groupOrder !== 0) return groupOrder;
    const severityOrder = (SEVERITY_ORDER[String(left.anomaly.severity ?? "LOW").toUpperCase()] ?? 99)
      - (SEVERITY_ORDER[String(right.anomaly.severity ?? "LOW").toUpperCase()] ?? 99);
    if (severityOrder !== 0) return severityOrder;
    return conciseReason(left.anomaly).localeCompare(conciseReason(right.anomaly));
  });
}

function severityLabel(anomaly: Anomaly): string {
  return String(anomaly.severity ?? "LOW").toUpperCase();
}

function stateLabel(state: ReviewIssueState): string {
  return state;
}

export function getLinkedReviewIssueState(applicationId: number, issue: ReviewIssue): ReviewIssueState {
  if (issue.decisionTaskIds.some((taskId) => getReviewTaskState(applicationId, taskId) === "Checked")) return "Checked";
  return getReviewIssueState(issue.key);
}

export function IssueQueue({
  applicationId,
  data,
  onSelectEvidence,
}: {
  applicationId: number;
  data: ApplicationReview;
  onSelectEvidence: (anomaly: Anomaly, pageNumber: number | null, allPageNumbers?: number[], decisionTaskIds?: string[]) => void;
}) {
  const issues = useMemo(() => buildReviewIssues(data, applicationId), [applicationId, data]);
  const [sessionRevision, setSessionRevision] = useState(0);
  const autoSelectedKey = useRef<string | null>(null);

  useEffect(() => {
    const handleStateChange = () => setSessionRevision((revision) => revision + 1);
    window.addEventListener(REVIEW_STATE_EVENT, handleStateChange);
    window.addEventListener("storage", handleStateChange);
    return () => {
      window.removeEventListener(REVIEW_STATE_EVENT, handleStateChange);
      window.removeEventListener("storage", handleStateChange);
    };
  }, []);

  const defaultIssue = issues.find((issue) => issue.group === "decision-blockers")
    ?? issues.find((issue) => issue.group === "business-exceptions")
    ?? issues[0];
  const [selectedKey, setSelectedKey] = useState(defaultIssue?.key ?? null);
  const selectIssue = (issue: ReviewIssue) => {
    setSelectedKey(issue.key);
    onSelectEvidence(issue.anomaly, issue.pages[0] ?? null, issue.pages.length > 1 ? issue.pages : undefined, issue.decisionTaskIds);
  };

  useEffect(() => {
    if (!defaultIssue || autoSelectedKey.current === defaultIssue.key) return;
    autoSelectedKey.current = defaultIssue.key;
    selectIssue(defaultIssue);
    // The ref prevents a parent re-render from reopening the default workspace.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [defaultIssue?.key]);

  if (issues.length === 0) {
    return (
      <section aria-labelledby="exception-review-heading" className="space-y-3">
        <div>
          <h2 id="exception-review-heading" className="font-serif text-base font-semibold text-slate-900">Exception review</h2>
          <p className="mt-1 text-xs font-medium text-slate-600">A compact, evidence-led queue for operational review.</p>
        </div>
        <InfoMessage message="No business exceptions, manual checks, or processing-quality issues detected." />
      </section>
    );
  }

  return (
    <section aria-labelledby="exception-review-heading" className="space-y-5" data-session-revision={sessionRevision}>
      <div className="flex flex-col gap-2 border-b border-slate-200 pb-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h2 id="exception-review-heading" className="font-serif text-base font-semibold text-slate-900">Exception review</h2>
          <p className="mt-1 max-w-3xl text-xs font-medium leading-relaxed text-slate-600">
            Start with the highest-risk business issue. Select a row to open its source evidence; status below is this-session state only.
          </p>
        </div>
        <div className="shrink-0 text-[10px] font-bold uppercase tracking-wider text-slate-500">{issues.length} review items</div>
      </div>

      <div className="space-y-5">
        {ISSUE_GROUPS.map((group) => {
          const groupIssues = issues.filter((issue) => issue.group === group.id);
          if (groupIssues.length === 0) return null;
          return (
            <section key={group.id} aria-labelledby={`${group.id}-heading`} className="space-y-2.5">
              <div className={`rounded-xl border px-4 py-3 ${group.tone}`}>
                <div className="flex items-baseline justify-between gap-3">
                  <h3 id={`${group.id}-heading`} className="text-sm font-bold text-slate-900">{group.label}</h3>
                  <span className="font-mono text-xs font-bold text-slate-600">{groupIssues.length}</span>
                </div>
                <p className="mt-1 text-xs font-medium text-slate-600">{group.description}</p>
              </div>

              <div className="space-y-2">
                {groupIssues.map((issue) => {
                  const severity = severityLabel(issue.anomaly);
                  const state = getLinkedReviewIssueState(applicationId, issue);
                  const selected = selectedKey === issue.key;
                  const pageText = issue.pages.length > 0
                    ? `${issue.pages.length} affected page${issue.pages.length === 1 ? "" : "s"}`
                    : "File-level evidence";
                  return (
                    <button
                      key={issue.key}
                      type="button"
                      aria-pressed={selected}
                      onClick={() => selectIssue(issue)}
                      className={`group w-full rounded-xl border bg-white p-4 text-left shadow-2xs transition-colors hover:border-[#2B4C7E] hover:bg-slate-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#2B4C7E] ${selected ? "border-[#2B4C7E] ring-1 ring-[#2B4C7E]/20" : "border-slate-200"}`}
                    >
                      <div className="flex flex-col gap-3 lg:grid lg:grid-cols-[minmax(0,1.7fr)_minmax(0,1fr)_minmax(0,1fr)_auto] lg:items-start lg:gap-4">
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className={`stamp ${severity === "HIGH" ? "mismatch" : severity === "MEDIUM" ? "attention" : "bg-slate-100 text-slate-700 border-slate-300"}`}>
                              {severity}
                            </span>
                            <span className="truncate text-sm font-bold text-slate-900">{conciseReason(issue.anomaly)}</span>
                          </div>
                          <p className="mt-2 text-xs font-medium leading-relaxed text-slate-600">{asText(issue.anomaly.rule_id)}</p>
                        </div>

                        <div className="grid grid-cols-2 gap-3 text-xs sm:grid-cols-3 lg:grid-cols-1">
                          <div>
                            <div className="mb-1 text-[10px] font-bold uppercase tracking-wider text-slate-400">Document type</div>
                            <div className="truncate font-semibold text-slate-800">{asText(issue.anomaly.document_type ?? "File-level")}</div>
                          </div>
                          <div>
                            <div className="mb-1 text-[10px] font-bold uppercase tracking-wider text-slate-400">Affected pages</div>
                            <div className="font-semibold text-slate-800" title={formatPageRange(issue.pages)}>{pageText}</div>
                          </div>
                        </div>

                        <div className="grid grid-cols-2 gap-3 text-xs">
                          <div>
                            <div className="mb-1 text-[10px] font-bold uppercase tracking-wider text-slate-400">Expected</div>
                            <div className="line-clamp-2 break-words font-mono text-slate-800">{asText(issue.anomaly.expected_value)}</div>
                          </div>
                          <div>
                            <div className="mb-1 text-[10px] font-bold uppercase tracking-wider text-slate-400">Found</div>
                            <div className="line-clamp-2 break-words font-mono text-slate-800">{asText(issue.anomaly.found_value)}</div>
                          </div>
                        </div>

                        <div className="flex items-center justify-between gap-3 lg:block lg:text-right">
                          <div className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[10px] font-bold ${state === "Checked" ? "border-emerald-200 bg-emerald-50 text-emerald-800" : state === "Viewed" ? "border-blue-200 bg-blue-50 text-blue-800" : "border-slate-200 bg-slate-50 text-slate-600"}`}>
                            <span aria-hidden="true" className={`h-1.5 w-1.5 rounded-full ${state === "Checked" ? "bg-emerald-600" : state === "Viewed" ? "bg-blue-600" : "bg-slate-400"}`} />
                            {stateLabel(state)}
                          </div>
                          <span className="text-[10px] font-semibold text-slate-500 group-hover:text-[#2B4C7E] lg:mt-3 lg:block">Review evidence →</span>
                        </div>
                      </div>
                    </button>
                  );
                })}
              </div>
            </section>
          );
        })}
      </div>
    </section>
  );
}
