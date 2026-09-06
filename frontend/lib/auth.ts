"use client";

import { createContext, createElement, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { loginRequest, setAuthTokenProvider } from "./api";

export type SessionStatus = "loading" | "authenticated" | "unauthenticated";

export interface SessionValue {
  status: SessionStatus;
  token: string | null;
  role: string | null;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

/** Decode the role claim from a JWT payload without verifying the signature. */
export function getRoleFromToken(token: string): string | null {
  try {
    const segment = token.split(".")[1];
    if (!segment) return null;
    const payload = JSON.parse(atob(segment.replace(/-/g, "+").replace(/_/g, "/")));
    const role = payload?.role;
    return typeof role === "string" ? role : null;
  } catch {
    return null;
  }
}

const SessionContext = createContext<SessionValue | null>(null);

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [token, setToken] = useState<string | null>(null);
  const [role, setRole] = useState<string | null>(null);
  const [status, setStatus] = useState<SessionStatus>("loading");

  useEffect(() => {
    // Re-register the getter whenever the token changes so api.ts always
    // sends the latest bearer value.
    setAuthTokenProvider(() => token);
    return () => {
      setAuthTokenProvider(null);
    };
  }, [token]);

  useEffect(() => {
    let cancelled = false;
    async function loadSession() {
      try {
        const response = await fetch("/api/session");
        if (!response.ok) {
          throw new Error("No session");
        }
        const session = (await response.json()) as { token: string; role: string };
        if (cancelled) {
          return;
        }
        setToken(session.token);
        setRole(session.role);
        setStatus("authenticated");
      } catch {
        if (!cancelled) {
          setToken(null);
          setRole(null);
          setStatus("unauthenticated");
        }
      }
    }
    void loadSession();
    return () => {
      cancelled = true;
    };
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const result = await loginRequest(email, password);
    const cookieResponse = await fetch("/api/session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token: result.token }),
    });
    if (!cookieResponse.ok) {
      throw new Error("Could not establish a session");
    }
    setToken(result.token);
    setRole(result.user.role);
    setStatus("authenticated");
  }, []);

  const logout = useCallback(async () => {
    try {
      await fetch("/api/session", { method: "DELETE" });
    } finally {
      setToken(null);
      setRole(null);
      setStatus("unauthenticated");
      window.location.assign("/login");
    }
  }, []);

  const value = useMemo(
    () => ({ status, token, role, login, logout }),
    [status, token, role, login, logout],
  );

  return createElement(SessionContext.Provider, { value }, children);
}

export function useSession(): SessionValue {
  const session = useContext(SessionContext);
  if (!session) {
    throw new Error("useSession must be used within a SessionProvider");
  }
  return session;
}
