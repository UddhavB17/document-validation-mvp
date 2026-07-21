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
    <div className="overflow-x-auto rounded border border-slate-200 bg-white">
      <table className="min-w-full divide-y divide-slate-200 text-sm">
        <thead className="bg-slate-100 text-left text-xs font-semibold uppercase text-slate-600">
          <tr>
            {columns.map((column) => (
              <th key={column.key} className="whitespace-nowrap px-3 py-2">
                <button
                  type="button"
                  className="font-semibold"
                  onClick={() =>
                    setSort((current) =>
                      current?.key === column.key
                        ? { key: column.key, direction: current.direction === "asc" ? "desc" : "asc" }
                        : { key: column.key, direction: "asc" },
                    )
                  }
                >
                  {column.header}
                  {sort?.key === column.key ? ` ${sort.direction === "asc" ? "Asc" : "Desc"}` : ""}
                </button>
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {sortedRows.map((row, index) => (
            <tr key={index} className="align-top">
              {columns.map((column) => (
                <td key={column.key} className="px-3 py-2 text-slate-800">
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
