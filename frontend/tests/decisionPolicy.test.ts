import assert from "node:assert/strict";
import test from "node:test";

import {
  buildDecisionTasks,
  buildPersistedReviewerNote,
  evaluateDecisionPolicy,
  getDecisionProcessingState,
  taskNeedsEvidence,
} from "../lib/decisionPolicy";

const manualReviewItems = [
  { s_no: 11, description: "KYC details checked in system", reason: "Verify the system control" },
  { s_no: 27, description: "Guarantee deed", reason: "Verify physical execution" },
];

const checklistRows = [
  { s_no: 19, status: "MISSING", description: "Bank statement", pages: "-", document_types: "Bank Statement" },
  { s_no: 26, status: "NOT_CHECKED", description: "CERSAI", pages: "4", document_types: "CERSAI" },
];

test("processing gate distinguishes completed warnings from blocked states", () => {
  assert.equal(getDecisionProcessingState("completed_with_warnings"), "completed");
  assert.equal(getDecisionProcessingState("queued"), "blocked");
  assert.equal(getDecisionProcessingState("completed", true), "blocked");
});

test("page-backed tasks require evidence before they can be acknowledged", () => {
  assert.equal(taskNeedsEvidence({ pageNumber: 4 }), true);
  assert.equal(taskNeedsEvidence({ pageNumber: null }), false);
});

test("Accept requires completed processing, no high business exception, and all required checks", () => {
  const tasks = buildDecisionTasks({ manualReviewItems, checklistRows });
  const incomplete = evaluateDecisionPolicy({
    action: "ACCEPT",
    processingStatus: "completed",
    manualReviewItems,
    checklistRows,
    checkedTaskIds: new Set([tasks[0].id]),
    businessExceptions: [{ s_no: 27, severity: "HIGH", reason: "Guarantee deed mismatch" }],
    rationale: "Reviewed the available evidence.",
  });
  assert.equal(incomplete.allowed, false);
  assert.ok(incomplete.reasons.some((reason) => reason.includes("high-severity")));
  assert.ok(incomplete.reasons.some((reason) => reason.includes("remain incomplete")));

  const complete = evaluateDecisionPolicy({
    action: "ACCEPT",
    processingStatus: "completed_with_warnings",
    manualReviewItems,
    checklistRows,
    checkedTaskIds: new Set(tasks.filter((task) => task.required).map((task) => task.id)),
    businessExceptions: [],
    rationale: "Reviewed the available evidence.",
  });
  assert.equal(complete.allowed, true);
});

test("Override requires every high task and a rationale", () => {
  const tasks = buildDecisionTasks({
    manualReviewItems,
    businessExceptions: [{ id: 91, severity: "HIGH", reason: "Identity mismatch", page_number: 8 }],
  });
  const highTask = tasks.find((task) => task.severity === "HIGH");
  assert.ok(highTask);

  const unchecked = evaluateDecisionPolicy({
    action: "OVERRIDE",
    processingStatus: "completed",
    manualReviewItems,
    businessExceptions: [{ id: 91, severity: "HIGH", reason: "Identity mismatch", page_number: 8 }],
    rationale: "Override after reviewing the identity evidence.",
  });
  assert.equal(unchecked.allowed, false);

  const noRationale = evaluateDecisionPolicy({
    action: "OVERRIDE",
    processingStatus: "completed",
    businessExceptions: [],
    rationale: "",
  });
  assert.equal(noRationale.allowed, false);
  assert.ok(noRationale.reasons.some((reason) => reason.includes("non-empty rationale")));

  const checked = evaluateDecisionPolicy({
    action: "OVERRIDE",
    processingStatus: "completed",
    manualReviewItems,
    businessExceptions: [{ id: 91, severity: "HIGH", reason: "Identity mismatch", page_number: 8 }],
    checkedTaskIds: [highTask.id],
    rationale: "Override after reviewing the identity evidence.",
  });
  assert.equal(checked.allowed, true);
});

test("Request documents needs a reason and borrower-facing preview", () => {
  const invalid = evaluateDecisionPolicy({ action: "REQUEST_DOCS", processingStatus: "completed" });
  assert.equal(invalid.allowed, false);
  assert.equal(invalid.reasons.length, 2);

  const valid = evaluateDecisionPolicy({
    action: "REQUEST_DOCS",
    processingStatus: "completed",
    requestReasons: ["Document missing"],
    borrowerMessage: "Please upload the missing bank statement.",
  });
  assert.equal(valid.allowed, true);
});

test("every decision action denies non-complete processing statuses", () => {
  for (const processingStatus of [undefined, "unknown", "queued", "processing", "paused", "stale", "failed", "completed_partial"]) {
    for (const action of ["ACCEPT", "OVERRIDE", "REQUEST_DOCS"] as const) {
      const result = evaluateDecisionPolicy({
        action,
        processingStatus,
        rationale: "Reviewed",
        requestReasons: ["Document missing"],
        borrowerMessage: "Please upload the missing document.",
      });
      assert.equal(result.processingComplete, false, `${String(processingStatus)} should not be complete`);
      assert.equal(result.allowed, false, `${String(processingStatus)} should deny ${action}`);
      assert.ok(result.reasons.some((reason) => reason.toLowerCase().includes("processing")));
    }
  }
});

test("persisted reviewer note identifies local completion and remaining checks", () => {
  const tasks = buildDecisionTasks({ manualReviewItems, checklistRows });
  const note = buildPersistedReviewerNote("Accept after review.", tasks, [tasks[0].id]);
  assert.match(note, /Accept after review\./);
  assert.match(note, /Decision safety checks \(this session\): 1\/3/);
  assert.match(note, /CERSAI/);
});

test("persisted reviewer note names checked high-severity exception tasks", () => {
  const tasks = buildDecisionTasks({ businessExceptions: [{ id: 88, severity: "HIGH", reason: "Identity mismatch" }] });
  const note = buildPersistedReviewerNote("Override after review.", tasks, [tasks[0].id]);
  assert.match(note, /Checked high-severity review task\(s\):/);
  assert.match(note, /Identity mismatch/);
});
