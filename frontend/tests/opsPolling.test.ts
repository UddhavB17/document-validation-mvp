import assert from "node:assert/strict";
import test from "node:test";

import {
  getApplicationReviewPollInterval,
  getStatusPollInterval,
  isApplicationReviewPollingStatus,
} from "../lib/queries";

test("status poll runs while processing and stops when terminal", () => {
  assert.equal(getStatusPollInterval("processing"), 2000);
  assert.equal(getStatusPollInterval("uploaded"), 2000);
  assert.equal(getStatusPollInterval("ocr_completed"), 2000);
  assert.equal(getStatusPollInterval("needs_review"), false);
  assert.equal(getStatusPollInterval("clean"), false);
  assert.equal(getStatusPollInterval("failed"), false);
  assert.equal(getStatusPollInterval(undefined), false);
});

test("review payload is fetched once, never polled", () => {
  assert.equal(getApplicationReviewPollInterval(), false);
  assert.equal(isApplicationReviewPollingStatus("processing"), true);
  assert.equal(isApplicationReviewPollingStatus("clean"), false);
});
