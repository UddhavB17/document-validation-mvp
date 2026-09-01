import { Metric } from "@/components/Metric";
import { SortableTable } from "@/components/SortableTable";
import { StatusBadge } from "@/components/StatusBadge";
import { ApplicationReview } from "@/lib/api";

export function Checklist({
  data,
  onSelectPage,
}: {
  data: ApplicationReview;
  onSelectPage?: (row: ApplicationReview["checklist"]["rows"][number], pageNo: number, allPages?: number[]) => void;
}) {
  return (
    <section className="space-y-4">
      <h2 className="text-base font-bold text-slate-800">MSFC Checklist ({data.checklist.total} items)</h2>
      <div className="grid grid-cols-3 gap-4">
        <Metric label="Found Items" value={data.checklist.found} />
        <Metric label="Missing Items" value={data.checklist.missing} />
        <Metric label="Exempt Items" value={data.checklist.not_checked} />
      </div>
      <SortableTable
        rows={data.checklist.rows}
        columns={[
          { key: "sno", header: "S.No", value: (row) => row.s_no ?? "-", sortValue: (row) => row.s_no },
          { key: "status", header: "Status", value: (row) => <StatusBadge status={row.status} />, sortValue: (row) => row.status },
          { key: "description", header: "Description", value: (row) => row.description, sortValue: (row) => row.description },
          { key: "looked", header: "Looked for", value: (row) => row.document_types, sortValue: (row) => row.document_types },
          {
            key: "pages",
            header: "Pages",
            value: (row) => {
              const pageStr = String(row.pages ?? "").trim();
              if (!pageStr) return "-";
              const pageNumbers = pageStr
                .split(/,\s*/)
                .map(Number)
                .filter((n) => !isNaN(n) && n > 0);
              if (pageNumbers.length === 0) return pageStr;
              return (
                <div className="flex flex-wrap gap-1">
                  {pageNumbers.map((pageNumber) => (
                    <button
                      key={pageNumber}
                      type="button"
                      onClick={() => onSelectPage?.(row, pageNumber)}
                      className="rounded border border-blue-200 bg-blue-50 px-2 py-0.5 text-xs font-bold text-blue-750 hover:bg-blue-100 transition-colors"
                    >
                      Page {pageNumber}
                    </button>
                  ))}
                </div>
              );
            },
            sortValue: (row) => row.pages,
          },
        ]}
      />
    </section>
  );
}
