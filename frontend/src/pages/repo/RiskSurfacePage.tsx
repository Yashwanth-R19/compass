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
import { useBenchmark, useRisk } from "../../api/hooks";
import type { BenchmarkResponse, RiskFileOut, RiskResponse } from "../../api/types";
import { Badge } from "../../components/ui/Badge";
import { Card } from "../../components/ui/Card";
import { ConfidenceMeter } from "../../components/ConfidenceMeter";
import { HonestyNote } from "../../components/HonestyNote";
import { InfoTooltip } from "../../components/ui/InfoTooltip";
import { MetricRow } from "../../components/MetricRow";
import { ScoreExplainer } from "../../components/ScoreExplainer";
import { SegmentedControl } from "../../components/ui/SegmentedControl";
import { StageGate } from "../../components/StageGate";
import { HONESTY, TOOLTIPS } from "../../content/explainability";
import { CORPUS_REPO_LIST_URL } from "../../content/methods";
import { confidenceLabel, formatPercent, formatScore } from "../../lib/format";
import { CONFIDENCE_COLOR, rechartsTheme } from "../../lib/chartTheme";
import type { RepoOutletContext } from "../RepoLayout";

export type RiskTab = "hotspots" | "benchmark";

function riskRowId(path: string): string {
  return `risk-row-${encodeURIComponent(path)}`;
}

/**
 * SCAFFOLDING -- mounted by `FindingsSurfacePage` at `findings?view=risk` /
 * `findings?view=benchmark` (rebuild spec section 4.4: Risk/Benchmark are
 * views inside Findings now, not their own surface). `initialTab` lets the
 * caller pick which of its own two tabs to open on, since the discriminator
 * arriving from the route is `?view=`, not this component's own `?tab=`.
 * Internally still merges the former Risk and Benchmark pages behind
 * `?tab=hotspots|benchmark` -- session 3 folds this fully into Findings.
 */
