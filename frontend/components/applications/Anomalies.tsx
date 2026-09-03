import { Anomaly, ApplicationReview } from "@/lib/api";

import { IssueQueue } from "@/components/applications/review/issueQueue";
import { ResultExplanation } from "@/components/applications/ResultExplanation";

export function Anomalies({
  applicationId,
  data,
  onSelectEvidence,
}: {
  applicationId: number;
  data: ApplicationReview;
  onSelectEvidence: (anomaly: Anomaly, pageNumber: number, allPageNumbers?: number[]) => void;
}) {
  return (
    <div className="space-y-6">
      <ResultExplanation data={data} />
      <IssueQueue
        applicationId={applicationId}
        data={data}
        onSelectEvidence={onSelectEvidence}
      />
    </div>
  );
}
