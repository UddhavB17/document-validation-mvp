import { InfoMessage } from "@/components/Message";
import { SortableTable } from "@/components/SortableTable";
import { StatusBadge } from "@/components/StatusBadge";
import { ApplicationReview } from "@/lib/api";
import { formatSeconds } from "@/lib/format";

import { formatLlmDocument, summarizeFields } from "./reviewUtils";

export function PageProcessing({
  data,
  onSelectPage,
}: {
  data: ApplicationReview;
  onSelectPage?: (pageNo: number, docType?: string) => void;
}) {
  if (data.page_events.length === 0) {
    return <InfoMessage message="No page events logged." />;
  }
  return (
    <section className="space-y-3">
      <h2 className="text-base font-bold text-slate-800">Page Processing Output</h2>
      <SortableTable
        rows={data.page_events}
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
                  onClick={() => onSelectPage?.(pageNo, row.document_type || undefined)}
                  className="rounded border border-blue-200 bg-blue-50 px-2 py-0.5 text-xs font-bold text-blue-750 hover:bg-blue-100 transition-colors"
                >
                  Page {pageNo}
                </button>
              );
            },
            sortValue: (row) => row.page_number,
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
