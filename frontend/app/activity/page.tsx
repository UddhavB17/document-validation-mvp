"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { ErrorMessage, InfoMessage, LoadingMessage } from "@/components/Message";
import { PageHeader } from "@/components/PageHeader";
import { InlineCount, ReviewStateBadge, formatReviewTimestamp } from "@/components/worklist/reviewDisplay";
import type { Activity } from "@/lib/api";
import { useActivityToday } from "@/lib/queries";

const PAGE_SIZE = 50;

export default function ActivityPage() {
  const activity = useActivityToday();
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);

  useEffect(() => {
    setVisibleCount(PAGE_SIZE);
  }, [activity.data?.rows.length]);

  return (
    <div className="mx-auto max-w-[1600px] space-y-5 animate-fade-in">
      <PageHeader title="My Activity" description="Decisions recorded today by the active reviewer profile." />
      {activity.isLoading ? <LoadingMessage message="Loading today’s activity…" /> : null}
      {activity.isError ? <ErrorMessage message="Unable to load reviewer activity. Refresh to try again." /> : null}
      {activity.data ? (
        activity.data.rows.length === 0 ? (
          <InfoMessage message="No reviewer decisions have been recorded today." />
        ) : (
          <div className="space-y-5">
            <dl className="flex flex-wrap items-center gap-x-5 gap-y-3 border-b border-[#E1E5EB] pb-4" aria-label="Today’s activity counts">
              <InlineCount label="Reviewed today" value={activity.data.total} />
              <InlineCount label="Accepted" value={activity.data.accepted} />
              <InlineCount label="Overridden" value={activity.data.overridden} />
              <InlineCount label="Sent back" value={activity.data.sent_back} />
            </dl>

            <ActivityRows rows={activity.data.rows.slice(0, visibleCount)} />
            {activity.data.rows.length > visibleCount ? (
              <div className="flex items-center justify-between gap-3 border-t border-[#E1E5EB] pt-3">
                <p className="text-xs text-[#5C6B7A]">
                  Showing {Math.min(visibleCount, activity.data.rows.length).toLocaleString("en-IN")} of {activity.data.rows.length.toLocaleString("en-IN")} decisions
                </p>
                <button
                  type="button"
                  onClick={() => setVisibleCount((current) => current + PAGE_SIZE)}
                  className="rounded-lg border border-[#E1E5EB] bg-white px-3.5 py-2 text-sm font-semibold text-[#2B4C7E] shadow-3xs hover:bg-[#EAF0F8] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[#2B4C7E]"
                >
                  Load next {Math.min(PAGE_SIZE, activity.data.rows.length - visibleCount)}
                </button>
              </div>
            ) : null}
          </div>
        )
      ) : null}
    </div>
  );
}

function ActivityRows({ rows }: { rows: Activity["rows"] }) {
  return (
    <div className="overflow-hidden rounded-xl border border-[#E1E5EB] bg-white shadow-3xs">
      <div className="hidden grid-cols-[minmax(120px,.7fr)_minmax(140px,.8fr)_minmax(180px,1.5fr)_minmax(140px,.8fr)_minmax(170px,1fr)] gap-4 border-b border-[#E1E5EB] bg-[#F6F7FA] px-4 py-3 text-[10px] font-bold uppercase tracking-[0.08em] text-[#5C6B7A] md:grid">
        <span>Decision</span>
        <span>Application</span>
        <span>Loan</span>
        <span>Outcome</span>
        <span>Recorded</span>
      </div>
      <ul className="divide-y divide-[#E1E5EB]" aria-label="Reviewer decisions">
        {rows.map((row) => (
          <li key={row.id}>
            <Link
              href={`/applications/${row.application_id}`}
              className="group block px-4 py-3 transition-colors hover:bg-[#EAF0F8]/35 focus-visible:bg-[#EAF0F8]/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[#2B4C7E]"
              aria-label={`Open ${row.loan_id} application`}
            >
              <div className="grid gap-3 md:grid-cols-[minmax(120px,.7fr)_minmax(140px,.8fr)_minmax(180px,1.5fr)_minmax(140px,.8fr)_minmax(170px,1fr)] md:items-center md:gap-4">
                <div>
                  <span className="mb-1 block text-[10px] font-bold uppercase tracking-[0.08em] text-[#5C6B7A] md:hidden">Decision</span>
                  <span className="font-mono text-[12px] font-bold text-[#16202E]">DEC-{String(row.id).padStart(4, "0")}</span>
                </div>
                <div>
                  <span className="mb-1 block text-[10px] font-bold uppercase tracking-[0.08em] text-[#5C6B7A] md:hidden">Application</span>
                  <span className="font-mono text-[12px] font-bold text-[#2B4C7E] group-hover:underline">APP-{String(row.application_id).padStart(4, "0")}</span>
                </div>
                <div>
                  <span className="mb-1 block text-[10px] font-bold uppercase tracking-[0.08em] text-[#5C6B7A] md:hidden">Loan</span>
                  <span className="font-mono text-[13px] font-bold text-[#16202E]">{row.loan_id}</span>
                </div>
                <div>
                  <span className="mb-1 block text-[10px] font-bold uppercase tracking-[0.08em] text-[#5C6B7A] md:hidden">Outcome</span>
                  <ReviewStateBadge status={row.decision} kind="decision" />
                </div>
                <time dateTime={row.decided_at} className="block text-[11px] font-medium leading-5 text-[#5C6B7A]">
                  <span className="mb-1 block text-[10px] font-bold uppercase tracking-[0.08em] md:hidden">Recorded</span>
                  {formatReviewTimestamp(row.decided_at)}
                </time>
              </div>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
