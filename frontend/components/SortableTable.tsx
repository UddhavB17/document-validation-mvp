"use client";

import { useMemo, useState } from "react";
import type { ReactNode } from "react";

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
  value: (row: T) => ReactNode;
  sortValue?: (row: T) => string | number | null | undefined;
};

export function SortableTable<T>({
  rows,
  columns,
  label = "Data table",
}: {
  rows: T[];
  columns: SortableColumn<T>[];
  label?: string;
}) {
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
    <div className="data-table-wrap">
      <table className="data-table" aria-label={label}>
        <caption className="sr-only">{label}</caption>
        <thead>
          <tr>
            {columns.map((column) => (
              <th
                key={column.key}
                scope="col"
                aria-sort={sortState?.key === column.key ? (sortState.direction === "asc" ? "ascending" : "descending") : "none"}
              >
                {column.sortValue ? (
                  <button
                    type="button"
                    className="data-table__sort-button"
                    aria-label={`${column.header}: ${getSortLabel(sortState, column.key)}`}
                    onClick={() =>
                      setSortState((currentSort) =>
                        currentSort?.key === column.key
                          ? { key: column.key, direction: currentSort.direction === "asc" ? "desc" : "asc" }
                          : { key: column.key, direction: "asc" },
                      )
                    }
                  >
                    <span>{column.header}</span>
                    <span className="data-table__sort-indicator" aria-hidden="true">
                      {sortState?.key === column.key ? (sortState.direction === "asc" ? "↑" : "↓") : "↕"}
                    </span>
                  </button>
                ) : (
                  column.header
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sortedRows.map((row, index) => (
            <tr key={index}>
              {columns.map((column) => <td key={column.key}>{column.value(row)}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function getSortLabel(sortState: SortState | null, key: string) {
  if (sortState?.key !== key) {
    return "sort ascending";
  }
  return sortState.direction === "asc" ? "sort descending" : "sort ascending";
}
