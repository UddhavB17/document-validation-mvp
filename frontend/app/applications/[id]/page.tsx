"use client";

import { useParams } from "next/navigation";
import { useState } from "react";

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

const rejectionReasons = {
  "Document missing": "Please resubmit with the missing document(s) listed above.",
  "Name mismatch": "Name on submitted document does not match application records. Please verify and resubmit.",
  "Scan unclear": "Scan quality is too low to verify. Please rescan and resubmit.",
  "Statement outdated": "Bank statement is outside the allowed recency window. Please upload a recent statement.",
  "Wrong applicant": "Document appears to belong to a different applicant. Please verify and resubmit.",
  "Signature missing": "Required signature is missing. Please upload a signed copy.",
};

const severityBadgeColors = {
  HIGH: "bg-red-100 text-red-800 border border-red-200",
  MEDIUM: "bg-amber-100 text-amber-800 border border-amber-200",
  LOW: "bg-blue-50 text-blue-700 border border-blue-200",
  INFO: "bg-slate-100 text-slate-700 border border-slate-200",
};

function getSeverityBadgeColor(severity: string | null | undefined) {
  const clean = String(severity ?? "INFO").toUpperCase();
  return severityBadgeColors[clean as keyof typeof severityBadgeColors] ?? severityBadgeColors.INFO;
}

type ActiveTab = "checklist" | "anomalies" | "logs" | "all_items" | "downloads";

export default function ApplicationReviewPage() {
  const params = useParams<{ id: string }>();
  const applicationId = Number(params.id);
  const review = useApplicationReview(Number.isFinite(applicationId) ? applicationId : null);
  const [activeTab, setActiveTab] = useState<ActiveTab>("checklist");

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

  const loanId = asText(review.data.application.loan_id);
  const reviewerCount = review.data.summary.reviewer_count;

  return (
    <>
      <PageHeader
        title={`Loan File Review - ${loanId}`}
        description={`Application ID: ${applicationId} | ${asText(review.data.application.product_type)} | ${asText(review.data.application.branch)}`}
      />
      <div className="space-y-6">
        <Verdict data={review.data} />
        
        {/* Consolidated Overview Header */}
        <Overview data={review.data} />

        {[
          "uploaded",
          "processing",
          "ocr_completed",
        ].includes(String(review.data.application.status)) || review.data.progress?.retryable ? (
          <ProgressPanel applicationId={applicationId} />
        ) : null}

        <div className="flex flex-wrap gap-1 border-b border-slate-200 mt-6 bg-slate-100/50 p-1 rounded-xl">
          <TabButton
            active={activeTab === "checklist"}
            onClick={() => setActiveTab("checklist")}
          >
            Checklist & Decisions
          </TabButton>
          <TabButton
            active={activeTab === "anomalies"}
            onClick={() => setActiveTab("anomalies")}
          >
            Anomalies & Flags ({reviewerCount})
          </TabButton>
          <TabButton
            active={activeTab === "logs"}
            onClick={() => setActiveTab("logs")}
          >
            Page Processing Logs
          </TabButton>
          <TabButton
            active={activeTab === "all_items"}
            onClick={() => setActiveTab("all_items")}
          >
            Full Verification List
          </TabButton>
          <TabButton
            active={activeTab === "downloads"}
            onClick={() => setActiveTab("downloads")}
          >
            Downloads
          </TabButton>
        </div>

        {/* Active Tab Card */}
        <div className="bg-white border border-slate-200 rounded-2xl p-6 shadow-sm min-h-[300px]">
          {activeTab === "checklist" ? (
            <div className="space-y-6">
              <ReviewerSummary data={review.data} />
              <ManualReviewAndDecision applicationId={applicationId} data={review.data} />
            </div>
          ) : null}

          {activeTab === "anomalies" ? (
            <div className="space-y-6">
              <ResultExplanation data={review.data} />
              <Anomalies applicationId={applicationId} data={review.data} />
            </div>
          ) : null}

          {activeTab === "logs" ? (
            <PageProcessing data={review.data} />
          ) : null}

          {activeTab === "all_items" ? (
            <Checklist data={review.data} />
          ) : null}

          {activeTab === "downloads" ? (
            <Downloads applicationId={applicationId} />
          ) : null}
        </div>
      </div>
    </>
  );
}

