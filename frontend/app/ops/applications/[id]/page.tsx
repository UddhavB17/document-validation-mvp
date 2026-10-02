"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

import { ErrorMessage, LoadingMessage } from "@/components/Message";
import { EvidenceWizard, type WizardMode } from "@/components/ops/EvidenceWizard";
import { FindingsList, PagesToVerifyChips } from "@/components/ops/FindingsList";
import { LedgerStamp } from "@/components/ops/LedgerStamp";
import { OpsChecklist } from "@/components/ops/OpsChecklist";
import { clampPercentage, pickText, statusProgressPercentage, takeTopFindings } from "@/components/ops/opsUtils";
import { normalizeOpsStatus } from "@/components/ops/StatusPill";
import type { OpsFinding } from "@/lib/api";
import { t, useLocale } from "@/lib/i18n";
import { isApplicationReviewPollingStatus, useApplicationStatus, useOpsApplication } from "@/lib/queries";

export default function OpsApplicationPage() {
  const params = useParams<{ id: string }>();
  const applicationId = Number(params.id);
  const isValid = Number.isInteger(applicationId) && applicationId > 0;
  const { locale } = useLocale();
  const ops = useOpsApplication(isValid ? applicationId : null);
  const status = useApplicationStatus(isValid ? applicationId : null);
  const [wizard, setWizard] = useState<WizardMode | null>(null);
  const [resolvedCodes, setResolvedCodes] = useState<Set<string>>(() => new Set());
  const wasProcessing = useRef(false);

  const liveStatus = status.data?.status ?? ops.data?.status;
  const processing = normalizeOpsStatus(liveStatus) === "processing";

  useEffect(() => {
    if (processing) {
      wasProcessing.current = true;
    }
  }, [processing]);

  useEffect(() => {
    if (wasProcessing.current && liveStatus && !isApplicationReviewPollingStatus(liveStatus)) {
      wasProcessing.current = false;
      void ops.refetch();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [liveStatus]);

  useEffect(() => {
    setResolvedCodes(new Set());
    setWizard(null);
  }, [applicationId]);

  const findings = useMemo(() => takeTopFindings(ops.data?.top_findings ?? []), [ops.data?.top_findings]);
  const openFindings = useMemo(
    () => findings.filter((finding) => !resolvedCodes.has(finding.code)),
    [findings, resolvedCodes],
  );
  const activeFinding = openFindings[0] ?? null;

  const openWizardForFinding = (finding: OpsFinding) => {
    const index = openFindings.findIndex((item) => item.code === finding.code);
    setWizard({ kind: "finding", index: Math.max(0, index) });
  };

  const markOk = (finding: OpsFinding) => {
    setResolvedCodes((current) => {
      const next = new Set(current);
      next.add(finding.code);
      return next;
    });
    setWizard((current) => {
      if (!current || current.kind !== "finding") {
        return current;
      }
      const remaining = openFindings.filter((item) => item.code !== finding.code);
      if (remaining.length === 0) {
        return null;
      }
      const nextIndex = Math.min(current.index, remaining.length - 1);
      return { kind: "finding", index: nextIndex };
    });
  };

  if (!isValid) {
    return (
      <div className="mx-auto max-w-[1100px] space-y-4">
        <ErrorMessage message={t(locale, "ops.review.loadError")} />
        <Link href="/ops" className="ledger-link text-sm">
          {t(locale, "ops.review.back")}
        </Link>
      </div>
    );
  }

  if (ops.isLoading) {
    return (
      <div className="mx-auto max-w-[1180px] space-y-4">
        <div className="h-16 rounded-desk ledger-shimmer" />
        <div className="h-28 rounded-desk ledger-shimmer" />
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1.4fr)_minmax(280px,.8fr)]">
          <div className="h-80 rounded-desk ledger-shimmer" />
          <div className="h-80 rounded-desk ledger-shimmer" />
        </div>
        <LoadingMessage message={t(locale, "ops.review.loading")} />
      </div>
    );
  }

  if (ops.isError || !ops.data) {
    return (
      <div className="mx-auto max-w-[1100px] space-y-4">
        <ErrorMessage message={t(locale, "ops.review.loadError")} />
        <div className="flex gap-3">
          <button type="button" onClick={() => void ops.refetch()} className="ledger-btn ledger-btn--outline">
            {t(locale, "ops.common.retry")}
          </button>
          <Link href="/ops" className="ledger-btn ledger-btn--electric">
            {t(locale, "ops.review.back")}
          </Link>
        </div>
      </div>
    );
  }

  const data = ops.data;
  const opsStatus = normalizeOpsStatus(liveStatus);
  const statusPercentage = statusProgressPercentage(status.data);
  const percentage = statusPercentage ?? clampPercentage(data.processing.percentage);
  const failureReason = status.data?.job?.failure_reason ?? data.processing.failure_reason;

  if (wizard) {
    return (
      <EvidenceWizard
        application={data}
        findings={findings}
        mode={wizard}
        resolvedCodes={resolvedCodes}
        onClose={() => setWizard(null)}
        onMarkOk={markOk}
        onFlag={() => {
          if (wizard.kind === "finding") {
            const remaining = openFindings;
            if (wizard.index < remaining.length - 1) {
              setWizard({ kind: "finding", index: wizard.index + 1 });
            }
          }
        }}
        onChangeIndex={(index) => setWizard({ kind: "finding", index })}
      />
    );
  }

  return (
    <div className="mx-auto max-w-[1180px] space-y-4 ledger-animate-in">
      <div className="ledger-surface flex flex-wrap items-center justify-between gap-3 px-4 py-3">
        <div className="min-w-0">
          <Link href="/ops" className="ledger-link text-sm">
            ← {t(locale, "ops.review.back")}
          </Link>
          <h1 className="mt-1 font-display text-[30px] font-semibold tracking-[-0.03em] text-desk-ink">
            {data.applicant_name || t(locale, "ops.common.unknown")}
          </h1>
          <p className="mt-0.5 font-mono text-xs text-desk-muted">
            {data.loan_id || t(locale, "ops.common.unknown")} · APP-{String(data.application_id).padStart(4, "0")}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <LedgerStamp
            tone={
              opsStatus === "needs_review"
                ? "warn"
                : opsStatus === "clean"
                  ? "ok"
                  : opsStatus === "failed"
                    ? "danger"
                    : "electric"
            }
          >
            {t(locale, `ops.review.status.${opsStatus}`)}
          </LedgerStamp>
          <button type="button" onClick={() => void ops.refetch()} className="ledger-btn ledger-btn--outline !min-h-[36px] !px-3 !text-xs">
            {t(locale, "ops.review.refresh")}
          </button>
        </div>
      </div>

      {opsStatus === "processing" ? (
        <section className="ledger-hero px-5 py-4" role="status" aria-live="polite">
          <p className="text-[11px] font-bold uppercase tracking-[0.14em] text-[color:var(--electric)]">
            {t(locale, "ops.review.processing")}
          </p>
          <p className="mt-2 text-sm text-[color:var(--hero-muted)]">{t(locale, "ops.review.processingDetail")}</p>
          <div
            className="mt-3 h-2 overflow-hidden rounded-full bg-white/15"
            role="progressbar"
            aria-valuenow={Math.round(percentage)}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label={t(locale, "ops.review.processing")}
          >
            <div className="h-full rounded-full bg-[color:var(--electric)] transition-all" style={{ width: `${percentage}%` }} />
          </div>
          <p className="mt-1 font-mono text-xs text-[color:var(--hero-muted)]">
            {Math.round(percentage)}% {t(locale, "ops.review.progress")}
          </p>
        </section>
      ) : null}

      {opsStatus === "failed" && failureReason ? (
        <p role="alert" className="rounded-desk border border-[color:var(--danger)] bg-[color:var(--danger-muted)] px-4 py-3 text-sm font-semibold text-desk-danger">
          {failureReason}
        </p>
      ) : null}

      {opsStatus === "needs_review" && activeFinding ? (
        <section className="ledger-hero px-5 py-5" aria-label={t(locale, "ops.review.nextAction")}>
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div className="min-w-0">
              <p className="text-[11px] font-bold uppercase tracking-[0.14em] text-[color:var(--electric)]">
                {t(locale, "ops.review.nextAction")}
              </p>
              <h2 className="mt-2 font-display text-[28px] font-semibold text-[color:var(--hero-text)]">
                {pickText(activeFinding.title, locale)}
              </h2>
              <p className="mt-2 text-sm text-[color:var(--hero-muted)]">
                {activeFinding.severity} · {t(locale, "ops.evidence.pageOf")}{" "}
                {activeFinding.pages[0] ?? activeFinding.evidence?.page ?? "—"} · {pickText(activeFinding.detail, locale)}
              </p>
            </div>
            <div className="flex flex-wrap items-end gap-3">
              <div className="text-right">
                <p className="font-display text-4xl font-semibold text-[color:var(--hero-text)]">{openFindings.length}</p>
                <p className="text-[11px] font-bold uppercase tracking-[0.12em] text-[color:var(--hero-muted)]">
                  {t(locale, "ops.review.openStamp")}
                </p>
              </div>
              <button
                type="button"
                className="ledger-btn ledger-btn--ghost"
                onClick={() => openWizardForFinding(activeFinding)}
              >
                {t(locale, "ops.review.openEvidence")}
              </button>
              <button type="button" className="ledger-btn ledger-btn--electric" onClick={() => markOk(activeFinding)}>
                {t(locale, "ops.review.markOk")}
              </button>
            </div>
          </div>
        </section>
      ) : null}

      {opsStatus === "clean" || (opsStatus === "needs_review" && openFindings.length === 0) ? (
        <section className="ledger-hero px-5 py-4">
          <p className="text-[11px] font-bold uppercase tracking-[0.14em] text-[color:var(--electric)]">
            {t(locale, "ops.review.readyToClose")}
          </p>
          <p className="mt-2 text-sm text-[color:var(--hero-muted)]">{t(locale, "ops.review.readyDetail")}</p>
        </section>
      ) : null}

      <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1.45fr)_minmax(300px,.85fr)]">
        <section aria-labelledby="ops-findings-heading" className="space-y-3">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <p className="text-[11px] font-bold uppercase tracking-[0.12em] text-desk-danger">
                {t(locale, "ops.review.starOfReview")}
              </p>
              <h2 id="ops-findings-heading" className="font-display text-[28px] font-semibold text-desk-ink">
                {t(locale, "ops.review.findings")}
              </h2>
            </div>
            <LedgerStamp tone="danger">
              {openFindings.length} {t(locale, "ops.review.openStamp")}
            </LedgerStamp>
          </div>
          <div className="rounded-desk border border-[color:var(--border)] bg-[color:var(--surface)] p-3 ledger-rail-danger">
            <FindingsList
              findings={findings}
              activeCode={activeFinding?.code ?? null}
              resolvedCodes={resolvedCodes}
              onOpenEvidence={(finding) => openWizardForFinding(finding)}
            />
          </div>
          <PagesToVerifyChips
            rows={data.pages_to_verify}
            onOpenPage={(page) => setWizard({ kind: "page", page })}
          />
        </section>

        <OpsChecklist
          rows={data.checklist.rows}
          applicationId={applicationId}
          counts={{
            found: data.checklist.found,
            missing: data.checklist.missing,
            not_checked: data.checklist.not_checked,
          }}
          summary={pickText(data.summary, locale)}
          onOpenPage={(page) => setWizard({ kind: "page", page })}
        />
      </div>
    </div>
  );
}
