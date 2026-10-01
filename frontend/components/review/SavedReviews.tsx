"use client";

import Link from "next/link";

import type { OpsReviewHistoryFile } from "@/lib/api";
import { useOpsReviewHistory } from "@/lib/queries";

function formatWhen(value: string | null): string {
  if (!value) return "Date unknown";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Date unknown";
  return date.toLocaleString("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function pagesLabel(pages: number[]): string {
  if (pages.length === 0) return "No page";
  if (pages.length === 1) return `p. ${pages[0]}`;
  return `p. ${pages[0]}+`;
}

function FindingRow({
  title,
  detail,
  severity,
  pages,
}: {
  title: string;
  detail: string;
  severity: "HIGH" | "MEDIUM" | "LOW";
  pages: number[];
}) {
  return (
    <li className="reviewer-saved__finding">
      <span className={`reviewer-severity reviewer-severity--${severity}`} aria-hidden="true" />
      <div>
        <p className="reviewer-saved__finding-title">{title}</p>
        <p className="reviewer-saved__finding-detail" title={detail}>
          {detail}
        </p>
      </div>
      <span className="reviewer-saved__pages">{pagesLabel(pages)}</span>
    </li>
  );
}

function SavedCard({ file }: { file: OpsReviewHistoryFile }) {
  const reviewers =
    file.reviewers.map((person) => person.name).filter(Boolean).join(", ") || "Unknown reviewer";
  const visible = file.problems.slice(0, 5);
  const remaining = Math.max(0, file.problems.length - visible.length);

  return (
    <li className="reviewer-saved__card">
      <div className="reviewer-saved__top">
        <div className="reviewer-saved__identity">
          <h3>{file.applicant_name || "Applicant"}</h3>
          <p className="reviewer-saved__loan">{file.loan_id || "No loan id"}</p>
          <div className="reviewer-saved__meta">
            <span>
              Reviewed by <strong>{reviewers}</strong>
            </span>
            <span>{formatWhen(file.reviewed_at)}</span>
            <span>
              <strong>{file.problem_count}</strong>{" "}
              {file.problem_count === 1 ? "problem saved" : "problems saved"}
            </span>
          </div>
        </div>
        <Link
          href={`/review/applications/${file.application_id}?tab=reviewed`}
          className="reviewer-saved__open"
        >
          Open file
        </Link>
      </div>
      {visible.length > 0 ? (
        <ul className="reviewer-saved__findings" aria-label="Problems found">
          {visible.map((problem) => (
            <FindingRow
              key={problem.item_id}
              title={problem.title.en}
              detail={problem.detail.en}
              severity={problem.severity}
              pages={problem.pages}
            />
          ))}
        </ul>
      ) : (
        <p className="reviewer-saved__more">No problem details were stored for this review.</p>
      )}
      {remaining > 0 ? (
        <p className="reviewer-saved__more">
          {remaining} more problem{remaining === 1 ? "" : "s"} on this file. Open the file to see
          the full saved set.
        </p>
      ) : null}
    </li>
  );
}

export function SavedReviews() {
  const history = useOpsReviewHistory(50);
  const files = history.data?.files ?? [];

  if (history.isLoading) {
    return (
      <div className="reviewer-empty" role="status">
        <p className="reviewer-empty__title">Loading saved reviews</p>
        <p className="reviewer-empty__body">Pulling finished file reviews from the cloud database.</p>
      </div>
    );
  }

  if (history.isError) {
    return (
      <div className="reviewer-empty" role="alert">
        <p className="reviewer-empty__title">Could not load saved reviews</p>
        <p className="reviewer-empty__body">Check the API connection, then try again.</p>
      </div>
    );
  }

  if (files.length === 0) {
    return (
      <div className="reviewer-empty" role="status">
        <p className="reviewer-empty__title">No saved reviews yet</p>
        <p className="reviewer-empty__body">
          When you finish a file in the queue and choose Save all findings, it will appear here with
          the reviewer name and the problems that were kept.
        </p>
      </div>
    );
  }

  return (
    <section aria-label="Saved reviews">
      <div className="reviewer__section-head">
        <div>
          <h2 className="reviewer__section-title">Finished reviews</h2>
          <p className="reviewer__section-note">
            Each card is one completed file: who reviewed it, when, and the problems found.
          </p>
        </div>
      </div>
      <ul className="reviewer-saved">
        {files.map((file) => (
          <SavedCard key={file.application_id} file={file} />
        ))}
      </ul>
    </section>
  );
}
