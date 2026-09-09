import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import { verifySessionToken } from "../../../lib/sessionVerify";

const SESSION_COOKIE = "dmef_session";
const TOKEN_TTL_SECONDS = 12 * 60 * 60;

// Authenticated content must never sit in a shared cache: every response
// below carries private,no-store so roles and bearer tokens are not kept.
const NO_STORE = "private, no-store";

function sessionCookieOptions(request: NextRequest) {
  return {
    httpOnly: true as const,
    sameSite: "lax" as const,
    secure: request.nextUrl.protocol === "https:" || process.env.NODE_ENV === "production",
    path: "/",
    maxAge: TOKEN_TTL_SECONDS,
  };
}

function clearSessionCookie(request: NextRequest) {
  return {
    ...sessionCookieOptions(request),
    maxAge: 0,
  };
}

function jsonResponse(
  payload: unknown,
  status: number,
  request: NextRequest,
  clearCookie = false,
): NextResponse {
  const response = NextResponse.json(payload, {
    status,
    headers: { "Cache-Control": NO_STORE },
  });
  if (clearCookie) {
    response.cookies.set(SESSION_COOKIE, "", clearSessionCookie(request));
  }
  return response;
}

// Every response below is derived from backend verification (GET /auth/me),
// never from locally decoded JWT claims: forged/expired tokens and tokens
// of deactivated users are rejected, and the role always reflects the
// current database row rather than a stale token claim.
export async function GET(request: NextRequest) {
  const token = request.cookies.get(SESSION_COOKIE)?.value;
  if (!token) {
    return jsonResponse({ detail: "No session" }, 401, request);
  }
  const outcome = await verifySessionToken(token);
  if (outcome.status === "valid" && outcome.user) {
    // The bearer is returned so page code can call the backend directly
    // (existing bearer-call architecture; see lib/sessionVerify.ts note).
    return jsonResponse({ token, role: outcome.user.role }, 200, request);
  }
  if (outcome.status === "invalid") {
    return jsonResponse({ detail: "Invalid session" }, 401, request, true);
  }
  // Backend unreachable: fail closed without touching the cookie, so a
  // transient blip neither logs the user out nor admits them.
  return jsonResponse({ detail: "Authentication service unavailable" }, 503, request);
}

export async function POST(request: NextRequest) {
  const body = (await request.json().catch(() => null)) as { token?: unknown } | null;
  const token = typeof body?.token === "string" ? body.token : "";
  if (!token) {
    return jsonResponse({ detail: "A valid token is required" }, 400, request);
  }
  const outcome = await verifySessionToken(token);
  if (outcome.status === "valid" && outcome.user) {
    const response = jsonResponse({ status: "ok", role: outcome.user.role }, 200, request);
    response.cookies.set(SESSION_COOKIE, token, sessionCookieOptions(request));
    return response;
  }
  if (outcome.status === "invalid") {
    // Fail closed: never mint a session cookie for an unverifiable token.
    return jsonResponse({ detail: "Token verification failed" }, 401, request);
  }
  return jsonResponse({ detail: "Authentication service unavailable" }, 503, request);
}

export async function DELETE(request: NextRequest) {
  const response = jsonResponse({ status: "ok" }, 200, request);
  response.cookies.set(SESSION_COOKIE, "", clearSessionCookie(request));
  return response;
}
