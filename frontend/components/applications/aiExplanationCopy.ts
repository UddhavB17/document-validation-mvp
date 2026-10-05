import type { Anomaly, ApplicationReview } from "@/lib/api";

import { getAiExplanation, parseLlmSummary } from "@/components/applications/AiAuditInsights";

const HIGH_CONFIDENCE_HINTS = [
  "probably wrong",
  "may be fine",
  "looks like a real problem",
  "automatic check is probably",
] as const;

export function aiExplanationLeadsReview(explanation: string): boolean {
  const normalized = explanation.toLowerCase();
  return HIGH_CONFIDENCE_HINTS.some((hint) => normalized.includes(hint));
}

export function buildAiExplanationBlock(
  data: ApplicationReview,
  anomaly?: Anomaly,
  pageNumber?: number,
): { body: string; footnote: string | null } | null {
  const explanation = getAiExplanation(data, anomaly, pageNumber);
  if (!explanation) {
    return null;
  }
  const parsed = parseLlmSummary(data.application.llm_summary);
  const pageSummary = parsed?.page_summaries?.find((item) => {
    const pageMatches = pageNumber === undefined || item.page_number === pageNumber;
    const ruleMatches = !anomaly?.rule_id || !item.rule_id || item.rule_id === anomaly.rule_id;
    return pageMatches && ruleMatches;
  });
  const recommendation = parsed?.final_recommendation?.toLowerCase() ?? "";
  const leads =
    aiExplanationLeadsReview(explanation)
    || recommendation.includes("false positive")
    || recommendation.includes("dismiss");
  if (leads) {
    return {
      body: explanation,
      footnote: "Automated rule output is still saved below for audit.",
    };
  }
  if (pageSummary?.problem_description) {
    return {
      body: explanation,
      footnote: "Compare this note with the rule detail and source page before you decide.",
    };
  }
  return {
    body: explanation,
    footnote: "Use the rule detail and source page to confirm before you decide.",
  };
}
