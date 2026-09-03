import assert from "node:assert/strict";
import test from "node:test";

import { buildChecklistTaskId, buildExceptionTaskId, buildManualTaskId } from "../lib/decisionPolicy";
import { getReviewTaskState } from "../components/applications/review/sessionState";

test("manual, checklist, and exception task IDs are stable and distinct", () => {
  assert.equal(buildManualTaskId(7, "KYC"), "manual:7");
  assert.equal(buildChecklistTaskId(7, "KYC"), "checklist:7");
  assert.notEqual(buildManualTaskId(7, "KYC"), buildChecklistTaskId(7, "KYC"));
  assert.equal(buildExceptionTaskId({ id: 42, severity: "HIGH" }), "exception:42");
});

test("task state is safe and empty outside a browser session", () => {
  assert.equal(getReviewTaskState(1, "manual:7"), "Unchecked");
});