export function RiskSurfacePage({ initialTab = "hotspots" }: { initialTab?: RiskTab } = {}) {
  const { repo, share } = useOutletContext<RepoOutletContext>();
  const [searchParams, setSearchParams] = useSearchParams();
  const [tab, setTab] = useState<RiskTab>(
    searchParams.get("tab") === "benchmark" || searchParams.get("tab") === "hotspots"
      ? (searchParams.get("tab") as RiskTab)
      : initialTab,
  );

  useEffect(() => {
    const fromUrl = searchParams.get("tab");
    if (fromUrl === "benchmark" || fromUrl === "hotspots") setTab(fromUrl);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams.get("tab")]);

  function changeTab(next: string) {
    setTab(next as RiskTab);
    setSearchParams(
      (prev) => {
        const merged = new URLSearchParams(prev);
        merged.set("tab", next);
        return merged;
      },
      { replace: true },
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <SegmentedControl
        aria-label="Risk view"
        value={tab}
        onValueChange={changeTab}
        options={[
          { value: "hotspots", label: "Hotspots" },
          { value: "benchmark", label: "Benchmark" },
        ]}
      />
      {tab === "benchmark" ? (
        <BenchmarkTab repoId={repo.id} share={share} />
      ) : (
        <HotspotsTab repoId={repo.id} share={share} />
      )}
    </div>
  );
}

// --- Hotspots tab -------------------------------------------------------------

function HotspotsTab({ repoId, share }: { repoId: string; share?: string }) {
  const risk = useRisk(repoId, share);
  const [searchParams] = useSearchParams();
  const [expandedPath, setExpandedPath] = useState<string | null>(searchParams.get("file"));

  useEffect(() => {
    const target = searchParams.get("file");
    if (!target) return;
    setExpandedPath(target);
    document
      .getElementById(riskRowId(target))
      ?.scrollIntoView({ block: "center", behavior: "smooth" });
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
          <RiskScatter files={data.files} />

          <Card
            eyebrow="Ranked by risk_score, highest first"
            title="Files by risk"
            action={
              <span className="cp-label text-text-muted">
                {data.files.length} {data.files.length === 1 ? "file" : "files"}
              </span>
            }
          >
            <HonestyNote variant="confidence-caveat" text={HONESTY.riskConfidenceNotAFourthTerm} />
            <ul className="mt-3">
              {data.files.map((file) => (
                <RiskRow
                  key={file.file_path}
                  file={file}
                  repoId={repoId}
                  calibration={data.calibration}
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

/** The risk-vs-confidence scatter (Part B): plotting the two LOCKED-
 * independent axes against each other is what makes "a file can be
 * high-risk and low-confidence at once" immediately legible, rather than a
 * claim the reader has to take on faith from two separate numbers in a
 * table row. */
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
      eyebrow="Two independent axes — a point in the top-left is high-risk AND low-confidence, not a contradiction"
    >
      <div className="h-72">
        <ResponsiveContainer width="100%" height="100%">
          <ScatterChart margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
            <CartesianGrid {...rechartsTheme.grid} />
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
                fill: rechartsTheme.axis.tick.fill,
              }}
              tick={rechartsTheme.axis.tick}
              stroke={rechartsTheme.axis.stroke}
            />
            <YAxis
              type="number"
              dataKey="y"
              name="risk score"
              domain={[0, 1]}
              tickFormatter={(v: number) => formatScore(v, 1)}
              label={{
                value: "risk_score",
                angle: -90,
                position: "insideLeft",
                fontSize: 11,
                fill: rechartsTheme.axis.tick.fill,
              }}
              tick={rechartsTheme.axis.tick}
              stroke={rechartsTheme.axis.stroke}
            />
            <ZAxis range={[40, 40]} />
            <Tooltip
              cursor={{ strokeDasharray: "3 3" }}
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null;
                const p = payload[0].payload as (typeof points)[number];
                return (
                  <div className="border border-border bg-bg-elevated px-2 py-1.5 text-xs">
                    <p className="max-w-[220px] truncate font-mono text-text">{p.path}</p>
                    <p className="text-text-muted">
                      risk {formatScore(p.y, 2)} · confidence {formatPercent(p.x)} ({p.tier})
                    </p>
                  </div>
                );
              }}
            />
            <Scatter data={byTier.low} fill={CONFIDENCE_COLOR.low} />
            <Scatter data={byTier.medium} fill={CONFIDENCE_COLOR.medium} />
            <Scatter data={byTier.high} fill={CONFIDENCE_COLOR.high} />
          </ScatterChart>
        </ResponsiveContainer>
      </div>
    </Card>
  );
}

function RiskRow({
  file,
  repoId,
  calibration,
  expanded,
  onToggle,
}: {
  file: RiskFileOut;
  repoId: string;
  calibration: string;
  expanded: boolean;
  onToggle: () => void;
}) {
  const isLowConfidence = confidenceLabel(file.risk_confidence) === "low";

  return (
    <li
      id={riskRowId(file.file_path)}
      // Low confidence gets a LEFT-BORDER treatment, not a background fill
      // -- a full-row `bg-warning-bg` wash measured only 4.4:1 for
      // text-muted content on top of it (this session's own accessibility
      // sweep, real data), just under the 4.5:1 body-text bar. A border
      // keeps the row's background at the already-verified bg-elevated
      // pairing and matches the "border carries the signal, fill stays
      // neutral" convention HeuristicNote/PartialResultNotice already use.
      className={`border-b border-border pl-2 last:border-0 ${
        isLowConfidence ? "border-l-2 border-l-warning" : ""
      } ${expanded ? "bg-bg-inset" : ""}`}
    >
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={expanded}
        className="flex w-full flex-col gap-2 py-3 text-left"
      >
        <div className="flex flex-wrap items-center gap-3">
          <span className="cp-label shrink-0">#{file.hotspot_rank + 1}</span>
          <span
            className="max-w-[280px] truncate font-mono text-xs text-text-muted"
            title={file.file_path}
          >
            {file.file_path}
          </span>
          <div className="ml-auto flex shrink-0 items-center gap-4">
            <div className="flex items-center gap-2">
              <div className="h-1.5 w-16 overflow-hidden rounded-full bg-bg-inset">
                <div
                  className="h-full rounded-full bg-accent"
                  style={{ width: `${Math.round(file.risk_score * 100)}%` }}
                />
              </div>
              <span className="cp-stat text-xs text-text-muted">
                {formatScore(file.risk_score)}
              </span>
            </div>
            {/* A SEPARATE visual dimension from the bar above -- never
                opacity, never folded into the score's own color/width. */}
            <ConfidenceMeter confidence={file.risk_confidence} size="sm" />
          </div>
        </div>
      </button>

      {expanded ? (
        <div className="pb-3">
          <RiskEvidence file={file} repoId={repoId} calibration={calibration} />
        </div>
      ) : null}
    </li>
  );
}

function RiskEvidence({
  file,
  repoId,
  calibration,
}: {
  file: RiskFileOut;
  repoId: string;
  calibration: string;
}) {
  return (
    <div className="flex flex-col gap-3 border-l-2 border-border-strong bg-bg-inset p-3">
      <MetricRow
        items={[
          {
            label: "churn (recency-weighted)",
            value: formatScore(file.churn_weighted, 0),
            tooltip: "churnWeighted",
          },
          { label: "complexity", value: formatScore(file.complexity, 1), tooltip: "complexity" },
          { label: "commits", value: file.commit_count },
          {
            label: "max coupling",
            value: formatPercent(file.max_coupling_degree),
            tooltip: "couplingDegree",
          },
        ]}
      />

      {/* The formula's own real weights (from GET /meta/formulas) plus every
          signal Compass measures for this file but does NOT fold into
          risk_score -- real, per-file values, not a generic description. */}
      <ScoreExplainer
        formulaKey="risk"
        calibration={calibration}
        contributions={[]}
        alsoMeasured={[
          {
            label: "Churn (total, unweighted)",
            value: String(file.churn_total),
            tooltip: "churnTotal",
          },
          {
            label: "Instability score",
            value: file.instability_score != null ? formatScore(file.instability_score, 2) : "—",
            tooltip: "instability",
          },
          {
            label: "Revert cycle count",
            value: String(file.revert_cycle_count ?? "—"),
            tooltip: "revertCycleCount",
          },
          { label: "Expert count", value: String(file.expert_count), tooltip: "expert" },
          {
            label: "Orphaned knowledge",
            value: file.is_orphaned_knowledge ? "yes" : "no",
            tooltip: "orphanedKnowledge",
          },
        ]}
      />

      <Link
        to={`/repos/${repoId}/structure?view=impact&path=${encodeURIComponent(file.file_path)}`}
        className="w-fit text-xs font-medium text-accent hover:underline"
      >
        View blast radius →
      </Link>
    </div>
  );
}

// --- Benchmark tab --------------------------------------------------------------

function MetricBar({ metric }: { metric: BenchmarkResponse["metrics"][number] }) {
  const pct = Math.round(metric.percentile * 100);
  return (
    <div>
      <div className="mb-1 flex items-center justify-between gap-2 text-xs">
        <span className="flex items-center gap-1 text-text-muted">
          {metric.metric}
          <InfoTooltip
            label="What is a benchmark percentile?"
            text={TOOLTIPS.benchmarkPercentile}
          />
        </span>
        <span className="flex items-center gap-2 tabular-nums text-text-muted">
          {formatScore(metric.value, 2)} · p{pct}
          {metric.widened ? (
            <span title={TOOLTIPS.widenedComparison}>
              <Badge tone="med">widened</Badge>
            </span>
          ) : null}
          <span>
            n={metric.n_repos} repos / {metric.n_files} files
          </span>
        </span>
      </div>
      <div className="h-2 w-full rounded-full bg-bg-inset">
        <div className="h-2 rounded-full bg-accent" style={{ width: `${Math.max(2, pct)}%` }} />
      </div>
    </div>
  );
}

function BenchmarkTab({ repoId, share }: { repoId: string; share?: string }) {
  const benchmark = useBenchmark(repoId, share);

  return (
    <StageGate
      query={benchmark}
      loadingLabel="Comparing against the corpus…"
      emptyTitle="No corpus data yet"
      emptyMessage="No comparable repositories exist for this language/size combination yet."
      isEmpty={(data: BenchmarkResponse) => data.metrics.every((m) => m.n_repos === 0)}
    >
      {(data) => (
        <div className="flex flex-col gap-4">
          <Card
            title="Compared against the curated corpus"
            eyebrow={`${data.dominant_language} · ${data.size_bucket} repositories`}
          >
            <ScoreExplainer formulaKey="baseline" contributions={[]} />
            <HonestyNote
              variant="scope-limitation"
              text={HONESTY.benchmarkVsPortfolioDistinct}
              className="mb-3 mt-2"
            />
            <p className="mb-4 text-xs text-text-muted">{data.corpus_note}</p>
            <div className="flex flex-col gap-3">
              {data.metrics.map((m) => (
                <MetricBar key={m.metric} metric={m} />
              ))}
            </div>
            <a
              href={CORPUS_REPO_LIST_URL}
              target="_blank"
              rel="noreferrer"
              className="mt-4 inline-block text-xs text-accent hover:underline"
            >
              See the exact repository list this corpus comes from →
            </a>
            <Link to="/methods" className="ml-4 inline-block text-xs text-accent hover:underline">
              How calibration works →
            </Link>
          </Card>
        </div>
      )}
    </StageGate>
  );
}
