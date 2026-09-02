import Link from "next/link";

import { Metric } from "@/components/Metric";
import { InfoMessage } from "@/components/Message";
import { ProgressPanel } from "@/components/ProgressPanel";
import { UploadResponse } from "@/lib/api";

export function UploadResultSummary({ result }: { result: UploadResponse }) {
  return (
    <section className="mt-8 space-y-6 border-t border-[#E1E5EB] pt-6 animate-fade-in">
      <InfoMessage message={`Application ${result.application_id} accepted with status ${result.status.toUpperCase()}.`} />
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Metric label="Application ID" value={result.application_id} />
        <Metric label="Total Pages" value={result.total_pages ?? "—"} />
        <Metric label="Digital Pages" value={result.digital_pages ?? "—"} />
        <Metric label="Scanned Pages" value={result.scanned_pages ?? "—"} />
      </div>
      <ProgressPanel applicationId={result.application_id} />
      <Link
        className="inline-block rounded-lg bg-[#EAF0F8] border border-[#E1E5EB] px-5 py-2.5 text-sm font-bold text-[#2B4C7E] shadow-3xs hover:bg-[#2B4C7E] hover:text-white transition-colors duration-150"
        href={`/applications/${result.application_id}`}
      >
        Open Completed Review
      </Link>
    </section>
  );
}
