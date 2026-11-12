import { evidenceProxyPageImageUrl } from "./evidenceProxy";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

type AuthHeaderProvider = () => Record<string, string>;

let authHeaderProvider: AuthHeaderProvider | null = null;

/** Register bearer headers for direct-backend evidence fallback (see fetchEvidenceImageBlob). */
export function setEvidenceAuthHeaderProvider(provider: AuthHeaderProvider | null) {
  authHeaderProvider = provider;
}

function backendPageImagePath(applicationId: number, pageNumber: number, highlight?: string, dpi?: number): string {
  const base = `/review/applications/${applicationId}/source-page/${pageNumber}`;
  const params = new URLSearchParams();
  if (highlight) params.set("highlight", highlight);
  if (dpi !== undefined) params.set("dpi", String(dpi));
  return params.size ? `${base}?${params.toString()}` : base;
}

/**
 * Load a rendered source page as a blob URL. Tries the same-origin evidence
 * proxy first (session cookie). If that returns 401, retries the backend
 * with the in-memory bearer token so images still load when API calls work.
 */
export async function fetchEvidenceImageBlob(
  applicationId: number,
  pageNumber: number,
  highlight?: string,
  dpi?: number,
  signal?: AbortSignal,
): Promise<string> {
  const proxyUrl = evidenceProxyPageImageUrl(applicationId, pageNumber, highlight, dpi);
  let response = await fetch(proxyUrl, { credentials: "same-origin", signal });
  if (response.status === 401 && authHeaderProvider) {
    const backendUrl = `${API_BASE_URL.replace(/\/+$/, "")}${backendPageImagePath(
      applicationId,
      pageNumber,
      highlight,
      dpi,
    )}`;
    response = await fetch(backendUrl, {
      headers: { ...authHeaderProvider() },
      signal,
    });
  }
  if (!response.ok) {
    throw new Error(`Evidence image unavailable (${response.status})`);
  }
  const blob = await response.blob();
  if (!blob.type.startsWith("image/")) {
    throw new Error("Evidence response was not an image");
  }
  return URL.createObjectURL(blob);
}
