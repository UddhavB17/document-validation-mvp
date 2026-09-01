import { ApplicationReview } from "@/lib/api";

export function Verdict({ data }: { data: ApplicationReview }) {
  const status = String(data.application.status ?? "NEEDS_REVIEW");
  const pipelineStatus = String(data.progress?.operational_status ?? "not_started");
  const reviewerCount = data.summary.reviewer_count;
  const highCount = data.summary.high_count;
  let title = "NEEDS REVIEW";
  let detail = `${reviewerCount} issue(s) to check`;
  let classes = "border-amber-300 bg-amber-50 text-amber-900";
  if (pipelineStatus === "stale") {
    title = "STALE";
    detail = "Processing stopped reporting progress; recovery is required";
    classes = "border-red-300 bg-red-50 text-red-900";
  } else if (pipelineStatus === "failed") {
    title = "FAILED";
    detail = "Processing failed; retry before making a decision";
    classes = "border-red-300 bg-red-50 text-red-900";
  } else if (["queued", "processing"].includes(pipelineStatus)) {
    title = "PROCESSING";
    detail = "Validation is not complete";
    classes = "border-blue-300 bg-blue-50 text-blue-900";
  } else if (pipelineStatus === "completed_with_warnings") {
    title = "COMPLETED WITH WARNINGS";
    detail = `${reviewerCount} issue(s) plus page-level processing warnings`;
    classes = "border-amber-300 bg-amber-50 text-amber-900";
  } else if (status === "CLEAN" || (pipelineStatus === "completed" && reviewerCount === 0)) {
    title = "CLEAN";
    detail = "No checklist issues found";
    classes = "border-emerald-300 bg-emerald-50 text-emerald-900";
  } else if (status === "CRITICAL" || highCount > 0) {
    title = "CRITICAL";
    detail = `${highCount || reviewerCount} high-severity issue(s)`;
    classes = "border-red-350 bg-red-50 text-red-900";
  }
  return (
    <div className={`rounded-xl border-l-4 px-5 py-4 font-bold flex items-center justify-between shadow-sm ${classes}`}>
      <div className="flex items-center gap-3">
        <div>
          <div className="text-xs uppercase tracking-wider opacity-70">Audit Result</div>
          <div className="text-sm font-extrabold">{title} — {detail}</div>
        </div>
      </div>
    </div>
  );
}
