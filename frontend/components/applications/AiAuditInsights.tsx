import { Anomaly, ApplicationReview } from "@/lib/api";

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
