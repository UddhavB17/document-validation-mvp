import { ApplicationReview } from "@/lib/api";
import { getDecisionProcessingState } from "@/lib/decisionPolicy";

export function Verdict({ data }: { data: ApplicationReview }) {
  const status = String(data.application.status ?? "NEEDS_REVIEW");
  const pipelineStatus = String(data.progress?.operational_status ?? data.progress?.status ?? "unknown");
  const processingState = getDecisionProcessingState(pipelineStatus, data.progress?.is_stale);
  const reviewerCount = data.summary.reviewer_count;
  const highCount = data.summary.business_anomalies.filter((item) => item.severity?.toUpperCase() === "HIGH").length;
  const businessCount = data.summary.business_count;
  const processingWarningCount = data.summary.processing_warning_count;
  let title = "NEEDS REVIEW";
  let detail = `${reviewerCount} issue(s) to check`;
  let classes = "border-[#A0701C] bg-[#FBF2E1] text-[#A0701C]";
  if (processingState === "blocked" && (data.progress?.is_stale || pipelineStatus.toLowerCase() === "stale")) {
    title = "STALE";
    detail = "Processing stopped reporting progress; recovery is required";
    classes = "border-[#AF3B2E] bg-[#FBEBE8] text-[#AF3B2E]";
  } else if (processingState === "blocked" && ["failed", "pipeline_failed"].includes(pipelineStatus.toLowerCase())) {
    title = "FAILED";
    detail = "Processing failed; retry before making a decision";
    classes = "border-[#AF3B2E] bg-[#FBEBE8] text-[#AF3B2E]";
  } else if (["queued", "processing"].includes(pipelineStatus.toLowerCase())) {
    title = "PROCESSING";
    detail = "Validation is not complete; decisions are disabled";
    classes = "border-blue-300 bg-blue-50 text-blue-900";
  } else if (pipelineStatus.toLowerCase() === "completed_with_warnings") {
    title = "COMPLETED WITH WARNINGS";
    detail = `${businessCount} business exception(s); ${processingWarningCount} processing warning(s)`;
    classes = "border-[#A0701C] bg-[#FBF2E1] text-[#A0701C]";
  } else if (status === "CLEAN" || (processingState === "completed" && reviewerCount === 0)) {
    title = "CLEAN";
    detail = "No checklist issues found";
    classes = "border-[#1F7A5C] bg-[#E7F3EE] text-[#1F7A5C]";
  } else if (status === "CRITICAL" || highCount > 0) {
    title = "CRITICAL";
    detail = highCount > 0 ? `${highCount} high-severity business exception(s)` : "Critical result requires reviewer attention";
    classes = "border-[#AF3B2E] bg-[#FBEBE8] text-[#AF3B2E]";
  }

  return (
    <div className={`rounded-xl border-l-4 px-5 py-4 font-bold flex items-center justify-between shadow-2xs ${classes}`} role="status" aria-live="polite" aria-label={`Audit result: ${title}. ${detail}`}>
      <div>
        <div className="text-xs uppercase tracking-wider opacity-70">Audit Result</div>
        <div className="text-sm font-extrabold">{title} — {detail}</div>
        {processingWarningCount > 0 && title !== "COMPLETED WITH WARNINGS" ? (
          <div className="mt-1 text-xs font-semibold opacity-80">{processingWarningCount} processing warning(s) are separate from business blockers.</div>
        ) : null}
      </div>
    </div>
  );
}
