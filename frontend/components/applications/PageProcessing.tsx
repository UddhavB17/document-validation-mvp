"use client";

import { useMemo, useState } from "react";

import { InfoMessage } from "@/components/Message";
import { Metric } from "@/components/Metric";
import { StatusBadge } from "@/components/StatusBadge";
import { averagePageTime, displayValue, formatLlmDocument, isProcessingIssue, summarizePublicFields } from "@/components/applications/reviewUtils";
import { ApplicationReview } from "@/lib/api";
import { formatSeconds } from "@/lib/format";

const PAGE_SIZE = 50;

export function PageProcessing({ data, onSelectPage }: { data: Pick<ApplicationReview, "page_events">; onSelectPage?: (pageNo: number, docType?: string) => void }) {
  const events = data.page_events;
  const [view, setView] = useState<"issues" | "all">("issues");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);

  const avgSeconds = averagePageTime(events);
  const issueCount = events.filter((event) => isProcessingIssue(event.status, event.error)).length;
  const filteredEvents = useMemo(() => {
    const normalizedSearch = search.trim().toLowerCase();
    return events.filter((event) => {
      if (view === "issues" && !isProcessingIssue(event.status, event.error)) {
        return false;
      }
      if (!normalizedSearch) {
        return true;
      }
      const searchable = [
        event.page_number,
        event.status,
        event.page_type,
        event.document_type,
        event.error,
        summarizePublicFields(event.extracted_fields),
      ].map((value) => String(value ?? "").toLowerCase());
      return searchable.some((value) => value.includes(normalizedSearch));
    });
  }, [events, search, view]);
  const pageCount = Math.max(1, Math.ceil(filteredEvents.length / PAGE_SIZE));
  const currentPage = Math.min(page, pageCount);
  const visibleEvents = filteredEvents.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE);

  if (events.length === 0) {
    return <InfoMessage message="No page events logged." />;
  }

  return (
    <section className="min-w-0 space-y-4">
      <div className="flex min-w-0 flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-base font-bold text-slate-800">Processing</h2>
          <p className="mt-1 text-xs font-medium text-[#5C6B7A]">Warnings and errors are shown first. Verbose diagnostics stay inside each row.</p>
        </div>
        <span className="rounded-lg border border-[#E1E5EB] bg-[#F6F7FA] px-3 py-1.5 text-xs font-bold text-[#5C6B7A]">50 rows per page</span>
      </div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <Metric label="Page events recorded" value={events.length} />
        <Metric label="Avg. processing speed" value={`${avgSeconds.toFixed(1)}s / page`} />
        <Metric label="Warnings / errors" value={issueCount} />
      </div>

      <div className="flex min-w-0 flex-wrap items-center gap-3 rounded-xl border border-[#E1E5EB] bg-[#F6F7FA]/70 p-3">
        <label className="flex min-w-[220px] flex-1 items-center gap-2 text-xs font-bold text-[#5C6B7A]">
          <span className="sr-only">Search processing events</span>
          <input
            type="search"
            value={search}
            onChange={(event) => { setSearch(event.target.value); setPage(1); }}
            placeholder="Search page, document, status, or diagnostic"
            className="w-full rounded-lg border border-[#E1E5EB] bg-white px-3 py-2 text-xs font-medium text-[#16202E] outline-none placeholder:text-slate-400 focus:border-[#2B4C7E]"
          />
        </label>
        <div className="flex gap-2" role="group" aria-label="Processing event filter">
          <button type="button" onClick={() => { setView("issues"); setPage(1); }} className={`rounded-lg border px-3 py-2 text-xs font-bold ${view === "issues" ? "border-[#2B4C7E] bg-[#EAF0F8] text-[#2B4C7E]" : "border-[#E1E5EB] bg-white text-[#5C6B7A]"}`}>Warnings &amp; errors ({issueCount})</button>
          <button type="button" onClick={() => { setView("all"); setPage(1); }} className={`rounded-lg border px-3 py-2 text-xs font-bold ${view === "all" ? "border-[#2B4C7E] bg-[#EAF0F8] text-[#2B4C7E]" : "border-[#E1E5EB] bg-white text-[#5C6B7A]"}`}>All events ({events.length})</button>
        </div>
      </div>

      {visibleEvents.length === 0 ? (
        <div className="rounded-xl border border-dashed border-[#E1E5EB] bg-slate-50 p-7 text-center text-sm font-medium text-[#5C6B7A]">
          No processing events match the current filter.
        </div>
      ) : (
        <div className="min-w-0 max-w-full overflow-x-auto rounded-xl border border-[#E1E5EB] bg-white shadow-3xs">
          <table className="min-w-[820px] w-full border-collapse text-left text-[13px]">
            <thead className="bg-[#F6F7FA] text-[10px] uppercase tracking-wider text-[#5C6B7A]">
              <tr className="border-b border-[#E1E5EB]">
                <th className="px-3.5 py-3 font-bold">Page</th>
                <th className="px-3.5 py-3 font-bold">Status</th>
                <th className="px-3.5 py-3 font-bold">Type</th>
                <th className="px-3.5 py-3 font-bold">Document</th>
                <th className="px-3.5 py-3 font-bold">Time</th>
                <th className="px-3.5 py-3 font-bold">Diagnostics</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#E1E5EB] text-[#16202E]">
              {visibleEvents.map((row, index) => {
                const pageNo = row.page_number;
                const isIssue = isProcessingIssue(row.status, row.error);
                return (
                  <tr key={`${pageNo ?? "unknown"}-${index}`} className="align-top hover:bg-slate-50/60">
                    <td className="px-3.5 py-3">
                      {typeof pageNo === "number" ? (
                        <button type="button" disabled={!onSelectPage} onClick={() => onSelectPage?.(pageNo, row.document_type || undefined)} className="rounded-md bg-[#EAF0F8] px-2.5 py-1 font-mono text-xs font-bold text-[#2B4C7E] transition-colors hover:bg-[#2B4C7E] hover:text-white disabled:cursor-wait disabled:opacity-60">Page {pageNo}</button>
                      ) : "-"}
                    </td>
                    <td className="px-3.5 py-3"><StatusBadge status={row.status ?? "unknown"} /></td>
                    <td className="px-3.5 py-3 text-[#5C6B7A]">{row.page_type ?? "-"}</td>
                    <td className="px-3.5 py-3 font-semibold">{row.document_type ?? "Unknown"}</td>
                    <td className="px-3.5 py-3 font-mono text-[11px] text-[#5C6B7A]">{formatSeconds(row.elapsed_seconds)}</td>
                    <td className="max-w-[360px] px-3.5 py-3">
                      <details>
                        <summary className={`cursor-pointer font-bold ${isIssue ? "text-[#AF3B2E]" : "text-[#2B4C7E]"}`}>{isIssue ? "View warning / error" : "View extracted fields"}</summary>
                        <div className="mt-2 space-y-2 rounded-lg bg-[#F6F7FA] p-3 text-xs text-[#5C6B7A]">
                          {row.error ? <p className="font-semibold text-[#AF3B2E]">{displayValue(row.error)}</p> : null}
                          <p><span className="font-bold text-[#16202E]">LLM document:</span> {formatLlmDocument(row.extracted_fields)}</p>
                          <p className="break-words"><span className="font-bold text-[#16202E]">Extracted fields:</span> {summarizePublicFields(row.extracted_fields)}</p>
                          {row.completed_at ? <p><span className="font-bold text-[#16202E]">Completed:</span> {row.completed_at}</p> : null}
                        </div>
                      </details>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {filteredEvents.length > PAGE_SIZE ? (
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-[#E1E5EB] pt-4">
          <button type="button" disabled={currentPage === 1} onClick={() => setPage((value) => Math.max(1, value - 1))} className="rounded-lg border border-[#E1E5EB] bg-white px-3 py-2 text-xs font-bold text-[#2B4C7E] disabled:cursor-not-allowed disabled:text-slate-400">← Previous</button>
          <span className="text-xs font-semibold text-[#5C6B7A]">Showing {(currentPage - 1) * PAGE_SIZE + 1}–{Math.min(currentPage * PAGE_SIZE, filteredEvents.length)} of {filteredEvents.length}</span>
          <button type="button" disabled={currentPage === pageCount} onClick={() => setPage((value) => Math.min(pageCount, value + 1))} className="rounded-lg border border-[#E1E5EB] bg-white px-3 py-2 text-xs font-bold text-[#2B4C7E] disabled:cursor-not-allowed disabled:text-slate-400">Next →</button>
        </div>
      ) : null}
    </section>
  );
}
