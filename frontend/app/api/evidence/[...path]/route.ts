import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import {
  EVIDENCE_SESSION_COOKIE,
  evidenceBackendPath,
  evidenceProxyErrorDetail,
  mapEvidenceBackendErrorStatus,
  parseEvidenceProxyRequest,
  resolveEvidenceBackendBase,
} from "@/lib/evidenceProxy";

// Authenticated content must never be statically optimized or cached.
export const dynamic = "force-dynamic";
export const revalidate = 0;

/**
 * Same-origin streaming proxy for the fixed evidence paths only:
 * - /review/applications/{id}/source-page/{page} (any authenticated role)
 * - /review/applications/{id}/source-pdf (backend enforces admin)
 * - /review/applications/{id}/ocr-json (backend enforces admin)
 *
 * The browser sends the `dmef_session` httpOnly cookie automatically with
 * this same-origin request (subresource `<img>`/`<a>` requests cannot attach
 * the in-memory bearer token). The cookie value is forwarded as
 * `Authorization: Bearer <token>`; the backend remains the sole
 * authorization authority — this route performs no local JWT verification
 * and puts no token in any URL. Only GET is exported, so other methods get
 * a 405 from the App Router.
 *
 * Middleware note: `middleware.ts` bypasses all `/api/*` routes, so this
 * route does not pass through middleware verification. That is compatible
 * by design — this handler performs its own authorization by forwarding
 * the session cookie as `Authorization: Bearer <token>` for real backend
 * authorization. A missing cookie answers 401 here (middleware redirects
 * page navigations to /login before that point).
 */

const NO_STORE = "private, no-store";

/** Content headers safe to pass through from the backend response. */
const FORWARDED_CONTENT_HEADERS = ["content-type", "content-disposition"] as const;

function errorResponse(status: 400 | 401 | 403 | 404 | 502, detail: string): NextResponse {
  return NextResponse.json({ detail }, { status, headers: { "Cache-Control": NO_STORE } });
}

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
): Promise<NextResponse> {
  const { path } = await params;
  const parsed = parseEvidenceProxyRequest(path ?? [], request.nextUrl.searchParams);
  if (!parsed.ok) {
    return errorResponse(parsed.status, parsed.detail);
  }

  const token = request.cookies.get(EVIDENCE_SESSION_COOKIE)?.value;
  if (!token) {
    return errorResponse(401, "Not authenticated");
  }

  const backendUrl = `${resolveEvidenceBackendBase()}${evidenceBackendPath(parsed.value)}`;
  let backendRes: Response;
  try {
    backendRes = await fetch(backendUrl, {
      headers: { Authorization: `Bearer ${token}` },
      cache: "no-store",
      // The backend must not redirect evidence fetches; fail closed instead.
      redirect: "error",
    });
  } catch {
    return errorResponse(502, evidenceProxyErrorDetail(502));
  }

  if (!backendRes.ok) {
    // Drain the body so the keep-alive socket can be reused, then answer
    // with a safe generic detail. Auth/not-found statuses are preserved.
    try {
      await backendRes.arrayBuffer();
    } catch {
      // Ignore drain errors; the status mapping below is what matters.
    }
    const status = mapEvidenceBackendErrorStatus(backendRes.status);
    return errorResponse(status, evidenceProxyErrorDetail(status));
  }

  const headers = new Headers();
  for (const name of FORWARDED_CONTENT_HEADERS) {
    const value = backendRes.headers.get(name);
    if (value) {
      headers.set(name, value);
    }
  }
  headers.set("Cache-Control", NO_STORE);
  headers.set("X-Content-Type-Options", "nosniff");
  // Stream the backend body straight through; the token stays in the
  // server-to-server request header and never enters a URL.
  return new NextResponse(backendRes.body, { status: 200, headers });
}
