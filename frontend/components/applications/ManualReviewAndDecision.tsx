"use client";

import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { InfoMessage } from "@/components/Message";
import { DecisionConfirmationDialog } from "@/components/applications/decision/DecisionConfirmationDialog";
import {
  buildDecisionTasks,
  buildPersistedReviewerNote,
  DecisionAction,
  DecisionTask,
  evaluateDecisionPolicy,
  taskNeedsEvidence,
} from "@/lib/decisionPolicy";
import { ApplicationReview, Decision } from "@/lib/api";
import { asText } from "@/lib/format";
import { decisionNoteSchema } from "@/lib/forms";
import { useCreateDecision, useUndoDecision } from "@/lib/queries";
import { rejectionReasons } from "@/components/applications/reviewUtils";
import {
  getCheckedReviewTaskIds,
  REVIEW_STATE_EVENT,
  setReviewTaskChecked,
} from "@/components/applications/review/sessionState";
import { getReviewQueueNeighbors, readReviewQueue, updateReviewQueuePosition } from "@/lib/reviewQueue";

const UNDO_WINDOW_SECONDS = 10 * 60;
const reasonLabels = Object.keys(rejectionReasons) as Array<keyof typeof rejectionReasons>;

function decisionId(decision: Decision | null | undefined): number | null {
  return decision?.id ?? decision?.decision_id ?? null;
}

function decisionResultingState(decision: string | null | undefined): string {
  if (decision === "ACCEPT") return "Verified";
  if (decision === "OVERRIDE") return "Verified with override";
  if (decision === "REQUEST_DOCS") return "Incomplete — waiting for documents";
  return "Recorded";
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : "Unable to record the reviewer decision. Please try again.";
}

function useUndoRemainingSeconds(decidedAt: string | null | undefined): number | null {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!decidedAt) return undefined;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [decidedAt]);

  if (!decidedAt) return null;
  const decidedAtMs = Date.parse(decidedAt);
  if (!Number.isFinite(decidedAtMs)) return null;
  return Math.max(0, Math.min(UNDO_WINDOW_SECONDS, UNDO_WINDOW_SECONDS - Math.floor((now - decidedAtMs) / 1000)));
}

function formatCountdown(seconds: number): string {
  const minutes = Math.floor(seconds / 60).toString().padStart(2, "0");
  const remainder = (seconds % 60).toString().padStart(2, "0");
  return `${minutes}:${remainder}`;
}

export function sourcePageForTask(task: DecisionTask): number | null {
  // A task may open source evidence only when the API explicitly attached a
  // page. Document type mappings are not proof of the source page.
  return taskNeedsEvidence(task) ? task.pageNumber : null;
}

