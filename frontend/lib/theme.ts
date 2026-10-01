export const THEME_STORAGE_KEY = "dmef_theme";

export const THEME_IDS = ["light", "dark", "harbor", "ember"] as const;

export type ThemeId = (typeof THEME_IDS)[number];

export const THEME_LABELS: Record<ThemeId, string> = {
  light: "Light",
  dark: "Dark",
  harbor: "Harbor",
  ember: "Ember",
};

export function isThemeId(value: string | null | undefined): value is ThemeId {
  return value === "light" || value === "dark" || value === "harbor" || value === "ember";
}

export function readStoredTheme(): ThemeId {
  if (typeof window === "undefined") return "light";
  try {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
    if (isThemeId(stored)) return stored;
  } catch {
    return "light";
  }
  return "light";
}

/** Apply theme to <html> and persist. Safe to call during hydration. */
export function applyTheme(theme: ThemeId): void {
  if (typeof document === "undefined") return;
  document.documentElement.dataset.theme = theme;
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    // Ignore quota / private-mode failures; in-memory theme still applies.
  }
}
