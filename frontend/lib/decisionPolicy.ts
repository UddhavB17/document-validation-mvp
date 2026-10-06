import { normalizeDocumentType } from "./documentType";
import type { ReviewDocumentType } from "./api";

export type DecisionAction = "ACCEPT" | "OVERRIDE" | "REQUEST_DOCS";

export type DecisionProcessingState =
  | "completed"
  | "blocked"
  | "incomplete"
  | "unknown";

export type DecisionTaskKind = "manual" | "checklist" | "exception";

export type DecisionReviewItem = {
  s_no?: number | string | null;
  description?: string | null;
  reason?: string | null;
  severity?: string | null;
  page_number?: number | null;
  document_type?: ReviewDocumentType;
};

export type DecisionChecklistRow = {
  s_no?: number | null;
  status?: string | null;
  description?: string | null;
  pages?: string | null;
  document_types?: string | null;
};

export type DecisionBusinessException = {
  id?: number | null;
  s_no?: number | null;
  rule_id?: string | null;
  severity?: string | null;
  reason?: string | null;
  page_number?: number | null;
  document_type?: string | null;
};

export type DecisionTask = {
  id: string;
  kind: DecisionTaskKind;
  label: string;
  reason: string;
  severity: string | null;
  pageNumber: number | null;
  required: boolean;
};

export type DecisionPolicyInput = {
  action: DecisionAction;
  processingStatus?: unknown;
  processingIsStale?: boolean;
  manualReviewItems?: readonly DecisionReviewItem[];
  checklistRows?: readonly DecisionChecklistRow[];
  businessExceptions?: readonly DecisionBusinessException[];
  checkedTaskIds?: ReadonlySet<string> | readonly string[];
  rationale?: unknown;
  requestReasons?: readonly string[];
  borrowerMessage?: unknown;
};

export type DecisionPolicyResult = {
  allowed: boolean;
  reasons: string[];
  processingState: DecisionProcessingState;
  processingBlocked: boolean;
  processingComplete: boolean;
  tasks: DecisionTask[];
  requiredTasks: DecisionTask[];
  highTasks: DecisionTask[];
  checkedCount: number;
  remainingRequiredTasks: DecisionTask[];
  uncheckedHighTasks: DecisionTask[];
};

export function taskNeedsEvidence(task: Pick<DecisionTask, "pageNumber">): boolean {
  return typeof task.pageNumber === "number" && Number.isFinite(task.pageNumber) && task.pageNumber > 0;
}

export function resolveDecisionProcessingStatus(
  progress: { operational_status?: unknown; status?: unknown } | null | undefined,
): unknown {
  return progress?.operational_status ?? progress?.status;
}

const COMPLETED_PROCESSING_STATUSES = new Set(["completed", "completed_with_warnings"]);
const BLOCKED_PROCESSING_STATUSES = new Set(["queued", "processing", "stale", "failed", "pipeline_failed"]);

function normalize(value: unknown): string {
  return String(value ?? "").trim().toLowerCase();
}

function nonEmpty(value: unknown): string {
  return String(value ?? "").trim();
}

function severityRank(value: string | null): number {
  const severity = normalize(value);
  if (severity === "high") return 3;
  if (severity === "medium") return 2;
  if (severity === "low") return 1;
  return 0;
}

function mergeSeverity(current: string | null, next: string | null): string | null {
  return severityRank(next) > severityRank(current) ? next : current;
}

function slug(value: unknown): string {
  return nonEmpty(value).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
}

export function buildManualTaskId(sNo: unknown, description?: unknown, index = 0): string {
  const serial = nonEmpty(sNo);
  return `manual:${serial || slug(description) || index + 1}`;
}

export function buildChecklistTaskId(sNo: unknown, description?: unknown, index = 0): string {
  const serial = nonEmpty(sNo);
  return `checklist:${serial || slug(description) || index + 1}`;
}

export function buildExceptionTaskId(exception: DecisionBusinessException, index = 0): string {
  const serial = nonEmpty(exception.s_no);
  const stablePart = nonEmpty(exception.id) || [serial, exception.rule_id, exception.page_number, slug(exception.reason)].filter(Boolean).join(":") || index + 1;
  return `exception:${stablePart}`;
}

function firstPage(value: unknown): number | null {
  const match = String(value ?? "").match(/\d+/);
  if (!match) return null;
  const page = Number(match[0]);
  return Number.isFinite(page) && page > 0 ? page : null;
}

