import assert from "node:assert/strict";
import test from "node:test";

import {
  extractOverallSummaryFromJsonString,
  parseLlmSummary,
  reviewerOverallSummaryText,
  reviewerSummaryText,
  unwrapSummaryPayload,
} from "../lib/llmSummaryParse";

test("parses JSON llm_summary with missing final_recommendation", () => {
  const raw = JSON.stringify({
    overall_summary: "The loan file contains two name mismatches on bank pages.",
    page_summaries: [],
  });
  const parsed = parseLlmSummary(raw);
  assert.equal(parsed?.overall_summary, "The loan file contains two name mismatches on bank pages.");
  assert.equal(parsed?.final_recommendation, "MANUAL REVIEW");
});

test("unwraps double-encoded JSON", () => {
  const inner = JSON.stringify({ overall_summary: "Ready for manual review." });
  const raw = JSON.stringify(inner);
  assert.equal(extractOverallSummaryFromJsonString(raw), "Ready for manual review.");
  assert.deepEqual(unwrapSummaryPayload(raw), { overall_summary: "Ready for manual review." });
});

test("reviewerSummaryText never returns a JSON blob", () => {
  const raw = '{"overall_summary":"Plain English only.","page_summaries":[]}';
  const text = reviewerSummaryText(raw);
  assert.equal(text, "Plain English only.");
  assert.ok(!text?.startsWith("{"));
});

test("parses TOON-style overall_summary lines", () => {
  const raw = `overall_summary: Verification found one PAN mismatch.
final_recommendation: MANUAL REVIEW`;
  const parsed = parseLlmSummary(raw);
  assert.equal(parsed?.overall_summary, "Verification found one PAN mismatch.");
});

test("reviewerOverallSummaryText recovers from truncated JSON blobs", () => {
  const raw = '{"overall_summary": "The loan file contains high-severity PAN mismatches for';
  const text = reviewerOverallSummaryText(raw);
  assert.equal(text, "The loan file contains high-severity PAN mismatches for");
  assert.ok(!text?.includes("{"));
});

test("unwraps overall_summary stored as nested JSON string", () => {
  const inner = JSON.stringify({
    overall_summary: "Plain English executive summary.",
    page_summaries: [],
  });
  const raw = JSON.stringify({ overall_summary: inner, final_recommendation: "MANUAL REVIEW" });
  assert.equal(reviewerOverallSummaryText(raw), "Plain English executive summary.");
});
