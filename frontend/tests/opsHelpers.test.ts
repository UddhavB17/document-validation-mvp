import assert from "node:assert/strict";
import test from "node:test";

import { bboxToStyle, normalizeSeverity } from "../components/ops/bbox";
import { formatPageList, MAX_FINDINGS, pickText, takeTopFindings } from "../components/ops/opsUtils";
import type { OpsFinding } from "../lib/api";
import { parseAnomalyEvidence } from "../lib/api";
import { t } from "../lib/i18n";

function finding(code: string): OpsFinding {
  return {
    code,
    severity: "HIGH",
    title: { en: `${code} en`, hi: `${code} hi` },
    detail: { en: "detail en", hi: "detail hi" },
    pages: [1],
    evidence: null,
  };
}

test("bbox converts to overlay percentages", () => {
  assert.deepEqual(bboxToStyle([0.12, 0.4, 0.55, 0.44]), {
    left: "12%",
    top: "40%",
    width: "43%",
    height: "4%",
  });
});

test("bbox clamps out-of-range coordinates", () => {
  const style = bboxToStyle([-0.5, 0.2, 1.5, 0.8]);
  assert.equal(style.left, "0%");
  assert.equal(style.width, "100%");
});

test("unknown severities fall back to low", () => {
  assert.equal(normalizeSeverity("critical"), "LOW");
  assert.equal(normalizeSeverity(null), "LOW");
});

test("findings are capped at five", () => {
  const many = ["A", "B", "C", "D", "E", "F", "G"].map(finding);
  assert.equal(takeTopFindings(many).length, 5);
  assert.equal(MAX_FINDINGS, 5);
  assert.deepEqual(
    takeTopFindings(many).map((item) => item.code),
    ["A", "B", "C", "D", "E"],
  );
});

test("page lists format for table cells", () => {
  assert.equal(formatPageList([1, 2]), "1, 2");
  assert.equal(formatPageList([]), "—");
});

test("locale switch swaps operations text", () => {  assert.equal(pickText({ en: "Summary", hi: "सारांश" }, "en"), "Summary");
  assert.equal(pickText({ en: "Summary", hi: "सारांश" }, "hi"), "सारांश");
  assert.notEqual(t("en", "ops.review.findings"), t("hi", "ops.review.findings"));
  assert.equal(t("en", "ops.review.status.clean"), "Clean");
});

test("evidence boxes narrow from object, text, or missing forms", () => {
  assert.deepEqual(parseAnomalyEvidence({ page: 2, bbox: [0, 0, 1, 1], text: "x" })?.page, 2);
  assert.deepEqual(
    parseAnomalyEvidence('{"page":2,"bbox":[0.1,0.2,0.3,0.4],"text":"y"}')?.bbox,
    [0.1, 0.2, 0.3, 0.4],
  );
  assert.equal(parseAnomalyEvidence(null), null);
  assert.equal(parseAnomalyEvidence("not-parseable"), null);
  assert.equal(parseAnomalyEvidence(undefined), null);
});
