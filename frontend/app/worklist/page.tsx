"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { ErrorMessage, InfoMessage, LoadingMessage } from "@/components/Message";
import { Metric } from "@/components/Metric";
import { PageHeader } from "@/components/PageHeader";
import { SortableTable } from "@/components/SortableTable";
import { StatusBadge } from "@/components/StatusBadge";
import { WorklistItem } from "@/lib/api";
import { useWorklist } from "@/lib/queries";

const filters = ["All", "Pending", "Needs Review", "Auto Clean", "Verified"] as const;
type Filter = (typeof filters)[number];

export default function WorklistPage() {
  const worklist = useWorklist();
  const [filter, setFilter] = useState<Filter>("All");
  const [queue, setQueue] = useState<number[]>([]);
  const [queueIndex, setQueueIndex] = useState(0);

  const stats = useMemo(() => {
    const items = worklist.data?.items ?? [];
    return {
      total: items.length,
      needsReview: items.filter(i => ["NEEDS_REVIEW", "CRITICAL"].includes(i.status)).length,
      clean: items.filter(i => i.status === "CLEAN").length,
      pending: items.filter(i => ["uploaded", "processing", "ocr_completed"].includes(i.status)).length,
    };
  }, [worklist.data?.items]);

  const filtered = useMemo(() => {
    const items = worklist.data?.items ?? [];
    return items.filter((item) => matchesFilter(item, filter));
  }, [filter, worklist.data?.items]);

  const queueApplicationId = queue[queueIndex];

  return (
    <>
      <PageHeader title="Reviewer Worklist" description="Manage incoming loan application validations and audit exceptions." />
      {worklist.isLoading ? <LoadingMessage /> : null}
      {worklist.isError ? <ErrorMessage message="Unable to load worklist." /> : null}
      {worklist.data ? (
        <div className="space-y-6">
          {/* Dashboard Summary Cards */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <Metric label="Total Files" value={stats.total} />
            <Metric label="Needs Attention" value={stats.needsReview} />
            <Metric label="Auto-Verified Clean" value={stats.clean} />
            <Metric label="Processing Queue" value={stats.pending} />
          </div>

          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 pt-2">
            <button
              type="button"
              className="px-4 py-2.5 text-sm font-semibold rounded-lg bg-blue-700 hover:bg-blue-600 text-white transition-colors duration-150 shadow-sm active:scale-[0.98] select-none"
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
                  onClick={() => setFilter(item)}
                  className={`rounded-lg border px-4 py-2 text-sm font-semibold transition-all duration-150 ${
                    filter === item
                      ? "border-blue-600 bg-blue-50 text-blue-700 shadow-sm"
                      : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50 hover:text-slate-800"
                  }`}
                >
                  {item}
                </button>
              ))}
            </div>
          </div>
          {queue.length > 0 ? (
            <InfoMessage message={`Review queue: file ${queueIndex + 1} of ${queue.length}.`} />
          ) : null}
          {queueApplicationId ? (
            <Link className="inline-block rounded-lg bg-blue-50 border border-blue-200 hover:bg-blue-100 px-4 py-2 text-sm font-bold text-blue-750 shadow-sm transition-all duration-150" href={`/applications/${queueApplicationId}`}>
              Open queue item
            </Link>
          ) : null}
          {filtered.length === 0 ? (
            <InfoMessage message="No applications found." />
          ) : (
            <SortableTable
              rows={filtered}
              columns={[
                {
                  key: "loan",
                  header: "Loan ID",
                  value: (row) => <Link className="font-bold text-blue-700 hover:text-blue-600 transition-colors duration-150 hover:underline" href={`/applications/${row.id}`}>{row.loan_id}</Link>,
                  sortValue: (row) => row.loan_id,
                },
                { key: "applicant", header: "Applicant", value: (row) => row.applicant_name ?? "-", sortValue: (row) => row.applicant_name },
                { key: "product", header: "Product", value: (row) => row.product_type ?? "-", sortValue: (row) => row.product_type },
                {
                  key: "status",
                  header: "Status",
                  value: (row) => <StatusBadge status={row.status} />,
                  sortValue: (row) => row.status,
                },
                { key: "issues", header: "Issues", value: (row) => row.reviewer_issues, sortValue: (row) => row.reviewer_issues },
                { key: "uploaded", header: "Uploaded", value: (row) => row.created_at, sortValue: (row) => row.created_at },
              ]}
            />
          )}
        </div>
      ) : null}
    </>
  );
}

function matchesFilter(item: WorklistItem, filter: Filter): boolean {
  if (filter === "All") {
    return true;
  }
  if (filter === "Pending") {
    return ["uploaded", "processing", "ocr_completed"].includes(item.status);
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
