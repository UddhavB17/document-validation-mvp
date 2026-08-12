"use client";

import { useParams } from "next/navigation";
import { useState } from "react";
import Link from "next/link";

import { ErrorMessage, InfoMessage, LoadingMessage } from "@/components/Message";
import { Metric } from "@/components/Metric";
import { PageHeader } from "@/components/PageHeader";
import { ProgressPanel } from "@/components/ProgressPanel";
import { SortableTable } from "@/components/SortableTable";
import { StatusBadge } from "@/components/StatusBadge";
import { api, Anomaly, ApplicationReview } from "@/lib/api";
import { decisionNoteSchema } from "@/lib/forms";
import { asText, formatSeconds } from "@/lib/format";
import { useApplicationReview, useCreateDecision, useUndoDecision } from "@/lib/queries";
import ComparisonTable from "@/components/applications/ComparisonTable";
import RelationshipGraph from "@/components/applications/RelationshipGraph";

const rejectionReasons = {
  "Document missing": "Please resubmit with the missing document(s) listed above.",
  "Name mismatch": "Name on submitted document does not match application records. Please verify and resubmit.",
  "Scan unclear": "Scan quality is too low to verify. Please rescan and resubmit.",
  "Statement outdated": "Bank statement is outside the allowed recency window. Please upload a recent statement.",
  "Wrong applicant": "Document appears to belong to a different applicant. Please verify and resubmit.",
  "Signature missing": "Required signature is missing. Please upload a signed copy.",
};

type ActiveTab = "overview" | "extracted" | "anomalies" | "checklist" | "logs" | "downloads";

const statusLabels = {
  match: "Match",
  mismatch: "Mismatch",
  attention: "Attention",
};

