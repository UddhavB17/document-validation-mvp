import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // ws-e ops ui: named tokens for the three most-used hex values plus
        // the severity scale, so new screens stop inlining hex.
        brand: {
          primary: "#2B4C7E",
          accent: "#5C6B7A",
          surface: "#F6F7FA",
          border: "#E1E5EB",
        },
        severity: {
          high: "#AF3B2E",
          medium: "#A0701C",
          low: "#1F7A5C",
        },
      },
    },
  },
  plugins: [],
};

export default config;
