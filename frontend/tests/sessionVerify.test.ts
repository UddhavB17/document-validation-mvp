import assert from "node:assert/strict";
import test from "node:test";

import { resolveApiBaseUrl, verifySessionToken } from "../lib/sessionVerify";

type CapturedCall = { url: unknown; init: { headers?: Record<string, string> } };

function stubFetch(outcome: { status: number; body: unknown } | Error, calls: CapturedCall[]) {
  return async (_url: unknown, _init: unknown): Promise<Response> => {
    calls.push({ url: _url, init: (_init ?? {}) as CapturedCall["init"] });
    if (outcome instanceof Error) {
      throw outcome;
    }
    return {
      status: outcome.status,
      ok: outcome.status >= 200 && outcome.status < 300,
      json: async () => outcome.body,
    } as unknown as Response;
  };
}

const BACKEND_USER = {
  id: 3,
  email: "user@example.com",
  display_name: "Reviewer",
  role: "user",
};

test("valid token returns the backend DB role and forwards the bearer", async () => {
  const calls: CapturedCall[] = [];
  const outcome = await verifySessionToken("good-token", {
    fetchFn: stubFetch({ status: 200, body: BACKEND_USER }, calls),
    apiBaseUrl: "https://api.example.test",
  });
  assert.equal(outcome.status, "valid");
  // The role comes from verified /auth/me, never from a JWT claim: even a
  // token carrying role=admin resolves to the current DB role.
  assert.equal(outcome.user?.role, "user");
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "https://api.example.test/auth/me");
  assert.equal(calls[0].init.headers?.Authorization, "Bearer good-token");
});

test("expired or forged tokens are invalid", async () => {
  for (const status of [401, 403]) {
    const calls: CapturedCall[] = [];
    const outcome = await verifySessionToken("stale-token", {
      fetchFn: stubFetch({ status, body: { detail: "Invalid token" } }, calls),
      apiBaseUrl: "https://api.example.test",
    });
    assert.equal(outcome.status, "invalid");
    assert.equal(outcome.user, null);
  }
});

test("blank tokens are invalid without calling the backend", async () => {
  for (const token of [null, undefined, "", "   "]) {
    const calls: CapturedCall[] = [];
    const outcome = await verifySessionToken(token, {
      fetchFn: stubFetch({ status: 200, body: BACKEND_USER }, calls),
      apiBaseUrl: "https://api.example.test",
    });
    assert.equal(outcome.status, "invalid");
    assert.equal(calls.length, 0);
  }
});

test("backend outage is unavailable, not invalid", async () => {
  const networkCalls: CapturedCall[] = [];
  const network = await verifySessionToken("good-token", {
    fetchFn: stubFetch(new Error("connection refused"), networkCalls),
    apiBaseUrl: "https://api.example.test",
  });
  assert.equal(network.status, "unavailable");

  const serverCalls: CapturedCall[] = [];
  const serverError = await verifySessionToken("good-token", {
    fetchFn: stubFetch({ status: 500, body: "boom" }, serverCalls),
    apiBaseUrl: "https://api.example.test",
  });
  assert.equal(serverError.status, "unavailable");
});

test("malformed success payloads are invalid", async () => {
  for (const body of [null, [], { id: "3", role: "admin" }, { id: 3 }]) {
    const calls: CapturedCall[] = [];
    const outcome = await verifySessionToken("good-token", {
      fetchFn: stubFetch({ status: 200, body }, calls),
      apiBaseUrl: "https://api.example.test",
    });
    assert.equal(outcome.status, "invalid");
    assert.equal(outcome.user, null);
  }
});

test("unknown roles fail closed even with backend 200", async () => {
  for (const role of ["superuser", "viewer", "", "ADMIN"]) {
    const calls: CapturedCall[] = [];
    const outcome = await verifySessionToken("good-token", {
      fetchFn: stubFetch({ status: 200, body: { ...BACKEND_USER, role } }, calls),
      apiBaseUrl: "https://api.example.test",
    });
    assert.equal(outcome.status, "invalid");
    assert.equal(outcome.user, null);
  }
  const calls: CapturedCall[] = [];
  const admin = await verifySessionToken("good-token", {
    fetchFn: stubFetch({ status: 200, body: { ...BACKEND_USER, role: "admin" } }, calls),
    apiBaseUrl: "https://api.example.test",
  });
  assert.equal(admin.status, "valid");
  assert.equal(admin.user?.role, "admin");
});

test("verification never follows backend redirects", async () => {
  const calls: CapturedCall[] = [];
  await verifySessionToken("good-token", {
    fetchFn: stubFetch({ status: 200, body: BACKEND_USER }, calls),
    apiBaseUrl: "https://api.example.test",
  });
  assert.equal(calls.length, 1);
  assert.equal((calls[0].init as Record<string, unknown>).redirect, "error");
});

test("resolveApiBaseUrl prefers explicit, BACKEND_, API_, NEXT_PUBLIC_, then default", () => {
  const savedBackend = process.env.BACKEND_API_BASE_URL;
  const savedAlias = process.env.API_BASE_URL;
  const savedPublic = process.env.NEXT_PUBLIC_API_BASE_URL;
  try {
    delete process.env.BACKEND_API_BASE_URL;
    delete process.env.API_BASE_URL;
    delete process.env.NEXT_PUBLIC_API_BASE_URL;
    assert.equal(resolveApiBaseUrl(), "http://127.0.0.1:8000");

    process.env.NEXT_PUBLIC_API_BASE_URL = "https://public.example.test/";
    assert.equal(resolveApiBaseUrl(), "https://public.example.test");

    process.env.API_BASE_URL = "https://alias.example.test/";
    assert.equal(resolveApiBaseUrl(), "https://alias.example.test");

    process.env.BACKEND_API_BASE_URL = "https://internal.example.test/";
    assert.equal(resolveApiBaseUrl(), "https://internal.example.test");

    assert.equal(resolveApiBaseUrl("https://explicit.example.test/"), "https://explicit.example.test");
  } finally {
    if (savedBackend === undefined) {
      delete process.env.BACKEND_API_BASE_URL;
    } else {
      process.env.BACKEND_API_BASE_URL = savedBackend;
    }
    if (savedAlias === undefined) {
      delete process.env.API_BASE_URL;
    } else {
      process.env.API_BASE_URL = savedAlias;
    }
    if (savedPublic === undefined) {
      delete process.env.NEXT_PUBLIC_API_BASE_URL;
    } else {
      process.env.NEXT_PUBLIC_API_BASE_URL = savedPublic;
    }
  }
});
