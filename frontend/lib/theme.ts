"use client";

import { createContext, createElement, useCallback, useContext, useEffect, useMemo, useState } from "react";

export type DeskTheme = "ledger" | "slate" | "ink";

export const THEME_STORAGE_KEY = "dmef_theme";
export const DEFAULT_THEME: DeskTheme = "ledger";

export const THEME_OPTIONS: Array<{
  id: DeskTheme;
  label: string;
  description: string;
}> = [
  {
    id: "ledger",
    label: "Ledger",
    description: "Warm paper + ink · locked product soul.",
  },
  {
    id: "slate",
    label: "Slate",
    description: "Cool neutral alternate · refined desk.",
  },
  {
    id: "ink",
    label: "Ink",
    description: "Dark desk · long ops sessions.",
  },
];

function isDeskTheme(value: string | null | undefined): value is DeskTheme {
  return value === "ledger" || value === "slate" || value === "ink";
}

export function readStoredTheme(): DeskTheme {
  if (typeof window === "undefined") {
    return DEFAULT_THEME;
  }
  try {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
    if (isDeskTheme(stored)) {
      return stored;
    }
  } catch {
    return DEFAULT_THEME;
  }
  return DEFAULT_THEME;
}

export function applyThemeToDocument(theme: DeskTheme): void {
  if (typeof document === "undefined") {
    return;
  }
  document.documentElement.dataset.theme = theme;
  document.documentElement.style.colorScheme = theme === "ink" ? "dark" : "light";
}

interface ThemeContextValue {
  theme: DeskTheme;
  setTheme: (next: DeskTheme) => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setThemeState] = useState<DeskTheme>(DEFAULT_THEME);

  useEffect(() => {
    const stored = readStoredTheme();
    setThemeState(stored);
    applyThemeToDocument(stored);
  }, []);

  const setTheme = useCallback((next: DeskTheme) => {
    setThemeState(next);
    applyThemeToDocument(next);
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, next);
    } catch {
      // Theme persistence is best-effort; in-memory choice still applies.
    }
  }, []);

  const value = useMemo(() => ({ theme, setTheme }), [theme, setTheme]);
  return createElement(ThemeContext.Provider, { value }, children);
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) {
    throw new Error("useTheme must be used within a ThemeProvider");
  }
  return ctx;
}
