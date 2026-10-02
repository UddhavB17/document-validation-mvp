"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { ErrorMessage } from "@/components/Message";
import { LedgerStamp } from "@/components/ops/LedgerStamp";
import { useSession } from "@/lib/auth";
import { t, useLocale } from "@/lib/i18n";

export default function LoginPage() {
  const router = useRouter();
  const { login } = useSession();
  const { locale } = useLocale();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const dateLabel = new Date().toLocaleDateString(locale === "hi" ? "hi-IN" : "en-GB", {
    weekday: "long",
    day: "2-digit",
    month: "short",
    year: "numeric",
  });

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
    <main className="grid min-h-screen lg:grid-cols-[minmax(320px,.9fr)_minmax(0,1.1fr)]">
      <section className="relative flex flex-col justify-between overflow-hidden bg-[color:var(--sidebar-bg)] px-8 py-10 text-[color:var(--sidebar-text)] sm:px-12">
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-0 opacity-40"
          style={{
            background:
              "radial-gradient(circle at 20% 15%, rgba(54,72,240,.35), transparent 40%), radial-gradient(circle at 85% 85%, rgba(54,72,240,.2), transparent 35%)",
          }}
        />
        <div className="relative">
          <div className="flex items-center gap-3">
            <span className="grid h-10 w-10 place-items-center rounded-md bg-[color:var(--electric)] font-mono text-lg font-bold text-white">
              D
            </span>
            <div>
              <p className="text-base font-extrabold tracking-wide">DMEF</p>
              <p className="text-xs text-[color:var(--sidebar-muted)]">Document validation</p>
            </div>
          </div>
          <p className="ledger-kicker mt-12">{t(locale, "ops.login.kicker")}</p>
          <h1 className="mt-3 max-w-md font-display text-[40px] font-semibold leading-[1.1] tracking-[-0.035em]">
            {t(locale, "ops.login.brandTitle")}
          </h1>
          <p className="mt-4 max-w-md text-sm leading-relaxed text-[color:var(--sidebar-muted)]">
            {t(locale, "ops.login.brandBody")}
          </p>
        </div>
        <div className="relative space-y-3">
          <div className="flex flex-wrap gap-2">
            <LedgerStamp tone="electric">Worklist</LedgerStamp>
            <LedgerStamp tone="electric">Case review</LedgerStamp>
            <LedgerStamp tone="electric">Evidence wizard</LedgerStamp>
          </div>
          <p className="text-xs text-[color:var(--sidebar-muted)]">
            After sign-in · users land on <span className="font-mono">/ops</span> · admins on{" "}
            <span className="font-mono">/admin</span>
          </p>
        </div>
        <div
          aria-hidden="true"
          className="absolute inset-y-0 left-0 w-[5px] bg-[color:var(--electric)]"
        />
      </section>

      <section className="relative flex flex-col justify-center bg-[color:var(--paper)] px-6 py-12 sm:px-12">
        <div className="mx-auto w-full max-w-md">
          <form
            onSubmit={handleSubmit}
            className="ledger-surface relative overflow-hidden px-6 py-7 shadow-lift"
          >
            <div aria-hidden="true" className="absolute inset-y-0 left-0 w-1 bg-[color:var(--electric)]" />
            <p className="ledger-kicker">{t(locale, "ops.login.accountKicker")}</p>
            <h2 className="mt-2 font-display text-[34px] font-semibold tracking-[-0.03em] text-desk-ink">
              {t(locale, "ops.login.title")}
            </h2>
            <p className="mt-2 text-sm text-desk-muted">{t(locale, "ops.login.hint")}</p>

            <label className="mt-6 flex flex-col gap-1.5 text-sm font-bold text-desk-ink">
              {t(locale, "ops.login.email")}
              <input
                type="email"
                autoComplete="username"
                required
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                disabled={isSubmitting}
                className="ledger-input font-mono"
              />
            </label>
            <label className="mt-4 flex flex-col gap-1.5 text-sm font-bold text-desk-ink">
              {t(locale, "ops.login.password")}
              <input
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                disabled={isSubmitting}
                className="ledger-input"
              />
            </label>

            {error ? (
              <div className="mt-4">
                <ErrorMessage message={error} />
              </div>
            ) : null}

            <button type="submit" disabled={isSubmitting} className="ledger-btn ledger-btn--electric mt-6 w-full">
              {isSubmitting ? t(locale, "ops.login.submitting") : t(locale, "ops.login.submit")}
            </button>
            <p className="mt-3 text-center text-xs italic text-desk-faint">{t(locale, "ops.login.ledgerHint")}</p>
            <div className="mt-5 border-t border-[color:var(--border)] pt-4">
              <LedgerStamp tone="electric">Reviewer</LedgerStamp>
              <p className="mt-2 text-xs leading-relaxed text-desk-muted">{t(locale, "ops.login.routeNote")}</p>
            </div>
          </form>
        </div>
        <div className="pointer-events-none absolute inset-x-0 bottom-4 flex justify-between px-6 text-[11px] text-desk-faint sm:px-12">
          <span>DMEF · Document Matching Early Finder</span>
          <span className="font-mono uppercase tracking-[0.08em]">{dateLabel}</span>
        </div>
      </section>
    </main>
  );
}