function addOrMergeTask(tasks: DecisionTask[], task: DecisionTask): void {
  const existing = tasks.find((candidate) => candidate.id === task.id);
  if (!existing) {
    tasks.push(task);
    return;
  }

  existing.required ||= task.required;
  existing.severity = mergeSeverity(existing.severity, task.severity);
  if (!existing.reason && task.reason) existing.reason = task.reason;
  if (existing.pageNumber === null && task.pageNumber !== null) existing.pageNumber = task.pageNumber;
  if (existing.kind === "exception" && task.kind !== "exception") existing.kind = task.kind;
}

/**
 * Build stable, reviewer-facing task IDs from the fields already returned by
 * the review API. These IDs are intentionally local to this browser session;
 * they are never sent as new API fields.
 */
export function buildDecisionTasks({
  manualReviewItems = [],
  checklistRows = [],
  businessExceptions = [],
}: {
  manualReviewItems?: readonly DecisionReviewItem[];
  checklistRows?: readonly DecisionChecklistRow[];
  businessExceptions?: readonly DecisionBusinessException[];
}): DecisionTask[] {
  const tasks: DecisionTask[] = [];
  const checklistStatusBySerial = new Map(
    checklistRows
      .filter((row) => nonEmpty(row.s_no))
      .map((row) => [nonEmpty(row.s_no), normalize(row.status)] as const),
  );

  manualReviewItems.forEach((item, index) => {
    if (checklistStatusBySerial.get(nonEmpty(item.s_no)) === "not_applicable") return;
    addOrMergeTask(tasks, {
      id: buildManualTaskId(item.s_no, item.description, index),
      kind: "manual",
      label: nonEmpty(item.description) || `Manual review item ${index + 1}`,
      reason: nonEmpty(item.reason) || "Required manual verification",
      severity: nonEmpty(item.severity) || null,
      pageNumber: typeof item.page_number === "number" ? item.page_number : null,
      required: true,
    });
  });

  checklistRows.forEach((row, index) => {
    if (normalize(row.status) !== "not_checked") return;
    addOrMergeTask(tasks, {
      id: buildChecklistTaskId(row.s_no, row.description, index),
      kind: "checklist",
      label: nonEmpty(row.description) || `Checklist item ${index + 1}`,
      reason: "Checklist item was not checked automatically",
      severity: null,
      pageNumber: firstPage(row.pages),
      required: true,
    });
  });

  businessExceptions.forEach((exception, index) => {
    const severity = nonEmpty(exception.severity) || null;
    addOrMergeTask(tasks, {
      id: buildExceptionTaskId(exception, index),
      kind: "exception",
      label: normalizeDocumentType(exception.document_type) || nonEmpty(exception.rule_id) || `Business exception ${index + 1}`,
      reason: nonEmpty(exception.reason) || "Business exception requires reviewer attention",
      severity,
      pageNumber: typeof exception.page_number === "number" ? exception.page_number : null,
      required: false,
    });
  });

  return tasks;
}

export function getDecisionProcessingState(status: unknown, isStale = false): DecisionProcessingState {
  const normalized = normalize(status);
  if (isStale || normalized === "stale") return "blocked";
  if (BLOCKED_PROCESSING_STATUSES.has(normalized)) return "blocked";
  if (COMPLETED_PROCESSING_STATUSES.has(normalized)) return "completed";
  if (!normalized) return "unknown";
  return "incomplete";
}

export function isDecisionProcessingBlocked(status: unknown, isStale = false): boolean {
  return getDecisionProcessingState(status, isStale) === "blocked";
}

function checkedSet(value: ReadonlySet<string> | readonly string[] | undefined): ReadonlySet<string> {
  return value instanceof Set ? value : new Set(value ?? []);
}

function checkedTaskCount(tasks: readonly DecisionTask[], checked: ReadonlySet<string>): number {
  return tasks.filter((task) => task.required && checked.has(task.id)).length;
}

function processingReason(status: unknown, isStale: boolean | undefined): string {
  const normalized = normalize(status);
  if (isStale || normalized === "stale") return "Processing is stale; recover the run before making a decision.";
  if (normalized === "failed" || normalized === "pipeline_failed") return "Processing failed; retry processing before making a decision.";
  if (!normalized) return "Processing status is unknown; wait for a verified completed status before making a decision.";
  if (normalized === "paused" || normalized === "pause_requested") return "Processing is paused; resume or complete processing before making a decision.";
  if (normalized === "queued") return "Processing is queued; wait until it completes before making a decision.";
  if (normalized === "processing") return "Processing is still running; wait until it completes before making a decision.";
  if (processingStateIsRecognizedIncomplete(normalized)) return `Processing is ${normalized.replace(/_/g, " ")}; complete it before making a decision.`;
  return `Processing status “${normalized}” is not recognized as complete; verify the pipeline before making a decision.`;
}

