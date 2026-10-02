"use client";

import { OpsFinding, OpsPageToVerify } from "@/lib/api";
import { t, useLocale } from "@/lib/i18n";

import { LedgerStamp } from "./LedgerStamp";
import { pickText, takeTopFindings } from "./opsUtils";

function severityTone(severity: string): "danger" | "warn" | "muted" {
  if (severity === "HIGH") return "danger";
  if (severity === "MEDIUM") return "warn";
  return "muted";
}

export function FindingsList({
  findings,
  onOpenEvidence,
  onMarkOk,
  activeCode,
  resolvedCodes,
}: {
  findings: OpsFinding[];
  onOpenEvidence: (finding: OpsFinding, page: number) => void;
  onMarkOk?: (finding: OpsFinding) => void;
  activeCode?: string | null;
  resolvedCodes?: Set<string>;
}) {
  const { locale } = useLocale();
  const visible = takeTopFindings(findings).filter((finding) => !resolvedCodes?.has(finding.code));
  if (visible.length === 0) {
    return (
      <p className="ledger-surface px-4 py-5 text-sm font-medium text-desk-muted">
        {t(locale, "ops.review.findingsNone")}
      </p>
    );
  }
  return (
    <ul className="space-y-3" aria-label={t(locale, "ops.review.findings")}>
      {visible.map((finding) => {
        const active = activeCode === finding.code;
        const page = finding.pages[0] ?? finding.evidence?.page ?? 1;
        const tone = severityTone(finding.severity);
        return (
          <li
            key={finding.code}
            className={`rounded-desk border border-[color:var(--border)] px-4 py-4 shadow-soft ${
              tone === "danger"
                ? "ledger-rail-danger bg-[color:var(--danger-muted)]"
                : tone === "warn"
                  ? "ledger-rail-warn bg-[color:var(--warning-muted)]"
                  : "bg-[color:var(--surface)]"
            }`}
          >
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="mb-2 flex flex-wrap gap-2">
                  <LedgerStamp tone={tone}>{finding.severity}</LedgerStamp>
                  <LedgerStamp tone="muted">
                    {t(locale, "ops.evidence.pageOf")} {page}
                  </LedgerStamp>
                </div>
                <h3 className="font-display text-[18px] font-semibold text-desk-ink">
                  {pickText(finding.title, locale)}
                </h3>
                <p className="mt-1 text-sm leading-relaxed text-desk-muted">{pickText(finding.detail, locale)}</p>
              </div>
              <button
                type="button"
                onClick={() => onOpenEvidence(finding, page)}
                className={`ledger-btn ${active ? "ledger-btn--electric" : "ledger-btn--ink"}`}
              >
                {t(locale, "ops.review.seePage")}
              </button>
            </div>
            {onMarkOk && active ? (
              <div className="mt-3 border-t border-[color:var(--border)] pt-3">
                <button type="button" className="ledger-btn ledger-btn--electric" onClick={() => onMarkOk(finding)}>
                  {t(locale, "ops.review.markOk")}
                </button>
              </div>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}

export function PagesToVerifyChips({
  rows,
  onOpenPage,
}: {
  rows: OpsPageToVerify[];
  onOpenPage: (page: number) => void;
}) {
  const { locale } = useLocale();
  if (rows.length === 0) {
    return null;
  }
  return (
    <div className="space-y-2">
      <p className="text-[10px] font-extrabold uppercase tracking-[0.12em] text-desk-faint">
        {t(locale, "ops.review.pagesToVerify")}
      </p>
      <div className="flex flex-wrap gap-2">
        {rows.map((row) => (
          <button
            key={row.page}
            type="button"
            onClick={() => onOpenPage(row.page)}
            className="rounded-md border border-[color:var(--border)] bg-[color:var(--surface)] px-3 py-2 text-left text-xs font-semibold text-desk-ink hover:border-[color:var(--electric)]"
          >
            <span className="font-mono text-desk-indigo">p.{row.page}</span>{" "}
            <span className="text-desk-muted">{pickText(row.document, locale)}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

/** @deprecated Prefer PagesToVerifyChips — kept for any residual imports. */
export function PagesToVerifyTable({
  rows,
  onOpenPage,
}: {
  rows: OpsPageToVerify[];
  onOpenPage: (page: number) => void;
}) {
  return <PagesToVerifyChips rows={rows} onOpenPage={onOpenPage} />;
}
