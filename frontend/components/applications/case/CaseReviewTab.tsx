import { Anomalies } from "@/components/applications/Anomalies";
import ComparisonTable from "@/components/applications/ComparisonTable";
import { OverviewTab } from "@/components/applications/OverviewTab";
import RelationshipGraph from "@/components/applications/RelationshipGraph";
import { Verdict } from "@/components/applications/Verdict";
import type { Anomaly, ApplicationReview } from "@/lib/api";

type CaseReviewTabProps = {
  applicationId: number;
  data: ApplicationReview;
  onSelectEvidence: (anomaly: Anomaly, pageNumber: number | null, allPageNumbers?: number[], decisionTaskIds?: string[]) => void;
  onSelectPage: (pageNumber: number, title: string, reason: string) => void;
};

export function CaseReviewTab({ applicationId, data, onSelectEvidence, onSelectPage }: CaseReviewTabProps) {
  return (
    <section className="min-w-0 space-y-6">
      <Verdict data={data} />
      <OverviewTab applicationId={applicationId} data={data} onSelectPage={onSelectPage} />

      <div className="min-w-0 max-w-full overflow-x-auto">
        <ComparisonTable
          coreParameters={data.comparison_matrix?.core_parameters}
          applicants={data.comparison_matrix?.applicants}
          onSelectPage={onSelectPage}
        />
      </div>

      <section className="min-w-0 space-y-3 border-t border-slate-100 pt-6">
        <div>
          <h2 className="font-serif text-[16px] font-semibold text-[#16202E]">Borrower relationship graph</h2>
          <p className="mt-1 text-xs font-medium text-[#5C6B7A]">Participants inferred from the application and supporting documents.</p>
        </div>
        <div className="min-w-0 max-w-full overflow-x-auto rounded-xl border border-[#E1E5EB] bg-[#F6F7FA]/30 p-2 shadow-2xs">
          <RelationshipGraph relationships={data.relationships} />
        </div>
      </section>

      <section className="min-w-0 space-y-3 border-t border-slate-100 pt-6">
        <div>
          <h2 className="font-serif text-[16px] font-semibold text-[#16202E]">Exceptions &amp; warnings</h2>
          <p className="mt-1 text-xs font-medium text-[#5C6B7A]">Review operational exceptions and open source evidence where available.</p>
        </div>
        <Anomalies applicationId={applicationId} data={data} onSelectEvidence={onSelectEvidence} />
      </section>
    </section>
  );
}
