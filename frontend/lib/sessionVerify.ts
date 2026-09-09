// Server-side session verification (used by the session route handler,
// middleware, and server components). The browser never sees the backend
// secret: verification forwards the bearer token to GET /auth/me and trusts
// only the backend's answer — never the unverified JWT role claim.
//
// NOTE on GET /api/session returning the bearer token to page code: that
// matches the existing architecture (lib/api.ts attaches the token as an
// `Authorization: Bearer …` header on every backend call, so page JavaScript
// must hold the token in memory). The httpOnly session cookie only protects
// the token at rest. This pass does not claim full XSS protection and does
// not rebuild that architecture.

export interface VerifiedSessionUser {
  id: number;
  email: string;
  display_name: string;
  role: string;
}

/** Roles the frontend treats as authenticated. Anything else fails closed. */
export const ALLOWED_SESSION_ROLES = ["admin", "operations"] as const;

export type VerifyStatus = "valid" | "invalid" | "unavailable";

export interface VerifyOutcome {
  status: VerifyStatus;
  /** Present only when status is "valid". Always the current DB role. */
  user: VerifiedSessionUser | null;
}

export interface VerifyOptions {
  fetchFn?: typeof fetch;
  /** Overrides resolveApiBaseUrl (tests, edge cases). */
  apiBaseUrl?: string;
  timeoutMs?: number;
}

/**
 * Base URL for server-to-backend calls. `BACKEND_API_BASE_URL` wins when
 * set (server-only, never inlined into the client bundle); `API_BASE_URL`
 * is accepted as a server override alias (same precedence as
 * `lib/evidenceProxy.ts`); `NEXT_PUBLIC_API_BASE_URL` is the build-time
 * fallback. No auth secret is involved: the backend verifies the forwarded
 * bearer token itself.
 */
export function resolveApiBaseUrl(explicit?: string): string {
  const raw =
    explicit ??
    process.env.BACKEND_API_BASE_URL ??
    process.env.API_BASE_URL ??
    process.env.NEXT_PUBLIC_API_BASE_URL ??
    "http://127.0.0.1:8000";
  return String(raw).replace(/\/+$/, "");
}

function parseVerifiedUser(payload: unknown): VerifiedSessionUser | null {
  if (typeof payload !== "object" || payload === null) {
    return null;
  }
  const record = payload as Record<string, unknown>;
  if (typeof record.id !== "number" || typeof record.role !== "string") {
    return null;
  }
  if (!(ALLOWED_SESSION_ROLES as readonly string[]).includes(record.role)) {
    // Unknown role: fail closed rather than admitting a session the
    // frontend cannot authorize (admin vs operations navigation).
    return null;
  }
  return {
    id: record.id,
    email: typeof record.email === "string" ? record.email : "",
    display_name: typeof record.display_name === "string" ? record.display_name : "",
    role: record.role,
  };
}

/**
 * Verify a bearer token against the backend (`GET /auth/me`, which reloads
 * the active user and current DB role). Never decodes the JWT locally.
 *
 * - "valid": backend accepted the token; `user.role` is the current DB role
 *   (restricted to admin/operations).
 * - "invalid": missing/blank token, expired, wrongly signed, unknown role,
 *   or the user is unknown/deactivated (backend 401/403 or an unparsable
 *   success payload).
 * - "unavailable": the backend could not be reached or errored otherwise;
 *   callers fail closed for auth decisions but must not treat this as proof
 *   the session is bad (no cookie wipe, no redirect loop fuel).
 */
export async function verifySessionToken(
  token: string | null | undefined,
  options: VerifyOptions = {},
): Promise<VerifyOutcome> {
  if (typeof token !== "string" || token.trim() === "") {
    return { status: "invalid", user: null };
  }
  const fetchFn = options.fetchFn ?? fetch;
  const url = `${resolveApiBaseUrl(options.apiBaseUrl)}/auth/me`;
  const timeoutMs = options.timeoutMs ?? 5000;
  const hasTimeout =
    typeof AbortSignal !== "undefined" && typeof AbortSignal.timeout === "function";
  try {
    const response = await fetchFn(url, {
      headers: { Authorization: `Bearer ${token}` },
      cache: "no-store",
      // The backend must not redirect auth verification; fail closed instead.
      redirect: "error",
      ...(hasTimeout ? { signal: AbortSignal.timeout(timeoutMs) } : {}),
    });
    if (response.status === 401 || response.status === 403) {
      return { status: "invalid", user: null };
    }
    if (!response.ok) {
      return { status: "unavailable", user: null };
    }
    const user = parseVerifiedUser(await response.json().catch(() => null));
    if (!user) {
      return { status: "invalid", user: null };
    }
    return { status: "valid", user };
  } catch {
    return { status: "unavailable", user: null };
  }
}
