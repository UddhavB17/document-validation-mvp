import assert from "node:assert/strict";
import test from "node:test";

import { NextRequest } from "next/server";

import { DELETE as sessionDelete, GET as sessionGet, POST as sessionPost } from "../app/api/session/route";
import { middleware } from "../middleware";

const NO_STORE = "private, no-store";
// Well-formed JWT shape, admin role claim, forged signature: proves routing
// decisions never trust local claims.
const INVENTED_TOKEN =
  "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiI5OTk5Iiwicm9sZSI6ImFkbWluIn0.forged-signature";

function backendOk(body: unknown) {
  return { status: 200, ok: true, json: async () => body };
}

function backendUnauthorized() {
  return { status: 401, ok: false, json: async () => ({ detail: "Invalid token" }) };
}

interface BackendCall {
  url: string;
  authorization: string | null;
}

/** Stub the server-to-backend fetch used by verifySessionToken. */
function installBackendStub() {
  const calls: BackendCall[] = [];
  let outage = false;
  const stub = (async (input: unknown, init: unknown) => {
    const headers =
      ((init as { headers?: Record<string, string> } | undefined)?.headers) ?? {};
    calls.push({ url: String(input), authorization: headers.Authorization ?? null });
    if (outage) {
      throw new Error("backend down");
    }
    const token = (headers.Authorization ?? "").replace(/^Bearer /, "");
    if (token === "tok-admin") {
      return backendOk({ id: 1, email: "a@example.com", display_name: "A", role: "admin" });
    }
    if (token === "tok-ops") {
      return backendOk({ id: 2, email: "o@example.com", display_name: "O", role: "operations" });
    }
    return backendUnauthorized();
  }) as unknown as typeof fetch;
  const realFetch = globalThis.fetch;
  globalThis.fetch = stub;
  return {
    calls,
    setOutage(value: boolean) {
      outage = value;
    },
    restore() {
      globalThis.fetch = realFetch;
    },
  };
}

function request(path: string, cookie?: string) {
  return new NextRequest(`http://localhost:3000${path}`, {
    headers: cookie ? { cookie: `dmef_session=${cookie}` } : {},
  });
}

