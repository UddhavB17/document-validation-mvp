"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { ErrorMessage } from "@/components/Message";
import { ThemePicker } from "@/components/ThemePicker";
import "@/components/review/reviewer.css";
import { useSession } from "@/lib/auth";

export default function LoginPage() {
  const router = useRouter();
  const { login } = useSession();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setIsSubmitting(true);
    try {
      await login(email.trim(), password);
      router.push("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign in failed");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <main className="reviewer login-page" style={{ minHeight: "100vh" }}>
      <div className="login-page__theme">
        <ThemePicker compact showLabel={false} />
      </div>
      <div className="reviewer__frame" style={{ maxWidth: 560, paddingTop: "4.5rem" }}>
        <p className="reviewer__kicker">DMEF</p>
        <h1 className="reviewer__title">Sign in to review loan files</h1>
        <p className="reviewer__lede">
          A calm workspace for checking exceptions, saving what you verified, and seeing who
          finished each file.
        </p>

        <form
          onSubmit={handleSubmit}
          style={{
            marginTop: "2rem",
            padding: "1.5rem",
            border: "1px solid var(--rv-line)",
            borderRadius: 20,
            background: "var(--rv-paper)",
            boxShadow: "0 12px 32px rgba(23, 32, 51, 0.06)",
            display: "grid",
            gap: "1rem",
          }}
        >
          <label style={{ display: "grid", gap: 6, fontSize: 14, fontWeight: 600 }}>
            Email
            <input
              type="email"
              autoComplete="username"
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              style={{
                border: "1px solid var(--rv-line)",
                borderRadius: 12,
                padding: "0.7rem 0.85rem",
                font: "inherit",
                background: "var(--surface-muted)",
                color: "var(--rv-ink)",
              }}
            />
          </label>
          <label style={{ display: "grid", gap: 6, fontSize: 14, fontWeight: 600 }}>
            Password
            <input
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              style={{
                border: "1px solid var(--rv-line)",
                borderRadius: 12,
                padding: "0.7rem 0.85rem",
                font: "inherit",
                background: "var(--surface-muted)",
                color: "var(--rv-ink)",
              }}
            />
          </label>
          {error ? <ErrorMessage message={error} /> : null}
          <button type="submit" className="reviewer-btn reviewer-btn--primary" disabled={isSubmitting}>
            {isSubmitting ? "Signing in..." : "Continue"}
          </button>
        </form>
      </div>
    </main>
  );
}
