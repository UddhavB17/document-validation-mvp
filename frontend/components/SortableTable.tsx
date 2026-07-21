"use client";

import { useMemo, useState } from "react";

type Column<T> = {
  key: string;
  header: string;
  value: (row: T) => React.ReactNode;
  sortValue?: (row: T) => string | number | null | undefined;
};

export function SortableTable<T>({ rows, columns }: { rows: T[]; columns: Column<T>[] }) {
  const [sort, setSort] = useState<{ key: string; direction: "asc" | "desc" } | null>(null);
  const sortedRows = useMemo(() => {
    if (!sort) {
      return rows;
    }
    const column = columns.find((item) => item.key === sort.key);
    if (!column) {
      return rows;
    }
    return [...rows].sort((a, b) => {
      const left = column.sortValue?.(a);
      const right = column.sortValue?.(b);
      const result = String(left ?? "").localeCompare(String(right ?? ""), undefined, { numeric: true });
      return sort.direction === "asc" ? result : -result;
    });
  }, [columns, rows, sort]);

  return (
    <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white shadow-sm">
      <table className="min-w-full divide-y divide-slate-200 text-sm">
        <thead className="bg-slate-50 text-left text-xs font-bold uppercase tracking-wider text-slate-500 border-b border-slate-200">
          <tr>
            {columns.map((column) => (
              <th key={column.key} className="whitespace-nowrap px-4 py-3">
                <button
                  type="button"
                  className="font-bold hover:text-slate-800 transition-colors duration-150 flex items-center gap-1"
                  onClick={() =>
                    setSort((current) =>
                      current?.key === column.key
                        ? { key: column.key, direction: current.direction === "asc" ? "desc" : "asc" }
                        : { key: column.key, direction: "asc" },
                    )
                  }
                >
                  {column.header}
                  {sort?.key === column.key ? (
                    <span className="text-[10px] text-blue-600 font-mono">
                      {sort.direction === "asc" ? " ▲" : " ▼"}
                    </span>
                  ) : null}
                </button>
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {sortedRows.map((row, index) => (
            <tr key={index} className="align-top hover:bg-slate-50/50 transition-colors duration-100">
              {columns.map((column) => (
                <td key={column.key} className="px-4 py-3.5 text-slate-700 font-medium">
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
