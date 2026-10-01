import assert from "node:assert/strict";
import test from "node:test";

import { navigateCaseTab } from "../lib/caseTabNavigation";

test("case sections use local history; new-tab and other-page links remain normal", () => {
  const original = Object.getOwnPropertyDescriptor(globalThis, "window");
  const history: string[] = [];
  const location = new URL("http://localhost:3000/admin/applications/1");
  Object.defineProperty(globalThis, "window", { configurable: true, value: {
    location, history: { pushState: (_state: unknown, _title: string, href: string) => history.push(href) },
  } });
  let prevented = 0;
  const click = { button: 0, metaKey: false, ctrlKey: false, altKey: false, shiftKey: false,
    defaultPrevented: false, preventDefault: () => { prevented += 1; } };
  try {
    navigateCaseTab(click, "/admin/applications/1?tab=processing");
    assert.deepEqual(history, ["/admin/applications/1?tab=processing"]);
    assert.equal(prevented, 1);
    for (const change of [{ metaKey: true }, { ctrlKey: true }, { shiftKey: true }, { altKey: true }, { button: 1 }]) {
      navigateCaseTab({ ...click, ...change }, "/admin/applications/1?tab=files");
    }
    navigateCaseTab(click, "/admin/applications/2?tab=processing");
    navigateCaseTab(click, "https://example.com/admin/applications/1");
    assert.equal(prevented, 1);
    assert.equal(history.length, 1);
  } finally {
    if (original) Object.defineProperty(globalThis, "window", original);
    else Reflect.deleteProperty(globalThis, "window");
  }
});
