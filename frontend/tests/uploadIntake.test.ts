import assert from "node:assert/strict";
import test from "node:test";

import { UPLOAD_TABS } from "../components/upload/uploadTabOptions";
import { getSanitizedManifest } from "../components/upload/uploadUtils";

test("intake navigation exposes ZIP first and mapped verification second", () => {
  assert.deepEqual(UPLOAD_TABS, [
    { value: "zip", label: "ZIP Package Intake" },
    { value: "mapped", label: "Mapped Verification" },
  ]);
  assert.equal(UPLOAD_TABS.some((tab) => (tab.value as string) === "pdf"), false);
  assert.equal(UPLOAD_TABS.some((tab) => (tab.value as string) === "json"), false);
});

test("ZIP trusted data keeps valid JSON and accepts raw database text", () => {
  const manifest = '{"loan_id":"LN-001","documents":[]}';
  assert.equal(getSanitizedManifest(manifest), manifest);
  assert.equal(getSanitizedManifest("loan_id=LN-001\napplicant_name=Example"), "loan_id=LN-001\napplicant_name=Example");
});
