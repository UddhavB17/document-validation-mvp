"use client";

import { useProgress, useReprocessApplication, useRestartApplication, useResumeApplication } from "@/lib/queries";
import { formatSeconds } from "@/lib/format";
import { summarizePublicFields } from "@/components/applications/reviewUtils";
import { ErrorMessage, InfoMessage, LoadingMessage } from "./Message";
import { Metric } from "./Metric";
import { SortableTable } from "./SortableTable";

// Shows live processing state for an uploaded application and exposes the
// existing recovery action when the backend marks that job retryable.
export function ProgressPanel({ applicationId }: { applicationId: number }) {
  const progress = useProgress(applicationId);
  const reprocess = useReprocessApplication(applicationId);
  const resume = useResumeApplication(applicationId);
  const restart = useRestartApplication(applicationId);

  function handleRestartFromBeginning() {
    const confirmed = window.confirm(
      "Restart processing from page 1? Completed pages will be processed again. This cannot be undone.",
    );
    if (confirmed) {
      restart.mutate(false);
    }
  }

  if (progress.isLoading) {
    return (
      <section className="space-y-3" role="status" aria-label="Loading processing progress">
        <div className="h-4 w-44 animate-pulse rounded bg-slate-200" />
        <div className="h-2 animate-pulse rounded bg-slate-100" />
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {Array.from({ length: 4 }).map((_, index) => <div key={index} className="h-16 animate-pulse rounded-lg bg-slate-100" />)}
        </div>
        <LoadingMessage message="Loading processing progress..." />
      </section>
    );
  }
  if (progress.isError) {
    return (
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800" role="alert">
        <span>Processing progress could not be loaded.</span>
        <button type="button" onClick={() => void progress.refetch()} className="rounded border border-red-300 bg-white px-3 py-1.5 text-xs font-bold text-red-800 hover:bg-red-100">Retry</button>
      </div>
    );
  }

  const progressData = progress.data;
  if (!progressData) {
    return null;
  }
  const completedPages = progressData.completed_pages ?? [];
  const visibleCompletedPages = completedPages.slice(0, 50);
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
        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            disabled={reprocess.isPending}
            onClick={() => void reprocess.mutate()}
            className="rounded-lg bg-blue-700 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-600 disabled:bg-slate-300"
          >
            {reprocess.isPending ? "Queuing recovery..." : "Retry processing"}
          </button>
          <button
            type="button"
            disabled={resume.isPending}
            onClick={() => void resume.mutate()}
            className="rounded-lg border border-blue-700 bg-white px-4 py-2 text-sm font-semibold text-blue-700 shadow-sm hover:bg-blue-50 disabled:opacity-50"
          >
            {resume.isPending ? "Resuming..." : "Resume from checkpoint"}
          </button>
          <button
            type="button"
            disabled={restart.isPending}
            onClick={handleRestartFromBeginning}
            className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-700 shadow-sm hover:bg-slate-50 disabled:opacity-50"
          >
            {restart.isPending ? "Restarting..." : "Restart from beginning"}
          </button>
          <span className="text-xs font-medium text-slate-500">Resume continues from the last completed page; restart reprocesses every page. A new audit event is recorded.</span>
        </div>
      ) : null}
      {reprocess.isError ? <ErrorMessage message={reprocess.error.message} /> : null}
      {resume.isError ? <ErrorMessage message={resume.error.message} /> : null}
      {restart.isError ? <ErrorMessage message={restart.error.message} /> : null}
      <div className="h-2 rounded bg-slate-200">
        <div className="h-2 rounded bg-blue-600" style={{ width: `${Math.min(progressData.percentage ?? 0, 100)}%` }} />
      </div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Metric label="Completed" value={`${completedPages.length}/${progressData.total_pages ?? "-"}`} />
        <Metric label="Digital" value={progressData.digital_pages ?? "-"} />
        <Metric label="Scanned" value={progressData.scanned_pages ?? "-"} />
        <Metric label="Pipeline Status" value={operationalStatus} />
      </div>
      {completedPages.length > 0 ? (
        <SortableTable
          rows={visibleCompletedPages}
          columns={[
            { key: "page", header: "Page", value: (row) => row.page_number ?? "-", sortValue: (row) => row.page_number },
            { key: "status", header: "Status", value: (row) => row.status ?? "-", sortValue: (row) => row.status },
            { key: "type", header: "Type", value: (row) => row.page_type ?? "-", sortValue: (row) => row.page_type },
            { key: "document", header: "Document", value: (row) => row.document_type ?? "Unknown", sortValue: (row) => row.document_type },
            { key: "time", header: "Time", value: (row) => formatSeconds(row.elapsed_seconds), sortValue: (row) => row.elapsed_seconds },
            { key: "data", header: "Data", value: (row) => row.error ?? summarizePublicFields(row.extracted_fields) },
          ]}
        />
      ) : (
        <LoadingMessage message="Waiting for page-level results..." />
      )}
      {completedPages.length > visibleCompletedPages.length ? (
        <p className="text-xs font-medium text-slate-500">Showing the first 50 completed pages. Open the Processing tab to search the full page event history.</p>
      ) : null}
    </section>
  );
}
