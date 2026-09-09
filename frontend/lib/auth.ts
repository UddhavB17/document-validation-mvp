"use client";

import { createContext, createElement, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { loginRequest, setAuthTokenProvider } from "./api";
import { createTokenStore } from "./tokenStore";

export type SessionStatus = "loading" | "authenticated" | "unauthenticated";

export interface SessionValue {
  status: SessionStatus;
  token: string | null;
  role: string | null;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const SessionContext = createContext<SessionValue | null>(null);

// Module-level bearer holder. Writers assign it synchronously *before* the
// matching status state lands, so the api.ts getter is provider-ready ahead
// of (not one effect after) the `authenticated` render.
const tokenStore = createTokenStore();

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [token, setToken] = useState<string | null>(null);
  const [role, setRole] = useState<string | null>(null);
  const [status, setStatus] = useState<SessionStatus>("loading");

  useEffect(() => {
    // Registered once: the getter reads the synchronously-updated store, so
    // it is correct from the first paint even though child query effects
    // run before parent effects.
    setAuthTokenProvider(() => tokenStore.getToken());
    return () => {
      setAuthTokenProvider(null);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function loadSession() {
      // GET /api/session verifies the cookie against backend GET /auth/me,
      // so token/role here are verified (current DB role), never stale
      // JWT claims. Any failure lands unauthenticated (fail closed).
      try {
        const response = await fetch("/api/session");
        if (!response.ok) {
          throw new Error("No session");
        }
        const session = (await response.json()) as { token: string; role: string };
        if (cancelled) {
          return;
        }
        // Store-first ordering: the bearer getter serves this token before
        // (and regardless of) the `authenticated` render, so protected
        // queries mounted by that render always carry Authorization.
        tokenStore.setToken(session.token);
        setToken(session.token);
        setRole(session.role);
        setStatus("authenticated");
      } catch {
        if (!cancelled) {
          tokenStore.clearToken();
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
    // Same store-first ordering as hydration: provider ready before status.
    tokenStore.setToken(result.token);
    setToken(result.token);
    setRole(result.user.role);
    setStatus("authenticated");
  }, []);

  const logout = useCallback(async () => {
    try {
      await fetch("/api/session", { method: "DELETE" });
    } finally {
      tokenStore.clearToken();
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
