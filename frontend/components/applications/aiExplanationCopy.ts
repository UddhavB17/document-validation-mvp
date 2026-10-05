import type { Anomaly, ApplicationReview } from "@/lib/api";
import { reviewerSummaryText } from "@/lib/llmSummaryParse";

export function buildAiExplanationBlock(
  data: ApplicationReview,
  anomaly?: Anomaly,
  pageNumber?: number,
): { body: string } | null {
  const body = reviewerSummaryText(data.application.llm_summary, {
    pageNumber,
    ruleId: anomaly?.rule_id ?? null,
  });
  return body ? { body } : null;
}
