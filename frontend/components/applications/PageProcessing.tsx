import { InfoMessage } from "@/components/Message";
import { Metric } from "@/components/Metric";
import { SortableTable } from "@/components/SortableTable";
import { StatusBadge } from "@/components/StatusBadge";
import { averagePageTime, formatLlmDocument, summarizeFields } from "@/components/applications/reviewUtils";
import { ApplicationReview } from "@/lib/api";
import { formatSeconds } from "@/lib/format";

export function PageProcessing({ data, onSelectPage }: { data: ApplicationReview; onSelectPage?: (pageNo: number, docType?: string) => void }) {
  const events = data.page_events;
  if (events.length === 0) {
    return <InfoMessage message="No page events logged." />;
  }
  const avgSeconds = averagePageTime(events);

  return (
    <section className="space-y-4">
      <h2 className="text-base font-bold text-slate-800">Page Processing Status</h2>
      <div className="grid grid-cols-2 gap-4">
        <Metric label="Pages Processed" value={events.length} />
        <Metric label="Avg. processing speed" value={`${avgSeconds.toFixed(1)}s / page`} />
      </div>
      <SortableTable
        rows={events}
        columns={[
          {
            key: "page",
            header: "Page",
            value: (row) => {
              const pageNo = row.page_number;
              if (typeof pageNo !== "number") return "-";
              return (
                <button
                  type="button"
                  className="font-mono text-xs bg-[#EAF0F8] text-[#2B4C7E] border-none rounded-md px-2.5 py-1 font-semibold hover:bg-[#2B4C7E] hover:text-white transition-all cursor-pointer"
                  onClick={() => onSelectPage?.(pageNo, row.document_type || undefined)}
                >
                  Page {pageNo}
                </button>
              );
            },
            sortValue: (row) => row.page_number
          },
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
