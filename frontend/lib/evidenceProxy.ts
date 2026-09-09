/**
 * Authenticated-evidence proxy helpers (focused transport fix).
 *
 * Problem: `EvidenceViewer` / `EvidenceViewerModal` render
 * `<img src={api.sourcePageImageUrl(...)}>` and plain `<a href>` links to the
 * backend. Those subresource requests cannot attach the in-memory
 * `Authorization: Bearer` token, so logged-in evidence views get 401.
 *
 * Fix: the three URL helpers now point at the same-origin proxy
 * `/api/evidence/...` (see `app/api/evidence/[...path]/route.ts`). The
 * browser sends the `dmef_session` httpOnly cookie automatically with a
 * same-origin request; the proxy forwards it as
 * `Authorization: Bearer <token>` to the backend, which remains the sole
 * authorization authority. Tokens never appear in URLs.
 *
 * This module is intentionally pure (no Next.js imports) so the validation
 * and forwarding rules are unit-testable. The route handler is a thin
 * wrapper around it.
 */

/** Same-origin prefix the proxy is mounted at. Helpers build URLs under it. */
export const EVIDENCE_PROXY_PREFIX = "/api/evidence";

/** Session cookie name (same value as the session route handler uses). */
export const EVIDENCE_SESSION_COOKIE = "dmef_session";

/** Upper bound for a forwarded `highlight` value (backend treats it as text). */
export const EVIDENCE_HIGHLIGHT_MAX_LENGTH = 1000;

/** Backend render bounds for `dpi` (`routes/review.py`: ge=72, le=288). */
export const EVIDENCE_DPI_MIN = 72;
export const EVIDENCE_DPI_MAX = 288;

export type EvidenceKind = "source-pdf" | "source-page" | "ocr-json";

export interface EvidenceTarget {
  kind: EvidenceKind;
  applicationId: number;
  pageNumber?: number;
}

export interface ParsedEvidenceRequest extends EvidenceTarget {
  highlight?: string;
  dpi?: number;
}

export type EvidenceParseSuccess = { ok: true; value: ParsedEvidenceRequest };
export type EvidenceParseFailure = { ok: false; status: 400 | 404; detail: string };
export type EvidenceParseResult = EvidenceParseSuccess | EvidenceParseFailure;

function parsePositiveInt(raw: string | undefined): number | null {
  if (typeof raw !== "string" || !/^\d+$/.test(raw)) {
    return null;
  }
  const value = Number(raw);
  if (!Number.isSafeInteger(value) || value <= 0) {
    return null;
  }
  return value;
}

/**
 * Validate the catch-all segments after `/api/evidence/`. Only the mirrored
 * backend evidence paths are accepted:
 * - `review/applications/{positive-id}/source-pdf`
 * - `review/applications/{positive-id}/ocr-json`
 * - `review/applications/{positive-id}/source-page/{positive-page}`
 * Everything else (including traversal, extra segments, unknown leaves)
 * returns null so the route can answer 404 without touching the backend.
 */
export function parseEvidenceProxyPath(pathSegments: readonly string[]): EvidenceTarget | null {
  if (pathSegments.length < 4 || pathSegments.length > 5) {
    return null;
  }
  const [first, second, idRaw, leaf, extra] = pathSegments;
  if (first !== "review" || second !== "applications") {
    return null;
  }
  const applicationId = parsePositiveInt(idRaw);
  if (applicationId === null) {
    return null;
  }
  if (leaf === "source-pdf" || leaf === "ocr-json") {
    if (pathSegments.length !== 4) {
      return null;
    }
    return { kind: leaf, applicationId };
  }
  if (leaf === "source-page") {
    if (pathSegments.length !== 5) {
      return null;
    }
    const pageNumber = parsePositiveInt(extra);
    if (pageNumber === null) {
      return null;
    }
    return { kind: leaf, applicationId, pageNumber };
  }
  return null;
}

/**
 * Validate path segments plus the allowlisted query parameters.
 * - `source-page` accepts only `highlight` (length-capped) and `dpi`
 *   (integer within the backend render bounds). Unknown parameters are
 *   stripped, never forwarded. An invalid `dpi` is a 400.
 * - `source-pdf` / `ocr-json` accept no query parameters; extras are
 *   stripped silently so shared links cannot smuggle anything downstream.
 */
