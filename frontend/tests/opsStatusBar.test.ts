import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";

import { clampPercentage, statusProgressPercentage } from "../components/ops/opsUtils";
import { applicationStatusSchema, opsApplicationSchema } from "../lib/api";

const fixturesDir = join(process.cwd(), "tests", "fixtures");

function loadOpsPayload(): Record<string, unknown> {
  return JSON.parse(readFileSync(join(fixturesDir, "ops-application.json"), "utf-8")) as Record<string, unknown>;
}

test("nested status progress.percentage drives the header bar", () => {
  const parsed = applicationStatusSchema.parse({
    application_id: 7,
    status: "processing",
    progress: { stage: "processing_pages", percentage: 40, completed_pages: 4, total_pages: 10 },
    updated_at: "2026-09-05T00:00:00Z",
    job: { id: 3, status: "running", attempt: 1, failure_reason: null },
  });
  assert.equal(parsed.progress?.percentage, 40);
  assert.equal(parsed.progress?.stage, "processing_pages");
  assert.equal(statusProgressPercentage(parsed), 40);
  assert.equal(clampPercentage(statusProgressPercentage(parsed)), 40);
});

test("missing status progress yields no bar value so the page keeps its fallback", () => {
  const parsed = applicationStatusSchema.parse({ application_id: 7, status: "needs_review" });
  assert.equal(statusProgressPercentage(parsed), null);
  assert.equal(statusProgressPercentage(null), null);
  assert.equal(statusProgressPercentage(undefined), null);
});

test("ops schema rejects a sixth finding", () => {
  const raw = loadOpsPayload();
  const findings = raw["top_findings"] as unknown[];
  const first = findings[0];
  assert.ok(first);
  findings.push(first, first, first);
  assert.equal(findings.length, 6);
  assert.throws(() => opsApplicationSchema.parse(raw));
});

test("ops schema rejects an unknown checklist status", () => {
  const raw = loadOpsPayload();
  const checklist = raw["checklist"] as { rows: Array<{ status: string }> };
  const first = checklist.rows[0];
  assert.ok(first);
  first.status = "BOGUS";
  assert.throws(() => opsApplicationSchema.parse(raw));
});

test("ops schema rejects an unknown severity or finding code", () => {
  const badSeverity = loadOpsPayload();
  const badSeverityFindings = badSeverity["top_findings"] as Array<{ severity: string }>;
  const badSeverityFirst = badSeverityFindings[0];
  assert.ok(badSeverityFirst);
  badSeverityFirst.severity = "CRITICAL";
  assert.throws(() => opsApplicationSchema.parse(badSeverity));

  const badCode = loadOpsPayload();
  const badCodeFindings = badCode["top_findings"] as Array<{ code: string }>;
  const badCodeFirst = badCodeFindings[0];
  assert.ok(badCodeFirst);
  badCodeFirst.code = "NOT_A_CODE";
  assert.throws(() => opsApplicationSchema.parse(badCode));
});

test("legacy reviewer statuses map to the ops vocabulary and null names become empty", () => {
  const raw = loadOpsPayload();
  const parsed = opsApplicationSchema.parse({ ...raw, status: "CRITICAL", loan_id: null, applicant_name: null });
  assert.equal(parsed.status, "needs_review");
  assert.equal(parsed.loan_id, "");
  assert.equal(parsed.applicant_name, "");
  assert.equal(opsApplicationSchema.parse({ ...raw, status: "CLEAN" }).status, "clean");
  assert.equal(opsApplicationSchema.parse({ ...raw, status: "NEEDS_REVIEW" }).status, "needs_review");
});
