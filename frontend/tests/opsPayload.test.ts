import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";

import { anomalySchema, opsApplicationSchema } from "../lib/api";

const fixturesDir = join(process.cwd(), "tests", "fixtures");

test("ops payload schema parses the section-5 fixture", () => {
  const raw = JSON.parse(readFileSync(join(fixturesDir, "ops-application.json"), "utf-8")) as unknown;
  const parsed = opsApplicationSchema.parse(raw);
  assert.equal(parsed.application_id, 12);
  assert.equal(parsed.status, "needs_review");
  assert.ok(parsed.top_findings.length <= 5);
  assert.equal(parsed.summary.en.length > 0, true);
  assert.equal(parsed.summary.hi.length > 0, true);
  assert.equal(parsed.pages_to_verify[0]?.page, 7);
  assert.equal(parsed.checklist.total, 4);
});

test("ops payload schema accepts a null evidence box", () => {
  const raw = JSON.parse(readFileSync(join(fixturesDir, "ops-application.json"), "utf-8")) as unknown as {
    top_findings: Array<{ evidence: { bbox: unknown } }>;
  };
  assert.equal(raw.top_findings[2]?.evidence.bbox, null);
  const parsed = opsApplicationSchema.parse(raw);
  assert.equal(parsed.top_findings[2]?.evidence?.bbox, null);
});

test("ops payload rejects technical internals", () => {
  const raw = JSON.parse(readFileSync(join(fixturesDir, "ops-application.json"), "utf-8")) as unknown;
  const parsed = opsApplicationSchema.parse(raw);
  for (const finding of parsed.top_findings) {
    assert.ok(!("rule_id" in finding));
  }
  assert.ok(!("ocr_text" in parsed));
});

test("anomaly schema parses the backend anomalies fixture including evidence boxes", () => {
  const raw = JSON.parse(readFileSync(join(fixturesDir, "anomalies.json"), "utf-8")) as unknown;
  const parsed = raw as Array<Record<string, unknown>>;
  assert.ok(parsed.length > 0);
  for (const item of parsed) {
    anomalySchema.parse(item);
  }
});
