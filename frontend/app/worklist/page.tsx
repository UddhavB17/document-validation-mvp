"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { ErrorMessage, InfoMessage, LoadingMessage } from "@/components/Message";
import { PageHeader } from "@/components/PageHeader";
import { SortableTable } from "@/components/SortableTable";
import { WorklistItem } from "@/lib/api";
import { statusTone } from "@/lib/format";
import { useWorklist } from "@/lib/queries";

const filters = ["All", "Pending", "Needs Review", "Auto Clean", "Verified"] as const;
type Filter = (typeof filters)[number];

export default function WorklistPage() {
  const worklist = useWorklist();
  const [filter, setFilter] = useState<Filter>("All");
  const [queue, setQueue] = useState<number[]>([]);
  const [queueIndex, setQueueIndex] = useState(0);

  const filtered = useMemo(() => {
    const items = worklist.data?.items ?? [];
    return items.filter((item) => matchesFilter(item, filter));
  }, [filter, worklist.data?.items]);

  const queueApplicationId = queue[queueIndex];

  return (
    <>
      <PageHeader title="Reviewer Worklist" />
      {worklist.isLoading ? <LoadingMessage /> : null}
      {worklist.isError ? <ErrorMessage message="Unable to load worklist." /> : null}
      {worklist.data ? (
        <div className="space-y-5">
          <div className="flex items-center justify-between gap-4">
            <button
              type="button"
              className="rounded bg-blue-700 px-4 py-2 text-sm font-medium text-white"
              onClick={() => {
                const pending = queueCandidates(worklist.data.items);
                setQueue(pending.map((item) => item.id));
                setQueueIndex(0);
              }}
            >
              Start Review Queue
            </button>
            <div className="flex gap-2">
              {filters.map((item) => (
                <button
                  type="button"
                  key={item}
                  onClick={() => setFilter(item)}
                  className={`rounded border px-3 py-1.5 text-sm ${
                    filter === item ? "border-blue-700 bg-blue-50 text-blue-700" : "border-slate-300 bg-white text-slate-700"
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
            <Link className="inline-block rounded bg-blue-700 px-4 py-2 text-sm font-medium text-white" href={`/applications/${queueApplicationId}`}>
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
                  value: (row) => <Link className="font-medium text-blue-700" href={`/applications/${row.id}`}>{row.loan_id}</Link>,
                  sortValue: (row) => row.loan_id,
                },
                { key: "applicant", header: "Applicant", value: (row) => row.applicant_name ?? "-", sortValue: (row) => row.applicant_name },
                { key: "product", header: "Product", value: (row) => row.product_type ?? "-", sortValue: (row) => row.product_type },
                {
                  key: "status",
                  header: "Status",
                  value: (row) => <span className={`font-medium ${statusTone(row.status)}`}>{row.status}</span>,
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