export function ManualReviewAndDecision({ applicationId, data, onSelectPage }: { applicationId: number; data: ApplicationReview; onSelectPage?: (pageNo: number, taskId?: string) => void }) {
  const [note, setNote] = useState("");
  const [selectedReasons, setSelectedReasons] = useState<string[]>([]);
  const [borrowerMessage, setBorrowerMessage] = useState("");
  const [messageTouched, setMessageTouched] = useState(false);
  const [showRequestDocs, setShowRequestDocs] = useState(false);
  const [checkedTaskIds, setCheckedTaskIds] = useState<Set<string>>(() => new Set());
  const [dialogAction, setDialogAction] = useState<DecisionAction | null>(null);
  const [typedLoanId, setTypedLoanId] = useState("");
  const [actionError, setActionError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [recordedDecision, setRecordedDecision] = useState<Decision | null>(null);
  const [undoneDecisionId, setUndoneDecisionId] = useState<number | null>(null);
  const [nextQueuedCaseId, setNextQueuedCaseId] = useState<number | null>(null);
  const createDecision = useCreateDecision(applicationId);
  const undoDecision = useUndoDecision(applicationId);
  const router = useRouter();

  const processingStatus = data.progress?.operational_status ?? data.progress?.status ?? data.application.status;
  const tasks = useMemo(
    () => buildDecisionTasks({
      manualReviewItems: data.manual_review_items,
      checklistRows: data.checklist.rows,
      businessExceptions: data.summary.business_anomalies,
    }),
    [data.checklist.rows, data.manual_review_items, data.summary.business_anomalies],
  );
  const taskIds = useMemo(() => tasks.map((task) => task.id), [tasks]);

  useEffect(() => {
    setCheckedTaskIds(getCheckedReviewTaskIds(applicationId, taskIds));
    const reconcile = (event: Event) => {
      const detail = (event as CustomEvent<{ applicationId?: number }>).detail;
      if (detail?.applicationId === applicationId || event.type === "storage") {
        setCheckedTaskIds(getCheckedReviewTaskIds(applicationId, taskIds));
      }
    };
    window.addEventListener(REVIEW_STATE_EVENT, reconcile);
    window.addEventListener("storage", reconcile);
    return () => {
      window.removeEventListener(REVIEW_STATE_EVENT, reconcile);
      window.removeEventListener("storage", reconcile);
    };
  }, [applicationId, taskIds]);

  const requiredTasks = tasks.filter((task) => task.required);
  const reviewTasks = tasks.filter((task) => task.required || task.severity?.toUpperCase() === "HIGH");
  const checkedCount = requiredTasks.filter((task) => checkedTaskIds.has(task.id)).length;
  const requestMessage = borrowerMessage.trim();
  const requestNote = [
    requestMessage,
    selectedReasons.length > 0 ? `Requested document reasons: ${selectedReasons.join(", ")}` : "",
  ].filter(Boolean).join("\n\n");
  const decisionInputs = {
    processingStatus,
    processingIsStale: data.progress?.is_stale,
    manualReviewItems: data.manual_review_items,
    checklistRows: data.checklist.rows,
    businessExceptions: data.summary.business_anomalies,
    checkedTaskIds,
  };
  const acceptPolicy = evaluateDecisionPolicy({ ...decisionInputs, action: "ACCEPT", rationale: note });
  const overridePolicy = evaluateDecisionPolicy({ ...decisionInputs, action: "OVERRIDE", rationale: note });
  const requestDocsPolicy = evaluateDecisionPolicy({
    ...decisionInputs,
    action: "REQUEST_DOCS",
    requestReasons: selectedReasons,
    borrowerMessage,
  });

  const serverDecision = data.latest_decision;
  const currentDecision = recordedDecision ?? (decisionId(serverDecision) === undoneDecisionId ? null : serverDecision);
  const currentDecisionId = decisionId(currentDecision);
  const undoRemainingSeconds = useUndoRemainingSeconds(currentDecision?.decided_at);
  const loanId = asText(data.application.loan_id) === "-" ? String(applicationId) : asText(data.application.loan_id);
  const applicantName = asText(data.application.applicant_name);
  const isCritical = String(data.application.status ?? "").toUpperCase() === "CRITICAL" || data.summary.business_anomalies.some((item) => item.severity?.toUpperCase() === "HIGH");
  const confirmationNote = dialogAction === "REQUEST_DOCS"
    ? buildPersistedReviewerNote(requestNote, tasks, checkedTaskIds)
    : buildPersistedReviewerNote(note, tasks, checkedTaskIds);
  const remainingWarnings = {
    business: data.summary.business_count,
    processing: data.summary.processing_warning_count,
  };
  const mutationBusy = isSubmitting || createDecision.isPending || undoDecision.isPending;

  useEffect(() => {
    const syncQueuePosition = () => setNextQueuedCaseId(getReviewQueueNeighbors(readReviewQueue(), applicationId).nextId);
    syncQueuePosition();
    window.addEventListener("dmef-review-queue-change", syncQueuePosition);
    window.addEventListener("storage", syncQueuePosition);
    return () => {
      window.removeEventListener("dmef-review-queue-change", syncQueuePosition);
      window.removeEventListener("storage", syncQueuePosition);
    };
  }, [applicationId]);

  function toggleTask(taskId: string): void {
    setCheckedTaskIds((current) => {
      const next = new Set(current);
      const checked = !next.has(taskId);
      if (checked) next.add(taskId);
      else next.delete(taskId);
      setReviewTaskChecked(applicationId, taskId, checked);
      return next;
    });
    setActionError(null);
  }

  function requestTaskEvidence(task: DecisionTask): void {
    const sourcePage = sourcePageForTask(task);
    if (sourcePage !== null && taskNeedsEvidence(task)) {
      if (onSelectPage) {
        onSelectPage(sourcePage, task.id);
      } else {
        setActionError("Open the task's source evidence before marking it checked.");
      }
      return;
    }
    toggleTask(task.id);
  }

  function toggleReason(reason: string): void {
    const next = selectedReasons.includes(reason)
      ? selectedReasons.filter((item) => item !== reason)
      : [...selectedReasons, reason];
    setSelectedReasons(next);
    if (!messageTouched) {
      setBorrowerMessage(next.map((item) => rejectionReasons[item as keyof typeof rejectionReasons]).join("\n"));
    }
    setActionError(null);
  }

  function policyFor(action: DecisionAction) {
    if (action === "ACCEPT") return acceptPolicy;
    if (action === "OVERRIDE") return overridePolicy;
    return requestDocsPolicy;
  }

  function openConfirmation(action: DecisionAction): void {
    setActionError(null);
    createDecision.reset();
    const policy = policyFor(action);
    if (!policy.allowed) {
      setActionError(policy.reasons.join(" "));
      return;
    }
    setTypedLoanId("");
    setDialogAction(action);
  }

  async function confirmDecision(): Promise<void> {
    if (!dialogAction) return;
    if (dialogAction === "OVERRIDE" && isCritical && typedLoanId.trim() !== loanId) {
      setActionError(`Type the exact loan ID ${loanId} to confirm this critical override.`);
      return;
    }

    const policy = policyFor(dialogAction);
    if (!policy.allowed) {
      setActionError(policy.reasons.join(" "));
      return;
    }

    const baseNote = dialogAction === "REQUEST_DOCS" ? requestNote : note;
    const parsed = decisionNoteSchema.safeParse(baseNote);
    if (!parsed.success) {
      setActionError(parsed.error.errors[0]?.message ?? "Reviewer note is required");
      return;
    }

    const persistedNote = buildPersistedReviewerNote(parsed.data, tasks, checkedTaskIds);
    setActionError(null);
    setIsSubmitting(true);
    try {
      const result = await createDecision.mutateAsync({
        application_id: applicationId,
        decision: dialogAction,
        reviewer_note: persistedNote,
      });
      setRecordedDecision(result);
      setUndoneDecisionId(null);
      setDialogAction(null);
      setActionError(null);
    } catch (error) {
      setActionError(errorText(error));
    } finally {
      setIsSubmitting(false);
    }
  }

  async function undoRecordedDecision(): Promise<void> {
    if (currentDecisionId === null || undoRemainingSeconds !== null && undoRemainingSeconds <= 0) return;
    setActionError(null);
    try {
      await undoDecision.mutateAsync(currentDecisionId);
      setUndoneDecisionId(currentDecisionId);
      setRecordedDecision(null);
      setActionError(null);
    } catch (error) {
      setActionError(errorText(error));
    }
  }

  function openNextQueuedCase(): void {
    const queue = readReviewQueue();
    const neighbors = getReviewQueueNeighbors(queue, applicationId);
    if (neighbors.position !== null) updateReviewQueuePosition(neighbors.position);
    router.push(neighbors.nextId !== null ? `/applications/${neighbors.nextId}` : "/worklist");
  }

  return (
    <section className="space-y-5" aria-labelledby="manual-review-heading">
      <div>
        <h2 id="manual-review-heading" className="text-base font-bold text-slate-800">Manual review and decision</h2>
        <p className="mt-1 text-sm text-slate-600">Complete each required review check individually. Completion is local to this session and is summarized in the saved reviewer note.</p>
      </div>

      {data.summary.processing_warning_count > 0 ? (
        <InfoMessage message={`${data.summary.processing_warning_count} processing warning(s) remain separate from business blockers. Review them in the processing log before relying on page evidence.`} />
      ) : null}
      {data.summary.business_count > 0 ? (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          <strong>{data.summary.business_count} business exception(s)</strong> affect the review. High-severity business exceptions block Accept; processing warnings do not.
        </div>
      ) : null}
      {!acceptPolicy.processingComplete && !currentDecision ? (
        <div role="status" aria-live="polite" className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm font-semibold text-red-800">
          Decisions are disabled: {acceptPolicy.reasons.find((reason) => reason.toLowerCase().includes("processing")) ?? "processing must be complete before deciding."}
        </div>
      ) : null}

      <div className="rounded-xl border border-slate-200 bg-slate-50 p-4" aria-labelledby="required-checks-heading">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h3 id="required-checks-heading" className="font-bold text-slate-900">Required review checks</h3>
          <p className="text-sm font-semibold text-slate-700" role="status" aria-live="polite">
            {checkedCount}/{requiredTasks.length} completed this session
          </p>
        </div>
        {reviewTasks.length === 0 ? (
          <p className="mt-3 text-sm text-slate-600">No manual or high-severity review tasks were returned for this application.</p>
        ) : (
          <div className="mt-3 space-y-3">
            {reviewTasks.map((task, index) => {
              const inputId = `manual-review-task-${index}`;
              const sourcePage = sourcePageForTask(task);
              return (
                <div key={task.id} className="rounded-lg border border-slate-200 bg-white p-3">
                  <div className="flex items-start gap-3">
                    <input
                      id={inputId}
                      type="checkbox"
                      checked={checkedTaskIds.has(task.id)}
                      onChange={() => {
                        if (checkedTaskIds.has(task.id)) toggleTask(task.id);
                        else requestTaskEvidence(task);
                      }}
                      disabled={mutationBusy || Boolean(currentDecision)}
                      className="mt-1 h-4 w-4 rounded border-slate-400 text-blue-700 focus:ring-blue-600/20"
                      aria-describedby={`${inputId}-detail`}
                    />
                    <div className="min-w-0 flex-1">
                      <label htmlFor={inputId} className="cursor-pointer text-sm font-bold text-slate-900">{task.label}</label>
                      <p id={`${inputId}-detail`} className="mt-1 text-xs font-medium text-slate-600">
                        {task.reason}{task.severity ? ` · ${task.severity.toUpperCase()} task` : ""}
                      </p>
                      {sourcePage ? <p className="mt-1 text-xs font-semibold text-blue-700">Checking this task opens page {sourcePage}; mark it checked from the evidence workspace after the image loads.</p> : null}
                      {sourcePage ? (
                        <button
                          type="button"
                          onClick={() => onSelectPage?.(sourcePage, task.id)}
                          disabled={!onSelectPage}
                          className="mt-2 rounded border border-blue-200 bg-blue-50 px-2 py-1 text-xs font-bold text-blue-750 hover:bg-blue-100 disabled:cursor-default disabled:opacity-60"
                          aria-label={`Open source page ${sourcePage} for ${task.label}`}
                        >
                          Open source page {sourcePage}
                        </button>
                      ) : (
                        <p className="mt-2 text-xs font-semibold text-slate-500">No single source page was returned for this task.</p>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {currentDecision ? (
        <div className="space-y-3 rounded-xl border border-emerald-200 bg-emerald-50 p-4" role="status" aria-live="polite">
          <div>
            <p className="text-xs font-bold uppercase tracking-wide text-emerald-800">Recorded decision</p>
            <p className="mt-1 text-sm font-bold text-emerald-950">
              {currentDecision.decision} · resulting state: {decisionResultingState(currentDecision.decision)}
            </p>
          </div>
          {undoRemainingSeconds === null ? (
            <p className="text-xs font-semibold text-emerald-900">Undo timing is unavailable because the backend did not return a valid decision time.</p>
          ) : undoRemainingSeconds > 0 ? (
            <p className="text-xs font-semibold text-emerald-900">Undo available for {formatCountdown(undoRemainingSeconds)}. The ten-minute window expires from the backend-recorded decision time.</p>
          ) : (
            <p className="text-xs font-semibold text-red-800">Undo window expired. This decision remains recorded; contact a supervisor to correct it.</p>
          )}
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              disabled={mutationBusy || currentDecisionId === null || undoRemainingSeconds === null || undoRemainingSeconds <= 0}
              onClick={() => void undoRecordedDecision()}
              className="rounded-lg border border-emerald-300 bg-white px-4 py-2 text-sm font-semibold text-emerald-900 hover:bg-emerald-100 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {undoDecision.isPending ? "Undoing…" : "Undo decision"}
            </button>
            <button type="button" onClick={openNextQueuedCase} className="rounded-lg bg-emerald-800 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-700">
              {nextQueuedCaseId !== null ? "Open next case" : "Return to worklist"}
            </button>
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          {actionError ? <div role="alert" className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm font-semibold text-red-800">{actionError}</div> : null}

          <div className="rounded-xl border border-slate-200 bg-white p-4">
            <label htmlFor="reviewer-note" className="text-sm font-bold text-slate-900">Reviewer rationale</label>
            <textarea
              id="reviewer-note"
              className="mt-2 h-24 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-base text-slate-900 placeholder-slate-400 focus:border-blue-600 focus:outline-none focus:ring-2 focus:ring-blue-600/20"
              value={note}
              onChange={(event) => { setNote(event.target.value); setActionError(null); }}
              placeholder="Enter the rationale that will be saved with this decision."
              disabled={mutationBusy}
            />
            <p className="mt-1 text-xs font-medium text-slate-500">The entered rationale is required; no generated fallback note will be used.</p>
          </div>

          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              disabled={mutationBusy || !acceptPolicy.processingComplete || !acceptPolicy.allowed}
              onClick={() => openConfirmation("ACCEPT")}
              className="rounded-lg bg-emerald-700 px-5 py-2 text-sm font-semibold text-white hover:bg-emerald-600 disabled:cursor-not-allowed disabled:bg-slate-300 disabled:text-slate-500"
            >
              Accept
            </button>
            <button
              type="button"
              disabled={mutationBusy || !overridePolicy.processingComplete || !overridePolicy.allowed}
              onClick={() => openConfirmation("OVERRIDE")}
              className="rounded-lg bg-blue-700 px-5 py-2 text-sm font-semibold text-white hover:bg-blue-600 disabled:cursor-not-allowed disabled:bg-slate-300 disabled:text-slate-500"
            >
              Override and accept
            </button>
            <button
              type="button"
              disabled={mutationBusy || !requestDocsPolicy.processingComplete}
              onClick={() => { setShowRequestDocs((current) => !current); setActionError(null); }}
              className="rounded-lg border border-slate-300 bg-white px-5 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-400"
            >
              {showRequestDocs ? "Hide request documents" : "Request documents"}
            </button>
          </div>

          <div className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-3 text-xs font-semibold text-slate-700" role="status" aria-live="polite">
            <p><span className="font-bold">Accept:</span> {acceptPolicy.allowed ? "ready to review" : acceptPolicy.reasons.join(" ")}</p>
            <p className="mt-1"><span className="font-bold">Override and accept:</span> {overridePolicy.allowed ? "ready to review" : overridePolicy.reasons.join(" ")}</p>
          </div>

          {showRequestDocs ? (
            <div className="space-y-4 rounded-xl border border-red-200 bg-red-50/50 p-4">
              <div>
                <h3 className="text-sm font-bold text-slate-900">Why are documents needed?</h3>
                <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
                  {reasonLabels.map((reason) => (
                    <label key={reason} className="flex items-start gap-2 rounded-lg border border-slate-200 bg-white p-2 text-sm font-semibold text-slate-700">
                      <input
                        type="checkbox"
                        checked={selectedReasons.includes(reason)}
                        onChange={() => toggleReason(reason)}
                        disabled={mutationBusy}
                        className="mt-0.5 h-4 w-4 rounded border-slate-400 text-red-700 focus:ring-red-600/20"
                      />
                      <span>{reason}</span>
                    </label>
                  ))}
                </div>
              </div>
              <div>
                <label htmlFor="borrower-message" className="text-sm font-bold text-slate-900">Borrower-facing message preview</label>
                <textarea
                  id="borrower-message"
                  className="mt-2 h-28 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-base text-slate-900 placeholder-slate-400 focus:border-red-600 focus:outline-none focus:ring-2 focus:ring-red-600/20"
                  value={borrowerMessage}
                  onChange={(event) => { setBorrowerMessage(event.target.value); setMessageTouched(true); setActionError(null); }}
                  placeholder="Preview the message the borrower will receive."
                  disabled={mutationBusy}
                />
              </div>
              {requestDocsPolicy.reasons.length > 0 ? <p className="text-xs font-semibold text-red-800">{requestDocsPolicy.reasons.join(" ")}</p> : null}
              <button
                type="button"
                disabled={mutationBusy || !requestDocsPolicy.allowed}
                onClick={() => openConfirmation("REQUEST_DOCS")}
                className="rounded-lg bg-red-700 px-5 py-2 text-sm font-semibold text-white hover:bg-red-600 disabled:cursor-not-allowed disabled:bg-slate-300 disabled:text-slate-500"
              >
                Review request for documents
              </button>
            </div>
          ) : null}
        </div>
      )}

      {dialogAction ? (
        <DecisionConfirmationDialog
          action={dialogAction}
          loanId={loanId}
          applicantName={applicantName}
          checkedCount={checkedCount}
          requiredCheckCount={requiredTasks.length}
          remainingWarnings={remainingWarnings}
          note={confirmationNote}
          criticalLoanId={dialogAction === "OVERRIDE" && isCritical ? loanId : undefined}
          typedLoanId={typedLoanId}
          onTypedLoanIdChange={(value) => { setTypedLoanId(value); setActionError(null); }}
          onCancel={() => { if (!isSubmitting) { setDialogAction(null); setActionError(null); } }}
          onConfirm={() => void confirmDecision()}
          isSubmitting={mutationBusy}
          error={actionError}
        />
      ) : null}
    </section>
  );
}
