"use client";

import Link from "next/link";

import { CaseQueueNavigation } from "@/components/applications/case/CaseQueueNavigation";
import { StatusBadge } from "@/components/StatusBadge";
import type { ApplicationReview, FieldComparison } from "@/lib/api";
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

  const applicant = asText(data.application.applicant_name || data.ground_truth.applicant_name);
  const loanId = asText(data.application.loan_id);
  const product = asText(data.application.product_type);
  const branch = asText(data.application.branch);
  const caseStatus = String(data.application.status || "unknown");
  const processingStatus = String(data.progress?.operational_status || data.progress?.status || "not available");
  const totalPages = data.uploaded_file.total_pages ?? data.progress?.total_pages ?? data.pages.length;
  const loanAmount = getParamVal("loan_amount", asText(data.ground_truth.loan_amount || data.application.loan_amount));
  const roi = getParamVal("roi", asText(data.ground_truth.roi || data.application.roi));
  const tenure = getParamVal("tenure", asText(data.ground_truth.tenure || data.application.tenure));
  const emi = getParamVal("emi", getParamVal("emi_amount", asText(data.ground_truth.emi || data.application.emi)));

  return (
    <header className="sticky top-0 z-30 min-w-0 rounded-xl border border-[#E1E5EB] bg-white/95 p-4 shadow-2xs backdrop-blur sm:p-5">
      <div className="flex min-w-0 flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <Link href="/worklist" className="inline-flex items-center text-xs font-bold text-[#2B4C7E] transition-colors hover:text-[#1E3559]">
            ← Back to Worklist
          </Link>
          <div className="mt-2 flex min-w-0 flex-wrap items-baseline gap-x-3 gap-y-1">
            <h1 className="truncate font-serif text-xl font-semibold text-[#16202E] sm:text-2xl">{applicant}</h1>
            <span className="font-mono text-xs font-semibold text-[#5C6B7A]">{loanId}</span>
          </div>
          <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs font-semibold text-[#5C6B7A]">
            <span>{product}</span>
            <span aria-hidden="true">·</span>
            <span>{branch}</span>
            <span aria-hidden="true">·</span>
            <span className="font-mono">APP-{String(applicationId).padStart(4, "0")}</span>
          </div>
        </div>

        <div className="flex min-w-0 flex-wrap items-center justify-end gap-3">
          <div className="flex items-center gap-2">
            <span className="text-[10px] font-bold uppercase tracking-wider text-[#5C6B7A]">Case</span>
            <StatusBadge status={caseStatus} />
          </div>
          <div className="flex items-center gap-2">
            <span className="text-[10px] font-bold uppercase tracking-wider text-[#5C6B7A]">Processing</span>
            <StatusBadge status={processingStatus} />
          </div>
          <CaseQueueNavigation applicationId={applicationId} />
        </div>
      </div>

      <div className="mt-4 flex min-w-0 flex-wrap items-center gap-x-5 gap-y-2 border-t border-[#E1E5EB] pt-3 text-xs">
        <div><span className="font-semibold text-[#5C6B7A]">Pages </span><span className="font-mono font-bold text-[#16202E]">{totalPages}</span></div>
        <div><span className="font-semibold text-[#5C6B7A]">Loan amount </span><span className="font-mono font-bold text-[#16202E]">{loanAmount}</span></div>
        <div><span className="font-semibold text-[#5C6B7A]">ROI </span><span className="font-mono font-bold text-[#16202E]">{roi}</span></div>
        <div><span className="font-semibold text-[#5C6B7A]">Tenure </span><span className="font-mono font-bold text-[#16202E]">{tenure}</span></div>
        <div><span className="font-semibold text-[#5C6B7A]">EMI </span><span className="font-mono font-bold text-[#16202E]">{emi}</span></div>
      </div>
    </header>
  );
}
