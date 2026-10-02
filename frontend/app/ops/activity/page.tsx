"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { ErrorMessage } from "@/components/Message";
import { LedgerStamp } from "@/components/ops/LedgerStamp";
import type { Activity } from "@/lib/api";
import { t, useLocale } from "@/lib/i18n";
import { useActivityToday } from "@/lib/queries";

const PAGE_SIZE = 5;

type OutcomeFilter = "all" | "accepted" | "overridden" | "sent_back";

function normalizeDecision(value: string): "accepted" | "overridden" | "sent_back" | "other" {
  const normalized = value.trim().toLowerCase().replace(/\s+/g, "_");
  if (normalized.includes("accept") || normalized === "approved" || normalized === "clean") {
    return "accepted";
  }
  if (normalized.includes("override") || normalized.includes("verified_with_override")) {
    return "overridden";
  }
  if (normalized.includes("sent") || normalized.includes("return") || normalized.includes("reject")) {
    return "sent_back";
  }
  return "other";
}

function outcomeTone(decision: string): "ok" | "warn" | "danger" | "muted" {
  const kind = normalizeDecision(decision);
  if (kind === "accepted") return "ok";
  if (kind === "overridden") return "warn";
  if (kind === "sent_back") return "danger";
  return "muted";
}

function outcomeLabel(decision: string, locale: "en" | "hi"): string {
  const kind = normalizeDecision(decision);
  if (kind === "accepted") return t(locale, "ops.activity.filter.accepted");
  if (kind === "overridden") return t(locale, "ops.activity.filter.overridden");
  if (kind === "sent_back") return t(locale, "ops.activity.filter.sentBack");
  return decision;
}

function formatTime(iso: string, locale: "en" | "hi"): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return "—";
  }
  return date.toLocaleTimeString(locale === "hi" ? "hi-IN" : "en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

export default function OpsActivityPage() {
  const { locale } = useLocale();
  const activity = useActivityToday();
  const [filter, setFilter] = useState<OutcomeFilter>("all");
  const [query, setQuery] = useState("");
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);

  useEffect(() => {
    setVisibleCount(PAGE_SIZE);
  }, [activity.data?.rows.length, filter, query]);

  const rows = useMemo(() => activity.data?.rows ?? [], [activity.data?.rows]);
  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return rows
      .filter((row) => {
        if (filter !== "all" && normalizeDecision(row.decision) !== filter) {
          return false;
        }
        if (!needle) {
          return true;
        }
        const haystack = `${row.loan_id} DEC-${row.id} ${row.application_id} ${row.decision}`.toLowerCase();
        return haystack.includes(needle);
      })
      .slice()
      .sort((a, b) => Date.parse(b.decided_at) - Date.parse(a.decided_at));
  }, [rows, filter, query]);

  const visible = filtered.slice(0, visibleCount);
  const remaining = Math.max(0, filtered.length - visible.length);
  const deskHint = new Date().toLocaleDateString(locale === "hi" ? "hi-IN" : "en-GB", {
    weekday: "long",
    day: "2-digit",
    month: "short",
  });

  return (
    <div className="mx-auto max-w-[1180px] space-y-5 ledger-animate-in">
      <header className="flex flex-wrap items-end justify-between gap-4 border-b border-[color:var(--border)] pb-4">
        <div>
          <p className="ledger-kicker">{t(locale, "ops.activity.kicker")}</p>
          <h1 className="mt-1 font-display text-[40px] font-semibold tracking-[-0.035em] text-desk-ink">
            {t(locale, "ops.activity.title")}
          </h1>
          <p className="mt-1 max-w-xl text-sm text-desk-muted">{t(locale, "ops.activity.description")}</p>
        </div>
        <LedgerStamp tone="ink">
          {activity.data?.total ?? 0} {t(locale, "ops.activity.decidedToday")}
        </LedgerStamp>
      </header>

      {activity.isError ? <ErrorMessage message={t(locale, "ops.review.loadError")} /> : null}

      {activity.isLoading ? (
        <div className="space-y-3" aria-busy="true">
          <div className="grid gap-3 sm:grid-cols-4">
            {Array.from({ length: 4 }, (_, index) => (
              <div key={index} className="h-24 rounded-desk ledger-shimmer" />
            ))}
          </div>
          <div className="h-64 rounded-desk ledger-shimmer" />
        </div>
      ) : null}

      {activity.data ? (
        <>
          <dl className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4" aria-label="Today’s activity counts">
            <MetricCard
              rail="electric"
              value={activity.data.total}
              label={t(locale, "ops.activity.metric.reviewed")}
              hint={t(locale, "ops.activity.metric.reviewedHint")}
            />
            <MetricCard
              rail="ok"
              value={activity.data.accepted}
              label={t(locale, "ops.activity.metric.accepted")}
              hint={t(locale, "ops.activity.metric.acceptedHint")}
            />
            <MetricCard
              rail="warn"
              value={activity.data.overridden}
              label={t(locale, "ops.activity.metric.overridden")}
              hint={t(locale, "ops.activity.metric.overriddenHint")}
            />
            <MetricCard
              rail="danger"
              value={activity.data.sent_back}
              label={t(locale, "ops.activity.metric.sentBack")}
              hint={t(locale, "ops.activity.metric.sentBackHint")}
            />
          </dl>

          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div className="flex min-w-0 flex-1 flex-col gap-3 sm:flex-row sm:items-center">
              <input
                type="search"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder={t(locale, "ops.activity.search")}
                className="ledger-input max-w-md"
                aria-label={t(locale, "ops.activity.search")}
              />
              <div className="flex flex-wrap gap-2">
                {(
                  [
                    ["all", activity.data.total, "ops.activity.filter.all"],
                    ["accepted", activity.data.accepted, "ops.activity.filter.accepted"],
                    ["overridden", activity.data.overridden, "ops.activity.filter.overridden"],
                    ["sent_back", activity.data.sent_back, "ops.activity.filter.sentBack"],
                  ] as const
                ).map(([key, count, labelKey]) => (
                  <button
                    key={key}
                    type="button"
                    className={`ledger-filter-chip${filter === key ? " is-active" : ""}`}
                    aria-pressed={filter === key}
                    onClick={() => setFilter(key)}
                  >
                    {t(locale, labelKey)} <span className="count">{count}</span>
                  </button>
                ))}
              </div>
            </div>
            <div className="flex items-center gap-3 text-xs font-semibold text-desk-faint">
              <span>
                {t(locale, "ops.activity.deskHint")} · {deskHint}
              </span>
              <LedgerStamp tone="muted">{t(locale, "ops.activity.sortNewest")}</LedgerStamp>
            </div>
          </div>

          {filtered.length === 0 ? (
            <div className="ledger-surface px-5 py-10 text-center">
              <p className="font-display text-2xl text-desk-ink">{t(locale, "ops.activity.empty")}</p>
              <button type="button" className="ledger-btn ledger-btn--outline mt-4" onClick={() => void activity.refetch()}>
                {t(locale, "ops.common.retry")}
              </button>
            </div>
          ) : (
            <ActivityTable rows={visible} locale={locale} total={filtered.length} remaining={remaining} onShowMore={() => setVisibleCount((c) => c + PAGE_SIZE)} />
          )}
        </>
      ) : null}
    </div>
  );
}

