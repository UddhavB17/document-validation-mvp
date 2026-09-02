import { ApplicationReview, FieldComparison } from "@/lib/api";
import { asText } from "@/lib/format";

export function ApplicationMetricsHeader({
  applicationId,
  data,
}: {
  applicationId: number;
  data: ApplicationReview;
}) {
  const coreParamsList = data.comparison_matrix?.core_parameters || [];
  const getParamVal = (fieldName: string, fallback: string) => {
    const item = coreParamsList.find((parameter: FieldComparison) => parameter.field_name === fieldName);
    return item?.expected_value || item?.extracted_value || fallback;
  };

  const loanAmount = getParamVal("loan_amount", asText(data.ground_truth?.loan_amount || data.application?.loan_amount));
  const roi = getParamVal("roi", asText(data.ground_truth?.roi || data.application?.roi));
  const tenure = getParamVal("tenure", asText(data.ground_truth?.tenure || data.application?.tenure));
  const emi = getParamVal("emi", getParamVal("emi_amount", "—"));

  return (
    <div className="bg-white border border-[#E1E5EB] rounded-2xl p-5 shadow-2xs space-y-4">
      <div className="flex items-baseline gap-3 flex-wrap">
        <h1 className="font-serif font-semibold text-2xl text-[#16202E] m-0">
          {asText(data.ground_truth.applicant_name ?? data.application.applicant_name)}
        </h1>
        <span className="font-mono text-[#5C6B7A] text-[13px]">
          APP-{String(applicationId).padStart(4, "0")} · {asText(data.application.product_type)}
        </span>
        <div className="ml-auto bg-[#EAF0F8] text-[#2B4C7E] rounded-full px-3 py-1 text-xs font-semibold flex items-center gap-1.5 animate-pulse">
          <span className="w-1.5 h-1.5 rounded-full bg-[#2B4C7E]" />
          In review
        </div>
      </div>

      <div className="flex flex-wrap gap-12 pt-4 border-t border-[#E1E5EB]">
        <div className="metric">
          <div className="text-[#5C6B7A] text-[11px] uppercase tracking-wider font-semibold font-medium">Loan Amount</div>
          <div className="font-mono text-[16px] font-semibold mt-1 text-[#16202E]">{loanAmount}</div>
        </div>
        <div className="metric">
          <div className="text-[#5C6B7A] text-[11px] uppercase tracking-wider font-semibold font-medium">ROI</div>
          <div className="font-mono text-[16px] font-semibold mt-1 text-[#16202E]">{roi}</div>
        </div>
        <div className="metric">
          <div className="text-[#5C6B7A] text-[11px] uppercase tracking-wider font-semibold font-medium">Tenure</div>
          <div className="font-mono text-[16px] font-semibold mt-1 text-[#16202E]">{tenure}</div>
        </div>
        <div className="metric">
          <div className="text-[#5C6B7A] text-[11px] uppercase tracking-wider font-semibold font-medium">EMI</div>
          <div className="font-mono text-[16px] font-semibold mt-1 text-[#16202E]">{emi}</div>
        </div>
      </div>
    </div>
  );
}
