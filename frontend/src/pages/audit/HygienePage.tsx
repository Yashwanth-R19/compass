import { useEffect, useMemo, useState } from "react";
import { useOutletContext, useSearchParams } from "react-router-dom";
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
import { useHygiene, useRisk, useTestGaps } from "../../api/hooks";
import type {
  HygieneEventKind,
  HygieneEventOut,
  HygieneFileOut,
  TestGapFileOut,
} from "../../api/types";
import { Card } from "../../components/Card";
import { EvidenceLink } from "../../components/EvidenceLink";
import { StageGate } from "../../components/StageGate";
import { HYGIENE_KIND_COPY, HYGIENE_KIND_LABEL, TEST_CLASSIFICATION_COPY } from "../../lib/copy";
import { formatPercent, formatScore } from "../../lib/format";
import { CHROME, SEVERITY_COLOR, rechartsTheme } from "../../lib/chartTheme";
import type { RepoOutletContext } from "../RepoLayout";

const KIND_ORDER: HygieneEventKind[] = ["risky_commit", "fixup_churn", "oversized"];
// risky_commit is the most severe of the three (an actual finding-worthy
// signal), fixup_churn is a softer warning, oversized is purely
// informational -- the same three-tier vocabulary severity already uses,
// reused rather than inventing a fourth colour family for one chart.
const KIND_COLOR: Record<HygieneEventKind, string> = {
  oversized: CHROME.inkMuted,
  fixup_churn: SEVERITY_COLOR.med,
  risky_commit: SEVERITY_COLOR.high,
};

function fileRowId(path: string): string {
  return `hygiene-file-${encodeURIComponent(path)}`;
}

/** Part E: a commit timeline of hygiene EVENTS (not a fabricated commit-
 * volume curve -- no endpoint returns per-day commit counts anywhere in this
 * codebase, the same data gap PassportPage's cadence card already documents
 * honestly rather than inventing intermediate points), per-file instability,
 * and test maintenance (never "test coverage" -- Known Hazard #7). */
export function HygienePage() {
  const { repo, share } = useOutletContext<RepoOutletContext>();
  const hygiene = useHygiene(repo.id, share);
  const [searchParams] = useSearchParams();
  const [highlightPath, setHighlightPath] = useState<string | null>(searchParams.get("file"));

  useEffect(() => {
    const target = searchParams.get("file");
    if (!target) return;
    setHighlightPath(target);
    const el = document.getElementById(fileRowId(target));
    el?.scrollIntoView({ block: "center", behavior: "smooth" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams.get("file")]);

  return (
    <StageGate
      query={hygiene}
      loadingLabel="Loading commit hygiene…"
      emptyTitle="No hygiene signal yet"
      isEmpty={(data) => Object.values(data.events_by_kind).every((v) => !v || v.length === 0)}
    >
      {(data) => (
        <div className="flex flex-col gap-4">
          <EventTimeline eventsByKind={data.events_by_kind} repoUrl={repo.url} />

          {data.insufficient_history_for_oversized ? (
            <p className="rounded-md bg-slate-50 px-3 py-2 text-xs text-ink-muted dark:bg-slate-800/60">
              Too few commits to compute a reliable "oversized commit" percentile for this repo yet.
            </p>
          ) : null}

          <InstabilityRanking files={data.files} highlightPath={highlightPath} />

          <TestGapsSection repoId={repo.id} share={share} highlightPath={highlightPath} />
        </div>
      )}
    </StageGate>
  );
}

// --- 1. Event timeline ------------------------------------------------------

function EventTimeline({
  eventsByKind,
  repoUrl,
}: {
  eventsByKind: Partial<Record<HygieneEventKind, HygieneEventOut[]>>;
  repoUrl: string;
}) {
  const points = useMemo(() => {
    const all: { x: number; y: number; kind: HygieneEventKind; event: HygieneEventOut }[] = [];
    KIND_ORDER.forEach((kind, laneIndex) => {
      for (const event of eventsByKind[kind] ?? []) {
        const t = Date.parse(event.occurred_at);
        if (!Number.isNaN(t)) all.push({ x: t, y: laneIndex, kind, event });
      }
    });
    return all;
  }, [eventsByKind]);

  if (points.length === 0) {
    return (
      <Card title="Commit hygiene timeline">
        <p className="py-6 text-center text-sm text-ink-faint">
          No oversized commits, fixup clusters, or risky commits were detected.
        </p>
      </Card>
    );
  }

  return (
    <Card
      title="Commit hygiene timeline"
      subtitle="Oversized commits, fixup clusters, and risky commits, over time"
    >
      <div className="h-56">
        <ResponsiveContainer width="100%" height="100%">
          <ScatterChart margin={{ top: 8, right: 16, bottom: 8, left: 8 }}>
            <CartesianGrid {...rechartsTheme.grid} />
            <XAxis
              type="number"
              dataKey="x"
              domain={["dataMin", "dataMax"]}
              tickFormatter={(v: number) => new Date(v).toLocaleDateString()}
              tick={rechartsTheme.axis.tick}
              stroke={rechartsTheme.axis.stroke}
            />
            <YAxis
              type="number"
              dataKey="y"
              domain={[-0.5, KIND_ORDER.length - 0.5]}
              ticks={KIND_ORDER.map((_, i) => i)}
              tickFormatter={(v: number) => HYGIENE_KIND_LABEL[KIND_ORDER[v]]?.() ?? ""}
              width={110}
              tick={rechartsTheme.axis.tick}
              stroke={rechartsTheme.axis.stroke}
            />
            <ZAxis range={[50, 50]} />
            <Tooltip
              cursor={{ strokeDasharray: "3 3" }}
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null;
                const p = payload[0].payload as (typeof points)[number];
                return (
                  <div className="max-w-xs border border-border bg-surface px-2 py-1.5 text-xs">
                    <p className="font-medium text-ink">{HYGIENE_KIND_LABEL[p.kind]()}</p>
                    <p className="mt-0.5 text-ink-muted">
                      {HYGIENE_KIND_COPY[p.kind](p.event.detail)}
                    </p>
                  </div>
                );
              }}
            />
            {KIND_ORDER.map((kind) => (
              <Scatter
                key={kind}
                data={points.filter((p) => p.kind === kind)}
                fill={KIND_COLOR[kind]}
              />
            ))}
          </ScatterChart>
        </ResponsiveContainer>
      </div>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {points.slice(0, 6).map((p) => (
          <EvidenceLink
            key={`${p.event.commit_sha}-${p.kind}`}
            repoUrl={repoUrl}
            sha={p.event.commit_sha}
          />
        ))}
      </div>
    </Card>
  );
}