function postSessionRequest(body: unknown) {
  return new NextRequest("http://localhost:3000/api/session", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

function isCookieWipe(setCookie: string | null) {
  return (
    setCookie !== null && setCookie.includes("dmef_session=") && setCookie.includes("Max-Age=0")
  );
}

// Backend env is pinned so routing tests never depend on ambient config.
let backend: ReturnType<typeof installBackendStub>;
const savedEnv = { ...process.env };

test.before(() => {
  process.env.BACKEND_API_BASE_URL = "http://backend.test";
  delete process.env.API_BASE_URL;
  delete process.env.NEXT_PUBLIC_API_BASE_URL;
  backend = installBackendStub();
});

test.after(() => {
  backend.restore();
  for (const key of Object.keys(process.env)) {
    if (!(key in savedEnv)) {
      delete process.env[key];
    }
  }
  Object.assign(process.env, savedEnv);
});

test.beforeEach(() => {
  backend.setOutage(false);
  backend.calls.length = 0;
});

test("middleware sends cookie-less navigation to login without backend call", async () => {
  const response = await middleware(request("/ops"));
  assert.equal(response.status, 307);
  assert.ok(response.headers.get("location")?.endsWith("/login"));
  assert.equal(response.headers.get("Cache-Control"), NO_STORE);
  assert.equal(backend.calls.length, 0);
});

test("middleware wipes fabricated cookies and redirects to login", async () => {
  for (const path of ["/ops", "/admin", "/admin/users"]) {
    const response = await middleware(request(path, INVENTED_TOKEN));
    assert.equal(response.status, 307, path);
    assert.ok(response.headers.get("location")?.endsWith("/login"), path);
    assert.ok(isCookieWipe(response.headers.get("set-cookie")), path);
    assert.equal(response.headers.get("Cache-Control"), NO_STORE, path);
  }
});

test("middleware admits verified roles and gates admin by DB role", async () => {
  const opsOnOps = await middleware(request("/ops", "tok-ops"));
  assert.equal(opsOnOps.headers.get("x-middleware-next"), "1");
  assert.equal(opsOnOps.headers.get("Cache-Control"), NO_STORE);

  const opsOnAdmin = await middleware(request("/admin/users", "tok-ops"));
  assert.equal(opsOnAdmin.status, 307);
  assert.ok(opsOnAdmin.headers.get("location")?.endsWith("/ops"));

  const adminOnAdmin = await middleware(request("/admin/users", "tok-admin"));
  assert.equal(adminOnAdmin.headers.get("x-middleware-next"), "1");

  // The backend saw the forwarded bearer on the verification call.
  assert.ok(backend.calls.every((call) => call.url === "http://backend.test/auth/me"));
  assert.ok(
    backend.calls.some((call) => call.authorization === "Bearer tok-ops"),
    "expected tok-ops verification call",
  );
});

test("middleware answers 503 without wiping the cookie when backend is down", async () => {
  backend.setOutage(true);
  for (const path of ["/ops", "/admin"]) {
    const response = await middleware(request(path, "tok-ops"));
    assert.equal(response.status, 503, path);
    assert.equal(response.headers.get("set-cookie"), null, path);
    assert.equal(response.headers.get("Cache-Control"), NO_STORE, path);
  }
});

test("middleware passes API routes through so handlers own their status", async () => {
  const evidence = await middleware(
    request("/api/evidence/review/applications/1/source-page/1", INVENTED_TOKEN),
  );
  assert.equal(evidence.headers.get("x-middleware-next"), "1");

  const evidenceBare = await middleware(
    request("/api/evidence/review/applications/1/source-page/1"),
  );
  assert.equal(evidenceBare.headers.get("x-middleware-next"), "1");

  const session = await middleware(request("/api/session", INVENTED_TOKEN));
  assert.equal(session.headers.get("x-middleware-next"), "1");

  const login = await middleware(request("/login", INVENTED_TOKEN));
  assert.equal(login.headers.get("x-middleware-next"), "1");

  assert.equal(backend.calls.length, 0);
});

test("session GET rejects invented tokens and clears the cookie", async () => {
  const response = await sessionGet(request("/api/session", INVENTED_TOKEN));
  assert.equal(response.status, 401);
  assert.ok(isCookieWipe(response.headers.get("set-cookie")));
  assert.equal(response.headers.get("Cache-Control"), NO_STORE);
});

test("session GET returns the verified DB role for valid tokens", async () => {
  const response = await sessionGet(request("/api/session", "tok-ops"));
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { token: "tok-ops", role: "operations" });
  assert.equal(response.headers.get("set-cookie"), null);
  assert.equal(response.headers.get("Cache-Control"), NO_STORE);
});

test("session GET without cookie is 401 and sets nothing", async () => {
  const response = await sessionGet(request("/api/session"));
  assert.equal(response.status, 401);
  assert.equal(response.headers.get("set-cookie"), null);
  assert.equal(response.headers.get("Cache-Control"), NO_STORE);
});

test("session GET is 503 with cookie intact when backend is down", async () => {
  backend.setOutage(true);
  const response = await sessionGet(request("/api/session", "tok-ops"));
  assert.equal(response.status, 503);
  assert.equal(response.headers.get("set-cookie"), null);
  assert.equal(response.headers.get("Cache-Control"), NO_STORE);
});

test("session POST never mints cookies for invented tokens", async () => {
  const response = await sessionPost(postSessionRequest({ token: INVENTED_TOKEN }));
  assert.equal(response.status, 401);
  assert.equal(response.headers.get("set-cookie"), null);
  assert.equal(response.headers.get("Cache-Control"), NO_STORE);

  const missing = await sessionPost(postSessionRequest({}));
  assert.equal(missing.status, 400);
});

test("session POST mints a cookie only for verified tokens", async () => {
  const response = await sessionPost(postSessionRequest({ token: "tok-admin" }));
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { status: "ok", role: "admin" });
  const setCookie = response.headers.get("set-cookie");
  assert.ok(setCookie !== null && setCookie.includes("dmef_session=tok-admin"));
  assert.equal(response.headers.get("Cache-Control"), NO_STORE);
});

test("session POST is 503 without a cookie when backend is down", async () => {
  backend.setOutage(true);
  const response = await sessionPost(postSessionRequest({ token: "tok-ops" }));
  assert.equal(response.status, 503);
  assert.equal(response.headers.get("set-cookie"), null);
});

test("session DELETE clears the cookie", async () => {
  const response = await sessionDelete(request("/api/session", "tok-ops"));
  assert.equal(response.status, 200);
  assert.ok(isCookieWipe(response.headers.get("set-cookie")));
  assert.equal(response.headers.get("Cache-Control"), NO_STORE);
});
