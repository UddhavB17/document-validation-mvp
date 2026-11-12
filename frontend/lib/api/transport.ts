import { z } from "zod";

/** Shared authenticated HTTP and response-validation primitives. */
export const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

type AuthTokenProvider = () => string | null;
let authTokenProvider: AuthTokenProvider | null = null;

export function setAuthTokenProvider(provider: AuthTokenProvider | null): void {
  authTokenProvider = provider;
}

export function authHeaders(): Record<string, string> {
  const token = authTokenProvider?.() ?? null;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function handleUnauthorized(status: number): void {
  if (typeof window === "undefined" || status !== 401 || window.location.pathname === "/login") return;
  void fetch("/api/session", { method: "DELETE" }).finally(() => {
    window.location.assign("/login");
  });
}

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
  }
}

export async function parseApiResponse<T>(response: Response, schema: z.ZodType<T>): Promise<T> {
  const text = await response.text();
  let payload: unknown = {};
  try {
    payload = text ? JSON.parse(text) : {};
  } catch {
    throw new ApiError(text || "Backend returned a non-JSON response", response.status);
  }
  if (!response.ok) {
    handleUnauthorized(response.status);
    const detailPayload =
      typeof payload === "object" && payload !== null && "detail" in payload ? payload.detail : payload;
    const detail = typeof detailPayload === "string" ? detailPayload : JSON.stringify(detailPayload);
    throw new ApiError(detail || "Request failed", response.status);
  }
  return schema.parse(payload);
}

export async function getJsonResponse<T>(path: string, schema: z.ZodType<T>): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, { headers: { ...authHeaders() } });
  return parseApiResponse(response, schema);
}

export async function postJsonResponse<T>(path: string, body: unknown, schema: z.ZodType<T>): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(body),
  });
  return parseApiResponse(response, schema);
}

export async function patchJsonResponse<T>(path: string, body: unknown, schema: z.ZodType<T>): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(body),
  });
  return parseApiResponse(response, schema);
}

export async function deleteJsonResponse<T>(path: string, schema: z.ZodType<T>): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: "DELETE",
    headers: { ...authHeaders() },
  });
  return parseApiResponse(response, schema);
}
