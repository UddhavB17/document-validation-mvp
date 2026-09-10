"use client";

import { useMemo, useState } from "react";
import type React from "react";
import type { ChecklistItem, ChecklistVerificationResponse } from "../generated/checklistTypes";

type Props = {
  data: ChecklistVerificationResponse;
};

type ChecklistFilter = "attention" | "found" | "not_checked" | "all";

const filters: Array<{ id: ChecklistFilter; label: string }> = [
  { id: "attention", label: "Needs attention" },
  { id: "found", label: "Found" },
  { id: "not_checked", label: "Not checked" },
  { id: "all", label: "All" },
];

const statusStyles = {
  required_and_present: "border-emerald-700/40 bg-emerald-950/30 text-emerald-200",
  manual_review: "border-amber-600/50 bg-amber-950/30 text-amber-100",
  required_and_missing: "border-rose-700/50 bg-rose-950/30 text-rose-100",
  not_evaluated_by_engine: "border-slate-600/60 bg-slate-900 text-slate-100",
  not_applicable: "border-sky-700/40 bg-sky-950/30 text-sky-100",
};

const statusIcons = {
  required_and_present: "OK",
  manual_review: "!",
  required_and_missing: "X",
  not_evaluated_by_engine: "?",
  not_applicable: "N/A",
};

function matchesFilter(item: ChecklistItem, filter: ChecklistFilter): boolean {
  if (filter === "attention") return item.status === "required_and_missing" || item.status === "manual_review";
  if (filter === "found") return item.status === "required_and_present";
  if (filter === "not_checked") return item.status === "not_evaluated_by_engine" || item.status === "manual_review";
  return true;
}

function reviewable(item: ChecklistItem): boolean {
  return item.status !== "required_and_present" && item.status !== "not_applicable";
}

export function NdcChecklistReview({ data }: Props) {
  const [filter, setFilter] = useState<ChecklistFilter>("attention");
  const [reviewedItems, setReviewedItems] = useState<Set<number>>(() => new Set());
  const items = useMemo(
    () => data.items
      .filter((item) => matchesFilter(item, filter))
      .sort((left, right) => {
        const rank = (status: ChecklistItem["status"]) => status === "required_and_missing" ? 0 : status === "manual_review" ? 1 : status === "not_evaluated_by_engine" ? 2 : status === "required_and_present" ? 3 : 4;
        return rank(left.status) - rank(right.status) || left.item_number - right.item_number;
      }),
    [data.items, filter],
  );
  const reviewableItems = data.items.filter(reviewable);
  const checkedCount = reviewableItems.filter((item) => reviewedItems.has(item.item_number)).length;

  function toggleReviewed(itemNumber: number): void {
    setReviewedItems((current) => {
      const next = new Set(current);
      if (next.has(itemNumber)) next.delete(itemNumber);
      else next.add(itemNumber);
      return next;
    });
  }

  return (
    <section className="min-h-screen bg-slate-950 p-6 text-slate-100" aria-labelledby="ndc-checklist-heading">
      <div className="mx-auto max-w-7xl space-y-5">
        <header className="flex flex-wrap items-end justify-between gap-4 border-b border-slate-800 pb-4">
          <div>
            <h1 id="ndc-checklist-heading" className="text-2xl font-semibold">NDC checklist review</h1>
            <p className="text-sm text-slate-400">Loan file {data.loan_file_id}</p>
            <p className="mt-2 text-sm font-semibold text-slate-300" role="status" aria-live="polite">
              {data.summary.required_and_present} found · {data.summary.required_and_missing} missing · {data.summary.manual_review + data.summary.not_evaluated_by_engine} manual/not checked
            </p>
          </div>
          <SummaryBar data={data} />
        </header>

        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap gap-2" role="group" aria-label="NDC checklist filters">
            {filters.map((item) => {
              const count = item.id === "attention"
                ? data.summary.required_and_missing + data.summary.manual_review
                : item.id === "found"
                ? data.summary.required_and_present
                : item.id === "not_checked"
                ? data.summary.not_evaluated_by_engine + data.summary.manual_review
                : data.summary.total;
              return (
                <button
                  key={item.id}
                  type="button"
                  aria-pressed={filter === item.id}
                  onClick={() => setFilter(item.id)}
                  className={`rounded-md border px-3 py-1.5 text-xs font-semibold ${filter === item.id ? "border-sky-400 bg-sky-900 text-sky-100" : "border-slate-700 bg-slate-900 text-slate-300 hover:bg-slate-800"}`}
                >
                  {item.label} ({count})
                </button>
              );
            })}
          </div>
          <p className="text-xs font-semibold text-slate-400" role="status" aria-live="polite">{checkedCount}/{reviewableItems.length} required checks completed this session</p>
        </div>

        <div className="overflow-hidden rounded-md border border-slate-800">
          {items.length === 0 ? (
            <p className="px-4 py-6 text-sm text-slate-400">No checklist items match this filter.</p>
          ) : items.map((item) => <ChecklistRow key={item.item_number} item={item} checked={reviewedItems.has(item.item_number)} onToggle={() => toggleReviewed(item.item_number)} />)}
        </div>
      </div>
    </section>
  );
}

