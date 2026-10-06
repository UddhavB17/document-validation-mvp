import { ProgressPanel } from "@/components/ProgressPanel";
import { PageProcessing } from "@/components/applications/PageProcessing";
import type { ApplicationReview } from "@/lib/api";

export function ProcessingTab({
  applicationId,
  data,
  onSelectPage,
}: {
  applicationId: number;
  data: ApplicationReview;
  onSelectPage?: (pageNo: number, docType?: string) => void;
}) {
  return (
    <section className="min-w-0 space-y-6">
      <ProgressPanel applicationId={applicationId} />
      <div className="min-w-0 border-t border-slate-100 pt-6">
        <PageProcessing data={data} onSelectPage={onSelectPage} />
      </div>
    </section>
  );
}
