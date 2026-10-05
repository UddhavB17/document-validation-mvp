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

/** Primary explanation for an ops finding (AI-led when confidence threshold met). */
export function opsFindingExplanation(finding: OpsFinding, locale: Locale): string {
  if (finding.ai_primary && finding.ai_detail) {
    return pickText(finding.ai_detail, locale);
  }
  return pickText(finding.ai_detail ?? finding.detail, locale);
}

/** Rule template text kept for audit when AI leads the headline explanation. */
export function opsFindingRuleDetail(finding: OpsFinding, locale: Locale): string | null {
  if (!finding.ai_detail) {
    return null;
  }
  if (finding.ai_primary) {
    return pickText(finding.detail, locale);
  }
  return null;
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
  return typeof raw === "number" && Number.isFinite(raw) ? clampPercentage(raw) : null;
}
