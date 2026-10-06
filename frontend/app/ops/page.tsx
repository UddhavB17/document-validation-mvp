"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { ErrorMessage } from "@/components/Message";
import { LedgerStamp } from "@/components/ops/LedgerStamp";
import { normalizeOpsStatus, type OpsStatus } from "@/components/ops/StatusPill";
import type { OpsWorklistItem } from "@/lib/api";
import { t, useLocale } from "@/lib/i18n";
import { useOpsWorklist } from "@/lib/queries";
import { formatWaitingSince } from "@/lib/waiting";

type FilterKey = "needs_review" | "processing" | "clean" | "all";

const PAGE_SIZE = 5;

function exceptionStamp(count: number): { label: string; tone: "danger" | "warn" | "muted" } {
  if (count <= 0) {
    return { label: "Clean", tone: "muted" };
  }
  if (count >= 3) {
    return { label: `${count} exceptions`, tone: "danger" };
  }
  return { label: `${count} checklist gap${count === 1 ? "" : "s"}`, tone: "warn" };
}

function statusTone(status: OpsStatus): "warn" | "ok" | "electric" | "danger" {
  if (status === "needs_review") return "warn";
  if (status === "clean") return "ok";
  if (status === "processing") return "electric";
  return "danger";
}

function sortOldest(a: OpsWorklistItem, b: OpsWorklistItem): number {
  const aTime = Date.parse(a.updated_at ?? "") || 0;
  const bTime = Date.parse(b.updated_at ?? "") || 0;
  if (aTime === bTime) {
    return a.application_id - b.application_id;
  }
  return aTime - bTime;
}

