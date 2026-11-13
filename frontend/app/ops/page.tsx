"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { ErrorMessage } from "@/components/Message";
import { LedgerStamp } from "@/components/ops/LedgerStamp";
import { normalizeOpsStatus, type OpsStatus } from "@/components/ops/StatusPill";
import type { OpsTATWorklist } from "@/lib/api";
import { t, useLocale } from "@/lib/i18n";
import { useAdminUsers, useClaimOpsCase, useCurrentUser, useOpsTatMetrics, useOpsWorklist, useReassignOpsCase, useReleaseOpsCase, useReviewNextOpsCase } from "@/lib/queries";
import { formatWaitingSince } from "@/lib/waiting";

type FilterKey = "all" | "ready" | "mine" | "waiting" | "completed" | "processing";

type OpsQueueItem = OpsTATWorklist["applications"][number];

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

function sortOldest(a: OpsQueueItem, b: OpsQueueItem): number {
  const aTime = Date.parse(a.queue_entered_at ?? a.ready_at ?? "") || 0;
  const bTime = Date.parse(b.queue_entered_at ?? b.ready_at ?? "") || 0;
  if (aTime === bTime) {
    return a.application_id - b.application_id;
  }
  return aTime - bTime;
}

function metricValue(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : `${Math.round(value)} min`;
}

function QueueOwnershipAction({ item, currentUserId, onUpdated }: { item: OpsQueueItem; currentUserId?: number; onUpdated: () => void }) {
  const claimCase = useClaimOpsCase(item.application_id);
  const releaseCase = useReleaseOpsCase(item.application_id);
  if (item.workflow_state !== "ready") return <span className="text-xs text-desk-faint">{item.next_action}</span>;
  if (item.owner_user_id === currentUserId) {
  return <button type="button" className="ledger-link text-xs" onClick={() => void releaseCase.mutateAsync(undefined).then(onUpdated)}>Release</button>;
  }
  if (item.owner_user_id !== null) return <span className="text-xs text-desk-muted">{item.owner_name || "Assigned"}</span>;
  return <button type="button" className="ledger-link text-xs" onClick={() => void claimCase.mutateAsync(undefined).then(onUpdated)}>Claim</button>;
}

function AdminReassignAction({ item, onUpdated }: { item: OpsQueueItem; onUpdated: () => void }) {
  const users = useAdminUsers();
  const reassign = useReassignOpsCase(item.application_id);
  const [targetId, setTargetId] = useState("");
  const [reason, setReason] = useState("");
  if (item.workflow_state !== "ready" || !users.data?.users.length) return null;
  return (
    <div className="mt-1 flex flex-wrap gap-1">
      <select className="ledger-input !min-h-8 max-w-36 text-xs" value={targetId} onChange={(event) => setTargetId(event.target.value)} aria-label="Reassign to">
        <option value="">Reassign…</option>
        {users.data.users.filter((user) => user.is_active && user.id !== item.owner_user_id).map((user) => <option key={user.id} value={user.id}>{user.display_name}</option>)}
      </select>
      {targetId ? <>
        <input className="ledger-input !min-h-8 max-w-40 text-xs" value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Reason" aria-label="Reassignment reason" />
        <button type="button" className="ledger-link text-xs" disabled={reason.trim().length < 3 || reassign.isPending} onClick={() => void reassign.mutateAsync({ user_id: Number(targetId), reason }).then(onUpdated)}>Assign</button>
      </> : null}
    </div>
  );
}