// --- 2. Per-file instability -------------------------------------------------

function InstabilityRanking({
  files,
  highlightPath,
}: {
  files: HygieneFileOut[];
  highlightPath: string | null;
}) {
  const ranked = useMemo(
    () =>
      [...files]
        .filter((f) => f.instability_score != null)
        .sort((a, b) => (b.instability_score ?? 0) - (a.instability_score ?? 0)),
    [files],
  );
  const [showAll, setShowAll] = useState(false);
  const visible = showAll ? ranked : ranked.slice(0, 15);

  if (ranked.length === 0) {
    return null;
  }

  return (
    <Card title="Per-file instability" subtitle={`${ranked.length} files with a computed score`}>
      <ul className="flex flex-col divide-y divide-slate-100 dark:divide-slate-800">
        {visible.map((f) => (
          <li
            key={f.file_path}
            id={fileRowId(f.file_path)}
            className={`flex flex-wrap items-center justify-between gap-2 py-2 text-sm ${
              highlightPath === f.file_path ? "bg-sky-50 dark:bg-sky-500/10" : ""
            }`}
          >
            <span
              className="max-w-[320px] truncate font-mono text-xs text-ink-muted"
              title={f.file_path}
            >
              {f.file_path}
            </span>
            <span className="flex shrink-0 items-center gap-3 text-xs text-ink-muted">
              <span className="flex items-center gap-1.5">
                <div className="h-1.5 w-16 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
                  <div
                    className="h-full rounded-full bg-amber-500"
                    style={{ width: `${Math.round((f.instability_score ?? 0) * 100)}%` }}
                  />
                </div>
                {formatScore(f.instability_score ?? 0, 2)}
              </span>
              <span>{f.oversized_commit_count ?? 0} oversized</span>
              <span>{f.fixup_commit_count ?? 0} fixup</span>
              <span>{f.revert_cycle_count ?? 0} reverts</span>
            </span>
          </li>
        ))}
      </ul>
      {ranked.length > 15 ? (
        <button
          type="button"
          onClick={() => setShowAll((v) => !v)}
          className="mt-2 w-fit rounded-md border border-slate-200 px-3 py-1.5 text-xs font-medium text-ink-muted hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800"
        >
          {showAll ? "Show top 15 only" : `Show all ${ranked.length} files`}
        </button>
      ) : null}
    </Card>
  );
}

