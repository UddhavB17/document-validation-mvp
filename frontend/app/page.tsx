import { cookies } from "next/headers";
import { redirect } from "next/navigation";

const SESSION_COOKIE = "dmef_session";

/** Decode the role claim without verifying; the API verifies on every call. */
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

/** Role redirect: operations → /ops, admin → /admin. */
export default function HomePage() {
  const session = cookies().get(SESSION_COOKIE)?.value;
  redirect(roleFromToken(session ?? "") === "admin" ? "/admin" : "/ops");
}
