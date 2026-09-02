import { useEffect, useState } from "react";
import { Link, useOutletContext, useSearchParams } from "react-router-dom";
import {
  CartesianGrid,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";
import { useRisk } from "../../api/hooks";
import { ConfidenceMeter } from "../../components/ConfidenceMeter";
import { Card } from "../../components/Card";
import { HeuristicNote } from "../../components/HeuristicNote";
import { MetricRow } from "../../components/MetricRow";
import { StageGate } from "../../components/StageGate";
import { TEST_CLASSIFICATION_COPY } from "../../lib/copy";
import { confidenceLabel, formatPercent, formatScore } from "../../lib/format";
import type { RiskFileOut, RiskResponse, TestGapClassification } from "../../api/types";
import type { RepoOutletContext } from "../RepoLayout";

// Same three confidence-tier colors ConfidenceMeter uses, reused here so the
// scatter's dot colors and every row's meter agree on what "low/medium/high
// confidence" looks like.
const TIER_DOT_COLOR: Record<"low" | "medium" | "high", string> = {
  low: "#f59e0b", // amber-500
  medium: "#94a3b8", // slate-400
  high: "#10b981", // emerald-500
};

export function RiskPage() {
  const { repo, share } = useOutletContext<RepoOutletContext>();
  const risk = useRisk(repo.id, share);
  const [searchParams] = useSearchParams();
  const [expandedPath, setExpandedPath] = useState<string | null>(searchParams.get("file"));

  useEffect(() => {
    const target = searchParams.get("file");
    if (!target) return;
    setExpandedPath(target);
    const el = document.getElementById(riskRowId(target));
    el?.scrollIntoView({ block: "center", behavior: "smooth" });
    // Only react to the URL's own `file` param changing (a deep link
    // landing or being followed again) -- not every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams.get("file")]);

  return (
    <StageGate
      query={risk}
      loadingLabel="Loading risk data…"
      emptyTitle="No scored files"
      emptyMessage="This repo has no analyzed files yet."
      isEmpty={(data: RiskResponse) => data.files.length === 0}
    >
      {(data) => (
        <div className="flex flex-col gap-4">
          <HeuristicNote message="risk_score is a heuristic composite (0.60·churn×complexity + 0.25·max coupling + 0.15·commit count), not yet corpus-calibrated. risk_confidence is a SEPARATE measure of how much history backs the score -- never folded into it." />

          <RiskScatter files={data.files} />

          <Card
            title="Files by risk"
            subtitle={`${data.files.length} ${data.files.length === 1 ? "file" : "files"}, ranked by risk_score`}
          >
            <ul>
              {data.files.map((file) => (
                <RiskRow
                  key={file.file_path}
                  file={file}
                  repoId={repo.id}
                  expanded={expandedPath === file.file_path}
                  onToggle={() =>
                    setExpandedPath((current) =>
                      current === file.file_path ? null : file.file_path,
                    )
                  }
                />
              ))}
            </ul>
          </Card>
        </div>
      )}
    </StageGate>
  );
}

function riskRowId(path: string): string {
  return `risk-row-${encodeURIComponent(path)}`;
}

/** The risk-vs-confidence scatter (Part C): plotting the two LOCKED-independent
 * axes against each other is what makes "a file can be high-risk and
 * low-confidence at once" immediately legible, rather than a claim the user
 * has to take on faith from two separate numbers in a table row. */
function RiskScatter({ files }: { files: RiskFileOut[] }) {
  const points = files.map((f) => ({
    x: f.risk_confidence,
    y: f.risk_score,
    path: f.file_path,
    tier: confidenceLabel(f.risk_confidence),
  }));
  const byTier = {
    low: points.filter((p) => p.tier === "low"),
    medium: points.filter((p) => p.tier === "medium"),
    high: points.filter((p) => p.tier === "high"),
  };

  return (
    <Card
      title="Risk vs. confidence"
      subtitle="Two independent axes — a point in the top-left is high-risk AND low-confidence, not a contradiction"
    >
      <div className="h-72">
        <ResponsiveContainer width="100%" height="100%">
          <ScatterChart margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
            <CartesianGrid
              strokeDasharray="3 3"
              className="stroke-slate-200 dark:stroke-slate-800"
            />
            <XAxis
              type="number"
              dataKey="x"
              name="confidence"
              domain={[0, 1]}
              tickFormatter={(v: number) => formatPercent(v)}
              label={{
                value: "risk_confidence",
                position: "insideBottom",
                offset: -4,
                fontSize: 11,
              }}
              tick={{ fontSize: 11 }}
            />
            <YAxis
              type="number"
              dataKey="y"
              name="risk score"
              domain={[0, 1]}
              tickFormatter={(v: number) => formatScore(v, 1)}
              label={{ value: "risk_score", angle: -90, position: "insideLeft", fontSize: 11 }}
              tick={{ fontSize: 11 }}
            />
            <ZAxis range={[40, 40]} />
            <Tooltip
              cursor={{ strokeDasharray: "3 3" }}
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null;
                const p = payload[0].payload as (typeof points)[number];
                return (
                  <div className="rounded-md border border-slate-200 bg-white px-2 py-1.5 text-xs shadow-sm dark:border-slate-700 dark:bg-slate-900">
                    <p className="max-w-[220px] truncate font-mono text-slate-700 dark:text-slate-200">
                      {p.path}
                    </p>
                    <p className="text-slate-500 dark:text-slate-400">
                      risk {formatScore(p.y, 2)} · confidence {formatPercent(p.x)} ({p.tier})
                    </p>
                  </div>
                );
              }}
            />
            <Scatter data={byTier.low} fill={TIER_DOT_COLOR.low} />
            <Scatter data={byTier.medium} fill={TIER_DOT_COLOR.medium} />
            <Scatter data={byTier.high} fill={TIER_DOT_COLOR.high} />
          </ScatterChart>
        </ResponsiveContainer>
      </div>
    </Card>
  );
}

function RiskRow({
  file,
  repoId,
  expanded,
  onToggle,
}: {
  file: RiskFileOut;
  repoId: string;
  expanded: boolean;
  onToggle: () => void;
}) {
  const isLowConfidence = confidenceLabel(file.risk_confidence) === "low";

  return (
    <li
      id={riskRowId(file.file_path)}
      className={`border-b border-slate-100 last:border-0 dark:border-slate-800 ${
        isLowConfidence ? "bg-amber-50/50 dark:bg-amber-500/5" : ""
      } ${expanded ? "bg-slate-50 dark:bg-slate-900/40" : ""}`}
    >
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={expanded}
        className="flex w-full flex-col gap-2 py-3 text-left"
      >
        <div className="flex flex-wrap items-center gap-3">
          <span className="shrink-0 text-xs text-slate-400 dark:text-slate-500">
            #{file.hotspot_rank + 1}
          </span>
          <span
            className="max-w-[280px] truncate font-mono text-xs text-slate-700 dark:text-slate-300"
            title={file.file_path}
          >
            {file.file_path}
          </span>
          <div className="ml-auto flex shrink-0 items-center gap-4">
            <div className="flex items-center gap-2">
              <div className="h-1.5 w-16 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
                <div
                  className="h-full rounded-full bg-indigo-500"
                  style={{ width: `${Math.round(file.risk_score * 100)}%` }}
                />
              </div>
              <span className="tabular-nums text-xs text-slate-700 dark:text-slate-300">
                {formatScore(file.risk_score)}
              </span>
            </div>
            {/* A SEPARATE visual dimension from the bar above -- never
                opacity, never folded into the score's own color/width
                (Known Hazard #3 / RULES.md sec 3). */}
            <ConfidenceMeter confidence={file.risk_confidence} size="sm" />
          </div>
        </div>
      </button>

      {expanded ? (
        <div className="pb-3">
          <RiskEvidence file={file} repoId={repoId} />
        </div>
      ) : null}
    </li>
  );
}

function RiskEvidence({ file, repoId }: { file: RiskFileOut; repoId: string }) {
  const classification = file.test_classification as TestGapClassification | null;

  return (
    <div className="flex flex-col gap-3 rounded-lg bg-slate-50 p-3 dark:bg-slate-950/40">
      <MetricRow
        items={[
          { label: "churn (recency-weighted)", value: formatScore(file.churn_weighted, 0) },
          { label: "churn (total)", value: file.churn_total },
          { label: "complexity", value: formatScore(file.complexity, 1) },
          { label: "commits", value: file.commit_count },
          { label: "max coupling", value: formatPercent(file.max_coupling_degree) },
        ]}
      />
      <MetricRow
        items={[
          {
            label: "instability",
            value: file.instability_score != null ? formatScore(file.instability_score, 2) : "—",
          },
          { label: "revert cycles", value: file.revert_cycle_count ?? "—" },
          { label: "experts", value: file.expert_count },
          {
            label: "orphaned knowledge",
            value: file.is_orphaned_knowledge ? "yes" : "no",
          },
        ]}
      />
      <p className="text-xs text-slate-500 dark:text-slate-400">
        {classification && TEST_CLASSIFICATION_COPY[classification]
          ? TEST_CLASSIFICATION_COPY[classification]()
          : "Test maintenance not yet computed for this file."}
        {file.test_cochange_ratio != null
          ? ` (co-changes with its test ${formatPercent(file.test_cochange_ratio)} of the time)`
          : ""}
      </p>
      <Link
        to={`/repos/${repoId}/onboard/impact?path=${encodeURIComponent(file.file_path)}`}
        className="w-fit text-xs font-medium text-indigo-600 hover:underline dark:text-indigo-400"
      >
        View blast radius →
      </Link>
    </div>
  );
}
