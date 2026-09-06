"use client";

import { OpsFinding, OpsPageToVerify } from "@/lib/api";
import { t, useLocale } from "@/lib/i18n";

import { severityBoxClass, severityPillClass } from "./bbox";
import { pickText, takeTopFindings } from "./opsUtils";

function PageChips({
  pages,
  onOpenPage,
  actionLabel,
}: {
  pages: number[];
  onOpenPage: (page: number) => void;
  actionLabel: string;
}) {
  const { locale } = useLocale();
  if (pages.length === 0) {
    return <span className="text-xs font-medium text-slate-500">{t(locale, "ops.common.unknown")}</span>;
  }
  return (
    <span className="flex flex-wrap gap-1.5">
      {pages.map((page) => (
        <button
          key={page}
          type="button"
          onClick={() => onOpenPage(page)}
          aria-label={`${actionLabel}: ${page}`}
          className="rounded-md border border-brand-primary/30 bg-brand-primary/5 px-2 py-1 text-xs font-bold text-brand-primary hover:bg-brand-primary/10 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-primary"
        >
          {page}
        </button>
      ))}
    </span>
  );
}

export function FindingsList({
  findings,
  onOpenEvidence,
}: {
  findings: OpsFinding[];
  onOpenEvidence: (finding: OpsFinding, page: number) => void;
}) {
  const { locale } = useLocale();
  const visible = takeTopFindings(findings);
  if (visible.length === 0) {
    return <p className="rounded-xl border border-slate-200 bg-white p-4 text-sm font-medium text-slate-600">{t(locale, "ops.review.findingsNone")}</p>;
  }
  return (
    <ul className="space-y-3" aria-label={t(locale, "ops.review.findings")}>
      {visible.map((finding) => (
        <li key={finding.code} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div className="flex min-w-0 items-start gap-2.5">
              <span aria-hidden="true" className={`mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full ${severityPillClass(finding.severity)}`} />
              <div className="min-w-0">
                <h3 className="text-sm font-bold text-slate-900">{pickText(finding.title, locale)}</h3>
                <p className="mt-1 text-sm leading-relaxed text-slate-700">{pickText(finding.detail, locale)}</p>
              </div>
            </div>
            <span className={`hidden shrink-0 rounded-full border-2 ${severityBoxClass(finding.severity)} px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-slate-500`}>
              {finding.severity}
            </span>
          </div>
          <div className="mt-3 flex items-center gap-2 border-t border-slate-100 pt-3">
            <PageChips
              pages={finding.pages}
              actionLabel={t(locale, "ops.review.openEvidence")}
              onOpenPage={(page) => onOpenEvidence(finding, page)}
            />
          </div>
        </li>
      ))}
    </ul>
  );
}

export function PagesToVerifyTable({
  rows,
  onOpenPage,
}: {
  rows: OpsPageToVerify[];
  onOpenPage: (page: number) => void;
}) {
  const { locale } = useLocale();
  if (rows.length === 0) {
    return <p className="rounded-xl border border-slate-200 bg-white p-4 text-sm font-medium text-slate-600">{t(locale, "ops.review.pagesToVerifyNone")}</p>;
  }
  return (
    <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
      <table className="min-w-full border-collapse text-left text-sm">
        <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
          <tr>
            <th scope="col" className="px-3 py-2.5">{t(locale, "ops.review.table.page")}</th>
            <th scope="col" className="px-3 py-2.5">{t(locale, "ops.review.table.document")}</th>
            <th scope="col" className="px-3 py-2.5">{t(locale, "ops.review.table.problem")}</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-200 text-slate-800">
          {rows.map((row) => (
            <tr key={row.page} className="hover:bg-slate-50">
              <td className="px-3 py-3">
                <button
                  type="button"
                  onClick={() => onOpenPage(row.page)}
                  aria-label={`${t(locale, "ops.review.openEvidence")}: ${row.page}`}
                  className="rounded-md border border-brand-primary/30 bg-brand-primary/5 px-2.5 py-1 font-mono text-xs font-bold text-brand-primary hover:bg-brand-primary/10 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-primary"
                >
                  {row.page}
                </button>
              </td>
              <td className="px-3 py-3 font-semibold">{pickText(row.document, locale)}</td>
              <td className="px-3 py-3 text-slate-600">{pickText(row.problem, locale)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
