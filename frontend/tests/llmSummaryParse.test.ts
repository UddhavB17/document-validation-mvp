import assert from "node:assert/strict";
import test from "node:test";

import {
  extractOverallSummaryFromJsonString,
  parseLlmSummary,
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
