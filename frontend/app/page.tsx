import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { verifySessionToken } from "@/lib/sessionVerify";

const SESSION_COOKIE = "dmef_session";

/** Role redirect driven by verified backend state (GET /auth/me). */
export default async function HomePage() {
  const session = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!session) {
    redirect("/login");
  }
  const outcome = await verifySessionToken(session);
  if (outcome.status === "valid" && outcome.user) {
    redirect(outcome.user.role === "admin" ? "/admin" : "/ops");
  }
  // Invalid or unverifiable: fail closed to login. There is deliberately no
  // unverified claim fallback — verification is authoritative (middleware
  // answers 503 first when the backend itself is unreachable, so this page
  // is not the outage path).
  redirect("/login");
}
