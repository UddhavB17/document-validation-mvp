"use client";

import { Locale, t, useLocale } from "@/lib/i18n";

export function LanguageToggle({ compact = false }: { compact?: boolean }) {
  const { locale, setLocale } = useLocale();

  const switchTo = (next: Locale) => () => setLocale(next);

  return (
    <div
      role="group"
      aria-label={t(locale, "nav.language")}
      className={`lang-toggle${compact ? " lang-toggle--compact" : ""}`}
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
            className={`lang-toggle__btn${active ? " is-active" : ""}`}
          >
            {option === "en" ? "EN" : "हिं"}
          </button>
        );
      })}
    </div>
  );
}
