import { Anomaly, ApplicationReview } from "@/lib/api";
import { buildAiExplanationBlock } from "@/components/applications/aiExplanationCopy";
import { getSeverityBadgeColor } from "@/components/applications/reviewUtils";
import {
  parseLlmSummary,
  reviewerOverallSummaryText,
  reviewerSummaryText,
  type LlmSummary,
  type PageSummary,
} from "@/lib/llmSummaryParse";

export type { LlmSummary, PageSummary };
export { parseLlmSummary };

export function getAiExplanation(
  data: ApplicationReview,
  anomaly?: Anomaly,
  pageNumber?: number,
): string | null {
  return reviewerSummaryText(data.application.llm_summary, {
    pageNumber,
    ruleId: anomaly?.rule_id ?? null,
  });
}

export function AiExplanationDisclosure({
  data,
}: {
  data: ApplicationReview;
  anomaly?: Anomaly;
  pageNumber?: number;
}) {
  const block = buildAiExplanationBlock(data);
  if (!block) return null;

  return (
    <details className="rounded-xl border border-violet-200 bg-violet-50/40">
      <summary className="cursor-pointer list-none px-4 py-3 text-sm font-bold text-violet-900 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-violet-700">
        AI summary
      </summary>
      <div className="border-t border-violet-200 px-4 py-3 text-sm leading-relaxed text-violet-950">
        <p>{block.body}</p>
      </div>
    </details>
  );
}

export function AiAuditInsights({
  data,
  onSelectEvidence,
}: {
  data: ApplicationReview;
  onSelectEvidence?: (anomaly: Anomaly, pageNumber: number | null) => void;
}) {
  const rawSummary = data.application.llm_summary;
  if (!rawSummary || !rawSummary.trim()) return null;

  const parsed = parseLlmSummary(rawSummary);
  const overallText = reviewerOverallSummaryText(rawSummary);
  if (!overallText) return null;

  const pageSummaries = parsed?.page_summaries?.slice(0, 3) ?? [];
  const remainingPageSummaries = Math.max(0, (parsed?.page_summaries?.length ?? 0) - pageSummaries.length);

  return (
    <section aria-labelledby="ai-audit-insights-heading" className="rounded-2xl border border-violet-200 bg-violet-50/30">
      <details>
        <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-5 py-4 text-sm font-bold text-slate-900 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-violet-700">
          <span id="ai-audit-insights-heading">AI summary</span>
        </summary>

        <div className="space-y-4 border-t border-violet-200 px-5 py-4 text-sm leading-relaxed text-slate-700">
          <p>{overallText}</p>
          {parsed?.final_recommendation ? (
            <div className="flex flex-wrap items-center gap-2">
              <span
                className={`rounded border px-2 py-1 text-[10px] font-bold uppercase ${getSeverityBadgeColor(parsed.final_recommendation)}`}
              >
                {parsed.final_recommendation}
              </span>
            </div>
          ) : null}
          {pageSummaries.length > 0 ? (
            <div className="space-y-2">
              <div className="text-[10px] font-bold uppercase tracking-wider text-slate-500">Page notes</div>
              {pageSummaries.map((item, index) => {
                const pageNumber = typeof item.page_number === "number" ? item.page_number : undefined;
                const anomaly: Anomaly = {
                  page_number: pageNumber,
                  document_type: item.document_type,
                  rule_id: item.rule_id ?? "AI_PAGE_REVIEW",
                  severity: "INFO",
                  reason: item.problem_description ?? item.summary_points?.[0] ?? "AI page note",
                };
                return (
                  <div key={`${item.rule_id ?? "page"}-${item.page_number ?? index}`} className="rounded-lg border border-violet-100 bg-white/70 p-3">
                    <div className="flex items-center justify-between gap-3 font-semibold text-slate-800">
                      <span>
                        {pageNumber ? `Page ${pageNumber}` : "General note"}
                        {item.document_type ? ` · ${item.document_type}` : ""}
                      </span>
                      {pageNumber && onSelectEvidence ? (
                        <button
                          type="button"
                          onClick={() => onSelectEvidence(anomaly, pageNumber)}
                          className="rounded-md border border-violet-200 bg-white px-2 py-1 text-[10px] font-bold text-violet-800 hover:bg-violet-100 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-violet-700"
                        >
                          Review page
                        </button>
                      ) : null}
                    </div>
                    {item.problem_description ? <p className="mt-1 text-xs">{item.problem_description}</p> : null}
                    {item.summary_points?.length ? (
                      <p className="mt-1 text-xs">{item.summary_points.join(" ")}</p>
                    ) : null}
                  </div>
                );
              })}
              {remainingPageSummaries > 0 ? (
                <p className="text-xs font-semibold text-slate-500">
                  {remainingPageSummaries} more page note(s) in the saved review.
                </p>
              ) : null}
            </div>
          ) : null}
        </div>
      </details>
    </section>
  );
}
