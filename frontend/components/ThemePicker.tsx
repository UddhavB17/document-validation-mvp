"use client";

import { useTheme } from "@/components/ThemeProvider";

export function ThemePicker({
  compact = false,
  showLabel = true,
}: {
  compact?: boolean;
  showLabel?: boolean;
}) {
  const { theme, setTheme, themes } = useTheme();

  return (
    <div className={`theme-picker${compact ? " theme-picker--compact" : ""}`}>
      {showLabel ? (
        <span className="theme-picker__label" id="theme-picker-label">
          Theme
        </span>
      ) : null}
      <div
        className="theme-picker__options"
        role="radiogroup"
        aria-labelledby={showLabel ? "theme-picker-label" : undefined}
        aria-label={showLabel ? undefined : "Theme"}
      >
        {themes.map((option) => {
          const active = theme === option.id;
          return (
            <button
              key={option.id}
              type="button"
              role="radio"
              aria-checked={active}
              className={`theme-picker__option${active ? " is-active" : ""}`}
              data-theme-swatch={option.id}
              title={option.label}
              onClick={() => setTheme(option.id)}
            >
              <span className="theme-picker__swatch" aria-hidden="true" />
              <span className="theme-picker__name">{option.label}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
