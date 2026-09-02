import { Anomaly, ApplicationReview } from "@/lib/api";
import { getSeverityBadgeColor } from "@/components/applications/reviewUtils";

export function AiAuditInsights({
  data,
  onSelectEvidence,
}: {
  data: ApplicationReview;
  onSelectEvidence?: (anomaly: Anomaly, pageNumber: number) => void;
}) {
  const rawSummary = data.application.llm_summary;
  if (!rawSummary || typeof rawSummary !== "string" || !rawSummary.trim()) {
    return null;
  }

  interface PageSummary {
    page_number?: number | null;
    document_type?: string | null;
    rule_id?: string | null;
    summary_points?: string[];
    problem_description?: string;
  }

  interface LlmSummarySchema {
    overall_summary: string;
    final_recommendation: string;
    page_summaries?: PageSummary[];
  }

  let parsed: LlmSummarySchema | null = null;
  try {
    parsed = JSON.parse(rawSummary) as LlmSummarySchema;
  } catch {
    parsed = null;
  }

  if (!parsed) {
    return (
      <section className="bg-slate-50 border border-slate-200 rounded-2xl p-5 space-y-3">
        <div className="flex items-center gap-2 text-violet-750 font-bold">
          <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth="2.5" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904L9 21l-.813-5.096L3 15l5.096-.813L9 9l.813 5.187L15 15l-5.187.813zM18 10.5l-.5-3-.5 3-3 .5 3 .5.5 3 .5-3 3-.5-3-.5zM20.25 5.25l-.25-1.5-.25 1.5-1.5.25 1.5.25.25 1.5.25-1.5 1.5-.25-1.5-.25z" />
          </svg>
          <h2 className="text-base font-bold text-slate-800">AI Audit Insights</h2>
        </div>
        <p className="text-sm text-slate-700 whitespace-pre-line font-medium leading-relaxed">{rawSummary}</p>
      </section>
    );
  }

  const rec = String(parsed.final_recommendation || "MANUAL REVIEW").toUpperCase();
  let badgeColor = "border-amber-300 bg-amber-50 text-amber-800";
  if (rec === "APPROVE") {
    badgeColor = "border-emerald-300 bg-emerald-50 text-emerald-800";
  } else if (rec === "MANUAL REVIEW") {
    badgeColor = "border-rose-300 bg-rose-50 text-rose-800";
  }

  return (
    <section className="overflow-hidden border border-slate-200 bg-slate-50/30 rounded-2xl shadow-sm space-y-0">
      <div className="bg-gradient-to-r from-violet-600 via-indigo-600 to-blue-600 px-6 py-4 text-white flex items-center justify-between shadow-xs">
        <div className="flex items-center gap-3">
          <div className="rounded-lg bg-white/20 p-1.5 backdrop-blur-md">
            <svg className="w-5 h-5 text-amber-300 animate-pulse animate-duration-1000" fill="none" stroke="currentColor" strokeWidth="2.5" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904L9 21l-.813-5.096L3 15l5.096-.813L9 9l.813 5.187L15 15l-5.187.813zM18 10.5l-.5-3-.5 3-3 .5 3 .5.5 3 .5-3 3-.5-3-.5zM20.25 5.25l-.25-1.5-.25 1.5-1.5.25 1.5.25.25 1.5.25-1.5 1.5-.25-1.5-.25z" />
            </svg>
          </div>
          <div>
            <h2 className="text-base font-extrabold tracking-tight">AI Audit Insights</h2>
            <p className="text-[10px] text-indigo-100 font-medium tracking-wide">TOKEN-OPTIMIZED PAGE EXPLANATION</p>
          </div>
        </div>
        <div className={`px-3 py-1 rounded-full border text-[11px] font-bold uppercase ${badgeColor} bg-white shadow-sm flex items-center gap-1.5`}>
          <span className="w-1.5 h-1.5 rounded-full bg-current animate-ping" />
          {rec}
        </div>
      </div>

      <div className="p-6 space-y-6">
        <div className="bg-white border border-slate-150 rounded-xl p-5 shadow-xs space-y-2">
          <h3 className="text-[10px] font-extrabold uppercase tracking-widest text-slate-400">Executive Summary</h3>
          <p className="text-sm font-semibold text-slate-700 leading-relaxed italic">
            &ldquo;{parsed.overall_summary}&rdquo;
          </p>
        </div>

        {parsed.page_summaries && parsed.page_summaries.length > 0 ? (
          <div className="space-y-4">
            <h3 className="text-[10px] font-extrabold uppercase tracking-widest text-slate-400 mb-1">Page-by-Page Findings</h3>
            <div className="grid gap-4 md:grid-cols-1">
              {parsed.page_summaries.map((item, index) => {
                const hasPage = typeof item.page_number === "number" || (typeof item.page_number === "string" && item.page_number);
                const pageAnomalies = data.anomalies.filter(a =>
                  a.page_number === Number(item.page_number) ||
                  a.collapsed_page_numbers?.includes(Number(item.page_number))
                );
                const correspondingAnomaly =
                  pageAnomalies.find(a => item.rule_id && a.rule_id === item.rule_id) ??
                  pageAnomalies.find(a => item.problem_description && a.reason === item.problem_description) ??
                  (pageAnomalies.length === 1 ? pageAnomalies[0] : undefined);
                return (
                  <div key={index} className="bg-white border border-slate-200 rounded-xl shadow-xs overflow-hidden flex flex-col hover:border-violet-300 transition-colors duration-200">
                    <div className="bg-slate-50/50 border-b border-slate-150 px-4 py-2.5 flex items-center justify-between">
                      <span className="text-xs font-bold text-slate-700 flex items-center gap-2">
                        <span className="rounded bg-violet-100 text-violet-700 px-2 py-0.5 text-[9px] font-bold uppercase tracking-wider">
                          {hasPage ? `PAGE ${item.page_number}` : "GENERAL"}
                        </span>
                        {item.document_type || "Unknown Document"}
                      </span>
                      {hasPage && onSelectEvidence ? (
                        <button
                          type="button"
                          onClick={() => {
                            const anomalyToSelect = correspondingAnomaly || {
                              page_number: Number(item.page_number),
                              document_type: item.document_type,
                              rule_id: "AI_PAGE_REVIEW",
                              severity: "INFO",
                              reason: item.problem_description
                            };
                            onSelectEvidence(anomalyToSelect, Number(item.page_number));
                          }}
                          className="rounded-lg border border-blue-200 bg-blue-50 px-2.5 py-1 text-[10px] font-bold text-blue-700 hover:bg-blue-100 transition-colors"
                        >
                          View Page {item.page_number}
                        </button>
                      ) : null}
                    </div>

                    <div className="p-4 space-y-3">
                      {item.summary_points && item.summary_points.length > 0 ? (
                        <div className="space-y-1.5">
                          <div className="text-[9px] font-bold uppercase text-slate-400 tracking-wider">Page Content Summary</div>
                          <ul className="space-y-1 text-xs text-slate-600 font-medium">
                            {item.summary_points.map((pt, i) => (
                              <li key={i} className="flex items-start gap-2">
                                <span className="text-emerald-500 font-bold mt-0.5">•</span>
                                <span>{pt}</span>
                              </li>
                            ))}
                          </ul>
                        </div>
                      ) : null}

                      {item.problem_description ? (
                        <div className="rounded-lg bg-rose-50 border border-rose-100 p-3 text-xs">
                          <div className="flex gap-2">
                            <span className="text-rose-500 font-bold">⚠️</span>
                            <div>
                              <div className="font-bold text-rose-800 flex items-center gap-2">
                                <span>Anomaly Detected</span>
                                {correspondingAnomaly ? (
                                  <>
                                    <span className={`rounded px-1.5 py-0.5 text-[9px] font-extrabold uppercase tracking-wider animate-pulse animate-duration-1000 ${getSeverityBadgeColor(correspondingAnomaly.severity)}`}>
                                      {correspondingAnomaly.severity}
                                    </span>
                                    <span className="rounded bg-slate-100 text-slate-700 px-1.5 py-0.5 text-[9px] font-extrabold uppercase tracking-wider">
                                      {correspondingAnomaly.rule_id}
                                    </span>
                                  </>
                                ) : null}
                              </div>
                              <div className="mt-0.5 text-rose-750 font-medium leading-relaxed">{item.problem_description}</div>
                            </div>
                          </div>
                        </div>
                      ) : null}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        ) : null}
      </div>
    </section>
  );
}
