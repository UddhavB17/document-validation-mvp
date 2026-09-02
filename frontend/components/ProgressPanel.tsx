"use client";

import { useProgress, useReprocessApplication } from "@/lib/queries";
import { formatSeconds } from "@/lib/format";
import { ErrorMessage, InfoMessage, LoadingMessage } from "./Message";
import { Metric } from "./Metric";
import { SortableTable } from "./SortableTable";

// Shows live processing state for an uploaded application and exposes the
// existing recovery action when the backend marks that job retryable.
export function ProgressPanel({ applicationId }: { applicationId: number }) {
  const progress = useProgress(applicationId);
  const reprocess = useReprocessApplication(applicationId);

  if (progress.isLoading) {
    return <LoadingMessage message="Loading processing progress..." />;
  }
  if (progress.isError) {
    return null;
  }

  const progressData = progress.data;
  if (!progressData) {
    return null;
  }
  const completedPages = progressData.completed_pages ?? [];
  const operationalStatus = progressData.operational_status ?? progressData.status ?? "unknown";

  return (
    <section className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold text-slate-950">Page Processing</h2>
        <p className="text-sm text-slate-600">
          {(progressData.message ?? "Processing your loan file") +
            `: ${progressData.processed_pages ?? 0}/${progressData.total_pages ?? 0} pages processed`}
        </p>
      </div>
      {operationalStatus === "stale" ? (
        <ErrorMessage message="Processing has not reported progress within the expected window. The job is marked stale and can be safely retried." />
      ) : null}
      {operationalStatus === "failed" ? (
        <ErrorMessage message={progressData.error ?? "Processing failed. The original PDF is available for a recovery run."} />
      ) : null}
      {operationalStatus === "completed_with_warnings" ? (
        <InfoMessage message="Processing completed with page-level warnings. Review the quality warnings below or run the file again." />
      ) : null}
      {progressData.retryable ? (
        <div className="flex items-center gap-3">
          <button
            type="button"
            disabled={reprocess.isPending}
            onClick={() => reprocess.mutate()}
            className="rounded-lg bg-blue-700 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-600 disabled:bg-slate-300"
          >
            {reprocess.isPending ? "Queuing recovery..." : "Retry processing"}
          </button>
          <span className="text-xs font-medium text-slate-500">Reprocesses the stored source PDF and records a new audit event.</span>
        </div>
      ) : null}
      {reprocess.isError ? <ErrorMessage message={reprocess.error.message} /> : null}
      <div className="h-2 rounded bg-slate-200">
        <div className="h-2 rounded bg-blue-600" style={{ width: `${Math.min(progressData.percentage ?? 0, 100)}%` }} />
      </div>
      <div className="grid grid-cols-4 gap-3">
        <Metric label="Completed" value={`${completedPages.length}/${progressData.total_pages ?? "-"}`} />
        <Metric label="Digital" value={progressData.digital_pages ?? "-"} />
        <Metric label="Scanned" value={progressData.scanned_pages ?? "-"} />
        <Metric label="Pipeline Status" value={operationalStatus} />
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
  const visibleFields = Object.fromEntries(
    Object.entries(fields).filter(([key, value]) => !key.startsWith("_") && value !== null && value !== ""),
  );
  const text = JSON.stringify(Object.keys(visibleFields).length ? visibleFields : fields);
  return text.length > 160 ? `${text.slice(0, 157)}...` : text;
}
