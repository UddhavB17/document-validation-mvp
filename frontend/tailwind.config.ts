import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          primary: "var(--electric)",
          accent: "var(--indigo)",
          surface: "var(--surface-muted)",
          border: "var(--border)",
        },
        desk: {
          paper: "var(--paper)",
          surface: "var(--surface)",
          ink: "var(--ink)",
          muted: "var(--text-muted)",
          faint: "var(--text-subtle)",
          line: "var(--border)",
          electric: "var(--electric)",
          indigo: "var(--indigo)",
          ok: "var(--success)",
          warn: "var(--warning)",
          danger: "var(--danger)",
          hero: "var(--hero-bg)",
        },
        severity: {
          high: "var(--danger)",
          medium: "var(--warning)",
          low: "var(--success)",
        },
      },
      fontFamily: {
        sans: ["var(--font-sans)", "Inter", "ui-sans-serif", "system-ui", "sans-serif"],
        display: ["var(--font-display)", "Fraunces", "Georgia", "serif"],
        mono: ["var(--font-mono)", "IBM Plex Mono", "ui-monospace", "monospace"],
      },
      boxShadow: {
        soft: "var(--shadow-subtle)",
        lift: "var(--shadow-raised)",
      },
      borderRadius: {
        desk: "var(--radius-md)",
      },
    },
  },
  plugins: [],
};

export default config;
