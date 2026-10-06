/**
 * Parse applications.llm_summary for reviewer-facing text. Stored values may be
 * JSON (sometimes double-encoded), or legacy TOON-shaped prose from the model.
 */

export interface PageSummary {
  page_number?: number | null;
  document_type?: string | null;
  rule_id?: string | null;
  summary_points?: string[];
  problem_description?: string;
}

export interface LlmSummary {
  overall_summary: string;
  final_recommendation: string;
  page_summaries?: PageSummary[];
}

function isPageSummary(value: unknown): value is PageSummary {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  return (
    (!("page_number" in value)
      || value.page_number === undefined
      || value.page_number === null
      || typeof value.page_number === "number")
    && (!("document_type" in value)
      || value.document_type === undefined
      || value.document_type === null
      || typeof value.document_type === "string")
    && (!("rule_id" in value)
      || value.rule_id === undefined
      || value.rule_id === null
      || typeof value.rule_id === "string")
    && (!("summary_points" in value)
      || value.summary_points === undefined
      || (Array.isArray(value.summary_points)
        && value.summary_points.every((item) => typeof item === "string")))
    && (!("problem_description" in value)
      || value.problem_description === undefined
      || typeof value.problem_description === "string")
  );
}

function normalizePageSummaries(value: unknown): PageSummary[] | undefined {
  if (!Array.isArray(value)) {
    return undefined;
  }
  const pages = value.filter(isPageSummary);
  return pages.length > 0 ? pages : undefined;
}

function plainReviewerText(text: string | null | undefined, depth = 0): string | null {
  if (!text?.trim() || depth > 4) {
    return null;
  }
  let candidate = text.trim();
  if (looksLikeJsonSummaryDump(candidate)) {
    const extracted = extractOverallSummaryFromJsonString(candidate);
    if (extracted && extracted !== candidate) {
      return plainReviewerText(extracted, depth + 1);
    }
    return extracted;
  }
  if (candidate.startsWith("{") || candidate.startsWith("[")) {
    const extracted = extractOverallSummaryFromJsonString(candidate);
    if (extracted) {
      return plainReviewerText(extracted, depth + 1);
    }
    return null;
  }
  if (candidate.includes("\"overall_summary\"")) {
    const extracted = extractOverallSummaryFromJsonString(candidate);
    if (extracted) {
      return plainReviewerText(extracted, depth + 1);
    }
    return null;
  }
  return candidate;
}

function normalizeFromRecord(record: Record<string, unknown>): LlmSummary | null {
  const overall = record.overall_summary;
  if (typeof overall !== "string" || !overall.trim()) {
    return null;
  }
  const overallText = plainReviewerText(overall.trim());
  if (!overallText) {
    return null;
  }
  const recommendation = record.final_recommendation;
  const finalRecommendation =
    typeof recommendation === "string" && recommendation.trim()
      ? recommendation.trim()
      : "MANUAL REVIEW";
  return {
    overall_summary: overallText,
    final_recommendation: finalRecommendation,
    page_summaries: normalizePageSummaries(record.page_summaries),
  };
}

/** Unwrap JSON strings that were stored encoded more than once. */
export function unwrapSummaryPayload(raw: string): unknown {
  let current: unknown = raw.trim();
  for (let depth = 0; depth < 3; depth += 1) {
    if (typeof current !== "string") {
      break;
    }
    const text = current.trim();
    if (!text.startsWith("{") && !text.startsWith("[") && !text.startsWith("\"")) {
      break;
    }
    try {
      current = JSON.parse(text) as unknown;
    } catch {
      break;
    }
  }
  return current;
}

