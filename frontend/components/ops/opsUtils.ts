import type { OpsFinding } from "@/lib/api";
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
