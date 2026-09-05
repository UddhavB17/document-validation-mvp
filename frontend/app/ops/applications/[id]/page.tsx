"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { ErrorMessage, LoadingMessage } from "@/components/Message";
import { PageHeader } from "@/components/PageHeader";
import { EvidenceViewer, EvidenceSelection } from "@/components/ops/EvidenceViewer";
import { FindingsList, PagesToVerifyTable } from "@/components/ops/FindingsList";
import { OpsChecklist } from "@/components/ops/OpsChecklist";
import { pickText, takeTopFindings } from "@/components/ops/opsUtils";
import { StatusPill, normalizeOpsStatus } from "@/components/ops/StatusPill";
import { OpsFinding } from "@/lib/api";
import { t, useLocale } from "@/lib/i18n";
import { isApplicationReviewPollingStatus, useApplicationStatus, useOpsApplication } from "@/lib/queries";

function isTerminalStatus(status: string | null | undefined): boolean {
  return !isApplicationReviewPollingStatus(status);
}

export default function OpsApplicationPage() {
  const params = useParams<{ id: string }>();
  const applicationId = Number(params.id);
  const isValid = Number.isInteger(applicationId) && applicationId > 0;
  const { locale } = useLocale();
  const ops = useOpsApplication(isValid ? applicationId : null);
  const status = useApplicationStatus(isValid ? applicationId : null);
  const [evidence, setEvidence] = useState<EvidenceSelection | null>(null);
  const wasProcessing = useRef(false);

  const liveStatus = status.data?.status ?? ops.data?.status;
  const processing = normalizeOpsStatus(liveStatus) === "processing";

  useEffect(() => {
    if (processing) {
      wasProcessing.current = true;
    }
  }, [processing]);

  // Refetch the payload once the lightweight status turns terminal. When the
  // status endpoint is unreachable the page keeps the last payload plus a
  // manual refresh button.
  useEffect(() => {
    if (wasProcessing.current && liveStatus && isTerminalStatus(liveStatus)) {
      wasProcessing.current = false;
      void ops.refetch();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [liveStatus]);

  if (!isValid) {
    return (
      <div className="mx-auto max-w-[1100px] space-y-4">
        <ErrorMessage message={t(locale, "ops.review.loadError")} />
        <Link href="/ops" className="text-sm font-bold text-brand-primary hover:underline">
          {t(locale, "ops.review.back")}
        </Link>
      </div>
    );
  }

  if (ops.isLoading) {
    return (
      <div className="mx-auto max-w-[1100px] space-y-4">
        <LoadingMessage message={t(locale, "ops.review.loading")} />
      </div>
    );
  }

  if (ops.isError || !ops.data) {
    return (
      <div className="mx-auto max-w-[1100px] space-y-4">
        <ErrorMessage message={t(locale, "ops.review.loadError")} />
        <div className="flex gap-3">
          <button
            type="button"
            onClick={() => void ops.refetch()}
            className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-bold text-slate-700 hover:bg-slate-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-primary"
          >
            {t(locale, "ops.common.retry")}
          </button>
          <Link href="/ops" className="rounded-lg px-4 py-2 text-sm font-bold text-brand-primary hover:underline">
            {t(locale, "ops.review.back")}
          </Link>
        </div>
      </div>
    );
  }

  const data = ops.data;
  const opsStatus = normalizeOpsStatus(liveStatus);
  const percentage = Math.min(100, Math.max(0, Number(data.processing.percentage ?? 0) || 0));

  const openEvidence = (finding: OpsFinding, page: number) => {
    const evidencePage = finding.evidence?.page;
    const matches = evidencePage === page && finding.evidence?.bbox;
    setEvidence({
      page,
      pages: finding.pages.length > 0 ? finding.pages : [page],
      bbox: matches && finding.evidence?.bbox ? [...finding.evidence.bbox] : null,
      severity: finding.severity,
      title: pickText(finding.title, locale),
    });
  };

  const openVerifyPage = (page: number) => {
    setEvidence({ page, pages: [page], bbox: null, severity: null, title: "" });
  };

  return (
    <div className="mx-auto max-w-[1100px] space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Link href="/ops" className="text-sm font-bold text-brand-primary hover:underline">
          ← {t(locale, "ops.review.back")}
        </Link>
        <button
          type="button"
          onClick={() => void ops.refetch()}
          className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-bold text-slate-600 hover:bg-slate-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-primary"
        >
          {t(locale, "ops.review.refresh")}
        </button>
      </div>

      <header className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <PageHeader
              title={data.applicant_name || t(locale, "ops.common.unknown")}
              description={data.loan_id || t(locale, "ops.common.unknown")}
            />
          </div>
          <StatusPill status={opsStatus} />
        </div>
        {opsStatus === "processing" ? (
          <div className="mt-4" role="status" aria-live="polite">
            <p className="text-sm font-semibold text-slate-600">{t(locale, "ops.review.processingDetail")}</p>
            <div className="mt-2 h-2.5 overflow-hidden rounded-full bg-slate-200" role="progressbar" aria-valuenow={Math.round(percentage)} aria-valuemin={0} aria-valuemax={100} aria-label={t(locale, "ops.review.processing")}>
              <div className="h-full rounded-full bg-brand-primary transition-all" style={{ width: `${percentage}%` }} />
            </div>
            <p className="mt-1 font-mono text-xs font-semibold text-slate-500">{Math.round(percentage)}% {t(locale, "ops.review.progress")}</p>
          </div>
        ) : null}
        {opsStatus === "failed" && data.processing.failure_reason ? (
          <p role="alert" className="mt-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm font-semibold text-red-900">
            {data.processing.failure_reason}
          </p>
        ) : null}
      </header>

      <section aria-labelledby="ops-summary-heading" className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <h2 id="ops-summary-heading" className="text-base font-bold text-slate-900">{t(locale, "ops.review.summary")}</h2>
        <p className="mt-2 text-sm leading-relaxed text-slate-700">{pickText(data.summary, locale)}</p>
      </section>

      <section aria-labelledby="ops-findings-heading" className="space-y-3">
        <h2 id="ops-findings-heading" className="text-base font-bold text-slate-900">{t(locale, "ops.review.findings")}</h2>
        <FindingsList findings={takeTopFindings(data.top_findings)} onOpenEvidence={openEvidence} />
      </section>

      <section aria-labelledby="ops-verify-heading" className="space-y-3">
        <h2 id="ops-verify-heading" className="text-base font-bold text-slate-900">{t(locale, "ops.review.pagesToVerify")}</h2>
        <PagesToVerifyTable rows={data.pages_to_verify} onOpenPage={openVerifyPage} />
      </section>

      <section aria-labelledby="ops-checklist-heading" className="space-y-3">
        <h2 id="ops-checklist-heading" className="text-base font-bold text-slate-900">
          {t(locale, "ops.review.checklist")} ({data.checklist.found} · {data.checklist.missing} · {data.checklist.not_checked})
        </h2>
        <OpsChecklist rows={data.checklist.rows} />
      </section>

      {evidence ? (
        <EvidenceViewer
          applicationId={applicationId}
          selection={evidence}
          onSelectPage={(page) => setEvidence((current) => {
            if (!current) return current;
            const pages = current.pages.includes(page) ? current.pages : [...current.pages, page].sort((a, b) => a - b);
            return { ...current, page, pages, bbox: null };
          })}
          onClose={() => setEvidence(null)}
        />
      ) : null}
    </div>
  );
}
