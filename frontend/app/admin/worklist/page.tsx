"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";

import { ErrorMessage, InfoMessage, LoadingMessage } from "@/components/Message";
import { PageHeader } from "@/components/PageHeader";
import {
  ExceptionSummary,
  InlineCount,
  ReviewStateBadge,
  formatReviewTimestamp,
  humanizeReviewState,
} from "@/components/worklist/reviewDisplay";
import type { WorklistItem } from "@/lib/api";
import { useResumeApplication, useWorklist } from "@/lib/queries";
import { startReviewQueue } from "@/lib/reviewQueue";
import { getActionableReviewItems, matchesWorklistFilter, sortWorklistItems } from "@/lib/worklistPolicy";

const PAGE_SIZE = 50;
const EMPTY_WORKLIST: WorklistItem[] = [];
const DEFAULT_FILTER: WorklistFilter = "review";
const DEFAULT_SORT: WorklistSort = "priority";

const WORKLIST_FILTERS = [
  { value: "review", label: "Review now" },
  { value: "processing", label: "Processing" },
  { value: "recovery", label: "Recovery" },
  { value: "closed", label: "Closed" },
  { value: "all", label: "All" },
] as const;

const WORKLIST_SORTS = [
  { value: "priority", label: "Priority" },
  { value: "received_asc", label: "Oldest received" },
  { value: "received_desc", label: "Newest received" },
] as const;

type WorklistFilter = (typeof WORKLIST_FILTERS)[number]["value"];
type WorklistSort = (typeof WORKLIST_SORTS)[number]["value"];

export default function WorklistPage() {
  return (
    <Suspense fallback={<WorklistLoading />}>
      <WorklistContent />
    </Suspense>
  );
}

