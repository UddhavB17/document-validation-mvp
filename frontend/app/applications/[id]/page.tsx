"use client";

import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { ApplicationMetricsHeader } from "@/components/applications/ApplicationMetricsHeader";
import { Checklist } from "@/components/applications/Checklist";
import { Downloads } from "@/components/applications/Downloads";
import { EvidenceViewerModal } from "@/components/applications/EvidenceViewerModal";
import { ExtractedDataTab } from "@/components/applications/ExtractedDataTab";
import { CaseNavigation } from "@/components/applications/case/CaseNavigation";
import { ProcessingTab } from "@/components/applications/case/ProcessingTab";
import { CaseReviewTab } from "@/components/applications/case/CaseReviewTab";
import { CaseErrorState, CaseLoadingSkeleton } from "@/components/applications/case/CaseStates";
import { getReviewErrorPresentation } from "@/components/applications/reviewUtils";
import type { Anomaly } from "@/lib/api";
import type { CaseTab, EvidenceSelection } from "@/components/applications/types";
import { useApplicationReview } from "@/lib/queries";
import { buildChecklistTaskId } from "@/lib/decisionPolicy";

// This route is the case workspace boundary. Legacy query values are mapped
// here so older worklist links continue to land on the closest new section.
const CASE_TABS: readonly CaseTab[] = ["review", "extracted", "checklist", "processing", "files"];
const LEGACY_TAB_MAP: Record<string, CaseTab> = {
  overview: "review",
  anomalies: "review",
  logs: "processing",
  downloads: "files",
  "extracted-data": "extracted",
  "processing-logs": "processing",
};

function getActiveTab(value: string | null): CaseTab {
  if (value && CASE_TABS.includes(value as CaseTab)) {
    return value as CaseTab;
  }
  return value ? LEGACY_TAB_MAP[value] ?? "review" : "review";
}

function caseTabHref(applicationId: number, tab: CaseTab): string {
  return tab === "review" ? `/applications/${applicationId}` : `/applications/${applicationId}?tab=${tab}`;
}

export default function ApplicationReviewPage() {
  const params = useParams<{ id: string }>();
  const applicationId = Number(params.id);
  const isValidApplicationId = Number.isInteger(applicationId) && applicationId > 0;
  const applicationReview = useApplicationReview(isValidApplicationId ? applicationId : null);
  const router = useRouter();
  const searchParams = useSearchParams();
  const activeTab = getActiveTab(searchParams.get("tab"));
  const [selectedEvidence, setSelectedEvidence] = useState<EvidenceSelection | null>(null);

  useEffect(() => {
    const requestedTab = searchParams.get("tab");
    if (!requestedTab || !isValidApplicationId) {
      return;
    }
    const canonicalTab = getActiveTab(requestedTab);
    if (requestedTab !== canonicalTab) {
      router.replace(caseTabHref(applicationId, canonicalTab));
    }
  }, [applicationId, isValidApplicationId, router, searchParams]);

  if (!isValidApplicationId) {
    return (
      <CaseErrorState
        title="Invalid application ID"
        message="This application link does not contain a valid numeric ID. Return to the Worklist and open a case from there."
      />
    );
  }

  if (applicationReview.isLoading) {
    return <CaseLoadingSkeleton />;
  }
  if (applicationReview.isError) {
    const errorPresentation = getReviewErrorPresentation(applicationReview.error, applicationId);
    return (
      <CaseErrorState
        title={errorPresentation.title}
        message={errorPresentation.message}
        onRetry={() => void applicationReview.refetch()}
      />
    );
  }
  if (!applicationReview.data) {
    return (
      <CaseErrorState
        title="Application review is unavailable"
        message="The review API returned no application data. Retry the request and check the local API health if it continues."
        onRetry={() => void applicationReview.refetch()}
      />
    );
  }

  const handleSelectEvidence = (anomaly: Anomaly, pageNumber: number | null, allPageNumbers?: number[], decisionTaskIds?: string[]) => {
    setSelectedEvidence({ anomaly, pageNumber, allPageNumbers, decisionTaskIds });
    setTimeout(() => {
      const viewer = document.getElementById("evidence-viewer");
      if (viewer) {
        viewer.scrollIntoView({ behavior: "smooth", block: "nearest" });
      }
    }, 100);
  };

  const handleSelectPageOnly = (pageNumber: number, title: string, reason: string, decisionTaskId?: string) => {
    const mockAnomaly: Anomaly = {
      rule_id: "PAGE_PREVIEW",
      severity: "INFO",
      document_type: title,
      reason: reason,
      expected_value: "-",
      found_value: `Page ${pageNumber}`
    };
    handleSelectEvidence(mockAnomaly, pageNumber, undefined, decisionTaskId ? [decisionTaskId] : undefined);
  };

  return (
    <div className="mx-auto w-full min-w-0 max-w-[1600px] space-y-4 overflow-x-hidden">
      <ApplicationMetricsHeader applicationId={applicationId} data={applicationReview.data} />

      <CaseNavigation applicationId={applicationId} activeTab={activeTab} />

      <main className="min-w-0 rounded-xl border border-[#E1E5EB] bg-white p-4 shadow-2xs sm:p-6">
        {activeTab === "review" && (
          <CaseReviewTab
            applicationId={applicationId}
            data={applicationReview.data}
            onSelectEvidence={handleSelectEvidence}
            onSelectPage={handleSelectPageOnly}
          />
        )}

        {activeTab === "extracted" && (
          <ExtractedDataTab data={applicationReview.data} onSelectPage={handleSelectPageOnly} />
        )}

        {activeTab === "checklist" ? (
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
              handleSelectEvidence(mockAnomaly, pageNo, allPages, row.status?.toLowerCase() === "not_checked"
                ? [buildChecklistTaskId(row.s_no, row.description)]
                : undefined);
            }}
          />
        ) : null}

        {activeTab === "processing" ? (
          <ProcessingTab
            applicationId={applicationId}
            data={applicationReview.data}
            onSelectPage={(pageNo, docType) => handleSelectPageOnly(pageNo, docType || "Processing Page", "Processing log validation review")}
          />
        ) : null}

        {activeTab === "files" ? (
          <Downloads applicationId={applicationId} />
        ) : null}
      </main>

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
