import assert from "node:assert/strict";
import test from "node:test";

import { asText, formatSeconds } from "../lib/format";

test("asText uses the display fallback for empty values", () => {
  assert.equal(asText(null), "-");
  assert.equal(asText(undefined), "-");
  assert.equal(asText(""), "-");
  assert.equal(asText("ready"), "ready");
  assert.equal(asText({ count: 2 }), '{"count":2}');
});

test("formatters preserve the frontend display conventions", () => {
  assert.equal(formatSeconds(1.5), "1.50s");
  assert.equal(formatSeconds(null), "-");
});