export default function ApplicationReviewPage() {
  const params = useParams<{ id: string }>();
  const applicationId = Number(params.id);
  const review = useApplicationReview(Number.isFinite(applicationId) ? applicationId : null);
  const [activeTab, setActiveTab] = useState<ActiveTab>("overview");
  const [selectedEvidence, setSelectedEvidence] = useState<{ anomaly: Anomaly; pageNumber: number; allPageNumbers?: number[] } | null>(null);
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(() => {
    if (typeof window !== "undefined") {
      return sessionStorage.getItem("sidebar_collapsed") === "true";
    }
    return false;
  });

  if (!Number.isFinite(applicationId)) {
    return <ErrorMessage message="Invalid application ID." />;
  }

  if (review.isLoading) {
    return <LoadingMessage />;
  }
  if (review.isError) {
    return <ErrorMessage message="Unable to load application review." />;
  }
  if (!review.data) {
    return null;
  }

  const handleSelectEvidence = (anomaly: Anomaly, pageNumber: number, allPageNumbers?: number[]) => {
    setSelectedEvidence({ anomaly, pageNumber, allPageNumbers });
    setTimeout(() => {
      const viewer = document.getElementById("evidence-viewer");
      if (viewer) {
        viewer.scrollIntoView({ behavior: "smooth", block: "nearest" });
      }
    }, 100);
  };

  const handleSelectPageOnly = (pageNumber: number, title: string, reason: string) => {
    const mockAnomaly: Anomaly = {
      rule_id: "PAGE_PREVIEW",
      severity: "INFO",
      document_type: title,
      reason: reason,
      expected_value: "-",
      found_value: `Page ${pageNumber}`
    };
    handleSelectEvidence(mockAnomaly, pageNumber);
  };

  const coreParamsList = review.data.comparison_matrix?.core_parameters || [];
  const getParamVal = (fieldName: string, fallback: string) => {
    const item = coreParamsList.find((p: any) => p.field_name === fieldName);
    return item?.expected_value || item?.extracted_value || fallback;
  };

  const loanAmount = getParamVal("loan_amount", asText(review.data.ground_truth?.loan_amount || review.data.application?.loan_amount));
  const roi = getParamVal("roi", asText(review.data.ground_truth?.roi || review.data.application?.roi));
  const tenure = getParamVal("tenure", asText(review.data.ground_truth?.tenure || review.data.application?.tenure));
  const emi = getParamVal("emi", getParamVal("emi_amount", "—"));

  const coreParams = review.data.comparison_matrix?.core_parameters || [];
  const applicantsRaw = review.data.comparison_matrix?.applicants;
  const applicantList: any[] = Array.isArray(applicantsRaw)
    ? applicantsRaw
    : (applicantsRaw && typeof applicantsRaw === "object" ? Object.values(applicantsRaw) : []);
  const allFields = [...coreParams, ...applicantList.flatMap((a: any) => a.fields || [])];
  const anomCount = allFields.filter((f: any) => f.status === "mismatch" || f.status === "attention").length;

  // Group raw extracted fields by document type dynamically
  const extractedByDoc: Record<string, Record<string, any>> = {};
  review.data.pages.forEach((p: any) => {
    const docType = p.document_type || "Unknown Document";
    const fields = p.extracted_fields || {};
    const cleanFields: Record<string, any> = {};
    Object.entries(fields).forEach(([k, v]) => {
      if (!k.startsWith("_") && v !== null && v !== undefined && String(v).trim()) {
        cleanFields[k] = v;
      }
    });
    
    if (Object.keys(cleanFields).length > 0) {
      if (!extractedByDoc[docType]) {
        extractedByDoc[docType] = {};
      }
      extractedByDoc[docType] = {
        ...extractedByDoc[docType],
        ...cleanFields,
      };
    }
  });

  const pagesToRender = selectedEvidence?.allPageNumbers && selectedEvidence.allPageNumbers.length > 0
    ? selectedEvidence.allPageNumbers
    : (selectedEvidence ? [selectedEvidence.pageNumber] : []);

  const firstPage = selectedEvidence ? review.data.pages.find((item: any) => Number(item.page_number) === selectedEvidence.pageNumber) : null;

  const combinedOcrText = pagesToRender
    .map((pageNo) => {
      const p = review.data.pages.find((item: any) => Number(item.page_number) === pageNo);
      return typeof p?.ocr_text === "string" && p.ocr_text.trim()
        ? `--- PAGE ${pageNo} ---\n${p.ocr_text.trim()}`
        : "";
    })
    .filter(Boolean)
    .join("\n\n");

  return (
    <div className="space-y-6 max-w-[1600px] mx-auto">
      {/* 1. Crumbs and Back Nav */}
      <div className="crumb text-xs text-[#5C6B7A] flex items-center gap-2 mb-1.5 font-semibold">
        <Link href="/worklist" className="hover:text-[#2B4C7E] transition-colors">← Applications</Link>
      </div>

      {/* 2. Headline & Metrics Topbar */}
      <div className="bg-white border border-[#E1E5EB] rounded-2xl p-5 shadow-2xs space-y-4">
        <div className="flex items-baseline gap-3 flex-wrap">
          <h1 className="font-serif font-semibold text-2xl text-[#16202E] m-0">
            {asText(review.data.ground_truth.applicant_name ?? review.data.application.applicant_name)}
          </h1>
          <span className="font-mono text-[#5C6B7A] text-[13px]">
            APP-{String(applicationId).padStart(4, "0")} · {asText(review.data.application.product_type)}
          </span>
          <div className="ml-auto bg-[#EAF0F8] text-[#2B4C7E] rounded-full px-3 py-1 text-xs font-semibold flex items-center gap-1.5 animate-pulse">
            <span className="w-1.5 h-1.5 rounded-full bg-[#2B4C7E]" />
            In review
          </div>
        </div>

        {/* Metrics Row */}
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

      {/* 3. Decision status banner */}
      <Verdict data={review.data} />
      
      {/* 4. Three-Column Shell */}
      <div className={`grid grid-cols-1 gap-6 items-start min-h-[calc(100vh-220px)] transition-all duration-300 ${isSidebarCollapsed ? "lg:grid-cols-[64px_1fr]" : "lg:grid-cols-[220px_1fr]"}`}>
        {/* Navigation Sidebar with custom vector symbols */}
        <aside className={`bg-white border border-[#E1E5EB] rounded-xl p-2 sticky top-4 shadow-2xs transition-all duration-300 flex flex-col ${isSidebarCollapsed ? "w-16 items-center" : "w-[220px]"}`}>
          {/* Toggle Button */}
          <div className={`flex w-full mb-1 border-b border-slate-100 pb-1.5 ${isSidebarCollapsed ? "justify-center" : "justify-end"}`}>
            <button
              type="button"
              onClick={() => {
                const next = !isSidebarCollapsed;
                setIsSidebarCollapsed(next);
                sessionStorage.setItem("sidebar_collapsed", String(next));
              }}
              className="p-1 rounded hover:bg-[#EAF0F8] text-[#5C6B7A] hover:text-[#2B4C7E] cursor-pointer border-none bg-transparent"
              title={isSidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
            >
              <svg className="w-4.5 h-4.5" fill="none" stroke="currentColor" strokeWidth="2.5" viewBox="0 0 24 24">
                {isSidebarCollapsed ? (
                  <path strokeLinecap="round" strokeLinejoin="round" d="M11.25 4.5l7.5 7.5-7.5 7.5M4.5 4.5l7.5 7.5-7.5 7.5" />
                ) : (
                  <path strokeLinecap="round" strokeLinejoin="round" d="M18.75 19.5l-7.5-7.5 7.5-7.5M12 19.5l-7.5-7.5 7.5-7.5" />
                )}
              </svg>
            </button>
          </div>

          <button
            type="button"
            onClick={() => setActiveTab("overview")}
            className={`flex items-center transition-all font-semibold rounded-lg select-none border-none cursor-pointer ${
              isSidebarCollapsed 
                ? "justify-center w-11 h-11 p-0 shrink-0" 
                : "gap-2.5 w-full px-3 py-2 text-[13.5px]"
            } ${
              activeTab === "overview"
                ? "bg-[#EAF0F8] text-[#2B4C7E]"
                : "text-[#5C6B7A] hover:bg-slate-50 hover:text-[#16202E]"
            }`}
            title={isSidebarCollapsed ? "Overview" : undefined}
          >
            <svg className="w-4.5 h-4.5 shrink-0" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M2.25 12l8.954-8.955c.44-.439 1.152-.439 1.591 0L21.75 12M4.5 9.75v10.125c0 .621.504 1.125 1.125 1.125H9.75v-4.875c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125V21h4.125c.621 0 1.125-.504 1.125-1.125V9.75M8.25 21h8.25" />
            </svg>
            {!isSidebarCollapsed && <span>Overview</span>}
          </button>

          <button
            type="button"
            onClick={() => setActiveTab("extracted")}
            className={`flex items-center transition-all font-semibold rounded-lg select-none border-none cursor-pointer ${
              isSidebarCollapsed 
                ? "justify-center w-11 h-11 p-0 shrink-0" 
                : "gap-2.5 w-full px-3 py-2 text-[13.5px]"
            } ${
              activeTab === "extracted"
                ? "bg-[#EAF0F8] text-[#2B4C7E]"
                : "text-[#5C6B7A] hover:bg-slate-50 hover:text-[#16202E]"
            }`}
            title={isSidebarCollapsed ? "Extracted Data" : undefined}
          >
            <svg className="w-4.5 h-4.5 shrink-0" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6A2.25 2.25 0 016 3.75h2.25A2.25 2.25 0 0110.5 6v2.25a2.25 2.25 0 01-2.25 2.25H6a2.25 2.25 0 01-2.25-2.25V6zM3.75 15.75A2.25 2.25 0 016 13.5h2.25a2.25 2.25 0 012.25 2.25V18a2.25 2.25 0 01-2.25 2.25H6A2.25 2.25 0 013.75 18v-2.25zM13.5 6a2.25 2.25 0 012.25-2.25H18A2.25 2.25 0 0120.25 6v2.25A2.25 2.25 0 0118 10.5h-2.25A2.25 2.25 0 0113.5 8.25V6zM13.5 15.75a2.25 2.25 0 012.25-2.25H18a2.25 2.25 0 012.25 2.25V18A2.25 2.25 0 0118 20.25h-2.25A2.25 2.25 0 0113.5 18v-2.25z" />
            </svg>
            {!isSidebarCollapsed && <span>Extracted Data</span>}
          </button>
          <button
            type="button"
            onClick={() => setActiveTab("anomalies")}
            className={`flex items-center transition-all font-semibold rounded-lg select-none border-none cursor-pointer ${
              isSidebarCollapsed 
                ? "justify-center w-11 h-11 p-0 shrink-0" 
                : "gap-2.5 w-full px-3 py-2 text-[13.5px] justify-between"
            } ${
              activeTab === "anomalies"
                ? "bg-[#EAF0F8] text-[#2B4C7E]"
                : "text-[#5C6B7A] hover:bg-slate-50 hover:text-[#16202E]"
            }`}
            title={isSidebarCollapsed ? "Anomalies & Flags" : undefined}
          >
            <div className={`flex items-center ${isSidebarCollapsed ? "justify-center" : "gap-2.5"}`}>
              <div className="relative">
                <svg className="w-4.5 h-4.5 shrink-0" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m0-10.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.75c0 5.592 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.57-.598-3.75h-.152c-3.196 0-6.1-1.249-8.25-3.286zm0 13.036h.008v.008H12v-.008z" />
                </svg>
                {isSidebarCollapsed && anomCount > 0 && (
                  <span className="absolute -top-1 -right-1 w-2.5 h-2.5 bg-[#AF3B2E] border border-white rounded-full" />
                )}
              </div>
              {!isSidebarCollapsed && <span>Anomalies &amp; Flags</span>}
            </div>
            {!isSidebarCollapsed && anomCount > 0 && (
              <span className={`font-mono text-[11px] px-1.5 py-0.5 rounded-md ${
                activeTab === "anomalies" ? "bg-[#2B4C7E] text-white" : "bg-[#FBEBE8] text-[#AF3B2E]"
              }`}>
                {anomCount}
              </span>
            )}
          </button>
          <button
            type="button"
            onClick={() => setActiveTab("checklist")}
            className={`flex items-center transition-all font-semibold rounded-lg select-none border-none cursor-pointer ${
              isSidebarCollapsed 
                ? "justify-center w-11 h-11 p-0 shrink-0" 
                : "gap-2.5 w-full px-3 py-2 text-[13.5px]"
            } ${
              activeTab === "checklist"
                ? "bg-[#EAF0F8] text-[#2B4C7E]"
                : "text-[#5C6B7A] hover:bg-slate-50 hover:text-[#16202E]"
            }`}
            title={isSidebarCollapsed ? "Checklist & Decisions" : undefined}
          >
            <svg className="w-4.5 h-4.5 shrink-0" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12c0 1.268-.63 2.39-1.593 3.068a3.745 3.745 0 01-1.043 3.296 3.745 3.745 0 01-3.296 1.043A3.745 3.745 0 0112 21c-1.268 0-2.39-.63-3.068-1.593a3.746 3.746 0 01-3.296-1.043 3.745 3.745 0 01-1.043-3.296A3.745 3.745 0 013 12c0-1.268.63-2.39 1.593-3.068a3.745 3.745 0 011.043-3.296 3.746 3.746 0 013.296-1.043A3.746 3.746 0 0112 3c1.268 0 2.39.63 3.068 1.593a3.746 3.746 0 013.296 1.043 3.746 3.746 0 011.043 3.296A3.745 3.745 0 0121 12z" />
            </svg>
            {!isSidebarCollapsed && <span>Checklist &amp; Decisions</span>}
          </button>
          <button
            type="button"
            onClick={() => setActiveTab("logs")}
            className={`flex items-center transition-all font-semibold rounded-lg select-none border-none cursor-pointer ${
              isSidebarCollapsed 
                ? "justify-center w-11 h-11 p-0 shrink-0" 
                : "gap-2.5 w-full px-3 py-2 text-[13.5px]"
            } ${
              activeTab === "logs"
                ? "bg-[#EAF0F8] text-[#2B4C7E]"
                : "text-[#5C6B7A] hover:bg-slate-50 hover:text-[#16202E]"
            }`}
            title={isSidebarCollapsed ? "Processing Logs" : undefined}
          >
            <svg className="w-4.5 h-4.5 shrink-0" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            {!isSidebarCollapsed && <span>Processing Logs</span>}
          </button>
          <button
            type="button"
            onClick={() => setActiveTab("downloads")}
            className={`flex items-center transition-all font-semibold rounded-lg select-none border-none cursor-pointer ${
              isSidebarCollapsed 
                ? "justify-center w-11 h-11 p-0 shrink-0" 
                : "gap-2.5 w-full px-3 py-2 text-[13.5px]"
            } ${
              activeTab === "downloads"
                ? "bg-[#EAF0F8] text-[#2B4C7E]"
                : "text-[#5C6B7A] hover:bg-slate-50 hover:text-[#16202E]"
            }`}
            title={isSidebarCollapsed ? "Downloads" : undefined}
          >
            <svg className="w-4.5 h-4.5 shrink-0" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3" />
            </svg>
            {!isSidebarCollapsed && <span>Downloads</span>}
          </button>
        </aside>

        {/* Center content active tab pane */}
        <div className="bg-white border border-[#E1E5EB] rounded-2xl p-6 shadow-2xs space-y-6 min-h-[500px]">
          
          {/* TAB: OVERVIEW */}
          {activeTab === "overview" && (
            <div className="space-y-6">
              <h2 className="font-serif text-[16px] font-semibold mb-3">Application summary</h2>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div className="bg-white border border-[#E1E5EB] rounded-xl p-4 shadow-3xs">
                  <div className="text-[#5C6B7A] text-[12.5px] font-medium">Purpose of Loan</div>
                  <div className="mt-1 font-bold text-sm text-[#16202E]">
                    {asText(review.data.application.purpose) || "Business expansion — LAP"}
                  </div>
                </div>
                <div className="bg-white border border-[#E1E5EB] rounded-xl p-4 shadow-3xs">
                  <div className="text-[#5C6B7A] text-[12.5px] font-medium">Property Details</div>
                  <div className="mt-1 font-bold text-sm text-[#16202E]">
                    {asText(review.data.application.property_address) || "Residential, Jaipur (Malviya Nagar)"}
                  </div>
                </div>
                <div className="bg-white border border-[#E1E5EB] rounded-xl p-4 shadow-3xs">
                  <div className="text-[#5C6B7A] text-[12.5px] font-medium">Documents received</div>
                  <div className="mt-1 font-mono font-bold text-sm text-[#16202E]">
                    {review.data.pages.length} pages processed
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
              <div className="border border-[#E1E5EB] rounded-xl overflow-hidden shadow-3xs">
                <table className="w-full border-collapse text-left text-[13px]">
                  <thead>
                    <tr className="bg-[#F6F7FA] border-b border-[#E1E5EB]">
                      <th className="text-[#5C6B7A] font-semibold text-[11px] uppercase tracking-wider px-3.5 py-2.5">Name</th>
                      <th className="text-[#5C6B7A] font-semibold text-[11px] uppercase tracking-wider px-3.5 py-2.5">Role</th>
                      <th className="text-[#5C6B7A] font-semibold text-[11px] uppercase tracking-wider px-3.5 py-2.5">KYC Status</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#E1E5EB] text-[#16202E]">
                    {applicantList.map((a: any) => {
                      const hasMismatch = a.fields.some((f: any) => f.status === "mismatch");
                      const hasAttention = a.fields.some((f: any) => f.status === "attention");
                      const status = hasMismatch ? "mismatch" : (hasAttention ? "attention" : "match");
                      const label = hasMismatch ? "Failed" : (hasAttention ? "Needs Review" : "Verified");
                      
                      return (
                        <tr key={a.person_name} className="hover:bg-slate-50/50 transition-colors duration-150">
                          <td className="px-3.5 py-3 font-bold text-[#16202E]">{a.person_name}</td>
                          <td className="px-3.5 py-3 text-[#5C6B7A] font-semibold">{a.applicant_label}</td>
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
              ].includes(String(review.data.application.status)) || review.data.progress?.retryable ? (
                <ProgressPanel applicationId={applicationId} />
              ) : null}

              <div className="pt-6 border-t border-[#E1E5EB] space-y-6">
                <ReviewerSummary
                  data={review.data}
                  onSelectPage={(pageNo) => handleSelectPageOnly(pageNo, "Manual Review Page", "Requested check by reviewer")}
                />
                <ManualReviewAndDecision
                  applicationId={applicationId}
                  data={review.data}
                  onSelectPage={(pageNo) => handleSelectPageOnly(pageNo, "Manual Check", "Manual item verification review")}
                />
              </div>
            </div>
          )}


          {/* TAB: EXTRACTED DATA */}
          {activeTab === "extracted" && (
            <div className="space-y-6">
              <h2 className="font-serif text-[16px] font-semibold mb-1">Extracted fields — raw output</h2>
              <p className="text-[#5C6B7A] text-[12.5px] mb-4 font-medium">What DMEF read off each document. No expected-value comparison here — see Anomalies &amp; Flags for that.</p>
              
              {Object.keys(extractedByDoc).length === 0 ? (
                <div className="bg-slate-50 border border-[#E1E5EB] rounded-xl p-6 text-center text-[#5C6B7A] italic">
                  No raw extracted parameters found in processed pages.
                </div>
              ) : (
                Object.entries(extractedByDoc).map(([docType, fields]) => (
                  <div key={docType} className="bg-white border border-[#E1E5EB] rounded-xl p-4.5 shadow-3xs mb-4 last:mb-0">
                    <h3 className="text-[13.5px] font-bold text-[#16202E] border-b border-slate-100 pb-2 mb-3 font-serif uppercase tracking-wider">{docType}</h3>
                    <table className="w-full text-[13px] border-collapse">
                      <tbody className="divide-y divide-slate-100 font-semibold text-[#16202E]">
                        {Object.entries(fields).map(([k, v]) => (
                          <tr key={k}>
                            <td className="py-2.5 text-[#5C6B7A] font-medium w-1/3 truncate">{k.replace(/_/g, " ")}</td>
                            <td className="py-2.5 font-mono text-[12px] select-all break-all">{String(v)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ))
              )}
            </div>
          )}

          {/* TAB: ANOMALIES & FLAGS */}
          {activeTab === "anomalies" && (
            <div className="space-y-6">
              <ComparisonTable
                coreParameters={review.data.comparison_matrix?.core_parameters}
                applicants={applicantList}
                onSelectPage={handleSelectPageOnly}
              />
              
              <h2 className="font-serif text-[16px] font-semibold mb-3">Borrower relationship graph</h2>
              <div className="border border-[#E1E5EB] rounded-xl p-2 shadow-2xs overflow-x-auto bg-[#F6F7FA]/30">
                <RelationshipGraph relationships={review.data.relationships} />
              </div>

              <h2 className="font-serif text-[16px] font-semibold mb-3 pt-4 border-t border-slate-100">Exceptions &amp; Warnings Details</h2>
              <Anomalies
                applicationId={applicationId}
                data={review.data}
                onSelectEvidence={handleSelectEvidence}
              />
            </div>
          )}

          {/* TAB: CHECKLIST */}
          {activeTab === "checklist" && (
            <Checklist
              data={review.data}
              onSelectPage={(row, pageNo, allPages) => {
                const mockAnomaly: Anomaly = {
                  rule_id: row.s_no ? `CHECK_${row.s_no}` : "CHECKLIST_PREVIEW",
                  severity: "INFO",
                  reason: row.description || "Verification List Preview",
                  document_type: row.looked || row.description || "Document Preview",
                  expected_value: "-",
                  found_value: allPages ? `Combined pages: ${allPages.join(", ")}` : `Page ${pageNo}`
                };
                handleSelectEvidence(mockAnomaly, pageNo, allPages);
              }}
            />
          )}

          {/* TAB: LOGS */}
          {activeTab === "logs" && (
            <PageProcessing
              data={review.data}
              onSelectPage={(pageNo, docType) => handleSelectPageOnly(pageNo, docType || "Processing Page", "Processing log validation review")}
            />
          )}

          {/* TAB: DOWNLOADS */}
          {activeTab === "downloads" && (
            <Downloads applicationId={applicationId} />
          )}

        </div>

      </div>

      {/* Evidence Viewer Modal Popup */}
      {selectedEvidence && (
        <div className="fixed inset-0 bg-slate-900/60 backdrop-blur-xs flex items-center justify-center z-50 p-4 animate-fade-in">
          <div className="bg-white rounded-2xl border border-[#E1E5EB] shadow-2xl w-full max-w-[850px] max-h-[90vh] flex flex-col overflow-hidden">
            {/* Modal Header */}
            <div className="border-b border-[#E1E5EB] bg-[#F6F7FA] px-6 py-4 flex items-center justify-between shrink-0">
              <div>
                <div className="text-[10px] font-bold uppercase tracking-wider text-[#5C6B7A]">Evidence viewer</div>
                <div className="font-semibold text-[15px] text-[#16202E] mt-0.5">
                  {selectedEvidence.allPageNumbers && selectedEvidence.allPageNumbers.length > 1
                    ? `Pages ${selectedEvidence.allPageNumbers.join(", ")} (Combined)`
                    : `Page ${selectedEvidence.pageNumber}`}
                  {" — "}
                  {asText(firstPage?.document_type ?? selectedEvidence.anomaly.document_type)}
                </div>
              </div>
              <div className="flex items-center gap-3">
                {selectedEvidence.allPageNumbers && selectedEvidence.allPageNumbers.length > 1 ? (
                  <span className="text-[10px] font-extrabold text-[#2B4C7E] uppercase bg-[#EAF0F8] px-2.5 py-1 rounded border border-[#E1E5EB]">
                    Combined Stack
                  </span>
                ) : (
                  <a
                    href={api.sourcePdfUrl(applicationId, selectedEvidence.pageNumber)}
                    target="_blank"
                    rel="noreferrer"
                    className="text-xs font-bold text-[#2B4C7E] hover:underline"
                  >
                    Open Full PDF
                  </a>
                )}
                <button
                  type="button"
                  onClick={() => setSelectedEvidence(null)}
                  className="rounded-lg border border-[#E1E5EB] bg-white px-3 py-1.5 text-xs font-bold text-[#5C6B7A] hover:bg-slate-50 hover:text-[#16202E] cursor-pointer"
                >
                  Close
                </button>
              </div>
            </div>
            
            {/* Modal Body: Side-by-side Image preview and text block */}
            <div className="flex-1 overflow-hidden grid grid-cols-1 md:grid-cols-[1fr_300px] divide-y md:divide-y-0 md:divide-x divide-[#E1E5EB] min-h-0">
              {/* Left Side: Page Image scroll */}
              <div className="overflow-y-auto bg-slate-800/10 p-4 flex flex-col gap-4 items-center min-h-0">
                {pagesToRender.map((pageNo) => (
                  <div key={pageNo} className="relative w-full flex flex-col items-center max-w-[500px]">
                    <div className="absolute top-2 left-2 rounded bg-black/75 px-2 py-0.5 text-[9px] font-mono text-white z-10">
                      Pg {pageNo}
                    </div>
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={api.sourcePageImageUrl(applicationId, pageNo)}
                      alt={`Original source PDF page ${pageNo}`}
                      className="h-auto w-full bg-white shadow border border-slate-200 rounded-sm"
                    />
                  </div>
                ))}
              </div>

              {/* Right Side: Expected, Extracted, and OCR text */}
              <div className="p-5 overflow-y-auto text-xs space-y-4 shrink-0 bg-white">
                <div className="grid grid-cols-2 gap-3 border-b border-slate-100 pb-4">
                  <EvidenceValue label="Expected" value={selectedEvidence.anomaly.expected_value} />
                  <EvidenceValue label="Extracted / Found" value={selectedEvidence.anomaly.found_value} />
                </div>
                <div className="space-y-2">
                  <div className="font-bold uppercase tracking-wider text-slate-500 text-[10px]">Extracted page text</div>
                  <div className="whitespace-pre-wrap rounded-lg bg-slate-950 p-3 font-mono leading-relaxed text-slate-100 text-[11px] max-h-[350px] overflow-y-auto select-all">
                    {combinedOcrText ? (
                      <HighlightedEvidenceText text={combinedOcrText.slice(0, 5000)} needle={selectedEvidence.anomaly.found_value ?? ""} />
                    ) : (
                      "No OCR text was extracted for this page."
                    )}
                  </div>
                </div>
              </div>
            </div>
            
            {/* Modal Footer */}
            <div className="border-t border-[#E1E5EB] bg-[#F6F7FA] px-6 py-3.5 flex justify-end shrink-0">
              <button
                type="button"
                onClick={() => setSelectedEvidence(null)}
                className="rounded-lg bg-[#2B4C7E] hover:bg-[#1E3559] px-5 py-2 text-sm font-semibold text-white shadow-3xs cursor-pointer border-none"
              >
                Done
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function Verdict({ data }: { data: ApplicationReview }) {
  const status = String(data.application.status ?? "NEEDS_REVIEW");
  const pipelineStatus = String(data.progress?.operational_status ?? "not_started");
  const reviewerCount = data.summary.reviewer_count;
  const highCount = data.summary.high_count;
  let title = "NEEDS REVIEW";
  let detail = `${reviewerCount} issue(s) to check`;
  let classes = "border-[#A0701C] bg-[#FBF2E1] text-[#A0701C]";
  if (pipelineStatus === "stale") {
    title = "STALE";
    detail = "Processing stopped reporting progress; recovery is required";
    classes = "border-[#AF3B2E] bg-[#FBEBE8] text-[#AF3B2E]";
  } else if (pipelineStatus === "failed") {
    title = "FAILED";
    detail = "Processing failed; retry before making a decision";
    classes = "border-[#AF3B2E] bg-[#FBEBE8] text-[#AF3B2E]";
  } else if (["queued", "processing"].includes(pipelineStatus)) {
    title = "PROCESSING";
    detail = "Validation is not complete";
    classes = "border-blue-300 bg-blue-50 text-blue-900";
  } else if (pipelineStatus === "completed_with_warnings") {
    title = "COMPLETED WITH WARNINGS";
    detail = `${reviewerCount} issue(s) plus page-level processing warnings`;
    classes = "border-[#A0701C] bg-[#FBF2E1] text-[#A0701C]";
  } else if (status === "CLEAN" || (pipelineStatus === "completed" && reviewerCount === 0)) {
    title = "CLEAN";
    detail = "No checklist issues found";
    classes = "border-[#1F7A5C] bg-[#E7F3EE] text-[#1F7A5C]";
  } else if (status === "CRITICAL" || highCount > 0) {
    title = "CRITICAL";
    detail = `${highCount || reviewerCount} high-severity issue(s)`;
    classes = "border-[#AF3B2E] bg-[#FBEBE8] text-[#AF3B2E]";
  }
  return (
    <div className={`rounded-xl border-l-4 px-5 py-4 font-bold flex items-center justify-between shadow-2xs ${classes}`}>
      <div className="flex items-center gap-3">
        <div>
          <div className="text-xs uppercase tracking-wider opacity-70">Audit Result</div>
          <div className="text-sm font-extrabold">{title} — {detail}</div>
        </div>
      </div>
    </div>
  );
}

function ReviewerSummary({
  data,
  onSelectPage,
}: {
  data: ApplicationReview;
  onSelectPage?: (pageNo: number) => void;
}) {
  const summary = data.reviewer_summary;
  if (!summary) {
    return null;
  }
  const text = asText(summary.note);
  return (
    <section className="space-y-3 rounded-xl border border-slate-200 p-4 shadow-3xs bg-[#F6F7FA]/40">
      <h3 className="text-xs font-bold text-[#5C6B7A] uppercase tracking-widest">Review Summary Notes</h3>
      <p className="text-sm text-slate-800 leading-relaxed whitespace-pre-wrap">{text || "No summary note entered."}</p>
    </section>
  );
}

function Anomalies({
  applicationId,
  data,
  onSelectEvidence,
}: {
  applicationId: number;
  data: ApplicationReview;
  onSelectEvidence: (anomaly: Anomaly, pageNumber: number, allPageNumbers?: number[]) => void;
}) {
  const business = data.summary.business_anomalies;
  const processing = data.summary.processing_warnings;
  if (business.length === 0 && processing.length === 0) {
    return (
      <section className="space-y-3">
        <h2 className="text-base font-bold text-slate-850 font-serif">Exceptions &amp; Quality Warnings</h2>
        <InfoMessage message="No issues detected." />
      </section>
    );
  }

  return (
    <section className="space-y-6">
      <AnomalyGroup
        title={`Checklist Exceptions (${business.length})`}
        description="Field, date, document, policy validation failures that affect operational clearance."
        anomalies={business}
        tone="business"
        onSelectEvidence={onSelectEvidence}
      />
      <AnomalyGroup
        title={`Processing Warnings (${processing.length})`}
        description="OCR, classification, and metadata limitations that did not prevent check extraction."
        anomalies={processing}
        tone="processing"
        onSelectEvidence={onSelectEvidence}
      />
    </section>
  );
}

function AnomalyGroup({
  title,
  description,
  anomalies,
  tone,
  onSelectEvidence,
}: {
  title: string;
  description: string;
  anomalies: Anomaly[];
  tone: "business" | "processing";
  onSelectEvidence: (anomaly: Anomaly, pageNumber: number, allPageNumbers?: number[]) => void;
}) {
  return (
    <section className="space-y-3">
      <div className={`rounded-xl border px-4 py-3 ${tone === "business" ? "border-red-200 bg-red-50" : "border-blue-200 bg-blue-50"}`}>
        <h2 className="text-base font-bold text-slate-900">{title}</h2>
        <p className="mt-1 text-xs font-semibold text-slate-600">{description}</p>
      </div>
      {anomalies.length === 0 ? <InfoMessage message={`No ${tone === "business" ? "exceptions" : "warnings"}.`} /> : null}
      <div className="space-y-2">
        {anomalies.map((anomaly, index) => {
          const isHigh = anomaly.severity === "HIGH";
          const pages = anomaly.collapsed_page_numbers?.length
            ? anomaly.collapsed_page_numbers
            : typeof anomaly.page_number === "number"
            ? [anomaly.page_number]
            : [];
          const severityColors = isHigh
            ? "border-red-200 bg-red-50 text-red-800"
            : anomaly.severity === "MEDIUM"
            ? "border-amber-200 bg-amber-50 text-amber-800"
            : "border-slate-200 bg-slate-50 text-slate-800";
          return (
            <details key={`${anomaly.rule_id}-${anomaly.id ?? index}`} className={`overflow-hidden rounded-xl border shadow-sm bg-white ${severityColors}`} open={index === 0 && isHigh}>
              <summary className="flex cursor-pointer items-center justify-between px-4 py-3 font-semibold hover:bg-slate-50/50">
                <div className="flex items-center gap-3">
                  <span className={`stamp ${anomaly.severity === "HIGH" ? "mismatch" : "attention"}`}>
                    {anomaly.severity}
                  </span>
                  {anomaly.document_type ? (
                    <span className="inline-flex rounded bg-slate-100 px-2 py-0.5 text-[10px] font-bold uppercase text-slate-700">
                      {anomaly.document_type}
                    </span>
                  ) : null}
                  <span className="text-sm">{anomaly.reason ?? anomaly.rule_id}</span>
                </div>
              </summary>
              <div className="space-y-4 border-t border-slate-200 bg-white px-4 py-3 text-xs">
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-5">
                  <EvidenceValue label="Expected" value={anomaly.expected_value} />
                  <EvidenceValue label="Found" value={anomaly.found_value} />
                  <EvidenceValue label="Document Type" value={anomaly.document_type ?? "File-level"} />
                  <EvidenceValue label="Severity" value={anomaly.severity} />
                  <EvidenceValue label="Rule ID" value={anomaly.rule_id} />
                </div>
                {pages.length ? (
                  <div>
                    <div className="mb-2 font-semibold uppercase tracking-wider text-slate-500 text-[10px]">Open source evidence</div>
                    <div className="flex flex-wrap gap-2 items-center">
                      {pages.length > 1 ? (
                        <button
                          type="button"
                          onClick={() => onSelectEvidence(anomaly, pages[0], pages)}
                          className="rounded-lg border border-violet-200 bg-violet-50 px-3 py-1.5 font-bold text-violet-700 hover:bg-violet-100 transition-colors shadow-sm"
                        >
                          👁️ View Combined ({pages.length} pgs)
                        </button>
                      ) : null}
                      {pages.slice(0, 12).map((pageNumber) => (
                        <button
                          key={pageNumber}
                          type="button"
                          onClick={() => onSelectEvidence(anomaly, pageNumber)}
                          className="rounded-lg border border-blue-200 bg-blue-50 px-3 py-1.5 font-bold text-blue-700 hover:bg-blue-100 transition-colors"
                        >
                          Page {pageNumber}
                        </button>
                      ))}
                      {pages.length > 12 ? <span className="px-2 py-1.5 font-semibold text-slate-500">+{pages.length - 12} more pages</span> : null}
                    </div>
                  </div>
                ) : (
                  <p className="font-medium text-slate-500">This is a file-level exception with no single source page.</p>
                )}
              </div>
            </details>
          );
        })}
      </div>
    </section>
  );
}

function PageProcessing({ data, onSelectPage }: { data: ApplicationReview; onSelectPage?: (pageNo: number, docType: string) => void }) {
  const events = data.page_events;
  const avgSeconds = averagePageTime(events);
  
  return (
    <section className="space-y-4">
      <h2 className="text-base font-bold text-slate-800">Page Processing Status</h2>
      <div className="grid grid-cols-2 gap-4">
        <Metric label="Pages Processed" value={events.length} />
        <Metric label="Avg. processing speed" value={`${avgSeconds.toFixed(1)}s / page`} />
      </div>
      <SortableTable
        rows={events}
        columns={[
          { key: "pageNumber", header: "Page", value: (row) => String(row.page_number ?? "-"), sortValue: (row) => Number(row.page_number) },
          { key: "documentType", header: "Document Label", value: (row) => asText(row.document_type), sortValue: (row) => String(row.document_type ?? "") },
          { key: "elapsedSeconds", header: "Elapsed Time", value: (row) => formatSeconds(row.elapsed_seconds), sortValue: (row) => Number(row.elapsed_seconds) },
          { key: "fields", header: "Extracted Key/Values Output", value: (row) => summarizeFields(row.extracted_fields), sortValue: (row) => summarizeFields(row.extracted_fields) },
          {
            key: "action",
            header: "Open",
            value: (row) => (
              <button
                type="button"
                className="font-mono text-xs bg-[#EAF0F8] text-[#2B4C7E] border-none rounded-md px-2.5 py-1 font-semibold hover:bg-[#2B4C7E] hover:text-white transition-all cursor-pointer"
                onClick={() => row.page_number && onSelectPage?.(row.page_number, String(row.document_type || "Page"))}
              >
                Page {row.page_number}
              </button>
            ),
            sortValue: (row) => Number(row.page_number)
          },
        ]}
      />
    </section>
  );
}



function EvidenceValue({ label, value }: { label: string; value: unknown }) {
  return (
    <div>
      <div className="mb-1 font-semibold uppercase tracking-wider text-slate-500 text-[10px]">{label}</div>
      <div className="break-all font-mono text-slate-800 text-[11.5px]">{asText(value)}</div>
    </div>
  );
}

function HighlightedEvidenceText({ text, needle }: { text: string; needle: string }) {
  const cleanedNeedle = needle.trim();
  if (cleanedNeedle.length < 4) {
    return <>{text}</>;
  }
  const index = text.toLowerCase().indexOf(cleanedNeedle.toLowerCase());
  if (index < 0) {
    return <>{text}</>;
  }
  return (
    <>
      {text.slice(0, index)}
      <mark className="rounded bg-amber-300 px-0.5 text-slate-950">{text.slice(index, index + cleanedNeedle.length)}</mark>
      {text.slice(index + cleanedNeedle.length)}
    </>
  );
}

function ManualReviewAndDecision({ applicationId, data, onSelectPage }: { applicationId: number; data: ApplicationReview; onSelectPage?: (pageNo: number) => void }) {
  const [manualConfirmed, setManualConfirmed] = useState(false);
  const [note, setNote] = useState("");
  const [showRequestDocs, setShowRequestDocs] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const createDecision = useCreateDecision(applicationId);
  const undoDecision = useUndoDecision(applicationId);
  const status = String(data.application.status ?? "");
  const latestDecisionId = data.latest_decision?.id;
  const locked = Boolean(data.latest_decision && ["verified", "verified_with_override", "incomplete"].includes(status));

  async function submitDecision(decision: string, reviewerNote: string) {
    setError(null);
    const parsed = decisionNoteSchema.safeParse(reviewerNote);
    if (!parsed.success) {
      setError(parsed.error.errors[0]?.message ?? "Reviewer note is required");
      return;
    }
    await createDecision.mutateAsync({ application_id: applicationId, decision, reviewer_note: parsed.data });
  }

  return (
    <section className="space-y-4">
      <h2 className="text-base font-bold text-slate-800">Manual Review Required</h2>
      <InfoMessage message="Items requiring manual verification cannot be checked automatically." />
      {data.manual_review_items.length > 0 ? (
        <SortableTable
          rows={data.manual_review_items}
          columns={[
            { key: "sno", header: "S.No", value: (row) => asText(row.s_no), sortValue: (row) => String(row.s_no ?? "") },
            { key: "description", header: "Item Description", value: (row) => asText(row.description), sortValue: (row) => String(row.description ?? "") },
            { key: "reason", header: "Why manual review needed", value: (row) => asText(row.reason), sortValue: (row) => String(row.reason ?? "") },
          ]}
        />
      ) : null}
      
      <label className="flex items-center gap-2.5 text-sm select-none cursor-pointer">
        <input type="checkbox" checked={manualConfirmed} onChange={(event) => setManualConfirmed(event.target.checked)} className="h-4 w-4 rounded border-slate-350 text-blue-600 focus:ring-blue-500/20" />
        <span className="text-slate-700 font-bold">I confirm I have manually verified all items in the above list</span>
      </label>
      
      {error ? <ErrorMessage message={error} /> : null}
      
      {locked ? (
        <div className="space-y-3">
          <InfoMessage message={`Reviewer decision already submitted: ${data.latest_decision?.decision ?? "-"}.`} />
          {latestDecisionId ? (
            <button
              type="button"
              className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-semibold hover:bg-slate-50 transition-colors"
              onClick={() => undoDecision.mutate(latestDecisionId)}
            >
              Undo decision
            </button>
          ) : null}
        </div>
      ) : (
        <div className="space-y-3">
          <textarea
            className="h-24 w-full rounded-lg border border-slate-300 bg-white px-4 py-3 text-sm text-slate-900 placeholder-slate-400 focus:border-blue-600 focus:outline-none focus:ring-1 focus:ring-blue-600 shadow-sm"
            value={note}
            onChange={(event) => setNote(event.target.value)}
            placeholder="Reviewer note"
          />
          <div className="flex gap-2">
            <button disabled={!manualConfirmed} className="rounded-lg bg-emerald-600 hover:bg-emerald-500 px-5 py-2 text-sm font-semibold text-white disabled:bg-slate-350 disabled:text-slate-500 transition-colors duration-155 shadow-sm" onClick={() => submitDecision("ACCEPT", note || "Accepted after manual review.")}>
              Accept
            </button>
            <button disabled={!manualConfirmed} className="rounded-lg bg-blue-600 hover:bg-blue-505 px-5 py-2 text-sm font-semibold text-white disabled:bg-slate-355 disabled:text-slate-500 transition-colors duration-155 shadow-sm" onClick={() => submitDecision("OVERRIDE", note || "Override approved after review.")}>
              Override
            </button>
            <button disabled={!manualConfirmed} className="rounded-lg border border-slate-350 bg-white px-5 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:bg-slate-105 disabled:text-slate-400 transition-colors duration-155 shadow-sm" onClick={() => setShowRequestDocs(true)}>
              Request Docs
            </button>
          </div>
          {showRequestDocs ? (
            <div className="space-y-3 rounded-lg border border-slate-200 bg-slate-50 p-4">
              <div className="flex flex-wrap gap-2">
                {Object.entries(rejectionReasons).map(([label, value]) => (
                  <button key={label} type="button" className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50 transition-colors" onClick={() => setNote(value)}>
                    {label}
                  </button>
                ))}
              </div>
              <button disabled={!manualConfirmed} className="rounded-lg bg-red-600 hover:bg-red-500 px-5 py-2 text-sm font-semibold text-white disabled:bg-slate-300 disabled:text-slate-500 transition-colors duration-155 shadow-sm" onClick={() => submitDecision("REQUEST_DOCS", note)}>
                Submit request for documents
              </button>
            </div>
          ) : null}
        </div>
      )}
    </section>
  );
}

function Checklist({ data, onSelectPage }: { data: ApplicationReview; onSelectPage?: (row: any, pageNo: number, allPages?: number[]) => void }) {
  return (
    <section className="space-y-4">
      <h2 className="text-base font-bold text-slate-800">MSFC Checklist ({data.checklist.total} items)</h2>
      <div className="grid grid-cols-3 gap-4">
        <Metric label="Found Items" value={data.checklist.found} />
        <Metric label="Missing Items" value={data.checklist.missing} />
        <Metric label="Exempt Items" value={data.checklist.not_checked} />
      </div>
      <SortableTable
        rows={data.checklist.rows}
        columns={[
          { key: "sno", header: "S.No", value: (row) => row.s_no ?? "-", sortValue: (row) => row.s_no },
          { key: "status", header: "Status", value: (row) => <StatusBadge status={row.status} />, sortValue: (row) => row.status },
          { key: "description", header: "Description", value: (row) => row.description, sortValue: (row) => row.description },
          { key: "looked", header: "Looked for", value: (row) => row.document_types, sortValue: (row) => row.document_types },
          {
            key: "pages",
            header: "Pages",
            value: (row) => {
              const pageStr = String(row.pages ?? "").trim();
              if (!pageStr) return "-";
              const pageNumbers = pageStr
                .split(/,\s*/)
                .map(Number)
                .filter((n) => !isNaN(n) && n > 0);
              if (pageNumbers.length === 0) return pageStr;
              return (
                <div className="flex flex-wrap gap-1">
                  {pageNumbers.map((pageNumber) => (
                    <button
                      key={pageNumber}
                      type="button"
                      onClick={() => onSelectPage?.(row, pageNumber)}
                      className="rounded border border-blue-200 bg-blue-50 px-2 py-0.5 text-xs font-bold text-blue-750 hover:bg-blue-100 transition-colors"
                    >
                      Page {pageNumber}
                    </button>
                  ))}
                </div>
              );
            },
            sortValue: (row) => row.pages
          },
        ]}
      />
    </section>
  );
}

function Downloads({ applicationId }: { applicationId: number }) {
  return (
    <section className="space-y-3">
      <h2 className="text-base font-bold text-slate-800">Downloads</h2>
      <a className="inline-block rounded-lg border border-slate-350 bg-white hover:bg-slate-55 px-5 py-2 text-sm font-semibold text-slate-700 shadow-sm transition-colors" href={api.ocrJsonUrl(applicationId)} download>
        Download Document OCR JSON
      </a>
    </section>
  );
}

function averagePageTime(pageEvents: ApplicationReview["page_events"]): number {
  const values = pageEvents.map((page) => page.elapsed_seconds).filter((value): value is number => typeof value === "number");
  if (values.length === 0) {
    return 0;
  }
  return values.reduce((total, value) => total + value, 0) / values.length;
}

function summarizeFields(fields: Record<string, unknown> | undefined): string {
  if (!fields || Object.keys(fields).length === 0) {
    return "-";
  }
  const publicFields = Object.fromEntries(Object.entries(fields).filter(([key, value]) => !key.startsWith("_") && value));
  const text = JSON.stringify(Object.keys(publicFields).length ? publicFields : fields);
  return text.length > 160 ? `${text.slice(0, 157)}...` : text;
}

function formatLlmDocument(fields: Record<string, unknown> | undefined): string {
  if (!fields) {
    return "-";
  }
  const llmResult = fields._structured_llm_classification as Record<string, unknown> | undefined;
  if (!llmResult || typeof llmResult !== "object") {
    return "-";
  }
  const documentType = String(llmResult.document_type || "").trim();
  if (!documentType) {
    return "-";
  }
  const confidence = llmResult.confidence;
  if (typeof confidence === "number") {
    return `${documentType} (${Math.round(confidence * 100)}%)`;
  }
  return documentType;
}

function asRecordValue(val: unknown): Record<string, unknown> | undefined {
  if (val && typeof val === "object" && !Array.isArray(val)) {
    return val as Record<string, unknown>;
  }
  return undefined;
}