function WorklistContent() {
  const worklist = useWorklist();
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);

  const search = searchParams.get("search") ?? "";
  const selectedFilter = parseFilter(searchParams.get("filter"));
  const selectedSort = parseSort(searchParams.get("sort"));
  const items = worklist.data?.items ?? EMPTY_WORKLIST;

  const updateUrl = useCallback(
    (updates: { search?: string; filter?: WorklistFilter; sort?: WorklistSort }) => {
      const nextParams = new URLSearchParams(searchParams.toString());
      if (updates.search !== undefined) {
        if (updates.search.trim()) {
          nextParams.set("search", updates.search);
        } else {
          nextParams.delete("search");
        }
      }
      if (updates.filter !== undefined) {
        nextParams.set("filter", updates.filter);
      }
      if (updates.sort !== undefined) {
        nextParams.set("sort", updates.sort);
      }
      const nextQuery = nextParams.toString();
      router.replace(nextQuery ? `${pathname}?${nextQuery}` : pathname, { scroll: false });
    },
    [pathname, router, searchParams],
  );

  const filteredItems = useMemo(() => {
    return sortWorklistItems(
      items.filter((item) => matchesWorklistFilter(item, selectedFilter) && matchesSearch(item, search)),
      selectedSort,
    );
  }, [items, search, selectedFilter, selectedSort]);

  const queueItems = useMemo(
    () => getActionableReviewItems(items, search),
    [items, search],
  );

  const counts = useMemo(
    () => ({
      review: items.filter((item) => matchesWorklistFilter(item, "review")).length,
      recovery: items.filter((item) => matchesWorklistFilter(item, "recovery")).length,
      processing: items.filter((item) => matchesWorklistFilter(item, "processing")).length,
    }),
    [items],
  );

  useEffect(() => {
    setVisibleCount(PAGE_SIZE);
  }, [search, selectedFilter, selectedSort]);

  const handleReviewNext = () => {
    const snapshot = startReviewQueue(queueItems.map((item) => item.id));
    const nextCaseId = snapshot.caseIds[snapshot.position];
    if (nextCaseId !== undefined) {
      router.push(`/admin/applications/${nextCaseId}`);
    }
  };

  return (
    <div className="mx-auto max-w-[1600px] space-y-5 animate-fade-in">
      <div className="flex flex-col gap-4 border-b border-slate-200 pb-4 lg:flex-row lg:items-end lg:justify-between">
        <PageHeader title="Reviewer Worklist" description="The next file to act on, with recovery and processing states visible at a glance." />
        <button
          type="button"
          onClick={handleReviewNext}
          disabled={queueItems.length === 0}
          className="rounded-lg bg-[#2B4C7E] px-5 py-2.5 text-sm font-bold text-white shadow-3xs transition-colors hover:bg-[#1E3559] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#2B4C7E] disabled:cursor-not-allowed disabled:bg-slate-300"
        >
          Review next ({queueItems.length})
        </button>
      </div>

      {worklist.isLoading ? <LoadingMessage message="Loading review queue…" /> : null}
      {worklist.isError ? <ErrorMessage message="Unable to load the review queue. Refresh to try again." /> : null}

      {worklist.data ? (
        <div className="space-y-5">
          <dl className="flex flex-wrap items-center gap-x-5 gap-y-3 border-b border-[#E1E5EB] pb-4" aria-label="Worklist counts">
            <InlineCount label="Review now" value={counts.review} />
            <InlineCount label="Recovery" value={counts.recovery} />
            <InlineCount label="Processing" value={counts.processing} />
          </dl>

          <section className="space-y-3" aria-label="Worklist filters and search">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
              <div className="relative block min-w-0 flex-1 lg:max-w-xl">
                <label htmlFor="worklist-search" className="sr-only">Search worklist</label>
                <input
                  id="worklist-search"
                  type="search"
                  value={search}
                  onChange={(event) => updateUrl({ search: event.target.value })}
                  placeholder="Search loan, applicant, product, or state"
                  className="w-full rounded-lg border border-[#E1E5EB] bg-white px-4 py-2.5 pr-10 text-sm text-[#16202E] shadow-3xs outline-none transition focus:border-[#2B4C7E] focus:ring-2 focus:ring-[#EAF0F8]"
                />
                {search ? (
                  <button
                    type="button"
                    onClick={() => updateUrl({ search: "" })}
                    aria-label="Clear search"
                    className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-lg leading-none text-[#5C6B7A] hover:bg-slate-100 hover:text-[#16202E] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#2B4C7E]"
                  >
                    ×
                  </button>
                ) : null}
              </div>
              <label className="flex items-center gap-2 text-xs font-bold uppercase tracking-[0.08em] text-[#5C6B7A]">
                <span>Sort</span>
                <select
                  value={selectedSort}
                  onChange={(event) => updateUrl({ sort: parseSort(event.target.value) })}
                  className="rounded-lg border border-[#E1E5EB] bg-white px-3 py-2 text-sm font-semibold normal-case tracking-normal text-[#16202E] shadow-3xs outline-none focus:border-[#2B4C7E] focus:ring-2 focus:ring-[#EAF0F8]"
                >
                  {WORKLIST_SORTS.map((option) => (
                    <option key={option.value} value={option.value}>{option.label}</option>
                  ))}
                </select>
              </label>
            </div>

            <div className="flex flex-wrap gap-2" aria-label="Filter worklist">
              {WORKLIST_FILTERS.map((filter) => (
                <button
                  type="button"
                  key={filter.value}
                  aria-pressed={selectedFilter === filter.value}
                  onClick={() => updateUrl({ filter: filter.value })}
                  className={`rounded-lg border px-3.5 py-2 text-sm font-semibold transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[#2B4C7E] ${
                    selectedFilter === filter.value
                      ? "border-[#2B4C7E] bg-[#EAF0F8] text-[#2B4C7E]"
                      : "border-[#E1E5EB] bg-white text-[#5C6B7A] hover:bg-slate-50 hover:text-[#16202E]"
                  }`}
                >
                  {filter.label}
                </button>
              ))}
            </div>
          </section>

          {filteredItems.length === 0 ? (
            <InfoMessage message={search ? "No cases match this search and filter." : "No cases are in this view."} />
          ) : (
            <>
              <WorklistRows items={filteredItems.slice(0, visibleCount)} queueIds={queueItems.map((item) => item.id)} />
              {filteredItems.length > visibleCount ? (
                <div className="flex items-center justify-between gap-3 border-t border-[#E1E5EB] pt-3">
                  <p className="text-xs text-[#5C6B7A]">
                    Showing {Math.min(visibleCount, filteredItems.length).toLocaleString("en-IN")} of {filteredItems.length.toLocaleString("en-IN")} cases
                  </p>
                  <button
                    type="button"
                    onClick={() => setVisibleCount((current) => current + PAGE_SIZE)}
                    className="rounded-lg border border-[#E1E5EB] bg-white px-3.5 py-2 text-sm font-semibold text-[#2B4C7E] shadow-3xs hover:bg-[#EAF0F8] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[#2B4C7E]"
                  >
                    Load next {Math.min(PAGE_SIZE, filteredItems.length - visibleCount)}
                  </button>
                </div>
              ) : null}
            </>
          )}
        </div>
      ) : null}
    </div>
  );
}

