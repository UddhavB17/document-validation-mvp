"use client";

import { useMemo, useState } from "react";

// Generic table used across worklists and review panels. It owns sorting state
// while callers provide rendering and optional values for comparison.
type SortDirection = "asc" | "desc";

type SortState = {
  key: string;
  direction: SortDirection;
};

type SortableColumn<T> = {
  key: string;
  header: string;
  value: (row: T) => React.ReactNode;
  sortValue?: (row: T) => string | number | null | undefined;
};

export function SortableTable<T>({ rows, columns }: { rows: T[]; columns: SortableColumn<T>[] }) {
  const [sortState, setSortState] = useState<SortState | null>(null);
  const sortedRows = useMemo(() => {
    if (!sortState) {
      return rows;
    }
    const sortColumn = columns.find((item) => item.key === sortState.key);
    if (!sortColumn) {
      return rows;
    }
    return [...rows].sort((a, b) => {
      const left = sortColumn.sortValue?.(a);
      const right = sortColumn.sortValue?.(b);
      const result = String(left ?? "").localeCompare(String(right ?? ""), undefined, { numeric: true });
      return sortState.direction === "asc" ? result : -result;
    });
  }, [columns, rows, sortState]);

  return (
    <div className="overflow-auto rounded-xl border border-[#E1E5EB] bg-white shadow-3xs max-h-[600px]">
      <table className="min-w-full divide-y divide-[#E1E5EB] text-[13px] relative border-collapse">
        <thead className="sticky top-0 bg-[#F6F7FA] text-left text-[11px] font-bold uppercase tracking-wider text-[#5C6B7A] border-b border-[#E1E5EB] z-10">
          <tr>
            {columns.map((column) => (
              <th key={column.key} className="whitespace-nowrap px-6 py-3.5">
                <button
                  type="button"
                  className="font-bold hover:text-[#16202E] transition-colors duration-150 flex items-center gap-1.5 border-none bg-transparent cursor-pointer"
                  onClick={() =>
                    setSortState((currentSort) =>
                      currentSort?.key === column.key
                        ? { key: column.key, direction: currentSort.direction === "asc" ? "desc" : "asc" }
                        : { key: column.key, direction: "asc" },
                    )
                  }
                >
                  {column.header}
                  {sortState?.key === column.key ? (
                    <span className="text-[10px] text-[#2B4C7E] font-mono font-bold">
                      {sortState.direction === "asc" ? " ▲" : " ▼"}
                    </span>
                  ) : null}
                </button>
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-[#E1E5EB] text-[#16202E]">
          {sortedRows.map((row, index) => (
            <tr key={index} className="align-middle hover:bg-[#EAF0F8]/15 transition-colors duration-100">
              {columns.map((column) => (
                <td key={column.key} className="px-6 py-3.5 text-[#16202E] font-medium leading-relaxed">
                  {column.value(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
