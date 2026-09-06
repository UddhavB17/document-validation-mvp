"use client";

import Link from "next/link";

import { ErrorMessage, InfoMessage, LoadingMessage } from "@/components/Message";
import { PageHeader } from "@/components/PageHeader";
import { StatusPill, normalizeOpsStatus } from "@/components/ops/StatusPill";
import { useOpsWorklist } from "@/lib/queries";
import { t, useLocale } from "@/lib/i18n";

export default function OpsWorklistPage() {
  const { locale } = useLocale();
  const worklist = useOpsWorklist();
  const applications = worklist.data?.applications ?? [];

  return (
    <div className="mx-auto max-w-[1100px] space-y-5">
      <PageHeader title={t(locale, "ops.worklist.title")} description={t(locale, "ops.worklist.description")} />

      {worklist.isLoading ? <LoadingMessage message={t(locale, "ops.review.loading")} /> : null}
      {worklist.isError ? (
        <ErrorMessage message={t(locale, "ops.review.loadError")} />
      ) : null}

      {worklist.data ? (
        applications.length === 0 ? (
          <InfoMessage message={t(locale, "ops.worklist.empty")} />
        ) : (
          <ul className="space-y-3" aria-label={t(locale, "ops.worklist.title")}>
            {applications.map((item) => (
              <li key={item.application_id} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-bold text-slate-900">
                      {item.applicant_name || t(locale, "ops.common.unknown")}
                    </p>
                    <p className="mt-0.5 font-mono text-xs font-semibold text-slate-500">
                      {item.loan_id || t(locale, "ops.common.unknown")} · {item.findings_count} {t(locale, "ops.worklist.findings")}
                    </p>
                  </div>
                  <div className="flex items-center gap-3">
                    <StatusPill status={normalizeOpsStatus(item.status)} />
                    <Link
                      href={`/ops/applications/${item.application_id}`}
                      aria-label={`${t(locale, "ops.worklist.open")}: ${item.loan_id ?? item.application_id}`}
                      className="rounded-lg bg-brand-primary px-4 py-2 text-sm font-bold text-white hover:bg-brand-primary/90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-primary"
                    >
                      {t(locale, "ops.worklist.open")}
                    </Link>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )
      ) : null}
    </div>
  );
}
