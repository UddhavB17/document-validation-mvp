"use client";

import { useEffect, useState } from "react";

import { LedgerStamp } from "@/components/ops/LedgerStamp";
import { useSession } from "@/lib/auth";
import { t, useLocale, type Locale } from "@/lib/i18n";
import { DEFAULT_THEME, THEME_OPTIONS, useTheme, type DeskTheme } from "@/lib/theme";

const LOCALE_OPTIONS: Array<{ id: Locale | "mr"; label: string }> = [
  { id: "en", label: "English" },
  { id: "hi", label: "हिन्दी" },
  { id: "mr", label: "मराठी" },
];

function ThemePreview({ theme }: { theme: DeskTheme }) {
  if (theme === "slate") {
    return (
      <div className="flex h-24 overflow-hidden rounded-md border border-[#D5DBE6]">
        <div className="w-1/3 bg-[#1A2332]" />
        <div className="flex flex-1 flex-col bg-[#EEF1F6] p-2">
          <div className="h-2 w-1/2 rounded bg-[#2B4C7E]/70" />
          <div className="mt-2 flex-1 rounded bg-white" />
        </div>
      </div>
    );
  }
  if (theme === "ink") {
    return (
      <div className="flex h-24 overflow-hidden rounded-md border border-[#3A342C]">
        <div className="w-1/3 bg-[#0C0B09]" />
        <div className="flex flex-1 flex-col bg-[#14120F] p-2">
          <div className="h-2 w-1/2 rounded bg-[#6B7CFF]/80" />
          <div className="mt-2 flex-1 rounded bg-[#1E1B17]" />
        </div>
      </div>
    );
  }
  return (
    <div className="flex h-24 overflow-hidden rounded-md border border-[#D6CCB8]">
      <div className="w-1/3 bg-[#12100E]" />
      <div className="flex flex-1 flex-col bg-[#EDE6D8] p-2">
        <div className="h-2 w-1/2 rounded bg-[#3648F0]/80" />
        <div className="mt-2 flex-1 rounded bg-[#FFFCF7]" />
      </div>
    </div>
  );
}

