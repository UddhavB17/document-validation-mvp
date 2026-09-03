"use client";

import { DecisionAction } from "@/lib/decisionPolicy";
import { useEffect, useRef } from "react";

function focusableElements(container: HTMLElement): HTMLElement[] {
  return Array.from(container.querySelectorAll<HTMLElement>(
    "button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])",
  ));
}

const actionLabels: Record<DecisionAction, string> = {
  ACCEPT: "Accept",
  OVERRIDE: "Override and accept",
  REQUEST_DOCS: "Request documents",
};

const resultingStates: Record<DecisionAction, string> = {
  ACCEPT: "Verified",
  OVERRIDE: "Verified with override",
  REQUEST_DOCS: "Incomplete — waiting for documents",
};

export function DecisionConfirmationDialog({
  action,
  loanId,
  applicantName,
  checkedCount,
  requiredCheckCount,
  remainingWarnings,
  note,
  criticalLoanId,
  typedLoanId,
  onTypedLoanIdChange,
  onCancel,
  onConfirm,
  isSubmitting,
  error,
}: {
  action: DecisionAction;
  loanId: string;
  applicantName: string;
  checkedCount: number;
  requiredCheckCount: number;
  remainingWarnings: { business: number; processing: number };
  note: string;
  criticalLoanId?: string;
  typedLoanId: string;
  onTypedLoanIdChange: (value: string) => void;
  onCancel: () => void;
  onConfirm: () => void;
  isSubmitting: boolean;
  error?: string | null;
}) {
  const requiresLoanConfirmation = action === "OVERRIDE" && Boolean(criticalLoanId);
  const dialogRef = useRef<HTMLElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const loanInputRef = useRef<HTMLInputElement>(null);
  const cancelHandlerRef = useRef(onCancel);
  const submittingRef = useRef(isSubmitting);
  cancelHandlerRef.current = onCancel;
  submittingRef.current = isSubmitting;

  useEffect(() => {
    const previousFocus = document.activeElement as HTMLElement | null;
    const dialog = dialogRef.current;
    (requiresLoanConfirmation ? loanInputRef.current : cancelRef.current)?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        if (!submittingRef.current) {
          event.preventDefault();
          cancelHandlerRef.current();
        }
        return;
      }
      if (event.key !== "Tab" || !dialog) return;
      const elements = focusableElements(dialog);
      if (elements.length === 0) {
        event.preventDefault();
        return;
      }
      const first = elements[0];
      const last = elements[elements.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      previousFocus?.focus();
    };
  }, [action, requiresLoanConfirmation]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/45 p-4" role="presentation">
      <section
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="decision-confirmation-title"
        aria-describedby="decision-confirmation-description"
        className="max-h-[90vh] w-full max-w-xl overflow-y-auto rounded-2xl border border-slate-200 bg-white p-6 shadow-2xl"
      >
        <div className="space-y-5">
          <div>
            <p className="text-xs font-bold uppercase tracking-[0.16em] text-slate-500">Confirm reviewer action</p>
            <h2 id="decision-confirmation-title" className="mt-1 text-xl font-bold text-slate-950">
              {actionLabels[action]}
            </h2>
            <p id="decision-confirmation-description" className="mt-1 text-sm text-slate-600">This will record the following resulting state: <strong>{resultingStates[action]}</strong>.</p>
          </div>

          <dl className="grid grid-cols-1 gap-3 rounded-xl bg-slate-50 p-4 text-sm sm:grid-cols-2">
            <div>
              <dt className="font-semibold text-slate-500">Loan / application</dt>
              <dd className="mt-1 font-bold text-slate-900">{loanId}</dd>
            </div>
            <div>
              <dt className="font-semibold text-slate-500">Applicant</dt>
              <dd className="mt-1 font-bold text-slate-900">{applicantName}</dd>
            </div>
            <div>
              <dt className="font-semibold text-slate-500">Checks completed this session</dt>
              <dd className="mt-1 font-bold text-slate-900">{checkedCount}/{requiredCheckCount}</dd>
            </div>
            <div>
              <dt className="font-semibold text-slate-500">Remaining warnings</dt>
              <dd className="mt-1 font-bold text-slate-900">
                {remainingWarnings.business} business · {remainingWarnings.processing} processing
              </dd>
            </div>
          </dl>

          <div>
            <h3 className="text-sm font-bold text-slate-900">Exact reviewer note to be saved</h3>
            <p className="mt-2 whitespace-pre-wrap rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm text-slate-700">
              {note}
            </p>
          </div>

          {requiresLoanConfirmation ? (
            <div className="space-y-2">
              <label htmlFor="critical-loan-confirmation" className="text-sm font-bold text-red-800">
                Critical override: type loan ID {criticalLoanId} to continue
              </label>
              <input
                id="critical-loan-confirmation"
                type="text"
                value={typedLoanId}
                onChange={(event) => onTypedLoanIdChange(event.target.value)}
                className="w-full rounded-lg border border-red-300 bg-white px-3 py-2 text-base text-slate-900 outline-none focus:border-red-600 focus:ring-2 focus:ring-red-600/20"
                ref={loanInputRef}
                autoComplete="off"
              />
            </div>
          ) : null}

          {error ? (
            <div role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm font-semibold text-red-800">
              {error}
            </div>
          ) : null}

          <div className="flex flex-wrap justify-end gap-2">
            <button
              ref={cancelRef}
              type="button"
              className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60"
              onClick={onCancel}
              disabled={isSubmitting}
            >
              Cancel
            </button>
            <button
              type="button"
              className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
              onClick={onConfirm}
              disabled={isSubmitting || (requiresLoanConfirmation && typedLoanId.trim() !== criticalLoanId)}
            >
              {isSubmitting ? "Recording…" : `Confirm ${actionLabels[action].toLowerCase()}`}
            </button>
          </div>
        </div>
      </section>
    </div>
  );
}
