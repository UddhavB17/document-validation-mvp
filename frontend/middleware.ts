import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import { verifySessionToken } from "./lib/sessionVerify";

const SESSION_COOKIE = "dmef_session";

// Authenticated navigation responses must never sit in a shared cache.
const NO_STORE = "private, no-store";

function redirectTo(request: NextRequest, pathname: string) {
  const url = request.nextUrl.clone();
  url.pathname = pathname;
  url.search = "";
  const response = NextResponse.redirect(url);
  response.headers.set("Cache-Control", NO_STORE);
  return response;
}

function clearSessionAndLogin(request: NextRequest) {
  // Fail closed without redirect loops: the cookie is wiped so the next
  // request takes the no-cookie path, and /login itself is never gated.
  const response = redirectTo(request, "/login");
  response.cookies.set(SESSION_COOKIE, "", { path: "/", maxAge: 0 });
  return response;
}

function serviceUnavailable() {
  // Fail closed when the backend cannot verify: admit nothing, but leave
  // the cookie intact (no proof the session is bad) so recovery needs no
  // re-login and no redirect loop is possible.
  return new NextResponse("Authentication service unavailable", {
    status: 503,
    headers: { "Cache-Control": NO_STORE },
  });
}

/**
 * Verified-session gate for every protected page navigation. The cookie
 * alone only proves a login once happened; each navigation re-verifies the
 * bearer against the backend (GET /auth/me), so fabricated, expired, or
 * deactivated sessions cannot enter the shell on a stale JWT claim, and
 * /admin additionally requires the current DB role to be admin.
 * API routes are passed through untouched: /api/session answers 401/503
 * JSON itself, and /api/evidence/* owns its 401/403/404/502 statuses — a
 * login HTML redirect here would break those contracts.
 */
export async function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  if (
    pathname === "/login" ||
    pathname.startsWith("/_next") ||
    pathname.startsWith("/api/")
  ) {
    return NextResponse.next();
  }
  const session = request.cookies.get(SESSION_COOKIE)?.value;
  if (!session) {
    return redirectTo(request, "/login");
  }
  const outcome = await verifySessionToken(session);
  if (outcome.status === "valid" && outcome.user) {
    if (
      (pathname === "/admin" || pathname.startsWith("/admin/")) &&
      outcome.user.role !== "admin"
    ) {
      return redirectTo(request, "/ops");
    }
    const response = NextResponse.next();
    response.headers.set("Cache-Control", NO_STORE);
    return response;
  }
  if (outcome.status === "invalid") {
    return clearSessionAndLogin(request);
  }
  return serviceUnavailable();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
