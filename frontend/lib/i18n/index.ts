"use client";

import { useCallback, useEffect, useState } from "react";

import { en } from "./en";
import { hi } from "./hi";

export type Locale = "en" | "hi";
export type I18nKey = keyof typeof en;

export const LOCALE_STORAGE_KEY = "dmef_locale";
export const LOCALE_COOKIE = "dmef_locale";
const LOCALE_EVENT = "dmef:locale";

const STRINGS = { en, hi } as const;

function readStoredLocale(): Locale {
  if (typeof window === "undefined") {
    return "en";
  }
  try {
    const stored = window.localStorage.getItem(LOCALE_STORAGE_KEY);
    if (stored === "hi" || stored === "en") {
      return stored;
    }
    const cookie = document.cookie
      .split(";")
      .map((part) => part.trim())
      .find((part) => part.startsWith(`${LOCALE_COOKIE}=`));
    const cookieValue = cookie?.split("=").slice(1).join("=");
    if (cookieValue === "hi" || cookieValue === "en") {
      return cookieValue;
    }
  } catch {
    return "en";
  }
  return "en";
}

/** Look up an operations-facing string for the active locale. */
export function t(locale: Locale, key: I18nKey): string {
  return STRINGS[locale][key] ?? en[key];
}

/** Active locale, persisted to localStorage and a cookie so SSR picks it up. */
export function useLocale(): { locale: Locale; setLocale: (next: Locale) => void } {
  const [locale, setLocaleState] = useState<Locale>("en");

  useEffect(() => {
    setLocaleState(readStoredLocale());
    const sync = (event: Event) => {
      const next = (event as CustomEvent<Locale>).detail;
      setLocaleState(next === "en" || next === "hi" ? next : readStoredLocale());
    };
    window.addEventListener(LOCALE_EVENT, sync);
    window.addEventListener("storage", sync);
    return () => {
      window.removeEventListener(LOCALE_EVENT, sync);
      window.removeEventListener("storage", sync);
    };
  }, []);

  useEffect(() => {
    document.documentElement.lang = locale === "hi" ? "hi" : "en";
  }, [locale]);

  const setLocale = useCallback((next: Locale) => {
    setLocaleState(next);
    try {
      window.localStorage.setItem(LOCALE_STORAGE_KEY, next);
      document.cookie = `${LOCALE_COOKIE}=${next}; path=/; max-age=${60 * 60 * 24 * 365}; SameSite=Lax`;
    } catch {
      // Locale persistence is best-effort; the in-memory choice still applies.
    }
    window.dispatchEvent(new CustomEvent(LOCALE_EVENT, { detail: next }));
  }, []);

  return { locale, setLocale };
}
