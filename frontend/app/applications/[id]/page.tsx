"use client";

import { useParams } from "next/navigation";
import { useState } from "react";

import { ErrorMessage, InfoMessage, LoadingMessage } from "@/components/Message";
import { Metric } from "@/components/Metric";
import { PageHeader } from "@/components/PageHeader";
import { ProgressPanel } from "@/components/ProgressPanel";
import { SortableTable } from "@/components/SortableTable";
import { api, Anomaly, ApplicationReview } from "@/lib/api";
import { decisionNoteSchema } from "@/lib/forms";
import { asText, formatSeconds, statusTone } from "@/lib/format";
import { useApplicationReview, useCreateDecision, useUndoDecision } from "@/lib/queries";

const rejectionReasons = {
  "Document missing": "Please resubmit with the missing document(s) listed above.",
  "Name mismatch": "Name on submitted document does not match application records. Please verify and resubmit.",
  "Scan unclear": "Scan quality is too low to verify. Please rescan and resubmit.",
  "Statement outdated": "Bank statement is outside the allowed recency window. Please upload a recent statement.",
  "Wrong applicant": "Document appears to belong to a different applicant. Please verify and resubmit.",
  "Signature missing": "Required signature is missing. Please upload a signed copy.",
};

export default function ApplicationReviewPage() {
  const params = useParams<{ id: string }>();
  const applicationId = Number(params.id);
  const review = useApplicationReview(Number.isFinite(applicationId) ? applicationId : null);

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
  return (
    <>
      <PageHeader
        title={`Loan File Review - ${loanId}`}
        description={`Application ${applicationId} | ${asText(review.data.application.product_type)} | ${asText(review.data.application.branch)}`}
      />
      <div className="space-y-8">
        <Verdict data={review.data} />
        {["uploaded", "processing", "ocr_completed"].includes(String(review.data.application.status)) ? (
          <ProgressPanel applicationId={applicationId} />
        ) : null}
        <ReviewerSummary data={review.data} />
        <SummaryMetrics data={review.data} />
        <ApplicationData data={review.data} />
        <ResultExplanation data={review.data} />
        <PageProcessing data={review.data} />
        <Anomalies anomalies={review.data.summary.reviewer_anomalies} />
        <ManualReviewAndDecision applicationId={applicationId} data={review.data} />
        <Checklist data={review.data} />
        <Downloads applicationId={applicationId} />
      </div>
    </>
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
    classes = "border-red-300 bg-red-50 text-red-900";
  }
  return <div className={`rounded border-l-4 px-4 py-3 font-semibold ${classes}`}>{title} - {detail}</div>;
}

function SummaryMetrics({ data }: { data: ApplicationReview }) {
  const uploaded = data.uploaded_file;
  const avgPageTime = averagePageTime(data.page_events);
  return (
    <section>
      <h2 className="mb-3 text-lg font-semibold">Review Summary</h2>
      <div className="grid grid-cols-6 gap-3">
        <Metric label="Status" value={data.application.status} />
        <Metric label="Total Pages" value={uploaded.total_pages ?? data.pages.length} />
        <Metric label="Digital" value={uploaded.digital_pages} />
        <Metric label="Scanned" value={uploaded.scanned_pages} />
        <Metric label="Checklist Passed" value={`${data.ai_checklist.passed}/${data.ai_checklist.total || "-"}`} />
        <Metric label="Avg Page Time" value={avgPageTime ? `${avgPageTime.toFixed(2)}s` : "-"} />
      </div>
      <p className="mt-2 text-sm text-slate-600">Reviewer-visible issues: {data.summary.reviewer_count}</p>
    </section>
  );
}

function ApplicationData({ data }: { data: ApplicationReview }) {
  return (
    <section>
      <h2 className="mb-3 text-lg font-semibold">Application Data</h2>
      <div className="grid grid-cols-5 gap-3">
        <Metric label="Applicant" value={data.ground_truth.applicant_name ?? data.application.applicant_name} />
        <Metric label="PAN" value={data.ground_truth.pan_number} />
        <Metric label="Loan Amount" value={data.ground_truth.loan_amount} />
        <Metric label="Branch" value={data.application.branch} />
        <Metric label="Product" value={data.application.product_type} />
      </div>
    </section>
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
    <section className="space-y-3">
      <h2 className="text-lg font-semibold">Reviewer Action Summary</h2>
      <InfoMessage message={`${status.replace(/_/g, " ")}: ${asText(summary.message)}`} />
      <p className="text-sm text-slate-700">{asText(summary.recommendation)}</p>
      {pages ? <div className="rounded border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">Pages to check manually: {pages}</div> : null}
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
    <section>
      <h2 className="mb-3 text-lg font-semibold">Result Explanation</h2>
      <InfoMessage message={message} />
    </section>
  );
}

