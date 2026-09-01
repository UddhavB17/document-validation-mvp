"use client";

import { useParams } from "next/navigation";
import { useState } from "react";

import { Anomalies } from "@/components/applications/Anomalies";
import { Checklist } from "@/components/applications/Checklist";
import { Downloads } from "@/components/applications/Downloads";
import { EvidenceViewer } from "@/components/applications/EvidenceViewer";
import { ManualReviewAndDecision } from "@/components/applications/ManualReviewAndDecision";
import { Overview } from "@/components/applications/Overview";
import { PageProcessing } from "@/components/applications/PageProcessing";
import { ResultExplanation } from "@/components/applications/ResultExplanation";
import { ReviewerSummary } from "@/components/applications/ReviewerSummary";
import { TabButton } from "@/components/applications/TabButton";
import { ActiveTab, EvidenceSelection } from "@/components/applications/types";
import { Verdict } from "@/components/applications/Verdict";
import { ErrorMessage, LoadingMessage } from "@/components/Message";
import { PageHeader } from "@/components/PageHeader";
import { ProgressPanel } from "@/components/ProgressPanel";
import { Anomaly } from "@/lib/api";
import { asText } from "@/lib/format";
import { useApplicationReview } from "@/lib/queries";

export default function ApplicationReviewPage() {
  const params = useParams<{ id: string }>();
  const applicationId = Number(params.id);
  const review = useApplicationReview(Number.isFinite(applicationId) ? applicationId : null);
  const [activeTab, setActiveTab] = useState<ActiveTab>("checklist");
  const [selectedEvidence, setSelectedEvidence] = useState<EvidenceSelection | null>(null);

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
      found_value: `Page ${pageNumber}`,
    };
    handleSelectEvidence(mockAnomaly, pageNumber);
  };

  return (
    <>
      <PageHeader
        title={`Loan File Review - ${loanId}`}
        description={`Application ID: ${applicationId} | ${asText(review.data.application.product_type)} | ${asText(review.data.application.branch)}`}
      />
      <div className="space-y-6">
        <Verdict data={review.data} />
        <Overview data={review.data} />

        {["uploaded", "processing", "ocr_completed"].includes(String(review.data.application.status)) ||
        review.data.progress?.retryable ? (
          <ProgressPanel applicationId={applicationId} />
        ) : null}

        <div className="flex flex-wrap gap-1 border-b border-slate-200 mt-6 bg-slate-100/50 p-1 rounded-xl">
          <TabButton active={activeTab === "checklist"} onClick={() => setActiveTab("checklist")}>
            Checklist & Decisions
          </TabButton>
          <TabButton active={activeTab === "anomalies"} onClick={() => setActiveTab("anomalies")}>
            Anomalies & Flags ({reviewerCount})
          </TabButton>
          <TabButton active={activeTab === "logs"} onClick={() => setActiveTab("logs")}>
            Page Processing Logs
          </TabButton>
          <TabButton active={activeTab === "all_items"} onClick={() => setActiveTab("all_items")}>
            Full Verification List
          </TabButton>
          <TabButton active={activeTab === "downloads"} onClick={() => setActiveTab("downloads")}>
            Downloads
          </TabButton>
        </div>

        <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(580px,1.3fr)] items-start">
          <div className="bg-white border border-slate-200 rounded-2xl p-6 shadow-sm min-h-[300px]">
            {activeTab === "checklist" ? (
              <div className="space-y-6">
                <ReviewerSummary
                  data={review.data}
                  onSelectPage={(pageNo) => handleSelectPageOnly(pageNo, "Manual Review Page", "Requested check by reviewer")}
                />
                <ManualReviewAndDecision applicationId={applicationId} data={review.data} />
              </div>
            ) : null}

            {activeTab === "anomalies" ? (
              <div className="space-y-6">
                <ResultExplanation data={review.data} />
                <Anomalies data={review.data} onSelectEvidence={handleSelectEvidence} />
              </div>
            ) : null}

            {activeTab === "logs" ? (
              <PageProcessing
                data={review.data}
                onSelectPage={(pageNo, docType) => handleSelectPageOnly(pageNo, docType || "Processing Page", "Processing log validation review")}
              />
            ) : null}

            {activeTab === "all_items" ? (
              <Checklist
                data={review.data}
                onSelectPage={(row, pageNo, allPages) => {
                  const mockAnomaly: Anomaly = {
                    rule_id: row.s_no ? `CHECK_${row.s_no}` : "CHECKLIST_PREVIEW",
                    severity: "INFO",
                    reason: row.description || "Verification List Preview",
                    document_type: row.document_types || row.description || "Document Preview",
                    expected_value: "-",
                    found_value: allPages ? `Combined pages: ${allPages.join(", ")}` : `Page ${pageNo}`,
                  };
                  handleSelectEvidence(mockAnomaly, pageNo, allPages);
                }}
              />
            ) : null}

            {activeTab === "downloads" ? <Downloads applicationId={applicationId} /> : null}
          </div>
          <EvidenceViewer applicationId={applicationId} data={review.data} selection={selectedEvidence} />
        </div>
      </div>
    </>
  );
}
