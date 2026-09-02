import type { ReactNode } from "react";

/**
 * A dense data table -- sticky header, tabular numerals on every numeric
 * column, optional per-column client-side sort.
 *
 * IMPORTANT, session 11 (CLAUDE.md "Audit mode"): `FindingsRankEngine`
 * computes one global, cross-category rank server-side, and no page may
 * re-sort the findings stream (filtering by removing rows is fine;
 * reordering what's left is not). `pages/audit/FindingsPage.tsx` renders
 * its list through `FindingItem`, never through this `Table`, specifically
 * so this component's sort affordance can never be reached for that data —
 * but if a future page ever DOES render findings through `Table`, it must
 * pass `sortable={false}` and must not wire a column's `sortKey`. This
 * primitive being sortable is fine; the findings page using that
 * sortability would not be.
 */
export function Table<T>({
  columns,
  rows,
  rowKey,
  sort,
  onSortChange,
  emptyMessage = "No rows.",
}: {
  columns: {
    key: string;
    header: string;
    align?: "left" | "right";
    numeric?: boolean;
    sortable?: boolean;
    render: (row: T) => ReactNode;
  }[];
  rows: T[];
  rowKey: (row: T) => string | number;
  sort?: { key: string; direction: "asc" | "desc" };
  onSortChange?: (key: string) => void;
  emptyMessage?: string;
}) {
  return (
    <div className="max-h-[32rem] overflow-auto border border-border">
      <table className="w-full border-collapse text-left text-sm">
        <thead className="sticky top-0 z-10 bg-surface-2">
          <tr>
            {columns.map((col) => {
              const isSorted = sort?.key === col.key;
              return (
                <th
                  key={col.key}
                  scope="col"
                  className={`cp-label border-b border-border px-3 py-2 font-normal ${
                    col.align === "right" ? "text-right" : "text-left"
                  }`}
                >
                  {col.sortable && onSortChange ? (
                    <button
                      type="button"
                      onClick={() => onSortChange(col.key)}
                      className="inline-flex items-center gap-1 hover:text-ink"
                      aria-sort={
                        isSorted ? (sort.direction === "asc" ? "ascending" : "descending") : "none"
                      }
                    >
                      {col.header}
                      <span aria-hidden="true" className="text-[10px]">
                        {isSorted ? (sort.direction === "asc" ? "▲" : "▼") : ""}
                      </span>
                    </button>
                  ) : (
                    col.header
                  )}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td colSpan={columns.length} className="px-3 py-6 text-center text-sm text-ink-faint">
                {emptyMessage}
              </td>
            </tr>
          ) : (
            rows.map((row) => (
              <tr
                key={rowKey(row)}
                className="border-b border-border last:border-b-0 hover:bg-surface-2"
              >
                {columns.map((col) => (
                  <td
                    key={col.key}
                    className={`px-3 py-2 align-top ${col.align === "right" ? "text-right" : "text-left"} ${
                      col.numeric ? "cp-stat" : ""
                    }`}
                  >
                    {col.render(row)}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}
