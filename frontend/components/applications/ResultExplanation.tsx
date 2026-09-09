import { InfoMessage } from "@/components/Message";
import { ApplicationReview } from "@/lib/api";

import { isDecisionBlocker } from "@/components/applications/review/issueQueue";

export function ResultExplanation({ data }: { data: ApplicationReview }) {
  const anomalies = data.anomalies;
  const unsupported = anomalies.find((item) => item.rule_id === "UNSUPPORTED_DOCUMENT_TYPE");
  const pageFailures = anomalies.filter((item) => item.rule_id === "PAGE_PROCESSING_ERROR");
  const missing = anomalies.filter((item) => String(item.rule_id ?? "").startsWith("MISSING_DOC"));
  let message = "The queue is ordered from validation output: decision blockers first, then business exceptions, manual checks, and processing quality.";
  if (unsupported) {
    message = `Unsupported input: ${unsupported.found_value ?? unsupported.reason ?? "Checklist evaluation skipped."}`;
  } else if (pageFailures.length) {
    message = `Partial failure: ${pageFailures.length} page(s) had processing errors and need manual review.`;
  } else if (missing.length) {
    message = `${missing.length} checklist item(s) are missing because no confident matching page was found.`;
  }
  const businessCount = data.summary.business_anomalies.length;
  const processingCount = data.summary.processing_warnings.length;
  return (
    <section aria-labelledby="deterministic-result-heading" className="space-y-3 rounded-xl border border-slate-200 bg-slate-50/60 p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="deterministic-result-heading" className="text-sm font-bold text-slate-900">Result basis</h2>
        <span className="text-[10px] font-bold uppercase tracking-wider text-slate-500">Rule output</span>
      </div>
      <InfoMessage message={message} />
      <div className="grid grid-cols-2 gap-3 text-xs sm:grid-cols-4">
        <div>
          <div className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Decision blockers</div>
          <div className="mt-1 font-mono font-bold text-slate-900">{data.summary.business_anomalies.filter(isDecisionBlocker).length}</div>
        </div>
        <div>
          <div className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Business exceptions</div>
          <div className="mt-1 font-mono font-bold text-slate-900">{businessCount}</div>
        </div>
        <div>
          <div className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Processing quality</div>
          <div className="mt-1 font-mono font-bold text-slate-900">{processingCount}</div>
        </div>
        <div>
          <div className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Raw flags</div>
          <div className="mt-1 font-mono font-bold text-slate-900">{data.summary.raw_count}</div>
        </div>
      </div>
    </section>
  );
}
