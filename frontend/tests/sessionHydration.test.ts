import assert from "node:assert/strict";
import test from "node:test";

import { api, setAuthTokenProvider } from "../lib/api";
import {
  isPublicPath,
  sessionRedirectTarget,
  shouldRenderProtectedChildren,
} from "../lib/sessionGate";
import { createTokenStore } from "../lib/tokenStore";

// Regression coverage for the auth hydration race: after login, a hard
// navigation remounted SessionProvider while protected queries fired from
// child effects (which run before parent effects), sending no Authorization
// header. The resulting 401s deleted a valid session. The fix has two
// halves, both exercised here without a DOM:
// - the bearer getter reads a synchronously-updated store, so it is correct
//   before (not one effect after) the `authenticated` render;
// - protected children do not mount until the verified session reports
//   authenticated.

test("token store starts empty and tracks the latest bearer synchronously", () => {
  const store = createTokenStore();
  assert.equal(store.getToken(), null);
  store.setToken("tok-first");
  assert.equal(store.getToken(), "tok-first");
  store.setToken("tok-second");
  assert.equal(store.getToken(), "tok-second");
  store.clearToken();
  assert.equal(store.getToken(), null);
});

test("stores are independent instances", () => {
  const first = createTokenStore();
  const second = createTokenStore();
  first.setToken("tok-a");
  assert.equal(second.getToken(), null);
});

test("only /login is public", () => {
  assert.equal(isPublicPath("/login"), true);
  for (const path of ["/", "/ops", "/admin", "/admin/users", "/ops/applications/1"]) {
    assert.equal(isPublicPath(path), false, path);
  }
});

test("protected children mount only after verified authentication", () => {
  // Loading: hold the placeholder on every protected path so no query fires
  // without a bearer.
  for (const path of ["/", "/ops", "/admin/users"]) {
    assert.equal(shouldRenderProtectedChildren("loading", path), false, path);
    assert.equal(sessionRedirectTarget("loading", path), null, path);
  }
  // Authenticated: everything renders, no redirects.
  for (const path of ["/", "/ops", "/admin/users", "/login"]) {
    assert.equal(shouldRenderProtectedChildren("authenticated", path), true, path);
    assert.equal(sessionRedirectTarget("authenticated", path), null, path);
  }
  // Unauthenticated on protected paths: keep children unmounted and reroute
  // to login exactly once (null target everywhere else prevents loops).
  for (const path of ["/", "/ops", "/admin/users"]) {
    assert.equal(shouldRenderProtectedChildren("unauthenticated", path), false, path);
    assert.equal(sessionRedirectTarget("unauthenticated", path), "/login", path);
  }
  // Login page always renders and never redirects by itself.
  assert.equal(shouldRenderProtectedChildren("loading", "/login"), true);
  assert.equal(shouldRenderProtectedChildren("unauthenticated", "/login"), true);
  assert.equal(sessionRedirectTarget("unauthenticated", "/login"), null);
});

test("api bearer header follows the store with no effect round-trip", async () => {
  const realFetch = globalThis.fetch;
  const seen: Array<Record<string, string>> = [];
  globalThis.fetch = (async (_url: unknown, init: unknown) => {
    seen.push({ ...(((init as { headers?: Record<string, string> } | undefined)?.headers) ?? {}) });
    return { ok: true, status: 200, text: async () => '{"status":"ok"}' };
  }) as unknown as typeof fetch;
  try {
    // Wired exactly like SessionProvider: one getter over the store.
    const store = createTokenStore();
    setAuthTokenProvider(() => store.getToken());

    // Token assigned synchronously (as hydration/login now do before
    // exposing `authenticated`): the very next request carries it, with no
    // render or effect flush in between.
    store.setToken("tok-hydrated");
    await api.health();
    assert.equal(seen.length, 1);
    assert.equal(seen[0].Authorization, "Bearer tok-hydrated");

    // Clearing (logout/session loss) drops the header on the next request.
    store.clearToken();
    await api.health();
    assert.equal(seen.length, 2);
    assert.ok(!("Authorization" in seen[1]));
  } finally {
    setAuthTokenProvider(null);
    globalThis.fetch = realFetch;
  }
});
