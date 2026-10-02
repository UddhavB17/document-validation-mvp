import assert from "node:assert/strict";
import test from "node:test";

import { formatWaitingSince } from "../lib/waiting";

test("formatWaitingSince renders compact waiting labels", () => {
  const now = Date.parse("2026-10-02T12:00:00.000Z");
  assert.equal(formatWaitingSince("2026-10-02T11:59:30.000Z", now), "<1m");
  assert.equal(formatWaitingSince("2026-10-02T11:06:00.000Z", now), "54m");
  assert.equal(formatWaitingSince("2026-10-02T09:19:00.000Z", now), "2h 41m");
  assert.equal(formatWaitingSince("2026-09-30T12:00:00.000Z", now), "2d");
  assert.equal(formatWaitingSince(null, now), "—");
  assert.equal(formatWaitingSince("not-a-date", now), "—");
});