function MetricCard({
  rail,
  value,
  label,
  hint,
}: {
  rail: "electric" | "ok" | "warn" | "danger";
  value: number;
  label: string;
  hint: string;
}) {
  const railColor =
    rail === "electric"
      ? "var(--electric)"
      : rail === "ok"
        ? "var(--success)"
        : rail === "warn"
          ? "var(--warning)"
          : "var(--danger)";
  return (
    <div className="ledger-surface relative overflow-hidden px-4 py-4">
      <div aria-hidden="true" className="absolute inset-y-0 left-0 w-1" style={{ background: railColor }} />
      <dt className="text-[11px] font-extrabold uppercase tracking-[0.1em] text-desk-faint">{label}</dt>
      <dd className="mt-1 font-display text-[34px] font-semibold text-desk-ink">{value}</dd>
      <p className="text-xs text-desk-muted">{hint}</p>
    </div>
  );
}

function ActivityTable({
  rows,
  locale,
  total,
  remaining,
  onShowMore,
}: {
  rows: Activity["rows"];
  locale: "en" | "hi";
  total: number;
  remaining: number;
  onShowMore: () => void;
}) {
  return (
    <div className="ledger-surface overflow-hidden">
      <div className="hidden grid-cols-[minmax(110px,.7fr)_minmax(140px,.9fr)_minmax(180px,1.3fr)_minmax(120px,.8fr)_minmax(90px,.6fr)_minmax(80px,.5fr)] gap-3 border-b border-[color:var(--border)] px-4 py-3 text-[10px] font-extrabold uppercase tracking-[0.12em] text-desk-faint md:grid">
        <span>{t(locale, "ops.activity.col.decision")}</span>
        <span>{t(locale, "ops.activity.col.loan")}</span>
        <span>{t(locale, "ops.activity.col.applicant")}</span>
        <span>{t(locale, "ops.activity.col.outcome")}</span>
        <span>{t(locale, "ops.activity.col.recorded")}</span>
        <span />
      </div>
      <ul aria-label={t(locale, "ops.activity.title")}>
        {rows.map((row) => (
          <li
            key={row.id}
            className="grid gap-3 border-b border-[color:var(--border)] px-4 py-3.5 last:border-b-0 md:grid-cols-[minmax(110px,.7fr)_minmax(140px,.9fr)_minmax(180px,1.3fr)_minmax(120px,.8fr)_minmax(90px,.6fr)_minmax(80px,.5fr)] md:items-center"
          >
            <span className="font-mono text-sm font-bold text-desk-ink">DEC-{String(row.id).padStart(4, "0")}</span>
            <Link href={`/ops/applications/${row.application_id}`} className="font-mono text-sm font-semibold text-desk-indigo hover:underline">
              {row.loan_id}
            </Link>
            <div>
              <p className="font-display text-[16px] font-semibold text-desk-ink">
                APP-{String(row.application_id).padStart(4, "0")}
              </p>
              <p className="text-xs text-desk-muted">{t(locale, "ops.common.unknown")}</p>
            </div>
            <LedgerStamp tone={outcomeTone(row.decision)}>{outcomeLabel(row.decision, locale)}</LedgerStamp>
            <time dateTime={row.decided_at} className="font-mono text-sm text-desk-muted">
              {formatTime(row.decided_at, locale)}
            </time>
            <Link href={`/ops/applications/${row.application_id}`} className="ledger-link text-sm">
              {t(locale, "ops.activity.open")}
            </Link>
          </li>
        ))}
      </ul>
      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-[color:var(--border)] px-4 py-3 text-xs font-semibold text-desk-muted">
        <p>
          {t(locale, "ops.activity.showing")} {rows.length} {t(locale, "ops.activity.of")} {total} ·{" "}
          {t(locale, "ops.activity.newestFirst")}
        </p>
        {remaining > 0 ? (
          <button type="button" className="ledger-link" onClick={onShowMore}>
            {t(locale, "ops.activity.showRemaining")} {remaining} →
          </button>
        ) : null}
      </div>
    </div>
  );
}
