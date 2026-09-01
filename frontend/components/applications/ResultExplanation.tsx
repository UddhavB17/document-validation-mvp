import { InfoMessage } from "@/components/Message";
import { ApplicationReview } from "@/lib/api";

export function ResultExplanation({ data }: { data: ApplicationReview }) {
  const anomalies = data.anomalies;
  const unsupported = anomalies.find((item) => item.rule_id === "UNSUPPORTED_DOCUMENT_TYPE");
  const pageFailures = anomalies.filter((item) => item.rule_id === "PAGE_PROCESSING_ERROR");
  const missing = anomalies.filter((item) => String(item.rule_id ?? "").startsWith("MISSING_DOC"));
  let message = "The result is based on confident page classifications and completed processing.";
  if (unsupported) {
    message = `Unsupported input: ${unsupported.found_value ?? unsupported.reason ?? "Checklist evaluation skipped."}`;
  } else if (pageFailures.length) {
    message = `Partial failure: ${pageFailures.length} page(s) had processing errors and need manual review.`;
  } else if (missing.length) {
    message = `${missing.length} checklist item(s) are missing because no confident matching page was found.`;
  }
  return (
    <section className="space-y-2">
      <h2 className="text-base font-bold text-slate-800">Result Explanation</h2>
      <InfoMessage message={message} />
    </section>
  );
}
