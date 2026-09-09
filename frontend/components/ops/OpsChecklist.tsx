"use client";

import { OpsChecklistRow } from "@/lib/api";
import { useLocale, t } from "@/lib/i18n";

import { formatPageList } from "./opsUtils";

const CHECKLIST_STATUS_KEY = {
  FOUND: "ops.review.statusFound",
  MISSING: "ops.review.statusMissing",
  NOT_CHECKED: "ops.review.statusNotChecked",
} as const;

const CHECKLIST_STATUS_TONE: Record<string, string> = {
  FOUND: "bg-emerald-100 text-emerald-900 border-emerald-300",
  MISSING: "bg-red-100 text-red-900 border-red-300",
  NOT_CHECKED: "bg-slate-100 text-slate-700 border-slate-300",
};

function statusLabel(status: string, locale: "en" | "hi"): string {
  const key = CHECKLIST_STATUS_KEY[status as keyof typeof CHECKLIST_STATUS_KEY];
  return key ? t(locale, key) : status;
}

export function OpsChecklist({ rows }: { rows: OpsChecklistRow[] }) {
  const { locale } = useLocale();
  return (
    <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
      <table className="min-w-full border-collapse text-left text-sm">
        <caption className="sr-only">{t(locale, "ops.review.checklist")}</caption>
        <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
          <tr>
            <th scope="col" className="px-3 py-2.5">{t(locale, "ops.review.table.sno")}</th>
            <th scope="col" className="px-3 py-2.5">{t(locale, "ops.review.table.description")}</th>
            <th scope="col" className="px-3 py-2.5">{t(locale, "ops.review.table.status")}</th>
            <th scope="col" className="px-3 py-2.5">{t(locale, "ops.review.table.pages")}</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-200 text-slate-800">
          {rows.map((row) => {
            const tone = CHECKLIST_STATUS_TONE[row.status] ?? CHECKLIST_STATUS_TONE.NOT_CHECKED;
            return (
              <tr key={row.s_no} className="hover:bg-slate-50">
                <td className="whitespace-nowrap px-3 py-3 font-mono text-xs font-bold">{row.s_no}</td>
                <td className="min-w-[220px] px-3 py-3 font-semibold">{row.description}</td>
                <td className="whitespace-nowrap px-3 py-3">
                  <span className={`inline-flex min-h-[24px] items-center rounded-full border px-2.5 py-0.5 text-[11px] font-bold ${tone}`}>
                    {statusLabel(row.status, locale)}
                  </span>
                </td>
                <td className="px-3 py-3 font-mono text-xs text-slate-600">{formatPageList(row.pages)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
