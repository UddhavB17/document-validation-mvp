import type { ApplicationStatus, OpsFinding } from "@/lib/api";
import type { Locale } from "@/lib/i18n";

/** Preserve every finding returned by the operations API. */
export function takeTopFindings(findings: OpsFinding[]): OpsFinding[] {
  return findings;
}

/** Localized text picker for bilingual payload strings. */
export function pickText(text: { en: string; hi: string }, locale: Locale): string {
  return locale === "hi" ? text.hi : text.en;
}

function englishAiReason(finding: OpsFinding): string {
  const raw = finding.ai_detail?.en?.trim() ?? "";
  if (!raw) return "";

  // Some saved reviews include an English reason followed by a Hindi translation.
  // The page already has a locale-specific rule explanation, so keep this short
  // AI-led line in English only and avoid showing the translation twice.
  const firstHindiCharacter = raw.search(/[\u0900-\u097F]/u);
  const english = (firstHindiCharacter >= 0 ? raw.slice(0, firstHindiCharacter) : raw)
    .replace(/[\s/]+$/u, "")
    .trim();
  const withoutVerdictBoilerplate = english
    .replace(/^This looks like a real problem\.\s*/i, "")
    .replace(/^The automatic check is probably wrong\.\s*The document may be fine\.\s*/i, "")
    .replace(/^We could not confirm this automatically\.\s*Please check the page\.\s*/i, "");

  const personMismatch = withoutVerdictBoilerplate.match(
    /^Passbook on page\s+(\d+)\s+belongs to\s+(.+?)\s+\(coapplicant_\d+\),\s+not coapplicant_\d+\s+\((.+?)\)\..*$/i,
  );
  if (personMismatch) {
    const caution = finding.ai_verdict === "possible_false_positive" ? "This may be a wrong match. " : "";
    return `${caution}Page ${personMismatch[1]} shows ${personMismatch[2]}'s passbook, but it is matched to ${personMismatch[3]}. Please check that it belongs to the right person.`;
  }

  const reassignment = withoutVerdictBoilerplate.match(
    /^Page\s+(\d+)\s+(.+?)\s+is in the name of\s+(.+?)\s+\(coapplicant_\d+\) rather than coapplicant_\d+\s+\((.+?)\), confirming suspected index mapping mismatch\. Reassign document index to coapplicant_\d+\.?$/i,
  );
  if (reassignment) {
    return `The ${reassignment[2].toLowerCase()} on page ${reassignment[1]} belongs to ${reassignment[3]}, not ${reassignment[4]}. Please assign it to ${reassignment[3]}.`;
  }

  const missingDocument = withoutVerdictBoilerplate.match(
    /^(.+?) document is reported missing, and the provided excerpts contain .+? However, because search coverage is bounded and candidate pages are omitted, human review of omitted pages is needed\.?$/i,
  );
  if (missingDocument) {
    return `No ${missingDocument[1].toLowerCase()} was found in the pages checked. It may be elsewhere in the file. Please check the other pages.`;
  }

  // Turn the common date-of-birth finding into a short, scannable explanation.
  const dateMismatch = withoutVerdictBoilerplate.match(
    /^The expected date of birth\s+(.+?)\s+was not found on .+? page\s+(\d+);\s+instead,\s+the card displays\s+[“'\"]?(.+?)[”'\"]?\.?$/i,
  );
  if (dateMismatch) {
    const expectedDate = dateMismatch[1].match(/^0?(\d{1,2})-([A-Za-z]+)-(\d{4})$/);
    const expected = expectedDate
      ? `${Number(expectedDate[1])} ${expectedDate[2]} ${expectedDate[3]}`
      : dateMismatch[1];
    return `The dates do not match. Expected: ${expected}. Page ${dateMismatch[2]} shows: ${dateMismatch[3]}. Please check this page.`;
  }

  const unreadablePage = withoutVerdictBoilerplate.match(
    /^Page\s+(\d+) contains garbled and truncated .* below standard threshold\. Manual verification of the form details is required\.?$/i,
  );
  if (unreadablePage) {
    return `The text on page ${unreadablePage[1]} is hard to read. Please check this page yourself.`;
  }

  return finding.ai_verdict === "possible_false_positive"
    ? `This check may be wrong. ${withoutVerdictBoilerplate}`
    : withoutVerdictBoilerplate;
}

/** Prefer the short AI reason in English; use the simple localized rule text otherwise. */
export function opsFindingExplanation(finding: OpsFinding, locale: Locale): string {
  if (finding.ai_detail && locale === "en") {
    const reason = englishAiReason(finding);
    if (reason) return reason;
  }
  return pickText(finding.detail, locale);
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
