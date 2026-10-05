import type { ApplicationReview } from "@/lib/api";
import { reviewerOverallSummaryText } from "@/lib/llmSummaryParse";

export function buildAiExplanationBlock(data: ApplicationReview): { body: string } | null {
  const body = reviewerOverallSummaryText(data.application.llm_summary);
  return body ? { body } : null;
}