function PageProcessing({ data }: { data: ApplicationReview }) {
  if (data.page_events.length === 0) {
    return null;
  }
  return (
    <section>
      <h2 className="mb-3 text-lg font-semibold">Page Processing Output</h2>
      <SortableTable
        rows={data.page_events}
        columns={[
          { key: "page", header: "Page", value: (row) => row.page_number ?? "-", sortValue: (row) => row.page_number },
          { key: "status", header: "Status", value: (row) => row.status ?? "-", sortValue: (row) => row.status },
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
      <section>
        <h2 className="mb-3 text-lg font-semibold">Anomalies</h2>
        <InfoMessage message="No issues detected." />
      </section>
    );
  }
  return (
    <section>
      <h2 className="mb-3 text-lg font-semibold">Anomalies</h2>
      <div className="space-y-3">
        {anomalies.map((anomaly, index) => (
          <details key={anomaly.id ?? index} className="rounded border border-slate-200 bg-white" open={index === 0 && anomaly.severity === "HIGH"}>
            <summary className="cursor-pointer px-4 py-3 font-medium">
              {asText(anomaly.severity).toUpperCase()} | Page {asText(anomaly.page_number)} | {asText(anomaly.reason ?? anomaly.rule_id)}
            </summary>
            <div className="grid grid-cols-2 gap-4 border-t border-slate-100 px-4 py-3 text-sm">
              <div>
                <div className="font-medium text-slate-700">Expected</div>
                <div>{asText(anomaly.expected_value)}</div>
              </div>
              <div>
                <div className="font-medium text-slate-700">Found</div>
                <div>{asText(anomaly.found_value)}</div>
              </div>
              <div>
                <div className="font-medium text-slate-700">Rule</div>
                <div>{asText(anomaly.rule_id)}</div>
              </div>
              <div>
                <div className="font-medium text-slate-700">Pages affected</div>
                <div>{anomaly.collapsed_page_numbers?.join(", ") ?? "-"}</div>
              </div>
            </div>
          </details>
        ))}
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
      <h2 className="text-lg font-semibold">Manual Review Required</h2>
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
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={manualConfirmed} onChange={(event) => setManualConfirmed(event.target.checked)} />
        I confirm I have manually verified all items in the above list
      </label>
      {error ? <ErrorMessage message={error} /> : null}
      {locked ? (
        <div className="space-y-3">
          <InfoMessage message={`Reviewer decision already submitted: ${data.latest_decision?.decision ?? "-"}.`} />
          {latestDecisionId ? (
            <button
              type="button"
              className="rounded border border-slate-300 bg-white px-4 py-2 text-sm"
              onClick={() => undoDecision.mutate(latestDecisionId)}
            >
              Undo decision
            </button>
          ) : null}
        </div>
      ) : (
        <div className="space-y-3">
          <textarea
            className="h-24 w-full rounded border border-slate-300 px-3 py-2 text-sm"
            value={note}
            onChange={(event) => setNote(event.target.value)}
            placeholder="Reviewer note"
          />
          <div className="flex gap-2">
            <button disabled={!manualConfirmed} className="rounded bg-blue-700 px-4 py-2 text-sm font-medium text-white disabled:bg-slate-400" onClick={() => submitDecision("ACCEPT", note || "Accepted after manual review.")}>
              Accept
            </button>
            <button disabled={!manualConfirmed} className="rounded bg-blue-700 px-4 py-2 text-sm font-medium text-white disabled:bg-slate-400" onClick={() => submitDecision("OVERRIDE", note || "Override approved after review.")}>
              Override
            </button>
            <button disabled={!manualConfirmed} className="rounded border border-slate-300 bg-white px-4 py-2 text-sm disabled:text-slate-400" onClick={() => setShowRequestDocs(true)}>
              Request Docs
            </button>
          </div>
          {showRequestDocs ? (
            <div className="space-y-3 rounded border border-slate-200 bg-white p-4">
              <div className="flex flex-wrap gap-2">
                {Object.entries(rejectionReasons).map(([label, value]) => (
                  <button key={label} type="button" className="rounded border border-slate-300 px-3 py-1.5 text-sm" onClick={() => setNote(value)}>
                    {label}
                  </button>
                ))}
              </div>
              <button disabled={!manualConfirmed} className="rounded bg-blue-700 px-4 py-2 text-sm font-medium text-white disabled:bg-slate-400" onClick={() => submitDecision("REQUEST_DOCS", note)}>
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
    <section>
      <h2 className="mb-3 text-lg font-semibold">MSFC Checklist ({data.checklist.total} items)</h2>
      <div className="mb-3 grid grid-cols-3 gap-3">
        <Metric label="Found" value={data.checklist.found} />
        <Metric label="Missing" value={data.checklist.missing} />
        <Metric label="Not checked" value={data.checklist.not_checked} />
      </div>
      <SortableTable
        rows={data.checklist.rows}
        columns={[
          { key: "sno", header: "S.No", value: (row) => row.s_no ?? "-", sortValue: (row) => row.s_no },
          { key: "status", header: "Status", value: (row) => <span className={statusTone(row.status)}>{statusLabel(row.status)}</span>, sortValue: (row) => row.status },
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
    <section>
      <h2 className="mb-3 text-lg font-semibold">Downloads</h2>
      <a className="inline-block rounded border border-slate-300 bg-white px-4 py-2 text-sm" href={api.ocrJsonUrl(applicationId)} download>
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

function statusLabel(status: string): string {
  if (status === "FOUND") {
    return "Found";
  }
  if (status === "MISSING") {
    return "Missing";
  }
  return "Not checked";
}
