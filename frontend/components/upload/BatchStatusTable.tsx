"use client";

import Link from "next/link";
import { useEffect } from "react";

import { useBatchStatus } from "@/lib/queries";

function displayStatus(item: {
  status: string;
  attempt: number;
  max_attempts?: number;
  failure_reason?: string | null;
}): string {
  const status = item.status.toLowerCase();
  if (status === "queued") return "Waiting";
  if (status === "running" || status === "processing") return "Processing";
  const maxAttempts = item.max_attempts ?? 3;
  if (status === "retrying") return `Retrying (${item.attempt} of ${maxAttempts})`;
  if (status === "completed") return "Completed";
  if (status === "failed") return item.failure_reason ? `Failed: ${item.failure_reason}` : "Failed";
  if (status === "paused") return "Paused";
  if (status === "cancelled") return "Cancelled";
  return item.status;
}

function pillClass(status: string): string {
  const normalized = status.toLowerCase();
  if (normalized === "completed") return "bg-green-100 text-green-800";
  if (normalized === "failed") return "bg-red-100 text-red-800";
  if (normalized === "retrying") return "bg-amber-100 text-amber-800";
  if (normalized === "running" || normalized === "processing") return "bg-blue-100 text-blue-800";
  return "bg-slate-100 text-slate-700";
}

export function BatchStatusTable({ batchId }: { batchId: string }) {
  const { data, isLoading, error } = useBatchStatus(batchId);

  useEffect(() => {
    // Polling is owned by the query hook; nothing extra to do here.
  }, [data]);

  if (isLoading) {
    return <p className="text-sm text-slate-500">Preparing file list…</p>;
  }
  if (error || !data) {
    return <p className="text-sm text-red-600">Could not load batch status.</p>;
  }
  return (
    <div className="overflow-x-auto rounded-xl border border-[#E1E5EB]">
      <table className="w-full text-sm">
        <thead>
          <tr className="bg-[#F6F7FA] text-left text-[11px] uppercase tracking-wider text-[#5C6B7A]">
            <th className="px-4 py-2.5">File</th>
            <th className="px-4 py-2.5">Status</th>
            <th className="px-4 py-2.5">Attempt</th>
            <th className="px-4 py-2.5">Reason</th>
            <th className="px-4 py-2.5">Review</th>
          </tr>
        </thead>
        <tbody>
          {data.items.map((item) => (
            <tr key={item.application_id} className="border-t border-slate-100">
              <td className="px-4 py-2.5 font-medium text-[#16202E]">{item.filename}</td>
              <td className="px-4 py-2.5">
                <span className={`inline-block rounded-full px-2.5 py-1 text-xs font-bold ${pillClass(item.status)}`}>
                  {displayStatus(item)}
                </span>
              </td>
              <td className="px-4 py-2.5 text-slate-600">
                {item.attempt}/{item.max_attempts ?? 3}
              </td>
              <td className="px-4 py-2.5 text-slate-600">
                {item.status.toLowerCase() === "failed" ? item.failure_reason ?? "—" : "—"}
              </td>
              <td className="px-4 py-2.5">
                {item.review_ready ? (
                  <Link
                    className="font-bold text-[#2B4C7E] hover:underline"
                    href={`/applications/${item.application_id}`}
                  >
                    Open review
                  </Link>
                ) : (
                  <span className="text-slate-400">—</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
