import assert from "node:assert/strict";
import test from "node:test";

import { withReadTimeout } from "../lib/requestTimeout";

test("read timeout preserves successful data and clears its timer", async () => {
  let signal: AbortSignal | undefined;
  assert.equal(await withReadTimeout(async (value) => { signal = value; return 42; }, 10), 42);
  await new Promise((resolve) => setTimeout(resolve, 20));
  assert.equal(signal?.aborted, false);
});

test("stalled fetch or body is bounded and its request is aborted", async () => {
  let signal: AbortSignal | undefined;
  await assert.rejects(withReadTimeout((value) => {
    signal = value;
    return new Promise(() => {});
  }, 5), { name: "TimeoutError", message: /Please retry/ });
  assert.equal(signal?.aborted, true);
});

test("read errors are preserved rather than disguised as timeouts", async () => {
  const error = new Error("Invalid response");
  await assert.rejects(withReadTimeout(async () => { throw error; }), (actual) => actual === error);
});
