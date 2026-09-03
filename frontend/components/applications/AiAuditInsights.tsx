import { Anomaly, ApplicationReview } from "@/lib/api";
import { getSeverityBadgeColor } from "@/components/applications/reviewUtils";

interface PageSummary {
  page_number?: number | null;
  document_type?: string | null;
  rule_id?: string | null;
  summary_points?: string[];
  problem_description?: string;
}

interface LlmSummary {
  overall_summary: string;
  final_recommendation: string;
  page_summaries?: PageSummary[];
}

function isPageSummary(value: unknown): value is PageSummary {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;

  return (!("page_number" in value) || value.page_number === undefined || value.page_number === null || typeof value.page_number === "number")
    && (!("document_type" in value) || value.document_type === undefined || value.document_type === null || typeof value.document_type === "string")
    && (!("rule_id" in value) || value.rule_id === undefined || value.rule_id === null || typeof value.rule_id === "string")
    && (!("summary_points" in value) || value.summary_points === undefined || (Array.isArray(value.summary_points) && value.summary_points.every((item) => typeof item === "string")))
    && (!("problem_description" in value) || value.problem_description === undefined || typeof value.problem_description === "string");
}

function isLlmSummary(value: unknown): value is LlmSummary {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  if (!("overall_summary" in value) || !("final_recommendation" in value)) return false;
  const pageSummaries = "page_summaries" in value ? value.page_summaries : undefined;
  return typeof value.overall_summary === "string"
    && typeof value.final_recommendation === "string"
    && (pageSummaries === undefined || (Array.isArray(pageSummaries) && pageSummaries.every(isPageSummary)));
}

export function parseLlmSummary(rawSummary: string | null | undefined): LlmSummary | null {
  if (!rawSummary || !rawSummary.trim()) return null;
  try {
    const payload: unknown = JSON.parse(rawSummary);
    return isLlmSummary(payload) ? payload : null;
  } catch {
    return null;
  }
}

function pageSummaryFor(
  parsed: LlmSummary,
  anomaly: Anomaly | undefined,
  pageNumber: number | undefined,
): PageSummary | undefined {
  return parsed.page_summaries?.find((item) => {
    const pageMatches = pageNumber === undefined || item.page_number === pageNumber;
    const ruleMatches = !anomaly?.rule_id || !item.rule_id || item.rule_id === anomaly.rule_id;
    return pageMatches && ruleMatches;
  });
}

export function getAiExplanation(
  data: ApplicationReview,
  anomaly?: Anomaly,
  pageNumber?: number,
): string | null {
  const rawSummary = data.application.llm_summary;
  if (!rawSummary || !rawSummary.trim()) return null;
  const parsed = parseLlmSummary(rawSummary);
  if (!parsed) return rawSummary.trim().slice(0, 1600);

  const pageSummary = pageSummaryFor(parsed, anomaly, pageNumber);
  const pageDetails = pageSummary
    ? [pageSummary.problem_description, ...(pageSummary.summary_points ?? [])].filter(Boolean).join(" ")
    : "";
  return (pageDetails || parsed.overall_summary).trim() || null;
}

export function AiExplanationDisclosure({
  data,
  anomaly,
  pageNumber,
}: {
  data: ApplicationReview;
  anomaly?: Anomaly;
  pageNumber?: number;
}) {
  const explanation = getAiExplanation(data, anomaly, pageNumber);
  if (!explanation) return null;

  return (
    <details className="rounded-xl border border-violet-200 bg-violet-50/40">
      <summary className="cursor-pointer list-none px-4 py-3 text-sm font-bold text-violet-900 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-violet-700">
        <span className="mr-2" aria-hidden="true">＋</span>
        AI explanation <span className="ml-2 text-[10px] font-semibold uppercase tracking-wider text-violet-700">Secondary context</span>
      </summary>
      <div className="border-t border-violet-200 px-4 py-3 text-xs leading-relaxed text-violet-950">
        <p>{explanation}</p>
        <p className="mt-2 font-semibold text-violet-800">Deterministic rule output remains the primary review basis.</p>
      </div>
    </details>
  );
}

export function AiAuditInsights({
  data,
  onSelectEvidence,
}: {
  data: ApplicationReview;
  onSelectEvidence?: (anomaly: Anomaly, pageNumber: number) => void;
}) {
  const rawSummary = data.application.llm_summary;
  if (!rawSummary || !rawSummary.trim()) return null;

  const parsed = parseLlmSummary(rawSummary);
  const pageSummaries = parsed?.page_summaries?.slice(0, 3) ?? [];
  const remainingPageSummaries = Math.max(0, (parsed?.page_summaries?.length ?? 0) - pageSummaries.length);

  return (
    <section aria-labelledby="ai-audit-insights-heading" className="rounded-2xl border border-violet-200 bg-violet-50/30">
      <details>
        <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-5 py-4 text-sm font-bold text-slate-900 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-violet-700">
          <span id="ai-audit-insights-heading">
            <span className="mr-2 text-violet-700" aria-hidden="true">✦</span>
            AI Audit Insights
          </span>
          <span className="text-[10px] font-semibold uppercase tracking-wider text-violet-700">Secondary context</span>
        </summary>

        <div className="space-y-4 border-t border-violet-200 px-5 py-4 text-xs leading-relaxed text-slate-700">
          {parsed ? (
            <>
              <div>
                <div className="mb-1 text-[10px] font-bold uppercase tracking-wider text-slate-500">Executive summary</div>
                <p>{parsed.overall_summary}</p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <span className={`rounded border px-2 py-1 text-[10px] font-bold uppercase ${getSeverityBadgeColor(parsed.final_recommendation)}`}>
                  {parsed.final_recommendation}
                </span>
                <span className="font-semibold text-slate-500">AI output does not change deterministic findings.</span>
              </div>
              {pageSummaries.length > 0 ? (
                <div className="space-y-2">
                  <div className="text-[10px] font-bold uppercase tracking-wider text-slate-500">Selected page notes</div>
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
                          <span>{pageNumber ? `Page ${pageNumber}` : "General note"}{item.document_type ? ` · ${item.document_type}` : ""}</span>
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
                        {item.problem_description ? <p className="mt-1">{item.problem_description}</p> : null}
                        {item.summary_points?.length ? <p className="mt-1">{item.summary_points.join(" ")}</p> : null}
                      </div>
                    );
                  })}
                  {remainingPageSummaries > 0 ? <p className="font-semibold text-slate-500">{remainingPageSummaries} additional AI page note(s) remain collapsed.</p> : null}
                </div>
              ) : null}
            </>
          ) : (
            <p className="whitespace-pre-line">{rawSummary.trim().slice(0, 1600)}</p>
          )}
          <p className="font-semibold text-violet-800">Use deterministic rule detail and source evidence for the review decision.</p>
        </div>
      </details>
    </section>
  );
}
