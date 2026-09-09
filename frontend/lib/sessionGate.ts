import type { SessionStatus } from "./auth";

// Pure hydration-gate decisions for AppShell (unit-testable; see
// tests/sessionHydration.test.ts).
//
// Protected queries must not mount until the verified session has hydrated:
// mounting them while bearer state is still loading sends unauthenticated
// requests, and the resulting 401s delete a valid session via
// lib/api.ts handleUnauthorized.

/** Paths that render without an authenticated session. */
export function isPublicPath(pathname: string): boolean {
  return pathname === "/login";
}

/**
 * Whether protected page content (and its queries) may mount yet.
 * Public paths always render; protected paths render only once the
 * verified session reports authenticated.
 */
export function shouldRenderProtectedChildren(
  status: SessionStatus,
  pathname: string,
): boolean {
  if (isPublicPath(pathname)) {
    return true;
  }
  return status === "authenticated";
}

/**
 * Client-side backstop redirect for sessions middleware did not already
 * reroute (e.g. soft navigation landing on an invalid session).
 * Returns null while hydrating or when no redirect applies, so the gate
 * can never bounce between targets.
 */
export function sessionRedirectTarget(
  status: SessionStatus,
  pathname: string,
): "/login" | null {
  if (isPublicPath(pathname)) {
    return null;
  }
  return status === "unauthenticated" ? "/login" : null;
}
