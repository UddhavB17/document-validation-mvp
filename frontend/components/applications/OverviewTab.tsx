import { ProgressPanel } from "@/components/ProgressPanel";
import { ManualReviewAndDecision } from "@/components/applications/ManualReviewAndDecision";
import { ReviewerSummary } from "@/components/applications/ReviewerSummary";
import { statusLabels } from "@/components/applications/reviewUtils";
import { ApplicantComparison, ApplicationReview } from "@/lib/api";
import { asText } from "@/lib/format";

export function getApplicantList(data: ApplicationReview): ApplicantComparison[] {
  return data.comparison_matrix?.applicants ?? [];
}

export function getAnomalyCount(data: ApplicationReview) {
  const coreParams = data.comparison_matrix?.core_parameters || [];
  const applicantList = getApplicantList(data);
  const allFields = [...coreParams, ...applicantList.flatMap((applicant) => applicant.fields)];
  return allFields.filter((field) => field.status === "mismatch" || field.status === "attention").length;
}

export function OverviewTab({
  applicationId,
  data,
  onSelectPage,
}: {
  applicationId: number;
  data: ApplicationReview;
  onSelectPage: (pageNo: number, title: string, reason: string, decisionTaskId?: string) => void;
}) {
  const applicantList = getApplicantList(data);
  const anomCount = getAnomalyCount(data);

  return (
    <div className="min-w-0 space-y-6">
      <h2 className="font-serif text-[16px] font-semibold mb-3">Review summary</h2>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div className="bg-white border border-[#E1E5EB] rounded-xl p-4 shadow-3xs">
          <div className="text-[#5C6B7A] text-[12.5px] font-medium">Purpose of Loan</div>
          <div className="mt-1 font-bold text-sm text-[#16202E]">
            {asText(data.application.purpose) || "Business expansion — LAP"}
          </div>
        </div>
        <div className="bg-white border border-[#E1E5EB] rounded-xl p-4 shadow-3xs">
          <div className="text-[#5C6B7A] text-[12.5px] font-medium">Property Details</div>
          <div className="mt-1 font-bold text-sm text-[#16202E]">
            {asText(data.application.property_address) || "Residential, Jaipur (Malviya Nagar)"}
          </div>
        </div>
        <div className="bg-white border border-[#E1E5EB] rounded-xl p-4 shadow-3xs">
          <div className="text-[#5C6B7A] text-[12.5px] font-medium">Documents received</div>
          <div className="mt-1 font-mono font-bold text-sm text-[#16202E]">
            {data.pages.length} pages processed
          </div>
        </div>
        <div className="bg-white border border-[#E1E5EB] rounded-xl p-4 shadow-3xs">
          <div className="text-[#5C6B7A] text-[12.5px] font-medium">Extraction status</div>
          <div className="mt-1 font-bold text-sm text-[#A0701C]">
            {anomCount} fields need attention
          </div>
        </div>
      </div>

      <h2 className="font-serif text-[16px] font-semibold mb-3 mt-6">Applicant roster</h2>
      <div className="min-w-0 max-w-full overflow-x-auto rounded-xl border border-[#E1E5EB] shadow-3xs">
        <table className="min-w-[520px] w-full border-collapse text-left text-[13px]">
          <thead>
            <tr className="bg-[#F6F7FA] border-b border-[#E1E5EB]">
              <th className="text-[#5C6B7A] font-semibold text-[11px] uppercase tracking-wider px-3.5 py-2.5">Name</th>
              <th className="text-[#5C6B7A] font-semibold text-[11px] uppercase tracking-wider px-3.5 py-2.5">Role</th>
              <th className="text-[#5C6B7A] font-semibold text-[11px] uppercase tracking-wider px-3.5 py-2.5">KYC Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#E1E5EB] text-[#16202E]">
            {applicantList.map((applicant) => {
              const hasMismatch = applicant.fields.some((field) => field.status === "mismatch");
              const hasAttention = applicant.fields.some((field) => field.status === "attention");
              const status = hasMismatch ? "mismatch" : (hasAttention ? "attention" : "match");
              const label = hasMismatch ? "Failed" : (hasAttention ? "Needs Review" : "Verified");

              return (
                <tr key={applicant.person_name} className="hover:bg-slate-50/50 transition-colors duration-150">
                  <td className="px-3.5 py-3 font-bold text-[#16202E]">{applicant.person_name}</td>
                  <td className="px-3.5 py-3 text-[#5C6B7A] font-semibold">{applicant.applicant_label}</td>
                  <td className="px-3.5 py-3">
                    <span className={`stamp ${status} mr-2`}>
                      {statusLabels[status]}
                    </span>
                    <span className="font-bold text-sm" style={{ color: `var(--${status})` }}>
                      {label}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {[
        "uploaded",
        "processing",
        "ocr_completed",
      ].includes(String(data.application.status)) || data.progress?.retryable ? (
        <ProgressPanel applicationId={applicationId} />
      ) : null}

      <div className="pt-6 border-t border-[#E1E5EB] space-y-6">
        <ReviewerSummary
          data={data}
          onSelectPage={(pageNo) => onSelectPage(pageNo, "Manual Review Page", "Requested check by reviewer")}
        />
        <ManualReviewAndDecision
          applicationId={applicationId}
          data={data}
          onSelectPage={(pageNo, decisionTaskId) => onSelectPage(pageNo, "Manual Check", "Manual item verification review", decisionTaskId)}
        />
      </div>
    </div>
  );
}
