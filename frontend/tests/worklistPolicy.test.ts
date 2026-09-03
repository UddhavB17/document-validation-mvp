import assert from "node:assert/strict";
import test from "node:test";

import { classifyWorklistItem, getActionableReviewItems, matchesWorklistFilter } from "../lib/worklistPolicy";
import type { WorklistItem } from "../lib/api";

function item(overrides: Partial<WorklistItem>): WorklistItem {
  return {
    id: 1, loan_id: "L1", applicant_name: "A", product_type: "P", status: "needs_review",
    created_at: "2026-01-01T00:00:00Z", issues: 0, reviewer_issues: 0, business_issues: 0,
    processing_warnings: 0, pipeline_status: "completed", pipeline_retryable: false, ...overrides,
  };
}

test("retryable cases are recovery only and excluded from the actionable queue", () => {
  const recovery = item({ pipeline_status: "failed", pipeline_retryable: true });
  assert.equal(classifyWorklistItem(recovery), "recovery");
  assert.equal(matchesWorklistFilter(recovery, "review"), false);
  assert.equal(matchesWorklistFilter(recovery, "recovery"), true);
  assert.deepEqual(getActionableReviewItems([recovery]), []);
});

test("queued and processing cases are not actionable review", () => {
  const processing = item({ pipeline_status: "processing" });
  assert.equal(classifyWorklistItem(processing), "processing");
  assert.deepEqual(getActionableReviewItems([processing]), []);
});

test("not-started and unsupported inputs stay out of Review now/next", () => {
  const notStarted = item({ pipeline_status: "not_started" });
  const unsupported = item({ pipeline_status: "unsupported_input" });
  const failed = item({ pipeline_status: "failed", pipeline_retryable: false });
  assert.equal(classifyWorklistItem(notStarted), "processing");
  assert.equal(classifyWorklistItem(unsupported), "recovery");
  assert.equal(classifyWorklistItem(failed), "recovery");
  assert.equal(getActionableReviewItems([notStarted, unsupported, failed]).length, 0);
});

test("completed with warnings is actionable when the case is not closed", () => {
  const completedWithWarnings = item({ pipeline_status: "completed_with_warnings", status: "needs_review" });
  assert.equal(classifyWorklistItem(completedWithWarnings), "review");
  assert.deepEqual(getActionableReviewItems([completedWithWarnings]).map((entry) => entry.id), [1]);
});
