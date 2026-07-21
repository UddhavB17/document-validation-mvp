"use client";

import { useProgress } from "@/lib/queries";
import { formatSeconds } from "@/lib/format";
import { LoadingMessage } from "./Message";
import { Metric } from "./Metric";
import { SortableTable } from "./SortableTable";

export function ProgressPanel({ applicationId }: { applicationId: number }) {
  const progress = useProgress(applicationId);

  if (progress.isLoading) {
    return <LoadingMessage message="Loading processing progress..." />;
  }
  if (progress.isError) {
    return null;
  }

  const data = progress.data;
  if (!data) {
    return null;
  }
  const completedPages = data.completed_pages ?? [];

  return (
    <section className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold text-slate-950">Page Processing</h2>
        <p className="text-sm text-slate-600">
          {(data.message ?? "Processing your loan file") +
            `: ${data.processed_pages ?? 0}/${data.total_pages ?? 0} pages processed`}
        </p>
      </div>
      <div className="h-2 rounded bg-slate-200">
        <div className="h-2 rounded bg-blue-600" style={{ width: `${Math.min(data.percentage ?? 0, 100)}%` }} />
      </div>
      <div className="grid grid-cols-4 gap-3">
        <Metric label="Completed" value={`${completedPages.length}/${data.total_pages ?? "-"}`} />
        <Metric label="Digital" value={data.digital_pages ?? "-"} />
        <Metric label="Scanned" value={data.scanned_pages ?? "-"} />
        <Metric label="Status" value={data.status ?? "-"} />
      </div>
      {completedPages.length > 0 ? (
        <SortableTable
          rows={completedPages}
          columns={[
            { key: "page", header: "Page", value: (row) => row.page_number ?? "-", sortValue: (row) => row.page_number },
            { key: "status", header: "Status", value: (row) => row.status ?? "-", sortValue: (row) => row.status },
            { key: "type", header: "Type", value: (row) => row.page_type ?? "-", sortValue: (row) => row.page_type },
            { key: "document", header: "Document", value: (row) => row.document_type ?? "Unknown", sortValue: (row) => row.document_type },
            { key: "time", header: "Time", value: (row) => formatSeconds(row.elapsed_seconds), sortValue: (row) => row.elapsed_seconds },
            { key: "data", header: "Data", value: (row) => row.error ?? summarizeFields(row.extracted_fields) },
          ]}
        />
      ) : (
        <LoadingMessage message="Waiting for page-level results..." />
      )}
    </section>
  );
}

function summarizeFields(fields: Record<string, unknown> | undefined): string {
  if (!fields || Object.keys(fields).length === 0) {
    return "-";
  }
  const visible = Object.fromEntries(
    Object.entries(fields).filter(([key, value]) => !key.startsWith("_") && value !== null && value !== ""),
  );
  const text = JSON.stringify(Object.keys(visible).length ? visible : fields);
  return text.length > 160 ? `${text.slice(0, 157)}...` : text;
}
