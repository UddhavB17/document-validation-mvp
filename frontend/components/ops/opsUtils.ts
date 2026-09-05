import type { ApplicationStatus, OpsFinding } from "@/lib/api";
import type { Locale } from "@/lib/i18n";

export const MAX_FINDINGS = 5;

/** Keep at most the first 5 findings; the backend already caps, this is a guard. */
export function takeTopFindings(findings: OpsFinding[]): OpsFinding[] {
  return findings.slice(0, MAX_FINDINGS);
}

/** Localized text picker for bilingual payload strings. */
export function pickText(text: { en: string; hi: string }, locale: Locale): string {
  return locale === "hi" ? text.hi : text.en;
}

/** "1, 2, 3" for page lists, em dash when empty. */
export function formatPageList(pages: number[]): string {
  return pages.length > 0 ? pages.join(", ") : "—";
}

/** Clamp a raw value to the 0–100 bar range; non-numbers become 0. */
export function clampPercentage(value: unknown): number {
  const numeric = typeof value === "number" && Number.isFinite(value) ? value : 0;
  return Math.min(100, Math.max(0, numeric));
}

/**
 * In-flight bar value from the lightweight /status payload, which nests the
 * figure under `progress`. Returns null when the status carries no usable
 * figure so callers can fall back to the last full-payload value.
 */
export function statusProgressPercentage(status: ApplicationStatus | null | undefined): number | null {
  const raw = status?.progress?.percentage;
  if (typeof raw !== "number" || !Number.isFinite(raw)) {
    return null;
  }
  return clampPercentage(raw);
}
