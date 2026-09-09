import assert from "node:assert/strict";
import test from "node:test";

import { reviewItemSchema } from "../lib/api";
import { normalizeDocumentType } from "../lib/documentType";

test("review item schema accepts document type arrays from the API", () => {
  const parsed = reviewItemSchema.parse({ document_type: ["PAN", "Aadhaar"] });
  assert.deepEqual(parsed.document_type, ["PAN", "Aadhaar"]);
});

test("document type normalization produces safe reviewer-facing text", () => {
  assert.equal(normalizeDocumentType(["PAN", "", "Aadhaar"]), "PAN, Aadhaar");
  assert.equal(normalizeDocumentType("  Bank Statement  "), "Bank Statement");
  assert.equal(normalizeDocumentType(["", " "]), null);
});