export default function OpsWorklistPage() {
  const { locale } = useLocale();
  const worklist = useOpsWorklist();
  const [filter, setFilter] = useState<FilterKey>("needs_review");
  const [query, setQuery] = useState("");
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);

  const applications = useMemo(() => worklist.data?.applications ?? [], [worklist.data?.applications]);

  const counts = useMemo(() => {
    const next = { needs_review: 0, processing: 0, clean: 0, all: applications.length, failed: 0 };
    for (const item of applications) {
      const status = normalizeOpsStatus(item.status);
      if (status === "needs_review") next.needs_review += 1;
      if (status === "processing") next.processing += 1;
      if (status === "clean") next.clean += 1;
      if (status === "failed") next.failed += 1;
    }
    return next;
  }, [applications]);

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return applications
      .filter((item) => {
        const status = normalizeOpsStatus(item.status);
        if (filter !== "all" && status !== filter) {
          return false;
        }
        if (!needle) {
          return true;
        }
        const haystack = `${item.applicant_name ?? ""} ${item.loan_id ?? ""} ${item.application_id}`.toLowerCase();
        return haystack.includes(needle);
      })
      .slice()
      .sort(sortOldest);
  }, [applications, filter, query]);

  const reviewQueue = useMemo(
    () => applications.filter((item) => normalizeOpsStatus(item.status) === "needs_review").slice().sort(sortOldest),
    [applications],
  );
  const hero = filter === "needs_review" || filter === "all" ? reviewQueue[0] ?? null : null;
  const visible = filtered.slice(0, visibleCount);
  const remaining = Math.max(0, filtered.length - visible.length);
  const weekday = new Date().toLocaleDateString(locale === "hi" ? "hi-IN" : "en-IN", { weekday: "long" });

  return (
    <div className="mx-auto max-w-[1180px] space-y-5 ledger-animate-in">
      <header className="flex flex-wrap items-end justify-between gap-4 border-b border-[color:var(--border)] pb-4">
        <div className="min-w-0">
          <p className="ledger-kicker">{t(locale, "ops.worklist.kicker")}</p>
          <h1 className="mt-1 font-display text-[40px] font-semibold tracking-[-0.035em] text-desk-ink">
            {t(locale, "ops.worklist.title")}
          </h1>
          <p className="mt-1 max-w-xl text-sm text-desk-muted">
            {counts.needs_review > 0
              ? t(locale, "ops.worklist.descriptionGeneric")
              : t(locale, "ops.worklist.empty")}
          </p>
        </div>
        <LedgerStamp tone="ink">
          {counts.needs_review} {t(locale, "ops.worklist.needReview")}
        </LedgerStamp>
      </header>

      {worklist.isError ? <ErrorMessage message={t(locale, "ops.review.loadError")} /> : null}

      {worklist.isLoading ? (
        <div className="space-y-3" aria-busy="true">
          <div className="h-28 rounded-desk ledger-shimmer" />
          <div className="h-14 rounded-desk ledger-shimmer" />
          <div className="h-64 rounded-desk ledger-shimmer" />
        </div>
      ) : null}

      {worklist.data ? (
        <>
          {hero ? (
            <section className="ledger-hero ledger-animate-in-delay px-5 py-5 sm:px-6" aria-label={t(locale, "ops.worklist.reviewNext")}>
              <div className="flex flex-wrap items-end justify-between gap-4">
                <div className="min-w-0">
                  <p className="text-[11px] font-bold uppercase tracking-[0.14em] text-[color:var(--electric)]">
                    {t(locale, "ops.worklist.reviewNext")}
                  </p>
                  <h2 className="mt-2 font-display text-[28px] font-semibold tracking-[-0.03em] text-[color:var(--hero-text)]">
                    {hero.applicant_name || t(locale, "ops.common.unknown")}
                    <span className="text-[color:var(--hero-muted)]"> · </span>
                    <span className="font-mono text-[22px]">{hero.loan_id || `APP-${hero.application_id}`}</span>
                  </h2>
                  <p className="mt-2 text-sm text-[color:var(--hero-muted)]">
                    {hero.findings_count} {t(locale, "ops.worklist.exceptions")} · {t(locale, "ops.worklist.sortOldest").toLowerCase()} ·{" "}
                    {formatWaitingSince(hero.updated_at)}
                  </p>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {hero.findings_count > 0 ? (
                      <LedgerStamp tone="warn">{exceptionStamp(hero.findings_count).label}</LedgerStamp>
                    ) : (
                      <LedgerStamp tone="muted">{t(locale, "ops.review.status.needs_review")}</LedgerStamp>
                    )}
                  </div>
                </div>
                <div className="flex items-end gap-4">
                  <div className="text-right">
                    <p className="font-display text-4xl font-semibold text-[color:var(--hero-text)]">{hero.findings_count}</p>
                    <p className="text-[11px] font-bold uppercase tracking-[0.12em] text-[color:var(--hero-muted)]">
                      {t(locale, "ops.worklist.openCount")}
                    </p>
                  </div>
                  <Link href={`/ops/applications/${hero.application_id}`} className="ledger-btn ledger-btn--electric">
                    {t(locale, "ops.worklist.openCase")}
                  </Link>
                </div>
              </div>
            </section>
          ) : filter === "processing" && counts.processing > 0 ? (
            <section className="ledger-hero px-5 py-4">
              <p className="text-sm text-[color:var(--hero-muted)]">{t(locale, "ops.worklist.engineWorking")}</p>
            </section>
          ) : null}

          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div className="flex min-w-0 flex-1 flex-col gap-3 sm:flex-row sm:items-center">
              <input
                type="search"
                value={query}
                onChange={(event) => {
                  setQuery(event.target.value);
                  setVisibleCount(PAGE_SIZE);
                }}
                placeholder={t(locale, "ops.worklist.search")}
                className="ledger-input max-w-md"
                aria-label={t(locale, "ops.worklist.search")}
              />
              <div className="flex flex-wrap gap-2" role="group" aria-label="Queue filters">
                {(
                  [
                    ["needs_review", counts.needs_review, "ops.worklist.filter.needsReview"],
                    ["processing", counts.processing, "ops.worklist.filter.processing"],
                    ["clean", counts.clean, "ops.worklist.filter.clean"],
                    ["all", counts.all, "ops.worklist.filter.all"],
                  ] as const
                ).map(([key, count, labelKey]) => (
                  <button
                    key={key}
                    type="button"
                    className={`ledger-filter-chip${filter === key ? " is-active" : ""}`}
                    aria-pressed={filter === key}
                    onClick={() => {
                      setFilter(key);
                      setVisibleCount(PAGE_SIZE);
                    }}
                  >
                    {t(locale, labelKey)} <span className="count">{count}</span>
                  </button>
                ))}
              </div>
            </div>
            <div className="flex items-center gap-3 text-xs font-semibold text-desk-faint">
              <span>
                {t(locale, "ops.worklist.queueCalm")} · {weekday}
              </span>
              <LedgerStamp tone="muted">{t(locale, "ops.worklist.sortOldest")}</LedgerStamp>
            </div>
          </div>

          {filtered.length === 0 ? (
            <div className="ledger-surface px-5 py-10 text-center">
              <p className="font-display text-2xl text-desk-ink">{t(locale, "ops.worklist.empty")}</p>
              <button type="button" className="ledger-btn ledger-btn--outline mt-4" onClick={() => void worklist.refetch()}>
                {t(locale, "ops.worklist.refresh")}
              </button>
            </div>
          ) : (
            <div className="ledger-surface overflow-hidden">
              <div className="hidden grid-cols-[minmax(180px,1.4fr)_minmax(140px,.9fr)_minmax(150px,1fr)_minmax(90px,.6fr)_minmax(120px,.7fr)_minmax(90px,.5fr)] gap-3 border-b border-[color:var(--border)] px-4 py-3 text-[10px] font-extrabold uppercase tracking-[0.12em] text-desk-faint md:grid">
                <span>{t(locale, "ops.worklist.col.applicant")}</span>
                <span>{t(locale, "ops.worklist.col.loanId")}</span>
                <span>{t(locale, "ops.worklist.col.exceptions")}</span>
                <span>{t(locale, "ops.worklist.col.waiting")}</span>
                <span>{t(locale, "ops.worklist.col.status")}</span>
                <span>{t(locale, "ops.worklist.col.action")}</span>
              </div>
              <ul aria-label={t(locale, "ops.worklist.title")}>
                {visible.map((item) => {
                  const status = normalizeOpsStatus(item.status);
                  const stamp = exceptionStamp(item.findings_count);
                  const waiting = formatWaitingSince(item.updated_at);
                  const rail =
                    status === "needs_review"
                      ? item.findings_count >= 3
                        ? "ledger-rail-danger"
                        : "ledger-rail-warn"
                      : "";
                  const canReview = status === "needs_review" || status === "clean" || status === "failed";
                  return (
                    <li
                      key={item.application_id}
                      className={`grid gap-3 border-b border-[color:var(--border)] px-4 py-3.5 last:border-b-0 md:grid-cols-[minmax(180px,1.4fr)_minmax(140px,.9fr)_minmax(150px,1fr)_minmax(90px,.6fr)_minmax(120px,.7fr)_minmax(90px,.5fr)] md:items-center ${rail}`}
                    >
                      <div className="min-w-0">
                        <p className="truncate font-display text-[17px] font-semibold text-desk-ink">
                          {item.applicant_name || t(locale, "ops.common.unknown")}
                        </p>
                        <p className="mt-0.5 text-xs text-desk-muted">
                          APP-{String(item.application_id).padStart(4, "0")}
                        </p>
                      </div>
                      <p className="font-mono text-sm font-semibold text-desk-indigo">
                        {item.loan_id || t(locale, "ops.common.unknown")}
                      </p>
                      <div>
                        <LedgerStamp tone={stamp.tone}>{stamp.label}</LedgerStamp>
                      </div>
                      <p
                        className={`font-mono text-sm font-semibold ${
                          status === "needs_review" && item.findings_count >= 3 ? "text-desk-danger" : "text-desk-ink"
                        }`}
                      >
                        {waiting}
                      </p>
                      <div>
                        <LedgerStamp tone={statusTone(status)}>
                          {t(locale, `ops.review.status.${status}`)}
                        </LedgerStamp>
                      </div>
                      <div>
                        {canReview ? (
                          <Link href={`/ops/applications/${item.application_id}`} className="ledger-link text-sm">
                            {t(locale, "ops.worklist.review")} →
                          </Link>
                        ) : (
                          <span className="text-sm font-semibold text-desk-faint">—</span>
                        )}
                      </div>
                    </li>
                  );
                })}
              </ul>
              <div className="flex flex-wrap items-center justify-between gap-3 border-t border-[color:var(--border)] px-4 py-3 text-xs font-semibold text-desk-muted">
                <p>
                  {t(locale, "ops.worklist.showing")} {visible.length} {t(locale, "ops.worklist.of")} {filtered.length} ·{" "}
                  {t(locale, "ops.worklist.oldestFirst")}
                </p>
                {remaining > 0 ? (
                  <button
                    type="button"
                    className="ledger-link"
                    onClick={() => setVisibleCount((current) => current + PAGE_SIZE)}
                  >
                    {t(locale, "ops.worklist.showRemaining")} {remaining} →
                  </button>
                ) : null}
              </div>
            </div>
          )}
        </>
      ) : null}
    </div>
  );
}