/** Pull overall_summary from a partial JSON string without rendering the blob. */
export function extractOverallSummaryFromJsonString(raw: string | null | undefined): string | null {
  if (!raw?.trim()) {
    return null;
  }
  const unwrapped = unwrapSummaryPayload(raw);
  if (typeof unwrapped === "object" && unwrapped !== null && !Array.isArray(unwrapped)) {
    const normalized = normalizeFromRecord(unwrapped as Record<string, unknown>);
    if (normalized) {
      return normalized.overall_summary;
    }
  }
  const trimmed = raw.trim();
  if (!trimmed.startsWith("{")) {
    return null;
  }
  const closed = trimmed.match(/"overall_summary"\s*:\s*"((?:[^"\\]|\\.)*)"/);
  const match = closed ?? trimmed.match(/"overall_summary"\s*:\s*"((?:[^"\\]|\\.)*)/);
  if (!match) {
    return null;
  }
  try {
    return JSON.parse(`"${match[1]}"`).trim();
  } catch {
    return match[1].replace(/\\"/g, '"').trim();
  }
}

function parseToonStyleSummary(raw: string): LlmSummary | null {
  const overallMatch = raw.match(/^overall_summary:\s*(.+?)(?:\r?\nfinal_recommendation:|\r?\npage_summaries|\s*$)/is);
  if (!overallMatch) {
    return null;
  }
  const overall = overallMatch[1].trim();
  if (!overall) {
    return null;
  }
  const recMatch = raw.match(/final_recommendation:\s*(.+?)(?:\r?\n|$)/i);
  const finalRecommendation = recMatch?.[1]?.trim() || "MANUAL REVIEW";
  return {
    overall_summary: overall,
    final_recommendation: finalRecommendation,
    page_summaries: undefined,
  };
}

export function parseLlmSummary(rawSummary: string | null | undefined): LlmSummary | null {
  if (!rawSummary?.trim()) {
    return null;
  }
  const trimmed = rawSummary.trim();
  const unwrapped = unwrapSummaryPayload(trimmed);
  if (typeof unwrapped === "object" && unwrapped !== null && !Array.isArray(unwrapped)) {
    const normalized = normalizeFromRecord(unwrapped as Record<string, unknown>);
    if (normalized) {
      return normalized;
    }
  }
  return parseToonStyleSummary(trimmed);
}

export function looksLikeJsonSummaryDump(text: string): boolean {
  const trimmed = text.trim();
  return trimmed.startsWith("{") && trimmed.includes("\"overall_summary\"");
}

/** File-level overall summary only — for overview and evidence modal AI boxes. */
export function reviewerOverallSummaryText(rawSummary: string | null | undefined): string | null {
  if (!rawSummary?.trim()) {
    return null;
  }
  const parsed = parseLlmSummary(rawSummary);
  if (parsed?.overall_summary) {
    return plainReviewerText(parsed.overall_summary);
  }
  const extracted = extractOverallSummaryFromJsonString(rawSummary);
  if (extracted) {
    return plainReviewerText(extracted);
  }
  const trimmed = rawSummary.trim();
  if (looksLikeJsonSummaryDump(trimmed) || trimmed.startsWith("{") || trimmed.startsWith("[")) {
    return null;
  }
  return plainReviewerText(trimmed);
}

export function reviewerSummaryText(
  rawSummary: string | null | undefined,
  options?: { pageNumber?: number; ruleId?: string | null },
): string | null {
  if (!rawSummary?.trim()) {
    return null;
  }
  const parsed = parseLlmSummary(rawSummary);
  if (parsed) {
    const pageNumber = options?.pageNumber;
    const ruleId = options?.ruleId;
    const pageSummary = parsed.page_summaries?.find((item) => {
      const pageMatches = pageNumber === undefined || item.page_number === pageNumber;
      const ruleMatches = !ruleId || !item.rule_id || item.rule_id === ruleId;
      return pageMatches && ruleMatches;
    });
    if (pageSummary?.problem_description?.trim()) {
      return plainReviewerText(pageSummary.problem_description.trim());
    }
    const pageDetails = pageSummary
      ? (pageSummary.summary_points ?? []).filter(Boolean).join(" ")
      : "";
    if (pageDetails.trim()) {
      return plainReviewerText(pageDetails.trim());
    }
    return plainReviewerText(parsed.overall_summary);
  }

  const overall = reviewerOverallSummaryText(rawSummary);
  if (overall) {
    return overall;
  }
  return null;
}
