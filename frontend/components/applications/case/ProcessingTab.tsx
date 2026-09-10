import { ProgressPanel } from "@/components/ProgressPanel";
import { PageProcessing } from "@/components/applications/PageProcessing";
import type { ApplicationReview } from "@/lib/api";

export function ProcessingTab({
  applicationId,
  data,
  onSelectPage,
}: {
  applicationId: number;
  data?: ApplicationReview;
  onSelectPage?: (pageNo: number, docType?: string) => void;
}) {
  return (
    <section className="min-w-0 space-y-6">
      <ProgressPanel applicationId={applicationId}>
        {(progress) => (
          <div className="min-w-0 border-t border-slate-100 pt-6">
            {!onSelectPage ? <p className="mb-3 text-sm text-slate-600">Page evidence previews become available when review details finish loading.</p> : null}
            <PageProcessing data={{ page_events: progress.completed_pages ?? data?.page_events ?? [] }} onSelectPage={onSelectPage} />
          </div>
        )}
      </ProgressPanel>
    </section>
  );
}
