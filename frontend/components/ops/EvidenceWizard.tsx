"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { api, type OpsApplication, type OpsFinding } from "@/lib/api";
import { t, useLocale } from "@/lib/i18n";

import { bboxToStyle, severityBoxClass } from "./bbox";
import { LedgerStamp } from "./LedgerStamp";
import { pickText } from "./opsUtils";

export type WizardMode =
  | { kind: "finding"; index: number }
  | { kind: "page"; page: number };

export function EvidenceWizard({
  application,
  findings,
  mode,
  resolvedCodes,
  onClose,
  onMarkOk,
  onFlag,
  onChangeIndex,
}: {
  application: OpsApplication;
  findings: OpsFinding[];
  mode: WizardMode;
  resolvedCodes: Set<string>;
  onClose: () => void;
  onMarkOk: (finding: OpsFinding) => void;
  onFlag: () => void;
  onChangeIndex: (index: number) => void;
}) {
  const { locale } = useLocale();
  const [imageError, setImageError] = useState(false);

  const openFindings = useMemo(
    () => findings.filter((finding) => !resolvedCodes.has(finding.code)),
    [findings, resolvedCodes],
  );

  const isPageOnly = mode.kind === "page";
  const currentIndex = mode.kind === "finding" ? Math.min(Math.max(0, mode.index), Math.max(0, openFindings.length - 1)) : 0;
  const finding = !isPageOnly && openFindings.length > 0 ? openFindings[currentIndex] : null;
  const page =
    mode.kind === "page"
      ? mode.page
      : finding?.pages[0] ?? finding?.evidence?.page ?? 1;
  const total = isPageOnly ? 1 : Math.max(openFindings.length, 1);
  const step = isPageOnly ? 1 : currentIndex + 1;
  const bbox = finding?.evidence?.bbox && finding.evidence.page === page ? finding.evidence.bbox : null;
  const boxStyle = bbox ? bboxToStyle(bbox) : null;
  const isLast = !isPageOnly && currentIndex >= openFindings.length - 1;

  useEffect(() => {
    setImageError(false);
  }, [page, application.application_id]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="mx-auto flex max-w-[1100px] flex-col gap-4 ledger-animate-in">
      <div className="flex flex-wrap items-center justify-between gap-3 ledger-surface px-4 py-3">
        <div className="min-w-0">
          <button type="button" className="ledger-link text-sm" onClick={onClose}>
            ← {t(locale, "ops.evidence.backToCase")}
          </button>
          <h1 className="mt-1 font-display text-[28px] font-semibold text-desk-ink">
            {application.applicant_name || t(locale, "ops.common.unknown")}
          </h1>
          <p className="mt-0.5 font-mono text-xs text-desk-muted">
            {application.loan_id || t(locale, "ops.common.unknown")}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <LedgerStamp tone="warn">{t(locale, "ops.review.status.needs_review")}</LedgerStamp>
          <LedgerStamp tone="danger">
            {openFindings.length} {t(locale, "ops.review.openStamp")}
          </LedgerStamp>
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="font-mono text-xs font-bold uppercase tracking-[0.1em] text-desk-muted">
          {t(locale, "ops.evidence.problemOf")} {step} {t(locale, "ops.evidence.of")} {total}
        </p>
        <p className="text-xs text-desk-faint">{t(locale, "ops.evidence.hint")}</p>
      </div>
      <div className="flex gap-1.5" aria-hidden="true">
        {Array.from({ length: total }, (_, index) => {
          const done = !isPageOnly && index < currentIndex;
          const current = index === currentIndex || (isPageOnly && index === 0);
          return (
            <div
              key={index}
              className="h-1.5 flex-1 rounded-full"
              style={{
                background: done
                  ? "var(--success)"
                  : current
                    ? "var(--electric)"
                    : "var(--paper-deep)",
              }}
            />
          );
        })}
      </div>

      <section className="ledger-surface overflow-hidden">
        <div className="border-b border-[color:var(--border)] bg-[color:var(--surface-muted)] px-5 py-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <p className="ledger-kicker">{t(locale, "ops.evidence.problemKicker")}</p>
            <div className="flex flex-wrap gap-2">
              {finding ? <LedgerStamp tone={finding.severity === "HIGH" ? "danger" : "warn"}>{finding.severity}</LedgerStamp> : null}
              <LedgerStamp tone="ink">
                {t(locale, "ops.evidence.pageOf")} {page}
              </LedgerStamp>
              {finding ? <LedgerStamp tone="warn">{finding.code.replace(/_/g, " ")}</LedgerStamp> : null}
            </div>
          </div>
          <h2 className="mt-3 font-display text-[30px] font-semibold tracking-[-0.03em] text-desk-ink">
            {finding
              ? pickText(finding.title, locale)
              : `${t(locale, "ops.evidence.pageOf")} ${page}`}
          </h2>
          <p className="mt-2 text-sm text-desk-muted">
            {finding ? pickText(finding.detail, locale) : t(locale, "ops.review.pagesToVerify")}
          </p>
          <a
            className="ledger-link mt-3 inline-flex text-sm"
            href={api.sourcePdfUrl(application.application_id, page)}
            target="_blank"
            rel="noreferrer"
          >
            {t(locale, "ops.evidence.openPdf")}
          </a>
        </div>

        <div className="bg-[color:var(--paper-deep)] px-4 py-6">
          {boxStyle === null && finding ? (
            <p role="note" className="mb-3 rounded-md border border-[color:var(--warning)] bg-[color:var(--warning-muted)] px-3 py-2 text-xs font-semibold text-desk-warn">
              {t(locale, "ops.evidence.noBox")}
            </p>
          ) : null}
          {imageError ? (
            <p role="alert" className="mx-auto max-w-md rounded-desk border border-[color:var(--danger)] bg-[color:var(--danger-muted)] p-6 text-center text-sm font-semibold text-desk-danger">
              {t(locale, "ops.review.loadError")}
            </p>
          ) : (
            <div className="relative mx-auto w-fit max-w-full">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                key={`${application.application_id}-${page}`}
                src={api.sourcePageImageUrl(application.application_id, page)}
                alt={`${t(locale, "ops.evidence.pageOf")} ${page}`}
                onError={() => setImageError(true)}
                className="h-auto max-w-full rounded-sm border border-[color:var(--border)] bg-white shadow-lift"
              />
              {boxStyle ? (
                <div
                  aria-hidden="true"
                  className={`pointer-events-none absolute rounded-[2px] border-[3px] p-1 ${severityBoxClass(finding?.severity)}`}
                  style={boxStyle}
                >
                  <span className="absolute -top-6 left-0 rounded-sm bg-[color:var(--danger)] px-1.5 py-0.5 font-mono text-[10px] font-bold uppercase tracking-wide text-white">
                    {t(locale, "ops.evidence.extracted")}
                  </span>
                </div>
              ) : null}
            </div>
          )}
          {finding?.evidence?.text ? (
            <p className="mx-auto mt-4 max-w-2xl rounded-md border border-[color:var(--danger)] bg-[color:var(--danger-muted)] px-3 py-2 text-sm text-desk-danger">
              {finding.evidence.text}
            </p>
          ) : null}
        </div>
      </section>

      <footer className="sticky bottom-3 z-10 flex flex-wrap items-center justify-between gap-3 rounded-desk border border-[color:var(--border)] bg-[color:var(--surface)] px-4 py-3 shadow-lift">
        <button type="button" className="ledger-link text-sm" onClick={onClose}>
          {t(locale, "ops.evidence.seeAll")}
        </button>
        <div className="flex flex-wrap gap-2">
          <button type="button" className="ledger-btn ledger-btn--outline" onClick={onFlag} disabled={isPageOnly || !finding}>
            {t(locale, "ops.evidence.flag")}
          </button>
          <button
            type="button"
            className="ledger-btn ledger-btn--electric"
            disabled={isPageOnly || !finding}
            onClick={() => {
              if (finding) {
                onMarkOk(finding);
              }
            }}
          >
            {t(locale, "ops.evidence.markOk")}
          </button>
          <button
            type="button"
            className="ledger-btn ledger-btn--ink"
            onClick={() => {
              if (isPageOnly || isLast || openFindings.length === 0) {
                onClose();
                return;
              }
              onChangeIndex(currentIndex + 1);
            }}
          >
            {isPageOnly || isLast ? t(locale, "ops.evidence.done") : t(locale, "ops.evidence.nextProblem")}
          </button>
        </div>
      </footer>

      <p className="sr-only">
        <Link href="/ops">{t(locale, "ops.review.back")}</Link>
      </p>
    </div>
  );
}
