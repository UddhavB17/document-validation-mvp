import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

const SESSION_COOKIE = "dmef_session";

/** Decode the role claim without verifying; the API verifies on every call. */
function roleFromSession(session: string | undefined): string | null {
  if (!session) return null;
  try {
    const segment = session.split(".")[1];
    if (!segment) return null;
    const payload = JSON.parse(
      Buffer.from(segment.replace(/-/g, "+").replace(/_/g, "/"), "base64").toString("utf-8"),
    ) as { role?: unknown };
    return typeof payload.role === "string" ? payload.role : null;
  } catch {
    return null;
  }
}

/**
 * Redirect unauthenticated visits to /login (ws-d behavior, kept).
 * Role redirects (ws-e): operations users cannot open /admin/* and land on
 * /ops instead; admins may use both areas.
 */
export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  if (
    pathname === "/login" ||
    pathname.startsWith("/_next") ||
    pathname.startsWith("/api/session")
  ) {
    return NextResponse.next();
  }
  const session = request.cookies.get(SESSION_COOKIE)?.value;
  if (!session) {
    const loginUrl = request.nextUrl.clone();
    loginUrl.pathname = "/login";
    return NextResponse.redirect(loginUrl);
  }
  if (pathname === "/admin" || pathname.startsWith("/admin/")) {
    if (roleFromSession(session) !== "admin") {
      const opsUrl = request.nextUrl.clone();
      opsUrl.pathname = "/ops";
      return NextResponse.redirect(opsUrl);
    }
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