function processingStateIsRecognizedIncomplete(status: string): boolean {
  return status === "uploaded" || status === "ocr_completed" || status === "classified" || status === "mapping";
}

/**
 * Apply the decision guardrails without relying on UI state or server-side
 * defaults. The caller still submits only the existing reviewer_note field.
 */
export function evaluateDecisionPolicy(input: DecisionPolicyInput): DecisionPolicyResult {
  const tasks = buildDecisionTasks(input);
  const requiredTasks = tasks.filter((task) => task.required);
  const highTasks = tasks.filter((task) => severityRank(task.severity) >= 3);
  const checked = checkedSet(input.checkedTaskIds);
  const remainingRequiredTasks = requiredTasks.filter((task) => !checked.has(task.id));
  const uncheckedHighTasks = highTasks.filter((task) => !checked.has(task.id));
  const processingState = getDecisionProcessingState(input.processingStatus, input.processingIsStale);
  const processingBlocked = processingState === "blocked";
  const processingComplete = processingState === "completed";
  const reasons: string[] = [];
  const rationale = nonEmpty(input.rationale);

  if (!processingComplete) reasons.push(processingReason(input.processingStatus, input.processingIsStale));

  if (input.action === "ACCEPT") {
    if ((input.businessExceptions ?? []).some((exception) => severityRank(nonEmpty(exception.severity)) >= 3)) {
      reasons.push("A high-severity business exception must be resolved or overridden before accepting.");
    }
    if (remainingRequiredTasks.length > 0) {
      reasons.push(`${remainingRequiredTasks.length} required review check(s) remain incomplete in this session.`);
    }
    if (!rationale) reasons.push("Add a reviewer rationale before accepting.");
  }

  if (input.action === "OVERRIDE") {
    if (uncheckedHighTasks.length > 0) {
      reasons.push(`${uncheckedHighTasks.length} high-severity task(s) must be checked before overriding.`);
    }
    if (!rationale) reasons.push("Add a non-empty rationale before overriding and accepting.");
  }

  if (input.action === "REQUEST_DOCS") {
    if ((input.requestReasons ?? []).filter((reason) => nonEmpty(reason)).length === 0) {
      reasons.push("Select at least one document request reason.");
    }
    if (!nonEmpty(input.borrowerMessage)) {
      reasons.push("Add a borrower-facing message preview before requesting documents.");
    }
  }

  return {
    allowed: reasons.length === 0,
    reasons,
    processingState,
    processingBlocked,
    processingComplete,
    tasks,
    requiredTasks,
    highTasks,
    checkedCount: checkedTaskCount(requiredTasks, checked),
    remainingRequiredTasks,
    uncheckedHighTasks,
  };
}

/**
 * Persist the local checklist state in the existing reviewer note so a later
 * reviewer can see what was checked in this browser session.
 */
export function buildPersistedReviewerNote(
  baseNote: unknown,
  tasks: readonly DecisionTask[],
  checkedTaskIds: ReadonlySet<string> | readonly string[],
): string {
  const note = nonEmpty(baseNote);
  if (!note) return "";
  const checked = checkedSet(checkedTaskIds);
  const requiredTasks = tasks.filter((task) => task.required);
  const completed = requiredTasks.filter((task) => checked.has(task.id)).length;
  const remaining = requiredTasks.filter((task) => !checked.has(task.id));
  const completion = `Decision safety checks (this session): ${completed}/${requiredTasks.length} required review check(s) completed.`;
  const remainder = remaining.length
    ? `Remaining in-session checks: ${remaining.map((task) => task.label).join("; ")}.`
    : "All required review checks were completed in this session.";
  const checkedHighSeverity = tasks.filter((task) => severityRank(task.severity) >= 3 && checked.has(task.id));
  const highSummary = checkedHighSeverity.length > 0
    ? `Checked high-severity review task(s): ${checkedHighSeverity.map((task) => `${task.label} — ${task.reason}`).join("; ")}.`
    : "No high-severity review tasks were checked in this session.";
  return `${note}\n\n${completion} ${remainder}\n${highSummary}`;
}
