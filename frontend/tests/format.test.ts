import assert from "node:assert/strict";
import test from "node:test";

import { asText, formatNumber, formatSeconds, statusTone } from "../lib/format";

test("asText uses the display fallback for empty values", () => {
  assert.equal(asText(null), "-");
  assert.equal(asText(undefined), "-");
  assert.equal(asText(""), "-");
  assert.equal(asText("ready"), "ready");
  assert.equal(asText({ count: 2 }), '{"count":2}');
});

test("formatters preserve the frontend display conventions", () => {
  assert.equal(formatNumber(1234567), "12,34,567");
  assert.equal(formatNumber("123"), "-");
  assert.equal(formatSeconds(1.5), "1.50s");
  assert.equal(formatSeconds(null), "-");
});

test("statusTone maps known statuses and falls back safely", () => {
  assert.equal(statusTone("CLEAN"), "text-emerald-700");
  assert.equal(statusTone("incomplete"), "text-red-700");
  assert.equal(statusTone("processing"), "text-amber-700");
  assert.equal(statusTone("unknown"), "text-slate-700");
});
