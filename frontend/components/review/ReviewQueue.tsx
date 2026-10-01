"use client";

import type { OpsWorklistItem } from "@/lib/api";
import { usePortalWorklist } from "@/lib/queries";

function appLabel(applicationId: number): string {
  return `APP-${String(applicationId).padStart(4, "0")}`;
}

function statusLabel(status: OpsWorklistItem["status"]): { label: string; className: string } {
  switch (status) {
    case "clean":
      return { label: "Clear", className: "reviewer-pill reviewer-pill--clean" };
    case "processing":
      return { label: "Processing", className: "reviewer-pill reviewer-pill--processing" };
    case "failed":
      return { label: "Failed", className: "reviewer-pill reviewer-pill--failed" };
    case "needs_review":
    default:
      return { label: "Needs review", className: "reviewer-pill reviewer-pill--review" };
  }
}

export function ReviewQueue({
  onOpen,
  title = "Waiting for review",
  note = "Open a file to check findings, then save what you verified.",
}: {
  onOpen: (applicationId: number) => void;
  title?: string;
  note?: string;
}) {
  const worklist = usePortalWorklist();
  const rows = worklist.data?.applications ?? [];

  if (worklist.isLoading) {
    return (
      <div className="reviewer-empty" role="status">
        <p className="reviewer-empty__title">Loading the queue</p>
        <p className="reviewer-empty__body">Fetching loan files that still need a human look.</p>
      </div>
    );
  }

  if (rows.length === 0) {
    return (
      <div className="reviewer-empty" role="status">
        <p className="reviewer-empty__title">Queue is clear</p>
        <p className="reviewer-empty__body">
          There are no files waiting for review right now. Saved reviews will still show finished
          work.
        </p>
      </div>
    );
  }

  return (
    <section aria-label="Files waiting for review">
      <div className="reviewer__section-head">
        <div>
          <h2 className="reviewer__section-title">{title}</h2>
          <p className="reviewer__section-note">{note}</p>
        </div>
      </div>
      <ul className="reviewer-queue">
        {rows.map((item) => {
          const status = statusLabel(item.status);
          return (
            <li key={item.application_id}>
              <button
                type="button"
                className="reviewer-queue__row"
                onClick={() => onOpen(item.application_id)}
              >
                <div>
                  <p className="reviewer-queue__name">{item.applicant_name || "Applicant"}</p>
                  <p className="reviewer-queue__meta">{appLabel(item.application_id)}</p>
                </div>
                <div>
                  <p className="reviewer-queue__loan">{item.loan_id || "No loan id"}</p>
                  <p className="reviewer-queue__meta">
                    {item.findings_count > 0
                      ? `${item.findings_count} finding${item.findings_count === 1 ? "" : "s"}`
                      : "No open findings"}
                  </p>
                </div>
                <span className={status.className}>{status.label}</span>
                <span className="reviewer-queue__open">Open</span>
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
