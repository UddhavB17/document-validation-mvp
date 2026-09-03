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
