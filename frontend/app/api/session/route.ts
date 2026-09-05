import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

const SESSION_COOKIE = "dmef_session";
const TOKEN_TTL_SECONDS = 12 * 60 * 60;

function sessionCookieOptions(request: NextRequest) {
  return {
    httpOnly: true as const,
    sameSite: "lax" as const,
    secure: request.nextUrl.protocol === "https:" || process.env.NODE_ENV === "production",
    path: "/",
    maxAge: TOKEN_TTL_SECONDS,
  };
}

/** Decode the role claim from a JWT payload without verifying the signature. */
function roleFromToken(token: string): string | null {
  try {
    const segment = token.split(".")[1];
    if (!segment) {
      return null;
    }
    const payload = JSON.parse(
      Buffer.from(segment.replace(/-/g, "+").replace(/_/g, "/"), "base64").toString("utf-8"),
    ) as { role?: unknown };
    return typeof payload.role === "string" ? payload.role : null;
  } catch {
    return null;
  }
}

export async function GET(request: NextRequest) {
  const token = request.cookies.get(SESSION_COOKIE)?.value;
  if (!token) {
    return NextResponse.json({ detail: "No session" }, { status: 401 });
  }
  const role = roleFromToken(token);
  if (!role) {
    return NextResponse.json({ detail: "Invalid session" }, { status: 401 });
  }
  return NextResponse.json({ token, role });
}

export async function POST(request: NextRequest) {
  const body = (await request.json().catch(() => null)) as { token?: unknown } | null;
  const token = typeof body?.token === "string" ? body.token : "";
  if (!token || !roleFromToken(token)) {
    return NextResponse.json({ detail: "A valid token is required" }, { status: 400 });
  }
  const response = NextResponse.json({ status: "ok" });
  response.cookies.set(SESSION_COOKIE, token, sessionCookieOptions(request));
  return response;
}

export async function DELETE(request: NextRequest) {
  const response = NextResponse.json({ status: "ok" });
  response.cookies.set(SESSION_COOKIE, "", {
    ...sessionCookieOptions(request),
    maxAge: 0,
  });
  return response;
}
