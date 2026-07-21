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

        {["uploaded", "processing", "ocr_completed"].includes(String(review.data.application.status)) ? (
          <ProgressPanel applicationId={applicationId} />
        ) : null}

        {/* UX Tab Navigation Bar */}
        <div className="flex flex-wrap gap-1 border-b border-slate-200 mt-6 bg-slate-100/50 p-1 rounded-xl">
          <TabButton
            active={activeTab === "checklist"}
            onClick={() => setActiveTab("checklist")}
          >
            📋 Checklist & Decisions
          </TabButton>
          <TabButton
            active={activeTab === "anomalies"}
            onClick={() => setActiveTab("anomalies")}
          >
            ⚠️ Anomalies & Flags ({reviewerCount})
          </TabButton>
          <TabButton
            active={activeTab === "logs"}
            onClick={() => setActiveTab("logs")}
          >
            🔍 Page Processing Logs
          </TabButton>
          <TabButton
            active={activeTab === "all_items"}
            onClick={() => setActiveTab("all_items")}
          >
            📄 Full Verification List
          </TabButton>
          <TabButton
            active={activeTab === "downloads"}
            onClick={() => setActiveTab("downloads")}
          >
            📥 Downloads
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
              <Anomalies anomalies={review.data.summary.reviewer_anomalies} />
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
  const reviewerCount = data.summary.reviewer_count;
  const highCount = data.summary.high_count;
  let title = "NEEDS REVIEW";
  let detail = `${reviewerCount} issue(s) to check`;
  let classes = "border-amber-300 bg-amber-50 text-amber-900";
  if (status === "CLEAN" || reviewerCount === 0) {
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
        <span className="text-xl">📢</span>
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
      <h2 className="text-base font-bold text-slate-800 flex items-center gap-2">
        <span>📋</span> Reviewer Action Summary
      </h2>
      <div className="flex flex-wrap items-center gap-3">
        <StatusBadge status={status} />
        <span className="text-sm text-slate-700 font-bold">{asText(summary.message)}</span>
      </div>
      <p className="text-sm text-slate-600 font-medium leading-relaxed">{asText(summary.recommendation)}</p>
      {pages ? (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm font-semibold text-amber-800 shadow-sm">
          💡 Pages to check manually: <span className="font-bold">{pages}</span>
        </div>
      ) : null}
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

function Anomalies({ anomalies }: { anomalies: Anomaly[] }) {
  if (anomalies.length === 0) {
    return (
      <section className="space-y-3">
        <h2 className="text-base font-bold text-slate-800">System Anomalies</h2>
        <InfoMessage message="No issues detected." />
      </section>
    );
  }
  return (
    <section className="space-y-3">
      <h2 className="text-base font-bold text-slate-800">System Anomalies & Flags</h2>
      <div className="space-y-2">
        {anomalies.map((anomaly, index) => {
          const isHigh = anomaly.severity === "HIGH";
          const severityColors = isHigh 
            ? "border-red-200 bg-red-50 text-red-800" 
            : anomaly.severity === "MEDIUM"
            ? "border-amber-200 bg-amber-50 text-amber-800"
            : "border-slate-200 bg-slate-50 text-slate-800";
          return (
            <details key={anomaly.id ?? index} className={`rounded-xl border ${severityColors} overflow-hidden shadow-sm`} open={index === 0 && isHigh}>
              <summary className="cursor-pointer px-4 py-3 font-semibold hover:bg-slate-100 flex items-center justify-between select-none">
                <div className="flex items-center gap-3">
                  <span className={`inline-flex px-2 py-0.5 rounded text-[10px] font-bold uppercase ${
                    isHigh ? "bg-red-200 text-red-800" : anomaly.severity === "MEDIUM" ? "bg-amber-200 text-amber-800" : "bg-slate-200 text-slate-800"
                  }`}>
                    {anomaly.severity}
                  </span>
                  <span className="text-sm">Page {anomaly.page_number ?? "Global"} — {anomaly.reason ?? anomaly.rule_id}</span>
                </div>
              </summary>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-5 border-t border-slate-200 bg-white px-4 py-3 text-xs">
                <div>
                  <div className="font-semibold text-slate-500 uppercase tracking-wider mb-1">Expected</div>
                  <div className="font-mono text-slate-800 break-all">{asText(anomaly.expected_value)}</div>
                </div>
                <div>
                  <div className="font-semibold text-slate-500 uppercase tracking-wider mb-1">Found</div>
                  <div className="font-mono text-slate-800 break-all">{asText(anomaly.found_value)}</div>
                </div>
                <div>
                  <div className="font-semibold text-slate-500 uppercase tracking-wider mb-1">Rule ID</div>
                  <code className="text-blue-700 font-mono">{anomaly.rule_id}</code>
                </div>
                <div>
                  <div className="font-semibold text-slate-500 uppercase tracking-wider mb-1">Affected Pages</div>
                  <div className="font-mono text-slate-800">{anomaly.collapsed_page_numbers?.join(", ") ?? anomaly.page_number ?? "Global"}</div>
                </div>
              </div>
            </details>
          );
        })}
      </div>
    </section>
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
      <a className="inline-block rounded-lg border border-slate-300 bg-white hover:bg-slate-55 px-5 py-2 text-sm font-semibold text-slate-700 shadow-sm transition-colors" href={api.ocrJsonUrl(applicationId)} download>
        ⬇ Download Document OCR JSON
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