export function parseEvidenceProxyRequest(
  pathSegments: readonly string[],
  searchParams: URLSearchParams,
): EvidenceParseResult {
  const target = parseEvidenceProxyPath(pathSegments);
  if (!target) {
    return { ok: false, status: 404, detail: "Evidence not found" };
  }
  if (target.kind !== "source-page") {
    return { ok: true, value: target };
  }
  const highlightRaw = searchParams.get("highlight");
  const highlight =
    highlightRaw !== null && highlightRaw !== ""
      ? highlightRaw.slice(0, EVIDENCE_HIGHLIGHT_MAX_LENGTH)
      : undefined;
  const dpiRaw = searchParams.get("dpi");
  let dpi: number | undefined;
  if (dpiRaw !== null && dpiRaw !== "") {
    if (!/^\d+$/.test(dpiRaw)) {
      return { ok: false, status: 400, detail: "Invalid dpi" };
    }
    const parsed = Number(dpiRaw);
    if (!Number.isSafeInteger(parsed) || parsed < EVIDENCE_DPI_MIN || parsed > EVIDENCE_DPI_MAX) {
      return { ok: false, status: 400, detail: "Invalid dpi" };
    }
    dpi = parsed;
  }
  return { ok: true, value: { ...target, highlight, dpi } };
}

/** Backend path (with allowlisted query string) for a validated request. */
export function evidenceBackendPath(request: ParsedEvidenceRequest): string {
  const base =
    request.kind === "source-page"
      ? `/review/applications/${request.applicationId}/source-page/${request.pageNumber}`
      : `/review/applications/${request.applicationId}/${request.kind}`;
  if (request.kind !== "source-page") {
    return base;
  }
  const params = new URLSearchParams();
  if (request.highlight !== undefined) {
    params.set("highlight", request.highlight);
  }
  if (request.dpi !== undefined) {
    params.set("dpi", String(request.dpi));
  }
  const query = params.toString();
  return query ? `${base}?${query}` : base;
}

/**
 * Base URL for server-to-backend calls. `BACKEND_API_BASE_URL` wins when set
 * (server-only, never inlined into the client bundle); `API_BASE_URL` is
 * accepted as a server override alias; `NEXT_PUBLIC_API_BASE_URL` is the
 * build-time fallback. Mirrors `lib/sessionVerify.ts` precedence.
 */
export function resolveEvidenceBackendBase(explicit?: string): string {
  const raw =
    explicit ??
    process.env.BACKEND_API_BASE_URL ??
    process.env.API_BASE_URL ??
    process.env.NEXT_PUBLIC_API_BASE_URL ??
    "http://127.0.0.1:8000";
  return String(raw).replace(/\/+$/, "");
}

// --- Same-origin proxy URL builders (no backend host, no tokens) ---

export function evidenceProxyPdfUrl(applicationId: number, pageNumber?: number): string {
  const base = `${EVIDENCE_PROXY_PREFIX}/review/applications/${applicationId}/source-pdf`;
  // Fragments never reach the server; the PDF viewer jumps client-side.
  return typeof pageNumber === "number" && Number.isFinite(pageNumber)
    ? `${base}#page=${pageNumber}&zoom=page-width`
    : base;
}

export function evidenceProxyPageImageUrl(
  applicationId: number,
  pageNumber: number,
  highlight?: string,
): string {
  const base = `${EVIDENCE_PROXY_PREFIX}/review/applications/${applicationId}/source-page/${pageNumber}`;
  return highlight ? `${base}?highlight=${encodeURIComponent(highlight)}` : base;
}

export function evidenceProxyOcrJsonUrl(applicationId: number): string {
  return `${EVIDENCE_PROXY_PREFIX}/review/applications/${applicationId}/ocr-json`;
}

// --- Backend error mapping (backend stays the authorization authority) ---

export type EvidenceProxyErrorStatus = 401 | 403 | 404 | 502;

/**
 * Preserve auth/not-found semantics; every other backend failure (5xx,
 * redirect, unexpected status, unreachable) becomes a safe 502 so no backend
 * internals leak to the viewer.
 */
export function mapEvidenceBackendErrorStatus(backendStatus: number): EvidenceProxyErrorStatus {
  if (backendStatus === 401) {
    return 401;
  }
  if (backendStatus === 403) {
    return 403;
  }
  if (backendStatus === 404) {
    return 404;
  }
  return 502;
}

export function evidenceProxyErrorDetail(status: EvidenceProxyErrorStatus): string {
  switch (status) {
    case 401:
      return "Not authenticated";
    case 403:
      return "Forbidden";
    case 404:
      return "Evidence not found";
    default:
      return "Evidence backend unavailable";
  }
}