export default function OpsSettingsPage() {
  const { locale, setLocale } = useLocale();
  const { theme, setTheme } = useTheme();
  const session = useSession();
  const [draftTheme, setDraftTheme] = useState<DeskTheme>(theme);
  const [draftLocale, setDraftLocale] = useState<Locale | "mr">(locale);
  const [displayName, setDisplayName] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    setDraftTheme(theme);
  }, [theme]);

  useEffect(() => {
    setDraftLocale(locale);
  }, [locale]);

  useEffect(() => {
    if (session.displayName) {
      setDisplayName(session.displayName);
    }
  }, [session.displayName]);

  const reviewerName = session.displayName?.trim() || "Reviewer";
  const reviewerEmail = session.email ?? "—";
  const avatarLetter = reviewerName.charAt(0).toUpperCase() || "R";

  async function handleSave() {
    setSaving(true);
    setSaved(false);
    setTheme(draftTheme);
    if (draftLocale === "en" || draftLocale === "hi") {
      setLocale(draftLocale);
    }
    // Marathi is shown as a locale chip for the mock IA; until strings ship,
    // selecting it keeps English copy while still confirming save.
    await new Promise((resolve) => window.setTimeout(resolve, 250));
    setSaving(false);
    setSaved(true);
  }

  return (
    <div className="mx-auto max-w-[1180px] space-y-5 ledger-animate-in">
      <header className="flex flex-wrap items-end justify-between gap-4 border-b border-[color:var(--border)] pb-4">
        <div>
          <p className="ledger-kicker">{t(locale, "ops.settings.kicker")}</p>
          <h1 className="mt-1 font-display text-[40px] font-semibold tracking-[-0.035em] text-desk-ink">
            {t(locale, "ops.settings.title")}
          </h1>
          <p className="mt-1 max-w-xl text-sm text-desk-muted">{t(locale, "ops.settings.description")}</p>
        </div>
        <LedgerStamp tone="ink">
          {theme === DEFAULT_THEME
            ? t(locale, "ops.settings.ledgerDefault")
            : THEME_OPTIONS.find((item) => item.id === theme)?.label}
        </LedgerStamp>
      </header>

      <section className="ledger-surface p-5">
        <p className="ledger-kicker">{t(locale, "ops.settings.appearance")}</p>
        <h2 className="mt-1 font-display text-[28px] font-semibold text-desk-ink">
          {t(locale, "ops.settings.chooseDesk")}
        </h2>
        <div className="mt-5 grid gap-4 md:grid-cols-3">
          {THEME_OPTIONS.map((option) => {
            const selected = draftTheme === option.id;
            return (
              <button
                key={option.id}
                type="button"
                onClick={() => {
                  setDraftTheme(option.id);
                  setTheme(option.id);
                  setSaved(false);
                }}
                className={`rounded-desk border-2 bg-[color:var(--surface)] p-3 text-left transition ${
                  selected ? "border-[color:var(--ink)] shadow-lift" : "border-[color:var(--border)]"
                }`}
                aria-pressed={selected}
              >
                <div className="relative">
                  <ThemePreview theme={option.id} />
                  {option.id === DEFAULT_THEME ? (
                    <span className="absolute left-2 top-2">
                      <LedgerStamp tone="ink">{t(locale, "ops.settings.themeDefault")}</LedgerStamp>
                    </span>
                  ) : null}
                </div>
                <p className="mt-3 font-display text-lg font-semibold text-desk-ink">{option.label}</p>
                <p className="mt-1 text-xs text-desk-muted">{option.description}</p>
                <div className="mt-3">
                  <LedgerStamp tone={selected ? "ink" : "muted"}>
                    {selected ? t(locale, "ops.settings.themeActive") : t(locale, "ops.settings.themeAvailable")}
                  </LedgerStamp>
                </div>
              </button>
            );
          })}
        </div>
        <div className="mt-5 flex flex-wrap items-start gap-3 rounded-md border border-[color:var(--border)] bg-[color:var(--info-muted)] px-4 py-3">
          <LedgerStamp tone="electric">{t(locale, "ops.settings.policy")}</LedgerStamp>
          <p className="min-w-0 flex-1 text-sm text-desk-ink">{t(locale, "ops.settings.policyNote")}</p>
        </div>
      </section>

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="ledger-surface p-5">
          <p className="ledger-kicker">{t(locale, "ops.settings.profile")}</p>
          <h2 className="mt-1 font-display text-[24px] font-semibold text-desk-ink">
            {t(locale, "ops.settings.reviewer")}
          </h2>
          <div className="mt-4 flex items-center gap-3">
            <span className="grid h-12 w-12 place-items-center rounded-full bg-[color:var(--electric)] font-mono text-lg font-bold text-white">
              {avatarLetter}
            </span>
            <div>
              <p className="font-display text-lg font-semibold text-desk-ink">{reviewerName}</p>
              <p className="font-mono text-sm text-desk-indigo">{reviewerEmail}</p>
            </div>
          </div>
          <label className="mt-5 flex flex-col gap-1.5 text-sm font-bold text-desk-ink">
            {t(locale, "ops.settings.displayName")}
            <input
              className="ledger-input"
              value={displayName}
              onChange={(event) => {
                setDisplayName(event.target.value);
                setSaved(false);
              }}
              readOnly
              aria-readonly="true"
            />
          </label>
        </section>

        <section className="ledger-surface flex flex-col p-5">
          <p className="ledger-kicker">{t(locale, "ops.settings.language")}</p>
          <h2 className="mt-1 font-display text-[24px] font-semibold text-desk-ink">
            {t(locale, "ops.settings.language")}
          </h2>
          <div className="mt-4 flex flex-wrap gap-2">
            {LOCALE_OPTIONS.map((option) => (
              <button
                key={option.id}
                type="button"
                className={`ledger-filter-chip${draftLocale === option.id ? " is-active" : ""}`}
                aria-pressed={draftLocale === option.id}
                onClick={() => {
                  setDraftLocale(option.id);
                  setSaved(false);
                }}
              >
                {option.label}
              </button>
            ))}
          </div>
          <div className="mt-6 flex flex-wrap items-center gap-3">
            <button type="button" className="ledger-btn ledger-btn--ink" disabled={saving} onClick={() => void handleSave()}>
              {saving ? t(locale, "ops.settings.saving") : t(locale, "ops.settings.save")}
            </button>
            {saved ? <LedgerStamp tone="ok">{t(locale, "ops.settings.saved")}</LedgerStamp> : null}
          </div>
          <div className="mt-auto border-t border-[color:var(--border)] pt-4 text-xs text-desk-faint">
            <p className="font-bold uppercase tracking-[0.1em]">{t(locale, "ops.settings.notOnPage")}</p>
            <p className="mt-1">{t(locale, "ops.settings.cutList")}</p>
          </div>
        </section>
      </div>
    </div>
  );
}