export default function OpsWorklistPage() {
  const { locale } = useLocale();
  const [view, setView] = useState<FilterKey>("ready");
  const worklist = useOpsWorklist(view);
  const metrics = useOpsTatMetrics();
  const currentUser = useCurrentUser();
  const reviewNext = useReviewNextOpsCase();
  const [filter, setFilter] = useState<"all" | "needs_review" | "processing" | "clean" | "failed">("all");
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

  const reviewQueue = useMemo(() => applications.filter((item) => item.workflow_state === "ready").slice().sort(sortOldest), [applications]);
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
          {worklist.data?.total ?? 0} {t(locale, "ops.worklist.needReview")}
        </LedgerStamp>
      </header>

      <section className="grid gap-3 rounded-desk border border-[color:var(--border)] bg-[color:var(--surface)] p-4 sm:grid-cols-2 xl:grid-cols-4" aria-label="Prospective Ops turnaround baseline">
        <div><p className="text-[10px] font-bold uppercase tracking-wide text-desk-faint">First touch · p50 / p90</p><p className="mt-1 text-sm font-semibold text-desk-ink">{metricValue(metrics.data?.first_touch.p50_minutes)} / {metricValue(metrics.data?.first_touch.p90_minutes)}</p><p className="text-xs text-desk-muted">{metrics.data?.first_touch.sample_count ?? 0} cases</p></div>
        <div><p className="text-[10px] font-bold uppercase tracking-wide text-desk-faint">First outcome · p50 / p90</p><p className="mt-1 text-sm font-semibold text-desk-ink">{metricValue(metrics.data?.first_outcome_after_start.p50_minutes)} / {metricValue(metrics.data?.first_outcome_after_start.p90_minutes)}</p><p className="text-xs text-desk-muted">{metrics.data?.first_outcome_after_start.sample_count ?? 0} cases</p></div>
        <div><p className="text-[10px] font-bold uppercase tracking-wide text-desk-faint">Ready to completion · p50 / p90</p><p className="mt-1 text-sm font-semibold text-desk-ink">{metricValue(metrics.data?.ready_to_completion.p50_minutes)} / {metricValue(metrics.data?.ready_to_completion.p90_minutes)}</p><p className="text-xs text-desk-muted">Total elapsed, including document waits</p><p className="text-xs text-desk-muted">Excluding waits: {metricValue(metrics.data?.ready_to_completion_excluding_document_wait.p50_minutes)} p50</p></div>
        <div><p className="text-[10px] font-bold uppercase tracking-wide text-desk-faint">Document wait · p50 / p90</p><p className="mt-1 text-sm font-semibold text-desk-ink">{metricValue(metrics.data?.document_wait.p50_minutes)} / {metricValue(metrics.data?.document_wait.p90_minutes)}</p><p className="text-xs text-desk-muted">Prospective baseline · {metrics.data?.sample_count ?? 0} tracked cases</p></div>
        <div><p className="text-[10px] font-bold uppercase tracking-wide text-desk-faint">Follow-up quality signals</p><p className="mt-1 text-sm font-semibold text-desk-ink">{metrics.data?.cases_reopened_after_documents ?? 0} reopened · {metrics.data?.decision_undo_count ?? 0} decision undos</p><p className="text-xs text-desk-muted">{metrics.data?.document_request_rounds.total ?? 0} request rounds · {metrics.data?.document_request_rounds.cases_with_multiple_requests ?? 0} repeat cases</p></div>
        <button type="button" className="ledger-btn ledger-btn--electric justify-self-start xl:col-span-4 xl:justify-self-end" disabled={reviewNext.isPending} onClick={() => void reviewNext.mutateAsync(undefined).then(async (result) => { const nextId = (result as { application_id?: number | null }).application_id; if (nextId) window.location.assign(`/ops/applications/${nextId}`); else await worklist.refetch(); })}>Review next</button>
      </section>

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
                  {formatWaitingSince(hero.queue_entered_at ?? hero.ready_at)}
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
                    ["all", counts.all, "ops.worklist.filter.all"],
                    ["needs_review", counts.needs_review, "ops.worklist.filter.needsReview"],
                    ["processing", counts.processing, "ops.worklist.filter.processing"],
                    ["clean", counts.clean, "ops.worklist.filter.clean"],
                    ["failed", counts.failed, "ops.worklist.filter.failed"],
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

          <div className="flex flex-wrap gap-2" role="group" aria-label="Ops workflow views">
            {(["ready", "mine", "waiting", "completed", "processing", "all"] as const).map((key) => (
              <button key={key} type="button" className={`ledger-filter-chip${view === key ? " is-active" : ""}`} aria-pressed={view === key} onClick={() => { setView(key); setVisibleCount(PAGE_SIZE); }}>
                {key === "ready" ? "Ready" : key === "mine" ? "My cases" : key === "waiting" ? "Waiting for documents" : key === "completed" ? "Completed" : key === "processing" ? "Processing" : "All cases"}
              </button>
            ))}
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
                  const waiting = formatWaitingSince(item.queue_entered_at ?? item.ready_at ?? item.updated_at);
                  const rail =
                    status === "needs_review"
                      ? item.findings_count >= 3
                        ? "ledger-rail-danger"
                        : "ledger-rail-warn"
                      : "";
                  const canReview = item.workflow_state === "ready";
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
                      <div className="flex flex-col gap-1">
                        {canReview && item.workflow_state !== "waiting_documents" ? (
                          <Link href={`/ops/applications/${item.application_id}`} className="ledger-link text-sm">
                            {t(locale, "ops.worklist.review")} →
                          </Link>
                        ) : (
                          <span className="text-sm font-semibold text-desk-faint">—</span>
                        )}
                        <QueueOwnershipAction item={item} currentUserId={currentUser.data?.id} onUpdated={() => void worklist.refetch()} />
                        {currentUser.data?.role === "admin" ? <AdminReassignAction item={item} onUpdated={() => void worklist.refetch()} /> : null}
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