function TabButton({
  active,
  children,
  onClick,
}: {
  active: boolean;
  children: React.ReactNode;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={`px-4 py-2.5 text-sm font-semibold transition-all rounded-lg select-none ${
        active
          ? "bg-white text-blue-700 shadow-sm border border-slate-200/50"
          : "text-slate-500 hover:text-slate-800 hover:bg-slate-200/50"
      }`}
    >
      {children}
    </button>
  );
}

function Verdict({ data }: { data: ApplicationReview }) {
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

function Overview({ data }: { data: ApplicationReview }) {
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

function ReviewerSummary({ data }: { data: ApplicationReview }) {
  const summary = data.reviewer_summary;
  if (!summary) {
    return null;
  }
  const status = String(summary.overall_status ?? "LIMITED_REVIEW");
  const pages = Array.isArray(summary.pages_to_review) ? summary.pages_to_review.join(", ") : "";
  return (
    <section className="bg-slate-50 border border-slate-200 rounded-xl p-5 space-y-3">
      <h2 className="text-base font-bold text-slate-800">
        Reviewer Action Summary
      </h2>
      <div className="flex flex-wrap items-center gap-3">
        <StatusBadge status={status} />
        <span className="text-sm text-slate-700 font-bold">{asText(summary.message)}</span>
      </div>
      <p className="text-sm text-slate-600 font-medium leading-relaxed">{asText(summary.recommendation)}</p>
      {pages ? (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm font-semibold text-amber-800 shadow-sm">
          Pages to check manually: <span className="font-bold">{pages}</span>
        </div>
      ) : null}
    </section>
  );
}

function AiAuditInsights({
  data,
  onSelectEvidence,
}: {
  data: ApplicationReview;
  onSelectEvidence?: (anomaly: Anomaly, pageNumber: number) => void;
}) {
  const rawSummary = data.application.llm_summary;
  if (!rawSummary || typeof rawSummary !== "string" || !rawSummary.trim()) {
    return null;
  }

  interface PageSummary {
    page_number?: number | null;
    document_type?: string | null;
    summary_points?: string[];
    problem_description?: string;
  }

  interface LlmSummarySchema {
    overall_summary: string;
    final_recommendation: string;
    page_summaries?: PageSummary[];
  }

  let parsed: LlmSummarySchema | null = null;
  try {
    parsed = JSON.parse(rawSummary) as LlmSummarySchema;
  } catch (err) {
    parsed = null;
  }

  if (!parsed) {
    return (
      <section className="bg-slate-50 border border-slate-200 rounded-2xl p-5 space-y-3">
        <div className="flex items-center gap-2 text-violet-750 font-bold">
          <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth="2.5" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904L9 21l-.813-5.096L3 15l5.096-.813L9 9l.813 5.187L15 15l-5.187.813zM18 10.5l-.5-3-.5 3-3 .5 3 .5.5 3 .5-3 3-.5-3-.5zM20.25 5.25l-.25-1.5-.25 1.5-1.5.25 1.5.25.25 1.5.25-1.5 1.5-.25-1.5-.25z" />
          </svg>
          <h2 className="text-base font-bold text-slate-800">AI Audit Insights</h2>
        </div>
        <p className="text-sm text-slate-700 whitespace-pre-line font-medium leading-relaxed">{rawSummary}</p>
      </section>
    );
  }

  const rec = String(parsed.final_recommendation || "MANUAL REVIEW").toUpperCase();
  let badgeColor = "border-amber-300 bg-amber-50 text-amber-800";
  if (rec === "APPROVE") {
    badgeColor = "border-emerald-300 bg-emerald-50 text-emerald-800";
  } else if (rec === "MANUAL REVIEW") {
    badgeColor = "border-rose-300 bg-rose-50 text-rose-800";
  }

  return (
    <section className="overflow-hidden border border-slate-200 bg-slate-50/30 rounded-2xl shadow-sm space-y-0">
      <div className="bg-gradient-to-r from-violet-600 via-indigo-600 to-blue-600 px-6 py-4 text-white flex items-center justify-between shadow-xs">
        <div className="flex items-center gap-3">
          <div className="rounded-lg bg-white/20 p-1.5 backdrop-blur-md">
            <svg className="w-5 h-5 text-amber-300 animate-pulse animate-duration-1000" fill="none" stroke="currentColor" strokeWidth="2.5" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904L9 21l-.813-5.096L3 15l5.096-.813L9 9l.813 5.187L15 15l-5.187.813zM18 10.5l-.5-3-.5 3-3 .5 3 .5.5 3 .5-3 3-.5-3-.5zM20.25 5.25l-.25-1.5-.25 1.5-1.5.25 1.5.25.25 1.5.25-1.5 1.5-.25-1.5-.25z" />
            </svg>
          </div>
          <div>
            <h2 className="text-base font-extrabold tracking-tight">AI Audit Insights</h2>
            <p className="text-[10px] text-indigo-100 font-medium tracking-wide">TOKEN-OPTIMIZED PAGE EXPLANATION</p>
          </div>
        </div>
        <div className={`px-3 py-1 rounded-full border text-[11px] font-bold uppercase ${badgeColor} bg-white shadow-sm flex items-center gap-1.5`}>
          <span className="w-1.5 h-1.5 rounded-full bg-current animate-ping" />
          {rec}
        </div>
      </div>

      <div className="p-6 space-y-6">
        <div className="bg-white border border-slate-150 rounded-xl p-5 shadow-xs space-y-2">
          <h3 className="text-[10px] font-extrabold uppercase tracking-widest text-slate-400">Executive Summary</h3>
          <p className="text-sm font-semibold text-slate-700 leading-relaxed italic">
            &ldquo;{parsed.overall_summary}&rdquo;
          </p>
        </div>

        {parsed.page_summaries && parsed.page_summaries.length > 0 ? (
          <div className="space-y-4">
            <h3 className="text-[10px] font-extrabold uppercase tracking-widest text-slate-400 mb-1">Page-by-Page Findings</h3>
            <div className="grid gap-4 md:grid-cols-1">
              {parsed.page_summaries.map((item, index) => {
                const hasPage = typeof item.page_number === "number" || (typeof item.page_number === "string" && item.page_number);
                const correspondingAnomaly = data.anomalies.find(a => 
                  a.page_number === Number(item.page_number) || 
                  a.collapsed_page_numbers?.includes(Number(item.page_number))
                );
                return (
                  <div key={index} className="bg-white border border-slate-200 rounded-xl shadow-xs overflow-hidden flex flex-col hover:border-violet-300 transition-colors duration-200">
                    <div className="bg-slate-50/50 border-b border-slate-150 px-4 py-2.5 flex items-center justify-between">
                      <span className="text-xs font-bold text-slate-700 flex items-center gap-2">
                        <span className="rounded bg-violet-100 text-violet-700 px-2 py-0.5 text-[9px] font-bold uppercase tracking-wider">
                          {hasPage ? `PAGE ${item.page_number}` : "GENERAL"}
                        </span>
                        {item.document_type || "Unknown Document"}
                      </span>
                      {hasPage && onSelectEvidence ? (
                        <button
                          type="button"
                          onClick={() => {
                            const anomalyToSelect = correspondingAnomaly || { 
                              page_number: Number(item.page_number), 
                              document_type: item.document_type,
                              rule_id: "AI_PAGE_REVIEW",
                              severity: "INFO",
                              reason: item.problem_description
                            };
                            onSelectEvidence(anomalyToSelect, Number(item.page_number));
                          }}
                          className="rounded-lg border border-blue-200 bg-blue-50 px-2.5 py-1 text-[10px] font-bold text-blue-700 hover:bg-blue-100 transition-colors"
                        >
                          View Page {item.page_number}
                        </button>
                      ) : null}
                    </div>

                    <div className="p-4 space-y-3">
                      {item.summary_points && item.summary_points.length > 0 ? (
                        <div className="space-y-1.5">
                          <div className="text-[9px] font-bold uppercase text-slate-400 tracking-wider">Page Content Summary</div>
                          <ul className="space-y-1 text-xs text-slate-600 font-medium">
                            {item.summary_points.map((pt, i) => (
                              <li key={i} className="flex items-start gap-2">
                                <span className="text-emerald-500 font-bold mt-0.5">•</span>
                                <span>{pt}</span>
                              </li>
                            ))}
                          </ul>
                        </div>
                      ) : null}

                      {item.problem_description ? (
                        <div className="rounded-lg bg-rose-50 border border-rose-100 p-3 text-xs">
                          <div className="flex gap-2">
                            <span className="text-rose-500 font-bold">⚠️</span>
                            <div>
                              <div className="font-bold text-rose-800 flex items-center gap-2">
                                <span>Anomaly Detected</span>
                                {correspondingAnomaly ? (
                                  <>
                                    <span className={`rounded px-1.5 py-0.5 text-[9px] font-extrabold uppercase tracking-wider animate-pulse animate-duration-1000 ${getSeverityBadgeColor(correspondingAnomaly.severity)}`}>
                                      {correspondingAnomaly.severity}
                                    </span>
                                    <span className="rounded bg-slate-100 text-slate-700 px-1.5 py-0.5 text-[9px] font-extrabold uppercase tracking-wider">
                                      {correspondingAnomaly.rule_id}
                                    </span>
                                  </>
                                ) : null}
                              </div>
                              <div className="mt-0.5 text-rose-750 font-medium leading-relaxed">{item.problem_description}</div>
                            </div>
                          </div>
                        </div>
                      ) : null}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        ) : null}
      </div>
    </section>
  );
}

function ResultExplanation({ data }: { data: ApplicationReview }) {
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

function PageProcessing({ data }: { data: ApplicationReview }) {
  if (data.page_events.length === 0) {
    return <InfoMessage message="No page events logged." />;
  }
  return (
    <section className="space-y-3">
      <h2 className="text-base font-bold text-slate-800">Page Processing Output</h2>
      <SortableTable
        rows={data.page_events}
        columns={[
          { key: "page", header: "Page", value: (row) => row.page_number ?? "-", sortValue: (row) => row.page_number },
          { key: "status", header: "Status", value: (row) => <StatusBadge status={row.status ?? "unknown"} />, sortValue: (row) => row.status },
          { key: "type", header: "Type", value: (row) => row.page_type ?? "-", sortValue: (row) => row.page_type },
          { key: "document", header: "Document", value: (row) => row.document_type ?? "Unknown", sortValue: (row) => row.document_type },
          { key: "llm_document", header: "LLM Document", value: (row) => formatLlmDocument(row.extracted_fields), sortValue: (row) => formatLlmDocument(row.extracted_fields) },
          { key: "time", header: "Time", value: (row) => formatSeconds(row.elapsed_seconds), sortValue: (row) => row.elapsed_seconds },
          { key: "data", header: "Data", value: (row) => row.error ?? summarizeFields(row.extracted_fields) },
        ]}
      />
    </section>
  );
}

function Anomalies({ applicationId, data }: { applicationId: number; data: ApplicationReview }) {
  const [selectedEvidence, setSelectedEvidence] = useState<{ anomaly: Anomaly; pageNumber: number } | null>(null);
  const business = data.summary.business_anomalies;
  const processing = data.summary.processing_warnings;
  if (business.length === 0 && processing.length === 0) {
    return (
      <section className="space-y-3">
        <h2 className="text-base font-bold text-slate-800">Exceptions and Quality Warnings</h2>
        <InfoMessage message="No issues detected." />
      </section>
    );
  }

  const handleSelectEvidence = (anomaly: Anomaly, pageNumber: number) => {
    setSelectedEvidence({ anomaly, pageNumber });
    setTimeout(() => {
      const viewer = document.getElementById("evidence-viewer");
      if (viewer) {
        viewer.scrollIntoView({ behavior: "smooth", block: "nearest" });
      }
    }, 100);
  };

  return (
    <section className="space-y-4">
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(580px,1.3fr)] items-start">
        <div className="space-y-6">
          <AiAuditInsights data={data} onSelectEvidence={handleSelectEvidence} />
          <AnomalyGroup
            title={`Business Checklist Exceptions (${business.length})`}
            description="Document, identity, field, date, and policy exceptions that can affect the operational decision."
            anomalies={business}
            tone="business"
            onSelectEvidence={handleSelectEvidence}
          />
          <AnomalyGroup
            title={`Processing Quality Warnings (${processing.length})`}
            description="OCR, classification, ownership, and page-processing limitations. These require evidence review but are not business failures by themselves."
            anomalies={processing}
            tone="processing"
            onSelectEvidence={handleSelectEvidence}
          />
        </div>
        <EvidenceViewer applicationId={applicationId} data={data} selection={selectedEvidence} />
      </div>
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
  onSelectEvidence: (anomaly: Anomaly, pageNumber: number) => void;
}) {
  return (
    <section className="space-y-3">
      <div className={`rounded-xl border px-4 py-3 ${tone === "business" ? "border-red-200 bg-red-50" : "border-blue-200 bg-blue-50"}`}>
        <h2 className="text-base font-bold text-slate-900">{title}</h2>
        <p className="mt-1 text-xs font-medium text-slate-600">{description}</p>
      </div>
      {anomalies.length === 0 ? <InfoMessage message={`No ${tone === "business" ? "business exceptions" : "processing warnings"}.`} /> : null}
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
            <details key={`${anomaly.rule_id}-${anomaly.id ?? index}`} className={`overflow-hidden rounded-xl border shadow-sm ${severityColors}`} open={index === 0 && isHigh}>
              <summary className="flex cursor-pointer items-center justify-between px-4 py-3 font-semibold hover:bg-white/50">
                <div className="flex items-center gap-3">
                  <span className={`inline-flex rounded px-2 py-0.5 text-[10px] font-bold uppercase ${getSeverityBadgeColor(anomaly.severity)}`}>
                    {anomaly.severity}
                  </span>
                  {anomaly.document_type ? (
                    <span className="inline-flex rounded bg-white/70 px-2 py-0.5 text-[10px] font-bold uppercase text-slate-700">
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
                    <div className="mb-2 font-semibold uppercase tracking-wider text-slate-500">Open source evidence</div>
                    <div className="flex flex-wrap gap-2">
                      {pages.slice(0, 12).map((pageNumber) => (
                        <button
                          key={pageNumber}
                          type="button"
                          onClick={() => onSelectEvidence(anomaly, pageNumber)}
                          className="rounded-lg border border-blue-200 bg-blue-50 px-3 py-1.5 font-bold text-blue-700 hover:bg-blue-100"
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

function EvidenceViewer({
  applicationId,
  data,
  selection,
}: {
  applicationId: number;
  data: ApplicationReview;
  selection: { anomaly: Anomaly; pageNumber: number } | null;
}) {
  if (!selection) {
    return (
      <aside id="evidence-viewer" className="sticky top-4 flex h-[70vh] items-center justify-center rounded-xl border-2 border-dashed border-slate-200 bg-slate-50 p-8 text-center">
        <div>
          <div className="text-base font-bold text-slate-700">Source Evidence Viewer</div>
          <p className="mt-2 max-w-sm text-sm text-slate-500">Select a page from an exception to open the original PDF beside its expected and extracted values.</p>
        </div>
      </aside>
    );
  }
  const page = data.pages.find((item) => Number(item.page_number) === selection.pageNumber);
  const ocrText = typeof page?.ocr_text === "string" ? page.ocr_text : "";
  return (
    <aside id="evidence-viewer" className="sticky top-4 overflow-hidden rounded-xl border border-slate-300 bg-white shadow-sm">
      <div className="border-b border-slate-200 bg-slate-50 px-4 py-3">
        <div className="flex items-center justify-between gap-4">
          <div>
            <div className="text-xs font-bold uppercase tracking-wider text-slate-500">Original source evidence</div>
            <div className="font-bold text-slate-900">Page {selection.pageNumber} · {asText(page?.document_type ?? selection.anomaly.document_type)}</div>
          </div>
          <a href={api.sourcePdfUrl(applicationId, selection.pageNumber)} target="_blank" rel="noreferrer" className="text-xs font-bold text-blue-700 hover:underline">Open full PDF</a>
        </div>
      </div>
      <div
        key={selection.pageNumber}
        className="flex h-[65vh] items-start justify-center overflow-auto bg-slate-800 p-4"
      >
        {/* The evidence image is generated by the local API and needs its natural aspect ratio. */}
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={api.sourcePageImageUrl(applicationId, selection.pageNumber)}
          alt={`Original source PDF page ${selection.pageNumber}`}
          className="h-auto max-w-full bg-white shadow-lg"
        />
      </div>
      <div className="max-h-[24vh] space-y-3 overflow-auto border-t border-slate-200 p-4 text-xs">
        <div className="grid grid-cols-2 gap-3">
          <EvidenceValue label="Expected" value={selection.anomaly.expected_value} />
          <EvidenceValue label="Extracted / Found" value={selection.anomaly.found_value} />
        </div>
        <div>
          <div className="mb-1 font-semibold uppercase tracking-wider text-slate-500">Extracted page text</div>
          <div className="whitespace-pre-wrap rounded-lg bg-slate-950 p-3 font-mono leading-relaxed text-slate-100">
            {ocrText ? <HighlightedEvidenceText text={ocrText.slice(0, 3500)} needle={selection.anomaly.found_value ?? ""} /> : "No OCR text was extracted for this page. Review the original image above."}
          </div>
        </div>
      </div>
    </aside>
  );
}

function EvidenceValue({ label, value }: { label: string; value: unknown }) {
  return (
    <div>
      <div className="mb-1 font-semibold uppercase tracking-wider text-slate-500">{label}</div>
      <div className="break-all font-mono text-slate-800">{asText(value)}</div>
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

function ManualReviewAndDecision({ applicationId, data }: { applicationId: number; data: ApplicationReview }) {
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
        <input type="checkbox" checked={manualConfirmed} onChange={(event) => setManualConfirmed(event.target.checked)} className="h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500/20" />
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
            <button disabled={!manualConfirmed} className="rounded-lg bg-emerald-600 hover:bg-emerald-500 px-5 py-2 text-sm font-semibold text-white disabled:bg-slate-300 disabled:text-slate-500 transition-colors duration-150 shadow-sm" onClick={() => submitDecision("ACCEPT", note || "Accepted after manual review.")}>
              Accept
            </button>
            <button disabled={!manualConfirmed} className="rounded-lg bg-blue-600 hover:bg-blue-500 px-5 py-2 text-sm font-semibold text-white disabled:bg-slate-300 disabled:text-slate-500 transition-colors duration-150 shadow-sm" onClick={() => submitDecision("OVERRIDE", note || "Override approved after review.")}>
              Override
            </button>
            <button disabled={!manualConfirmed} className="rounded-lg border border-slate-350 bg-white px-5 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:bg-slate-100 disabled:text-slate-400 transition-colors duration-150 shadow-sm" onClick={() => setShowRequestDocs(true)}>
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
              <button disabled={!manualConfirmed} className="rounded-lg bg-red-600 hover:bg-red-500 px-5 py-2 text-sm font-semibold text-white disabled:bg-slate-300 disabled:text-slate-500 transition-colors duration-150 shadow-sm" onClick={() => submitDecision("REQUEST_DOCS", note)}>
                Submit request for documents
              </button>
            </div>
          ) : null}
        </div>
      )}
    </section>
  );
}

function Checklist({ data }: { data: ApplicationReview }) {
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
          { key: "pages", header: "Pages", value: (row) => row.pages, sortValue: (row) => row.pages },
        ]}
      />
    </section>
  );
}

function Downloads({ applicationId }: { applicationId: number }) {
  return (
    <section className="space-y-3">
      <h2 className="text-base font-bold text-slate-800">Downloads</h2>
      <a className="inline-block rounded-lg border border-slate-300 bg-white hover:bg-slate-50 px-5 py-2 text-sm font-semibold text-slate-700 shadow-sm transition-colors" href={api.ocrJsonUrl(applicationId)} download>
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
