"use client";

import { useParams, useSearchParams } from "next/navigation";
import { useState } from "react";
import Link from "next/link";

import { ErrorMessage, LoadingMessage } from "@/components/Message";
import { Anomalies } from "@/components/applications/Anomalies";
import { ApplicationMetricsHeader } from "@/components/applications/ApplicationMetricsHeader";
import { Checklist } from "@/components/applications/Checklist";
import ComparisonTable from "@/components/applications/ComparisonTable";
import { Downloads } from "@/components/applications/Downloads";
import { EvidenceViewerModal } from "@/components/applications/EvidenceViewerModal";
import { ExtractedDataTab } from "@/components/applications/ExtractedDataTab";
import { getApplicantList, OverviewTab } from "@/components/applications/OverviewTab";
import { PageProcessing } from "@/components/applications/PageProcessing";
import RelationshipGraph from "@/components/applications/RelationshipGraph";
import { ActiveTab, EvidenceSelection } from "@/components/applications/types";
import { Verdict } from "@/components/applications/Verdict";
import { Anomaly } from "@/lib/api";
import { useApplicationReview } from "@/lib/queries";

// This route coordinates the application review tabs and the shared evidence
// viewer; the tab content itself lives in components/applications.
const APPLICATION_TABS: readonly ActiveTab[] = ["overview", "extracted", "anomalies", "checklist", "logs", "downloads"];

function getActiveTab(value: string | null): ActiveTab {
  return APPLICATION_TABS.find((tab) => tab === value) ?? "overview";
}

export default function ApplicationReviewPage() {
  const params = useParams<{ id: string }>();
  const applicationId = Number(params.id);
  const applicationReview = useApplicationReview(Number.isFinite(applicationId) ? applicationId : null);
  const searchParams = useSearchParams();
  const activeTab = getActiveTab(searchParams.get("tab"));
  const [selectedEvidence, setSelectedEvidence] = useState<EvidenceSelection | null>(null);

  if (!Number.isFinite(applicationId)) {
    return <ErrorMessage message="Invalid application ID." />;
  }

  if (applicationReview.isLoading) {
    return <LoadingMessage />;
  }
  if (applicationReview.isError) {
    return <ErrorMessage message="Unable to load application review." />;
  }
  if (!applicationReview.data) {
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

  const applicants = getApplicantList(applicationReview.data);

  return (
    <div className="space-y-6 max-w-[1600px] mx-auto">
      <div className="crumb text-xs text-[#5C6B7A] flex items-center gap-2 mb-1.5 font-semibold font-medium">
        <Link href="/worklist" className="hover:text-[#2B4C7E] transition-colors">← Applications</Link>
      </div>

      <ApplicationMetricsHeader applicationId={applicationId} data={applicationReview.data} />

      <Verdict data={applicationReview.data} />

      <div className="bg-white border border-[#E1E5EB] rounded-2xl p-6 shadow-2xs space-y-6 min-h-[500px]">
        {activeTab === "overview" && (
          <OverviewTab
            applicationId={applicationId}
            data={applicationReview.data}
            onSelectPage={handleSelectPageOnly}
          />
        )}

        {activeTab === "extracted" && (
          <ExtractedDataTab data={applicationReview.data} />
        )}

        {activeTab === "anomalies" && (
          <div className="space-y-6">
            <ComparisonTable
              coreParameters={applicationReview.data.comparison_matrix?.core_parameters}
              applicants={applicants}
              onSelectPage={handleSelectPageOnly}
            />

            <h2 className="font-serif text-[16px] font-semibold mb-3">Borrower relationship graph</h2>
            <div className="border border-[#E1E5EB] rounded-xl p-2 shadow-2xs overflow-x-auto bg-[#F6F7FA]/30">
              <RelationshipGraph relationships={applicationReview.data.relationships} />
            </div>

            <h2 className="font-serif text-[16px] font-semibold mb-3 pt-4 border-t border-slate-100">Exceptions &amp; Warnings Details</h2>
            <Anomalies
              applicationId={applicationId}
              data={applicationReview.data}
              onSelectEvidence={handleSelectEvidence}
            />
          </div>
        )}

        {activeTab === "checklist" && (
          <Checklist
            data={applicationReview.data}
            onSelectPage={(row, pageNo, allPages) => {
              const mockAnomaly: Anomaly = {
                rule_id: row.s_no ? `CHECK_${row.s_no}` : "CHECKLIST_PREVIEW",
                severity: "INFO",
                reason: row.description || "Verification List Preview",
                document_type: row.document_types || row.description || "Document Preview",
                expected_value: "-",
                found_value: allPages ? `Combined pages: ${allPages.join(", ")}` : `Page ${pageNo}`
              };
              handleSelectEvidence(mockAnomaly, pageNo, allPages);
            }}
          />
        )}

        {activeTab === "logs" && (
          <PageProcessing
            data={applicationReview.data}
            onSelectPage={(pageNo, docType) => handleSelectPageOnly(pageNo, docType || "Processing Page", "Processing log validation review")}
          />
        )}

        {activeTab === "downloads" && (
          <Downloads applicationId={applicationId} />
        )}
      </div>

      {selectedEvidence && (
        <EvidenceViewerModal
          applicationId={applicationId}
          data={applicationReview.data}
          selectedEvidence={selectedEvidence}
          onClose={() => setSelectedEvidence(null)}
        />
      )}
    </div>
  );
}