// --- 3. Test gaps -------------------------------------------------------------

function TestGapsSection({
  repoId,
  share,
  highlightPath,
}: {
  repoId: string;
  share?: string;
  highlightPath: string | null;
}) {
  const testGaps = useTestGaps(repoId, share);
  const risk = useRisk(repoId, share);

  const riskByPath = useMemo(() => {
    const map = new Map<string, number>();
    if (risk.data?.kind === "data") {
      for (const f of risk.data.data.files) map.set(f.file_path, f.risk_score);
    }
    return map;
  }, [risk.data]);

  return (
    <StageGate
      query={testGaps}
      loadingLabel="Loading test maintenance data…"
      emptyTitle="No test-mapped files"
      isEmpty={(data) => data.files.length === 0}
    >
      {(data) => {
        const counts: Record<TestGapFileOut["classification"], number> = {
          no_test: 0,
          stale_test: 0,
          tracked: 0,
        };
        for (const f of data.files) counts[f.classification]++;
        const total = data.files.length || 1;

        const topGapsWithRisk = data.files
          .filter((f) => f.classification !== "tracked" && riskByPath.has(f.file_path))
          .map((f) => ({ ...f, risk_score: riskByPath.get(f.file_path)! }))
          .sort((a, b) => b.risk_score - a.risk_score)
          .slice(0, 10);

        return (
          <Card
            title="Test maintenance"
            subtitle="Whether tests change alongside the code they cover"
          >
            {/* Take the API's limitation string verbatim -- Known Hazard #7:
                "untested code" is shorter and reads better, and it is wrong. */}
            <p className="mb-3 rounded-md bg-slate-50 px-3 py-2 text-xs text-ink-muted dark:bg-slate-800/60">
              {data.limitation}
            </p>

            <div className="mb-4 flex h-3 w-full overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
              <div
                className="h-full bg-red-400"
                style={{ width: `${(counts.no_test / total) * 100}%` }}
                title={`${TEST_CLASSIFICATION_COPY.no_test()} (${counts.no_test})`}
              />
              <div
                className="h-full bg-amber-400"
                style={{ width: `${(counts.stale_test / total) * 100}%` }}
                title={`${TEST_CLASSIFICATION_COPY.stale_test()} (${counts.stale_test})`}
              />
              <div
                className="h-full bg-emerald-400"
                style={{ width: `${(counts.tracked / total) * 100}%` }}
                title={`${TEST_CLASSIFICATION_COPY.tracked()} (${counts.tracked})`}
              />
            </div>
            <div className="mb-4 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-muted">
              <span>No mapped test: {counts.no_test}</span>
              <span>Rarely changes with code: {counts.stale_test}</span>
              <span>Changes with code: {counts.tracked}</span>
              <span className="text-ink-faint">
                · mean co-change ratio {formatPercent(data.mean_test_cochange_ratio)}
              </span>
            </div>

            <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-ink-faint">
              Top-risk files with a maintenance gap
            </h3>
            {topGapsWithRisk.length === 0 ? (
              <p className="text-sm text-ink-faint">
                No top-risk file currently has a test-maintenance gap.
              </p>
            ) : (
              <ul className="flex flex-col divide-y divide-slate-100 dark:divide-slate-800">
                {topGapsWithRisk.map((f) => (
                  <li
                    key={f.file_path}
                    id={fileRowId(f.file_path)}
                    className={`flex flex-wrap items-center justify-between gap-2 py-2 text-sm ${
                      highlightPath === f.file_path ? "bg-sky-50 dark:bg-sky-500/10" : ""
                    }`}
                  >
                    <span
                      className="max-w-[280px] truncate font-mono text-xs text-ink-muted"
                      title={f.file_path}
                    >
                      {f.file_path}
                    </span>
                    <span className="shrink-0 text-xs text-ink-muted">
                      {TEST_CLASSIFICATION_COPY[f.classification]()} · risk{" "}
                      {formatScore(f.risk_score, 2)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        );
      }}
    </StageGate>
  );
}
