"use client";

import { useMemo, useState } from "react";

import type { OpsChecklistRow } from "@/lib/api";
import { api } from "@/lib/api";
import { useLocale, t } from "@/lib/i18n";

import { LedgerStamp } from "./LedgerStamp";
import { formatPageList } from "./opsUtils";

function CheckBox({
  checked,
  tone,
  label,
  disabled,
  onToggle,
}: {
  checked: boolean;
  tone: "system" | "manual";
  label: string;
  disabled?: boolean;
  onToggle?: () => void;
}) {
  return (
    <button
      type="button"
      className="ledger-check"
      data-checked={checked ? "true" : "false"}
      data-tone={tone}
      data-disabled={disabled ? "true" : "false"}
      aria-pressed={checked}
      aria-label={label}
      disabled={disabled}
      onClick={onToggle}
    >
      {checked ? "✓" : ""}
    </button>
  );
}

export function OpsChecklist({
  rows,
  applicationId,
  counts,
  summary,
  onOpenPage,
}: {
  rows: OpsChecklistRow[];
  applicationId: number;
  counts: { found: number; missing: number; not_checked: number };
  summary?: string;
  onOpenPage?: (page: number) => void;
}) {
  const { locale } = useLocale();
  const [manualAck, setManualAck] = useState<Record<number, boolean>>({});

  const { actionRows, foundRows } = useMemo(() => {
    const action: OpsChecklistRow[] = [];
    const found: OpsChecklistRow[] = [];
    for (const row of rows) {
      if (row.status === "FOUND") {
        found.push(row);
      } else {
        action.push(row);
      }
    }
    return { actionRows: action, foundRows: found };
  }, [rows]);

  const showFoundDisclosure = foundRows.length > 0 && actionRows.length + foundRows.length > 8;
  const visibleFound = showFoundDisclosure ? [] : foundRows;
  const ordered = [...actionRows, ...visibleFound];

  return (
    <aside className="ledger-surface flex h-full flex-col p-4" aria-labelledby="ops-checklist-heading">
      <p className="font-mono text-[10px] font-bold uppercase tracking-[0.14em] text-desk-faint">
        {t(locale, "ops.review.checklistSecondary")}
      </p>
      <h2 id="ops-checklist-heading" className="mt-1 font-display text-[22px] font-semibold text-desk-ink">
        {t(locale, "ops.review.checklist")}
      </h2>
      <div className="mt-3 flex flex-wrap gap-2">
        <LedgerStamp tone="ok">
          {counts.found} {t(locale, "ops.review.checklistFound")}
        </LedgerStamp>
        <LedgerStamp tone="danger">
          {counts.missing} {t(locale, "ops.review.checklistMissing")}
        </LedgerStamp>
        <LedgerStamp tone="warn">
          {counts.not_checked} {t(locale, "ops.review.checklistManual")}
        </LedgerStamp>
      </div>

      <ul className="mt-4 divide-y divide-[color:var(--border)]" aria-label={t(locale, "ops.review.checklist")}>
        {ordered.map((row) => {
          const systemChecked = row.status === "FOUND";
          const manualChecked = row.status === "NOT_CHECKED" ? Boolean(manualAck[row.s_no]) : false;
          const missing = row.status === "MISSING";
          const pageLabel = formatPageList(row.pages);
          return (
            <li key={row.s_no} className="flex items-center gap-3 py-3">
              <span className="w-6 shrink-0 font-mono text-xs text-desk-faint">
                {String(row.s_no).padStart(2, "0")}
              </span>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-semibold text-desk-ink">{row.description}</p>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                <CheckBox
                  checked={systemChecked}
                  tone="system"
                  label={`${t(locale, "ops.review.checklistSystem")}: ${row.description}`}
                  disabled
                />
                <CheckBox
                  checked={manualChecked}
                  tone="manual"
                  label={`${t(locale, "ops.review.checklistManualBox")}: ${row.description}`}
                  disabled={missing || systemChecked}
                  onToggle={() =>
                    setManualAck((current) => ({
                      ...current,
                      [row.s_no]: !current[row.s_no],
                    }))
                  }
                />
                {row.pages[0] && onOpenPage ? (
                  <button
                    type="button"
                    className="font-mono text-xs font-bold text-desk-indigo hover:underline"
                    onClick={() => onOpenPage(row.pages[0])}
                  >
                    p.{pageLabel}
                  </button>
                ) : (
                  <span className="min-w-[2.5rem] text-right font-mono text-xs text-desk-faint">
                    {missing ? "—" : pageLabel === "—" ? "—" : `p.${pageLabel}`}
                  </span>
                )}
              </div>
            </li>
          );
        })}
      </ul>

      {showFoundDisclosure ? (
        <details className="mt-2 rounded-md border border-[color:var(--border)] bg-[color:var(--surface-muted)] px-3 py-2">
          <summary className="cursor-pointer text-xs font-bold text-desk-muted">
            {t(locale, "ops.review.statusFound")} ({foundRows.length})
          </summary>
          <ul className="mt-2 divide-y divide-[color:var(--border)]">
            {foundRows.map((row) => (
              <li key={row.s_no} className="flex items-center gap-3 py-2 text-sm">
                <span className="w-6 font-mono text-xs text-desk-faint">{String(row.s_no).padStart(2, "0")}</span>
                <span className="flex-1 text-desk-ink">{row.description}</span>
                <CheckBox checked tone="system" label={row.description} disabled />
                <span className="font-mono text-xs text-desk-indigo">
                  {row.pages.length ? `p.${formatPageList(row.pages)}` : "—"}
                </span>
              </li>
            ))}
          </ul>
        </details>
      ) : null}

      <p className="mt-4 text-[11px] leading-relaxed text-desk-faint">{t(locale, "ops.review.checklistLegend")}</p>

      {summary ? (
        <p className="mt-3 line-clamp-3 text-xs text-desk-muted" title={summary}>
          {summary}
        </p>
      ) : null}

      <div className="mt-auto flex flex-wrap items-center gap-2 border-t border-[color:var(--border)] pt-3 text-xs font-semibold text-desk-muted">
        <span>{t(locale, "ops.review.summaryTucked")}</span>
        <a className="ledger-link" href={api.sourcePdfUrl(applicationId)} target="_blank" rel="noreferrer">
          {t(locale, "ops.review.checklistFullPdf")}
        </a>
      </div>
    </aside>
  );
}
