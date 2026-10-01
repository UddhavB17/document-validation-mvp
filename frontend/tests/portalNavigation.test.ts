import assert from "node:assert/strict";
import test from "node:test";

import { portalApplicationHref, portalViewFromSearch } from "../lib/portalNavigation";

test("portal navigation encodes report selection and preserves browser-addressable state", () => {
  assert.equal(portalViewFromSearch(new URLSearchParams("tab=action-needed&exception=ri_123")), "report");
  assert.equal(
    portalApplicationHref(3, "tab=action-needed&exception=ri_old", { view: "report", selectedKey: "ri_new" }),
    "/ops/applications/3?tab=action-needed&exception=ri_new",
  );
  assert.equal(
    portalApplicationHref(3, "tab=action-needed&exception=ri_new", { view: "reviewed" }),
    "/ops/applications/3?tab=reviewed",
  );
});

test("portal navigation returns to the application overview", () => {
  assert.equal(portalViewFromSearch(new URLSearchParams("tab=checklist")), "checklist");
  assert.equal(
    portalApplicationHref(3, "tab=action-needed&exception=ri_123", { view: "dashboard", selectedKey: null }),
    "/ops/applications/3",
  );
});
