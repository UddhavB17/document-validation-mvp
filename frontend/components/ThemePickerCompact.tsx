"use client";

import { DEFAULT_THEME, THEME_OPTIONS, useTheme, type DeskTheme } from "@/lib/theme";

export function ThemePickerCompact({ label = "Desk theme" }: { label?: string }) {
  const { theme, setTheme } = useTheme();

  return (
    <div className="app-shell__theme-picker" aria-label={label}>
      <span className="app-shell__nav-label">{label}</span>
      <div className="app-shell__theme-options" role="radiogroup" aria-label={label}>
        {THEME_OPTIONS.map((option) => {
          const selected = theme === option.id;
          return (
            <button
              key={option.id}
              type="button"
              role="radio"
              aria-checked={selected}
              title={option.description}
              className={`app-shell__theme-chip${selected ? " is-active" : ""}`}
              onClick={() => setTheme(option.id)}
            >
              {option.label}
              {option.id === DEFAULT_THEME ? " (default)" : ""}
            </button>
          );
        })}
      </div>
    </div>
  );
}
