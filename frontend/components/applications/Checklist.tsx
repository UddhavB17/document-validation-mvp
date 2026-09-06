"use client";

import { useMemo, useState } from "react";

import { InfoMessage } from "@/components/Message";
import { StatusBadge } from "@/components/StatusBadge";
import { ApplicationReview, ChecklistRow } from "@/lib/api";

type ChecklistFilter = "attention" | "found" | "not_checked" | "all";

const filters: Array<{ id: ChecklistFilter; label: string }> = [
  { id: "attention", label: "Needs attention" },
  { id: "found", label: "Found" },
  { id: "not_checked", label: "Not checked" },
  { id: "all", label: "All" },
];

function normalizedStatus(status: string | null | undefined): string {
  return String(status ?? "").trim().toUpperCase();
}

function statusLabel(status: string): string {
  return status.replace(/_/g, " ").toLowerCase().replace(/(^|\s)\S/g, (letter) => letter.toUpperCase());
}

function statusRank(status: string): number {
  const normalized = normalizedStatus(status);
  if (normalized === "REQUIRED_AND_MISSING" || normalized === "MISSING") return 0;
  if (normalized === "NOT_EVALUATED_BY_ENGINE" || normalized === "NOT_CHECKED") return 1;
  if (normalized === "MANUAL_REVIEW" || normalized === "NEEDS_REVIEW") return 2;
  if (normalized === "REQUIRED_AND_PRESENT" || normalized === "FOUND") return 3;
  return 4;
}

function pageNumbersFor(row: ChecklistRow): number[] {
  return [...new Set(
    String(row.pages ?? "")
      .split(/,\s*/)
      .map(Number)
      .filter((page) => Number.isFinite(page) && page > 0),
  )];
}

function matchesFilter(row: ChecklistRow, filter: ChecklistFilter): boolean {
  const status = normalizedStatus(row.status);
  if (filter === "attention")
    return status === "REQUIRED_AND_MISSING" || status === "MISSING" || status === "MANUAL_REVIEW" || status === "NEEDS_REVIEW";
  if (filter === "found") return status === "REQUIRED_AND_PRESENT" || status === "FOUND";
  if (filter === "not_checked")
    return status === "NOT_EVALUATED_BY_ENGINE" || status === "NOT_CHECKED" || status === "MANUAL_REVIEW";
  return true;
}

export function Checklist({ data, onSelectPage }: { data: ApplicationReview; onSelectPage?: (row: ChecklistRow, pageNo: number, allPages?: number[]) => void }) {
  const [filter, setFilter] = useState<ChecklistFilter>("attention");
  const rows = useMemo(
    () => data.checklist.rows
      .filter((row) => matchesFilter(row, filter))
      .map((row, index) => ({ row, index }))
      .sort((left, right) => {
        const statusDifference = statusRank(left.row.status) - statusRank(right.row.status);
        if (statusDifference !== 0) return statusDifference;
        return Number(left.row.s_no ?? left.index) - Number(right.row.s_no ?? right.index);
      })
      .map(({ row }) => row),
    [data.checklist.rows, filter],
  );

  const attentionCount = data.checklist.rows.filter((row) => matchesFilter(row, "attention")).length;
  const notCheckedCount = data.checklist.rows.filter((row) => matchesFilter(row, "not_checked")).length;

  return (
    <section className="space-y-4" aria-labelledby="checklist-heading">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id="checklist-heading" className="text-base font-bold text-slate-800">MSFC Checklist ({data.checklist.total} items)</h2>
          <p className="mt-1 text-sm font-semibold text-slate-600" role="status" aria-live="polite">
            {data.checklist.found} found · {data.checklist.missing} missing · {data.checklist.not_checked} manual/not checked
          </p>
        </div>
        <p className="max-w-sm text-right text-xs font-medium text-slate-500">
          Missing and not-checked items are shown first so unresolved work is visible before found items.
        </p>
      </div>

      <div className="flex flex-wrap gap-2" role="group" aria-label="Checklist filters">
        {filters.map((item) => {
          const count = item.id === "attention"
            ? attentionCount
            : item.id === "found"
            ? data.checklist.found
            : item.id === "not_checked"
            ? notCheckedCount
            : data.checklist.total;
          return (
            <button
              key={item.id}
              type="button"
              aria-pressed={filter === item.id}
              onClick={() => setFilter(item.id)}
              className={`rounded-lg border px-3 py-1.5 text-xs font-bold transition-colors ${filter === item.id ? "border-blue-700 bg-blue-700 text-white" : "border-slate-300 bg-white text-slate-700 hover:bg-slate-50"}`}
            >
              {item.label} ({count})
            </button>
          );
        })}
      </div>

      {rows.length === 0 ? (
        <InfoMessage message={filter === "attention" ? "No checklist items need attention." : `No checklist items match “${filters.find((item) => item.id === filter)?.label}”.`} />
      ) : (
        <div className="overflow-x-auto rounded-xl border border-slate-200">
          <table className="min-w-full border-collapse text-left text-sm">
            <caption className="sr-only">Filtered MSFC checklist items</caption>
            <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th scope="col" className="px-3 py-2.5">S.No</th>
                <th scope="col" className="px-3 py-2.5">Status</th>
                <th scope="col" className="px-3 py-2.5">Description</th>
                <th scope="col" className="px-3 py-2.5">Looked for</th>
                <th scope="col" className="px-3 py-2.5">Source pages</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200 bg-white text-slate-800">
              {rows.map((row, index) => {
                const pageNumbers = pageNumbersFor(row);
                const status = normalizedStatus(row.status);
                return (
                  <tr key={`${row.s_no ?? "row"}-${index}`} className={status === "MISSING" || status === "NOT_CHECKED" ? "bg-amber-50/50" : undefined}>
                    <td className="whitespace-nowrap px-3 py-3 font-mono text-xs font-bold">{row.s_no ?? "-"}</td>
                    <td className="whitespace-nowrap px-3 py-3">
                      <span aria-label={`Checklist status: ${statusLabel(status)}`}><StatusBadge status={statusLabel(status)} /></span>
                    </td>
                    <td className="min-w-[220px] px-3 py-3 font-semibold">{row.description}</td>
                    <td className="min-w-[160px] px-3 py-3 text-slate-600">{row.document_types || "-"}</td>
                    <td className="min-w-[180px] px-3 py-3">
                      {pageNumbers.length > 0 ? (
                        <div className="flex flex-wrap gap-1.5">
                          {pageNumbers.map((pageNumber) => (
                            <button
                              key={pageNumber}
                              type="button"
                              disabled={!onSelectPage}
                              onClick={() => onSelectPage?.(row, pageNumber, pageNumbers.length > 1 ? pageNumbers : undefined)}
                              aria-label={`Open source page ${pageNumber} for ${row.description}`}
                              className="rounded border border-blue-200 bg-blue-50 px-2 py-1 text-xs font-bold text-blue-750 hover:bg-blue-100 disabled:cursor-default disabled:opacity-60"
                            >
                              Page {pageNumber}
                            </button>
                          ))}
                        </div>
                      ) : (
                        <span className="text-xs font-medium text-slate-500">No source page found</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