function SummaryBar({ data }: Props) {
  const items = [
    ["Present", data.summary.required_and_present, "text-emerald-300"],
    ["Manual review", data.summary.manual_review, "text-amber-300"],
    ["Missing", data.summary.required_and_missing, "text-rose-300"],
    ["Not evaluated", data.summary.not_evaluated_by_engine, "text-slate-300"],
    ["N/A", data.summary.not_applicable, "text-sky-300"],
  ] as const;

  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
      {items.map(([label, value, color]) => (
        <div key={label} className="rounded-md border border-slate-800 bg-slate-900 px-4 py-3">
          <div className={`text-xl font-semibold ${color}`}>{value}/{data.summary.total}</div>
          <div className="text-xs uppercase tracking-wide text-slate-500">{label}</div>
        </div>
      ))}
    </div>
  );
}

function ChecklistRow({ item, checked, onToggle }: { item: ChecklistItem; checked: boolean; onToggle: () => void }) {
  const expanded = item.status !== "required_and_present" && item.status !== "not_applicable";
  const canCheck = reviewable(item);

  return (
    <details open={expanded} className="group border-b border-slate-800 last:border-b-0">
      <summary className="grid cursor-pointer grid-cols-[auto_1fr_auto] items-center gap-3 bg-slate-950 px-4 py-3 hover:bg-slate-900">
        <span className={`flex h-7 w-7 items-center justify-center rounded-full border text-sm ${statusStyles[item.status]}`} aria-hidden="true">
          {statusIcons[item.status]}
        </span>
        <div className="min-w-0">
          <div className="truncate font-medium">{item.item_number}. {item.document_name}</div>
          <div className="text-sm text-slate-500">{item.confidence_detail}</div>
          <span className="sr-only">Checklist status: {item.status.replace("_", " ")}</span>
        </div>
        <div className="flex flex-wrap justify-end gap-2">
          <Badge>{item.status.replace("_", " ")}</Badge>
          <Badge>{item.confidence}</Badge>
          {item.extraction_source === "llm_fallback" && <Badge tone="warning">Sent to LLM fallback - recommend manual check</Badge>}
        </div>
      </summary>

      <div className="grid gap-4 bg-slate-900/70 px-4 py-4 md:grid-cols-[1fr_1.2fr]">
        <div className="space-y-3">
          {item.narration && (
            <div>
              <div className="text-xs uppercase tracking-wide text-slate-500">Narration</div>
              <p className="mt-1 text-sm text-slate-200">{item.narration}</p>
            </div>
          )}
          {item.flagged_reason && (
            <div>
              <div className="text-xs uppercase tracking-wide text-slate-500">Flagged reason</div>
              <p className="mt-1 font-mono text-sm text-slate-200">{item.flagged_reason}</p>
            </div>
          )}
          {canCheck ? (
            <label className="flex items-start gap-2 rounded-md border border-slate-700 bg-slate-950 p-3 text-sm font-medium text-slate-200">
              <input type="checkbox" checked={checked} onChange={onToggle} className="mt-0.5 h-4 w-4 rounded border-slate-600 bg-slate-900 text-sky-500 focus:ring-sky-500/30" />
              <span>Mark this required manual check complete for this session</span>
            </label>
          ) : null}
        </div>

        <div className="rounded-md border border-slate-800 bg-slate-950 p-3">
          <div className="mb-2 text-xs uppercase tracking-wide text-slate-500">Extracted fields</div>
          {Object.keys(item.extracted_fields).length === 0 ? (
            <p className="text-sm text-slate-500">No fields extracted.</p>
          ) : (
            <dl className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              {Object.entries(item.extracted_fields).map(([key, value]) => (
                <div key={key} className="min-w-0">
                  <dt className="truncate text-xs text-slate-500">{key}</dt>
                  <dd className="break-words text-sm text-slate-100">{value ?? "-"}</dd>
                </div>
              ))}
            </dl>
          )}
        </div>
      </div>
    </details>
  );
}

function Badge({ children, tone = "neutral" }: { children: React.ReactNode; tone?: "neutral" | "warning" }) {
  const className = tone === "warning"
    ? "border-amber-500/50 bg-amber-950/50 text-amber-200"
    : "border-slate-700 bg-slate-900 text-slate-300";
  return <span className={`rounded-md border px-2 py-1 text-xs font-medium ${className}`}>{children}</span>;
}
