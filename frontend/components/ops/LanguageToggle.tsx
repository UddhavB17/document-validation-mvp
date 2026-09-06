"use client";

import { Locale, t, useLocale } from "@/lib/i18n";

export function LanguageToggle({ compact = false }: { compact?: boolean }) {
  const { locale, setLocale } = useLocale();

  const switchTo = (next: Locale) => () => setLocale(next);

  return (
    <div
      role="group"
      aria-label={t(locale, "nav.language")}
      className={`flex items-center gap-1 rounded-lg border border-slate-200 bg-white ${compact ? "p-0.5" : "p-1"}`}
    >
      {(["en", "hi"] as const).map((option) => {
        const active = locale === option;
        return (
          <button
            key={option}
            type="button"
            onClick={switchTo(option)}
            aria-pressed={active}
            lang={option}
            className={`rounded-md font-bold transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-primary ${
              compact ? "px-2 py-1 text-[11px]" : "px-3 py-1.5 text-xs"
            } ${active ? "bg-brand-primary text-white" : "text-slate-600 hover:bg-slate-100"}`}
          >
            {option === "en" ? "EN" : "हिं"}
          </button>
        );
      })}
    </div>
  );
}
