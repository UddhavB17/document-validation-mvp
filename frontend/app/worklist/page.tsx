"use client";

import Link from "next/link";
import { useMemo, useState, useEffect } from "react";

import { ErrorMessage, InfoMessage, LoadingMessage } from "@/components/Message";
import { Metric } from "@/components/Metric";
import { PageHeader } from "@/components/PageHeader";
import { SortableTable } from "@/components/SortableTable";
import { StatusBadge } from "@/components/StatusBadge";
import { WorklistItem } from "@/lib/api";
import { useWorklist } from "@/lib/queries";

const filters = ["All", "Pending", "Recovery", "Needs Review", "Auto Clean", "Verified"] as const;
type Filter = (typeof filters)[number];

function isFilter(value: string): value is Filter {
  return filters.some((filter) => filter === value);
}

export default function WorklistPage() {
  const worklist = useWorklist();
  const [filter, setFilter] = useState<Filter>("All");
  const [queue, setQueue] = useState<number[]>([]);
  const [queueIndex, setQueueIndex] = useState(0);

  // 1. Session Storage Caching for Scroll and Filter
  useEffect(() => {
    const cachedFilter = sessionStorage.getItem("worklist_filter");
    if (cachedFilter && isFilter(cachedFilter)) {
      setFilter(cachedFilter);
    }
  }, []);

  useEffect(() => {
    if (worklist.data) {
      const cachedScrollY = sessionStorage.getItem("worklist_scroll_y");
      if (cachedScrollY) {
        setTimeout(() => {
          window.scrollTo(0, Number(cachedScrollY));
        }, 100);
      }
    }
  }, [worklist.data]);

  // Listener to capture scroll position changes
  useEffect(() => {
    const handleScroll = () => {
      sessionStorage.setItem("worklist_scroll_y", String(window.scrollY));
    };
    window.addEventListener("scroll", handleScroll);
    return () => window.removeEventListener("scroll", handleScroll);
  }, []);

  const handleFilterChange = (newFilter: Filter) => {
    setFilter(newFilter);
    sessionStorage.setItem("worklist_filter", newFilter);
    sessionStorage.setItem("worklist_scroll_y", "0");
    window.scrollTo(0, 0);
  };

  const stats = useMemo(() => {
    const items = worklist.data?.items ?? [];
    return {
      total: items.length,
      needsReview: items.filter(i => i.business_issues > 0).length,
      qualityWarnings: items.filter(i => i.processing_warnings > 0).length,
      clean: items.filter(i => i.status === "CLEAN").length,
      recovery: items.filter(i => i.pipeline_retryable).length,
    };
  }, [worklist.data?.items]);

  const filtered = useMemo(() => {
    const items = worklist.data?.items ?? [];
    return items.filter((item) => matchesFilter(item, filter));
  }, [filter, worklist.data?.items]);

  const queueApplicationId = queue[queueIndex];

  return (
    <div className="space-y-6 max-w-[1600px] mx-auto">
      <PageHeader title="Reviewer Worklist" description="Manage incoming loan application validations and audit exceptions." />
      {worklist.isLoading ? <LoadingMessage /> : null}
      {worklist.isError ? <ErrorMessage message="Unable to load worklist." /> : null}
      {worklist.data ? (
        <div className="space-y-6">
          {/* Dashboard Summary Cards */}
          <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
            <Metric label="Total Files" value={stats.total} />
            <Metric label="Business Exceptions" value={stats.needsReview} />
            <Metric label="Quality Warnings" value={stats.qualityWarnings} />
            <Metric label="Auto-Verified Clean" value={stats.clean} />
            <Metric label="Recovery Needed" value={stats.recovery} />
          </div>

          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 pt-2">
            <button
              type="button"
              className="px-5 py-2.5 text-sm font-semibold rounded-lg bg-[#2B4C7E] hover:bg-[#1E3559] text-white transition-all duration-150 shadow-3xs active:scale-[0.98] select-none cursor-pointer border-none"
              onClick={() => {
                const pending = queueCandidates(worklist.data.items);
                setQueue(pending.map((item) => item.id));
                setQueueIndex(0);
              }}
            >
              Start Review Queue
            </button>
            <div className="flex flex-wrap gap-2">
              {filters.map((item) => (
                <button
                  type="button"
                  key={item}
                  onClick={() => handleFilterChange(item)}
                  className={`rounded-lg border px-4 py-2 text-sm font-semibold transition-all duration-150 cursor-pointer ${
                    filter === item
                      ? "border-[#2B4C7E] bg-[#EAF0F8] text-[#2B4C7E] shadow-3xs"
                      : "border-[#E1E5EB] bg-white text-[#5C6B7A] hover:bg-slate-50 hover:text-[#16202E]"
                  }`}
                >
                  {item}
                </button>
              ))}
            </div>
          </div>
          {queue.length > 0 ? (
            <div className="animate-fade-in">
              <InfoMessage message={`Review queue: file ${queueIndex + 1} of ${queue.length}.`} />
            </div>
          ) : null}
          {queueApplicationId ? (
            <Link className="inline-block rounded-lg bg-[#EAF0F8] border border-[#E1E5EB] hover:bg-[#2B4C7E] hover:text-white px-4 py-2 text-sm font-bold text-[#2B4C7E] shadow-3xs transition-all duration-150" href={`/applications/${queueApplicationId}`}>
              Open queue item
            </Link>
          ) : null}
          {filtered.length === 0 ? (
            <InfoMessage message="No applications found matching the selected filter status." />
          ) : (
            <SortableTable
              rows={filtered}
              columns={[
                {
                  key: "loan",
                  header: "Loan ID",
                  value: (row) => (
                    <Link
                      className="font-mono font-bold text-[#2B4C7E] hover:text-[#1E3559] transition-colors duration-150 hover:underline text-[13.5px]"
                      href={`/applications/${row.id}`}
                    >
                      {row.loan_id}
                    </Link>
                  ),
                  sortValue: (row) => row.loan_id,
                },
                {
                  key: "applicant",
                  header: "Applicant Name",
                  value: (row) => <span className="font-serif font-bold text-slate-800">{row.applicant_name ?? "—"}</span>,
                  sortValue: (row) => row.applicant_name ?? "",
                },
                {
                  key: "product",
                  header: "Product Type",
                  value: (row) => <span className="font-semibold text-slate-650">{row.product_type ?? "—"}</span>,
                  sortValue: (row) => row.product_type ?? "",
                },
                {
                  key: "status",
                  header: "Decision",
                  value: (row) => <StatusBadge status={row.status} />,
                  sortValue: (row) => row.status,
                },
                {
                  key: "pipeline",
                  header: "Pipeline Status",
                  value: (row) => <StatusBadge status={row.pipeline_status} />,
                  sortValue: (row) => row.pipeline_status,
                },
                {
                  key: "anomalies_density",
                  header: "Anomalies Density (Exempt / Warnings)",
                  value: (row) => {
                    const hasBusiness = row.business_issues > 0;
                    const hasWarnings = row.processing_warnings > 0;
                    if (!hasBusiness && !hasWarnings) {
                      return <span className="stamp match text-[9px] py-0 px-1.5 rotate-0">CLEAN</span>;
                    }
                    return (
                      <div className="flex items-center gap-1.5 flex-wrap">
                        {hasBusiness && (
                          <span className="stamp mismatch text-[9.5px] py-0.5 px-2 rotate-0">
                            {row.business_issues} EXC
                          </span>
                        )}
                        {hasWarnings && (
                          <span className="stamp attention text-[9.5px] py-0.5 px-2 rotate-0">
                            {row.processing_warnings} WARN
                          </span>
                        )}
                      </div>
                    );
                  },
                  sortValue: (row) => row.business_issues * 100 + row.processing_warnings,
                },
                {
                  key: "uploaded",
                  header: "Uploaded Date",
                  value: (row) => <span className="font-mono text-slate-600 text-[11.5px]">{row.created_at}</span>,
                  sortValue: (row) => row.created_at,
                },
              ]}
            />
          )}
        </div>
      ) : null}
    </div>
  );
}

function matchesFilter(item: WorklistItem, filter: Filter): boolean {
  if (filter === "All") {
    return true;
  }
  if (filter === "Pending") {
    return ["queued", "processing"].includes(item.pipeline_status);
  }
  if (filter === "Recovery") {
    return item.pipeline_retryable;
  }
  if (filter === "Needs Review") {
    return ["NEEDS_REVIEW", "CRITICAL"].includes(item.status);
  }
  if (filter === "Auto Clean") {
    return item.status === "CLEAN";
  }
  if (filter === "Verified") {
    return ["verified", "verified_with_override"].includes(item.status);
  }
  return true;
}

function queueCandidates(items: WorklistItem[]): WorklistItem[] {
  return items
    .filter((item) => ["NEEDS_REVIEW", "CRITICAL", "ocr_completed", "checklist_run"].includes(item.status))
    .sort((left, right) => left.created_at.localeCompare(right.created_at));
}
