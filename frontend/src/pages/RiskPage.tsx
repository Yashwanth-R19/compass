import { useMemo, useState } from "react";
import { useOutletContext } from "react-router-dom";
import { useRisk } from "../api/hooks";
import { Card } from "../components/Card";
import { LoadingState } from "../components/LoadingState";
import { ErrorState } from "../components/ErrorState";
import { EmptyState } from "../components/EmptyState";
import { confidenceLabel, formatPercent, formatScore } from "../lib/format";
import type { RiskFileOut } from "../api/types";
import type { RepoOutletContext } from "./RepoLayout";

type SortKey = "hotspot_rank" | "risk_score" | "risk_confidence" | "complexity" | "churn_total" | "commit_count" | "max_coupling_degree";

const COLUMNS: { key: SortKey; label: string }[] = [
  { key: "hotspot_rank", label: "Rank" },
  { key: "risk_score", label: "Risk score" },
  { key: "risk_confidence", label: "Confidence" },
  { key: "complexity", label: "Complexity" },
  { key: "churn_total", label: "Churn" },
  { key: "commit_count", label: "Commits" },
  { key: "max_coupling_degree", label: "Max coupling" },
];

export function RiskPage() {
  const { repo } = useOutletContext<RepoOutletContext>();
  const risk = useRisk(repo.id);
  const [sortKey, setSortKey] = useState<SortKey>("hotspot_rank");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");

  const sorted = useMemo(() => {
    if (!risk.data) return [];
    const rows = [...risk.data.files];
    rows.sort((a, b) => {
      const diff = a[sortKey] - b[sortKey];
      return sortDir === "asc" ? diff : -diff;
    });
    return rows;
  }, [risk.data, sortKey, sortDir]);

  function toggleSort(key: SortKey) {
    if (key === sortKey) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir(key === "hotspot_rank" ? "asc" : "desc");
    }
  }

  if (risk.isPending) return <LoadingState label="Loading risk data…" />;
  if (risk.isError) return <ErrorState error={risk.error} onRetry={() => void risk.refetch()} />;
  if (risk.data.files.length === 0) {
    return <EmptyState title="No scored files" message="This repo has no analyzed files yet." />;
  }

  return (
    <Card
      title="Files by risk"
      subtitle={`${risk.data.files.length} ${risk.data.files.length === 1 ? "file" : "files"} — heuristic score, not yet corpus-calibrated`}
    >
      <div className="overflow-x-auto">
        <table className="w-full min-w-[720px] text-left text-sm">
          <thead>
            <tr className="border-b border-slate-200 text-xs text-slate-500 dark:border-slate-800 dark:text-slate-400">
              <th className="py-2 pr-3 font-medium">File</th>
              {COLUMNS.map((col) => (
                <th key={col.key} className="py-2 pr-3 font-medium">
                  <button
                    type="button"
                    onClick={() => toggleSort(col.key)}
                    className="inline-flex items-center gap-1 hover:text-slate-800 dark:hover:text-slate-200"
                  >
                    {col.label}
                    {sortKey === col.key ? <span>{sortDir === "asc" ? "↑" : "↓"}</span> : null}
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sorted.map((file) => (
              <RiskRow key={file.file_path} file={file} />
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function RiskRow({ file }: { file: RiskFileOut }) {
  const isLowConfidence = confidenceLabel(file.risk_confidence) === "low";

  return (
    <tr
      className={`border-b border-slate-100 last:border-0 dark:border-slate-800 ${
        isLowConfidence ? "bg-amber-50/60 dark:bg-amber-500/5" : ""
      }`}
    >
      <td className="max-w-[280px] truncate py-2 pr-3 font-mono text-xs text-slate-700 dark:text-slate-300" title={file.file_path}>
        {file.file_path}
      </td>
      <td className="py-2 pr-3 text-slate-500 dark:text-slate-400">#{file.hotspot_rank + 1}</td>
      <td className="py-2 pr-3">
        <div className="flex items-center gap-2">
          <div className="h-1.5 w-16 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
            <div
              className="h-full rounded-full bg-indigo-500"
              style={{ width: `${Math.round(file.risk_score * 100)}%` }}
            />
          </div>
          <span className="tabular-nums text-slate-700 dark:text-slate-300">{formatScore(file.risk_score)}</span>
        </div>
      </td>
      <td className="py-2 pr-3">
        <span
          className={`tabular-nums ${isLowConfidence ? "font-medium text-amber-600 dark:text-amber-400" : "text-slate-500 dark:text-slate-400"}`}
        >
          {formatPercent(file.risk_confidence)}
          {isLowConfidence ? " ⚠" : ""}
        </span>
      </td>
      <td className="py-2 pr-3 tabular-nums text-slate-600 dark:text-slate-300">{formatScore(file.complexity, 1)}</td>
      <td className="py-2 pr-3 tabular-nums text-slate-600 dark:text-slate-300">{file.churn_total}</td>
      <td className="py-2 pr-3 tabular-nums text-slate-600 dark:text-slate-300">{file.commit_count}</td>
      <td className="py-2 pr-3 tabular-nums text-slate-600 dark:text-slate-300">
        {formatPercent(file.max_coupling_degree)}
      </td>
    </tr>
  );
}