function WorklistRows({ items, queueIds }: { items: WorklistItem[]; queueIds: number[] }) {
  return (
    <div className="overflow-hidden rounded-xl border border-[#E1E5EB] bg-white shadow-3xs">
      <div className="hidden grid-cols-[minmax(220px,1.4fr)_minmax(135px,.8fr)_minmax(190px,1.2fr)_minmax(130px,.8fr)_minmax(145px,.9fr)_minmax(160px,.9fr)] gap-4 border-b border-[#E1E5EB] bg-[#F6F7FA] px-4 py-3 text-[10px] font-bold uppercase tracking-[0.08em] text-[#5C6B7A] md:grid">
        <span>Loan / applicant</span>
        <span>Product</span>
        <span>Exceptions</span>
        <span>Case state</span>
        <span>Processing</span>
        <span>Received</span>
      </div>
      <ul className="divide-y divide-[#E1E5EB]" aria-label="Review cases">
        {items.map((item) => (
          <li key={item.id}>
            <Link
              href={`/admin/applications/${item.id}`}
              onClick={() => {
                const position = queueIds.indexOf(item.id);
                if (position >= 0) startReviewQueue(queueIds, position);
              }}
              className="group block px-4 py-3 transition-colors hover:bg-[#EAF0F8]/35 focus-visible:bg-[#EAF0F8]/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[#2B4C7E]"
              aria-label={`Open ${item.loan_id}, ${item.applicant_name ?? "unnamed applicant"}`}
            >
              <div className="grid gap-3 md:grid-cols-[minmax(220px,1.4fr)_minmax(135px,.8fr)_minmax(190px,1.2fr)_minmax(130px,.8fr)_minmax(145px,.9fr)_minmax(160px,.9fr)] md:items-center md:gap-4">
                <div className="min-w-0">
                  <span className="mb-1 block text-[10px] font-bold uppercase tracking-[0.08em] text-[#5C6B7A] md:hidden">Loan / applicant</span>
                  <p className="truncate font-mono text-[13px] font-bold text-[#2B4C7E] group-hover:underline">{item.loan_id}</p>
                  <p className="truncate text-[13px] font-semibold text-[#16202E]">{item.applicant_name ?? "Unnamed applicant"}</p>
                </div>
                <div className="min-w-0">
                  <span className="mb-1 block text-[10px] font-bold uppercase tracking-[0.08em] text-[#5C6B7A] md:hidden">Product</span>
                  <p className="truncate text-[12px] font-semibold text-[#16202E]">{item.product_type ?? "—"}</p>
                </div>
                <div className="min-w-0">
                  <span className="mb-1 block text-[10px] font-bold uppercase tracking-[0.08em] text-[#5C6B7A] md:hidden">Exceptions</span>
                  <ExceptionSummary businessIssues={item.business_issues} processingWarnings={item.processing_warnings} />
                </div>
                <div>
                  <span className="mb-1 block text-[10px] font-bold uppercase tracking-[0.08em] text-[#5C6B7A] md:hidden">Case state</span>
                  <ReviewStateBadge status={item.status} kind="case" />
                </div>
                <div>
                  <span className="mb-1 block text-[10px] font-bold uppercase tracking-[0.08em] text-[#5C6B7A] md:hidden">Processing</span>
                  <ReviewStateBadge status={item.pipeline_status} kind="processing" />
                  <ProcessingProgress item={item} />
                  <WorklistResumeButton item={item} />
                </div>
                <time dateTime={item.created_at} className="block text-[11px] font-medium leading-5 text-[#5C6B7A]">
                  <span className="mb-1 block text-[10px] font-bold uppercase tracking-[0.08em] md:hidden">Received</span>
                  {formatReviewTimestamp(item.created_at)}
                </time>
              </div>
              <p className="mt-2 text-[11px] text-[#5C6B7A] md:hidden">
                {humanizeReviewState(item.status, "case")} · {humanizeReviewState(item.pipeline_status, "processing")}
              </p>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}

function ProcessingProgress({ item }: { item: WorklistItem }) {
  const processed = item.pipeline_processed_pages ?? null;
  const total = item.pipeline_total_pages ?? null;
  if (processed === null || total === null || total <= 0) {
    return null;
  }
  const percentage = item.pipeline_percentage ?? Math.round((processed / total) * 100);
  return (
    <div className="mt-1.5 min-w-0">
      <p className="font-mono text-[11px] font-bold text-[#16202E]">
        {processed}/{total} pages
      </p>
      <div className="mt-1 h-1.5 overflow-hidden rounded bg-slate-200" role="progressbar" aria-valuenow={percentage} aria-valuemin={0} aria-valuemax={100} aria-label={`Processing progress for ${item.loan_id}`}>
        <div className="h-1.5 rounded bg-[#2B4C7E]" style={{ width: `${Math.min(Math.max(percentage, 0), 100)}%` }} />
      </div>
    </div>
  );
}

function WorklistResumeButton({ item }: { item: WorklistItem }) {
  const resume = useResumeApplication(item.id);
  if (!item.pipeline_retryable) {
    return null;
  }
  return (
    <div className="mt-1.5">
      <button
        type="button"
        disabled={resume.isPending}
        onClick={(event) => {
          event.preventDefault();
          event.stopPropagation();
          resume.mutate();
        }}
        className="rounded-md border border-blue-700 bg-white px-2.5 py-1 text-[11px] font-bold text-blue-700 hover:bg-blue-50 disabled:opacity-50"
      >
        {resume.isPending ? "Resuming…" : "Resume"}
      </button>
      {resume.isError ? (
        <p className="mt-1 text-[11px] font-semibold text-red-700" role="alert">
          {resume.error.message}
        </p>
      ) : null}
    </div>
  );
}

function WorklistLoading() {
  return (
    <div className="mx-auto max-w-[1600px] space-y-5">
      <PageHeader title="Reviewer Worklist" description="The next file to act on, with recovery and processing states visible at a glance." />
      <LoadingMessage message="Loading review queue…" />
    </div>
  );
}

function parseFilter(value: string | null): WorklistFilter {
  return WORKLIST_FILTERS.some((filter) => filter.value === value) ? (value as WorklistFilter) : DEFAULT_FILTER;
}

function parseSort(value: string | null): WorklistSort {
  return WORKLIST_SORTS.some((sort) => sort.value === value) ? (value as WorklistSort) : DEFAULT_SORT;
}

function matchesSearch(item: WorklistItem, search: string): boolean {
  const query = search.trim().toLowerCase();
  if (!query) {
    return true;
  }
  return [
    item.loan_id,
    item.applicant_name,
    item.product_type,
    item.status,
    item.pipeline_status,
    humanizeReviewState(item.status, "case"),
    humanizeReviewState(item.pipeline_status, "processing"),
  ].some((value) => String(value ?? "").toLowerCase().includes(query));
}
