import assert from "node:assert/strict";
import test from "node:test";

import {
  averagePageTime,
  formatLlmDocument,
  getSeverityBadgeColor,
  rejectionReasons,
  statusLabels,
  summarizeFields,
} from "../components/applications/reviewUtils.ts";

test("averagePageTime ignores pages without elapsed time", () => {
  assert.equal(averagePageTime([{ elapsed_seconds: 2 }, { elapsed_seconds: null }, { elapsed_seconds: 4 }] as never), 3);
  assert.equal(averagePageTime([]), 0);
});

test("summarizeFields hides private fields and truncates long output", () => {
  assert.equal(summarizeFields(undefined), "-");
  assert.equal(summarizeFields({ _internal: "hidden" }), '{"_internal":"hidden"}');
  assert.equal(summarizeFields({ name: "Asha", _internal: "hidden" }), '{"name":"Asha"}');

  const summary = summarizeFields({ note: "x".repeat(200) });
  assert.equal(summary.length, 160);
  assert.ok(summary.endsWith("..."));
});

test("formatLlmDocument handles structured classification confidence", () => {
  assert.equal(formatLlmDocument(undefined), "-");
  assert.equal(formatLlmDocument({ _structured_llm_classification: { document_type: "PAN", confidence: 0.936 } }), "PAN (94%)");
  assert.equal(formatLlmDocument({ _structured_llm_classification: { document_type: "Passport" } }), "Passport");
  assert.equal(formatLlmDocument({ _structured_llm_classification: { confidence: 0.9 } }), "-");
});

test("review display constants and severity colors remain stable", () => {
  assert.equal(statusLabels.match, "Match");
  assert.equal(rejectionReasons["Name mismatch"], "Name on submitted document does not match application records. Please verify and resubmit.");
  assert.equal(getSeverityBadgeColor("HIGH"), "bg-rose-100 text-rose-800 border-rose-200 border");
  assert.equal(getSeverityBadgeColor("LOW"), "bg-slate-100 text-slate-800 border-slate-200 border");
});
