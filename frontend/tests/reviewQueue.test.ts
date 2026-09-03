import assert from "node:assert/strict";
import test from "node:test";

import { getReviewQueueNeighbors } from "../lib/reviewQueue";

test("review queue uses canonical shape and computes neighbors", () => {
  const snapshot = { caseIds: [11, 22, 33], position: 1 };
  assert.deepEqual(getReviewQueueNeighbors(snapshot, 22), { position: 1, previousId: 11, nextId: 33 });
  assert.deepEqual(getReviewQueueNeighbors(snapshot, 11), { position: 0, previousId: null, nextId: 22 });
  assert.deepEqual(getReviewQueueNeighbors(snapshot, 99), { position: null, previousId: null, nextId: null });
});
