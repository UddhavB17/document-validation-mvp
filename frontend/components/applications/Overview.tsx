import { Metric } from "@/components/Metric";
import { ApplicationReview } from "@/lib/api";

import { averagePageTime } from "./reviewUtils";

export function Overview({ data }: { data: ApplicationReview }) {
  const uploaded = data.uploaded_file;
  const avgPageTime = averagePageTime(data.page_events);

  return (
    <div className="bg-white rounded-2xl border border-slate-200 p-5 shadow-sm space-y-5">
      <div>
        <h3 className="text-xs font-bold text-slate-400 uppercase tracking-widest mb-3">Application Metadata</h3>
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-4">
          <Metric label="Applicant Name" value={data.ground_truth.applicant_name ?? data.application.applicant_name} />
          <Metric label="PAN Number" value={data.ground_truth.pan_number} />
          <Metric label="Loan Amount" value={data.ground_truth.loan_amount} />
          <Metric label="Branch" value={data.application.branch} />
          <Metric label="Product Type" value={data.application.product_type} />
        </div>
      </div>
      <div className="border-t border-slate-100 pt-4">
        <h3 className="text-xs font-bold text-slate-400 uppercase tracking-widest mb-3">Pipeline Summary</h3>
        <div className="grid grid-cols-2 sm:grid-cols-6 gap-4">
          <Metric label="Status" value={data.application.status} />
          <Metric label="Total Pages" value={uploaded.total_pages ?? data.pages.length} />
          <Metric label="Digital Count" value={uploaded.digital_pages} />
          <Metric label="Scanned Count" value={uploaded.scanned_pages} />
          <Metric label="Passed Items" value={`${data.ai_checklist.passed}/${data.ai_checklist.total || "-"}`} />
          <Metric label="Avg Page OCR" value={avgPageTime ? `${avgPageTime.toFixed(2)}s` : "-"} />
        </div>
      </div>
    </div>
  );
}
