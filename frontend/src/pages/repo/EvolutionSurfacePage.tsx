import { useEffect, useMemo, useState } from "react";
import { useOutletContext, useSearchParams } from "react-router-dom";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useCompare, useRuns, useTimeline } from "../../api/hooks";
import type {
  AnalysisRunOut,
  CompareFindingOut,
  CompareResponse,
  ContributorChangeOut,
  CouplingChangeOut,
  RiskMoverOut,
  SubsystemChangeOut,
  TimelineBounds,
  TimelineSnapshotOut,
} from "../../api/types";
import { Card } from "../../components/ui/Card";
import { EmptyState } from "../../components/EmptyState";
import { ErrorState } from "../../components/ErrorState";
import { HonestyNote } from "../../components/HonestyNote";
import { LoadingState } from "../../components/LoadingState";
import { SegmentedControl } from "../../components/ui/SegmentedControl";
import { SeverityChip } from "../../components/SeverityChip";
import { StageGate } from "../../components/StageGate";
import { HONESTY } from "../../content/explainability";
import { usePrefersReducedMotion } from "../../hooks/usePrefersReducedMotion";
import {
  CONTRIBUTOR_CHANGE_COPY,
  COUPLING_CHANGE_COPY,
  SUBSYSTEM_CHANGE_COPY,
} from "../../lib/copy";
import { DIRECTION_TEXT_CLASS, formatSignedDelta, headlineDirection } from "../../lib/compare";
import { colorForKey } from "../../lib/palette";
import { CHROME, SUBSYSTEM_PALETTE, rechartsTheme } from "../../lib/chartTheme";
import {
  contributorBandData,
  fixedDomain,
  hotspotBarDomain,
  snapshotDelta,
} from "../../lib/timeline";
import type { RepoOutletContext } from "../RepoLayout";

type EvolutionTab = "timeline" | "compare";

function isEvolutionTab(v: string | null): v is EvolutionTab {
  return v === "timeline" || v === "compare";
}

const NEUTRAL_LINE = CHROME.inkFaint;
const STEP_MS = 800;

/**
 * `/repos/:id/evolution` -- merges the former Evolution (time-travel
 * scrubber) and Compare (run-vs-run diff) pages. Rebuild spec section 4.5
 * names the discriminator `?view=timeline|compare`; this still reads its
 * own pre-existing `?tab=` too (whichever is present wins, `view` checked
 * first) so both the current redirect table (`evolution?view=compare`) and
 * any already-live `?tab=` link keep landing on the right tab.
 */
export function EvolutionSurfacePage() {
  const { repo, share } = useOutletContext<RepoOutletContext>();
  const [searchParams, setSearchParams] = useSearchParams();
  const urlTab = searchParams.get("view") ?? searchParams.get("tab");
  const [tab, setTab] = useState<EvolutionTab>(isEvolutionTab(urlTab) ? urlTab : "timeline");

  useEffect(() => {
    if (isEvolutionTab(urlTab)) setTab(urlTab);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [urlTab]);

  function changeTab(next: string) {
    setTab(next as EvolutionTab);
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
        aria-label="Evolution view"
        value={tab}
        onValueChange={changeTab}
        options={[
          { value: "timeline", label: "Timeline" },
          { value: "compare", label: "Compare" },
        ]}
      />
      {tab === "compare" ? (
        <CompareTab repoId={repo.id} share={share} />
      ) : (
        <TimelineTab repoId={repo.id} share={share} />
      )}
    </div>
  );
}

// =============================================================================
// Timeline tab (session 13's scrubber)
// =============================================================================

function TimelineTab({ repoId, share }: { repoId: string; share?: string }) {
  const timeline = useTimeline(repoId, share);

  return (
    <StageGate
      query={timeline}
      loadingLabel="Loading the evolution timeline…"
      emptyTitle="No history to show"
      emptyMessage="This repository has no commit history to build a timeline from yet."
      isEmpty={(data) => data.snapshots.length === 0}
    >
      {(data) => (
        <EvolutionView
          snapshots={data.snapshots}
          bounds={data.bounds}
          covers={data.covers}
          notCovered={data.not_covered}
        />
      )}
    </StageGate>
  );
}

function EvolutionView({
  snapshots,
  bounds,
  covers,
  notCovered,
}: {
  snapshots: TimelineSnapshotOut[];
  bounds: TimelineBounds;
  covers: string[];
  notCovered: string;
}) {
  const [position, setPosition] = useState(0);
  const [playing, setPlaying] = useState(false);
  const reducedMotion = usePrefersReducedMotion();

  useEffect(() => {
    if (!playing) return;
    const id = window.setInterval(() => {
      setPosition((p) => {
        if (p >= snapshots.length - 1) {
          setPlaying(false);
          return p;
        }
        return p + 1;
      });
    }, STEP_MS);
    return () => window.clearInterval(id);
  }, [playing, snapshots.length]);

  const current = snapshots[position];
  const previous = position > 0 ? snapshots[position - 1] : undefined;
  const delta = useMemo(() => snapshotDelta(previous, current), [previous, current]);

  return (
    <div className="flex flex-col gap-4 pb-4">
      {/* Rendered verbatim, unconditionally, above every chart -- never
          paraphrased into something that sounds more precise. */}
      <Card>
        <p className="cp-label text-warning">History-derived only</p>
        <p className="mt-1 text-sm text-text-muted">{notCovered}</p>
        <p className="mt-2 text-xs text-text-muted">
          Sampled at every point below: {covers.join(", ")}.
        </p>
      </Card>

      <MetricLines snapshots={snapshots} bounds={bounds} position={position} />

      <div className="grid gap-4 lg:grid-cols-2">
        <HotspotBars snapshot={current} bounds={bounds} animate={!reducedMotion} />
        <ContributorBand snapshots={snapshots} position={position} />
      </div>

      <WhatChangedPanel delta={delta} current={current} />

      <Scrubber
        snapshots={snapshots}
        position={position}
        onChange={(p) => {
          setPlaying(false);
          setPosition(p);
        }}
        playing={playing}
        onTogglePlay={() => setPlaying((p) => !p)}
      />
    </div>
  );
}

// --- 1. Metric lines ---------------------------------------------------------

const METRIC_LINES: {
  key: keyof TimelineSnapshotOut;
  label: string;
  color: string;
  boundsKey: keyof TimelineBounds;
}[] = [
  { key: "file_count", label: "Files", color: SUBSYSTEM_PALETTE[0], boundsKey: "file_count" },
  {
    key: "commits_to_date",
    label: "Commits",
    color: SUBSYSTEM_PALETTE[2],
    boundsKey: "commits_to_date",
  },
  {
    key: "active_contributors",
    label: "Active contributors",
    color: SUBSYSTEM_PALETTE[3],
    boundsKey: "active_contributors",
  },
  { key: "churn_to_date", label: "Churn", color: SUBSYSTEM_PALETTE[5], boundsKey: "churn_to_date" },
  {
    key: "coupling_pairs_count",
    label: "Coupling pairs",
    color: SUBSYSTEM_PALETTE[7],
    boundsKey: "coupling_pairs_count",
  },
];

function MetricLines({
  snapshots,
  bounds,
  position,
}: {
  snapshots: TimelineSnapshotOut[];
  bounds: TimelineBounds;
  position: number;
}) {
  return (
    <Card
      title="Metrics over time"
      eyebrow="Fixed scale -- each chart's axis never changes as you scrub"
    >
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-5">
        {METRIC_LINES.map((m) => (
          <div key={m.key} className="flex flex-col gap-1">
            <span className="cp-label">{m.label}</span>
            <div className="h-24">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={snapshots} margin={{ top: 4, right: 4, bottom: 0, left: 4 }}>
                  <XAxis dataKey="position" hide />
                  {/* THE fixed-scale contract: every axis domain comes from
                      the server-computed `bounds`, never from the currently
                      displayed snapshot -- lib/timeline.ts::fixedDomain. */}
                  <YAxis domain={fixedDomain(bounds[m.boundsKey])} hide />
                  <ReferenceLine x={position} stroke={NEUTRAL_LINE} strokeDasharray="3 3" />
                  <Line
                    type="monotone"
                    dataKey={m.key}
                    stroke={m.color}
                    strokeWidth={2}
                    dot={false}
                    isAnimationActive={false}
                  />
                  <Tooltip
                    {...rechartsTheme.tooltip}
                    labelFormatter={(p) => {
                      const index = typeof p === "number" ? p : Number(p);
                      const at = snapshots[index]?.at_date ?? snapshots[0].at_date;
                      return new Date(at).toLocaleDateString();
                    }}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
            <span className="cp-stat text-sm font-semibold text-text">
              {(snapshots[position][m.key] as number).toLocaleString()}
            </span>
          </div>
        ))}
      </div>
    </Card>
  );
}

// --- 2. Hotspot bars, fixed axis ---------------------------------------------

function HotspotBars({
  snapshot,
  bounds,
  animate,
}: {
  snapshot: TimelineSnapshotOut;
  bounds: TimelineBounds;
  animate: boolean;
}) {
  const rows = snapshot.churn_ranked_hotspots.slice(0, 10);
  const domain = hotspotBarDomain(bounds);

  return (
    <Card
      title="Churn-ranked hotspots"
      eyebrow="Top files by cumulative churn at this point -- NOT the full risk formula (complexity isn't sampled historically)"
    >
      {rows.length === 0 ? (
        <p className="py-6 text-center text-sm text-text-muted">
          No churn recorded yet at this point in history.
        </p>
      ) : (
        <div style={{ height: Math.max(200, rows.length * 28) }}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart
              data={rows}
              layout="vertical"
              margin={{ top: 4, right: 16, bottom: 4, left: 4 }}
            >
              <CartesianGrid {...rechartsTheme.grid} horizontal={false} />
              <XAxis
                type="number"
                domain={domain}
                tick={rechartsTheme.axis.tick}
                stroke={rechartsTheme.axis.stroke}
              />
              <YAxis
                type="category"
                dataKey="path"
                width={180}
                tick={rechartsTheme.axis.tick}
                stroke={rechartsTheme.axis.stroke}
                tickFormatter={(p: string) => (p.length > 28 ? `…${p.slice(-27)}` : p)}
              />
              <Tooltip {...rechartsTheme.tooltip} />
              <Bar
                dataKey="churn_to_date"
                fill={CHROME.inkMuted}
                isAnimationActive={animate}
                animationDuration={STEP_MS * 0.6}
              />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </Card>
  );
}

// --- 3. Contributor band ------------------------------------------------------

function ContributorBand({
  snapshots,
  position,
}: {
  snapshots: TimelineSnapshotOut[];
  position: number;
}) {
  const { rows, names } = useMemo(() => contributorBandData(snapshots), [snapshots]);

  return (
    <Card
      title="Contributor activity share"
      eyebrow="Commit share among active contributors, trailing 90-day window"
    >
      {names.length === 0 ? (
        <p className="py-6 text-center text-sm text-text-muted">
          No contributor activity recorded yet at this point in history.
        </p>
      ) : (
        <div className="h-56">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={rows} margin={{ top: 4, right: 16, bottom: 4, left: 4 }}>
              <CartesianGrid {...rechartsTheme.grid} />
              <XAxis
                dataKey="position"
                tick={rechartsTheme.axis.tick}
                stroke={rechartsTheme.axis.stroke}
              />
              <YAxis
                domain={[0, 1]}
                tick={rechartsTheme.axis.tick}
                stroke={rechartsTheme.axis.stroke}
                tickFormatter={(v: number) => `${Math.round(v * 100)}%`}
              />
              <ReferenceLine x={position} stroke={NEUTRAL_LINE} strokeDasharray="3 3" />
              <Tooltip
                {...rechartsTheme.tooltip}
                formatter={(v) => `${Math.round(Number(v) * 100)}%`}
              />
              {names.map((name) => (
                <Area
                  key={name}
                  type="monotone"
                  dataKey={name}
                  stackId="share"
                  stroke={name === "Other" ? NEUTRAL_LINE : colorForKey(`contributor:${name}`)}
                  fill={name === "Other" ? NEUTRAL_LINE : colorForKey(`contributor:${name}`)}
                  fillOpacity={0.7}
                  isAnimationActive={false}
                />
              ))}
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}
    </Card>
  );
}

// --- 4. What changed here -----------------------------------------------------

function WhatChangedPanel({
  delta,
  current,
}: {
  delta: ReturnType<typeof snapshotDelta>;
  current: TimelineSnapshotOut;
}) {
  return (
    <Card title="What changed here" eyebrow={new Date(current.at_date).toLocaleDateString()}>
      {delta === null ? (
        <p className="text-sm text-text-muted">
          This is the first sampled point -- nothing to compare against yet.
        </p>
      ) : (
        <div className="flex flex-col gap-3 text-sm">
          <div className="flex flex-wrap gap-x-6 gap-y-1 text-text-muted">
            <DeltaStat label="Files" delta={delta.filesDelta} />
            <DeltaStat label="Commits" delta={delta.commitsDelta} />
            <DeltaStat label="Churn" delta={delta.churnDelta} />
            <DeltaStat label="Active contributors" delta={delta.contributorsDelta} />
          </div>

          {delta.topChurnMovers.length > 0 ? (
            <div>
              <h3 className="cp-label mb-1 text-text-muted">Biggest churn movers</h3>
              <ul className="flex flex-col gap-0.5">
                {delta.topChurnMovers.map((m) => (
                  <li
                    key={m.path}
                    className="flex justify-between gap-2 font-mono text-xs text-text-muted"
                  >
                    <span className="truncate">{m.path}</span>
                    <span className="shrink-0 tabular-nums text-warning">
                      +{m.churnDelta.toLocaleString()}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {delta.contributorsAppeared.length > 0 || delta.contributorsLeft.length > 0 ? (
            <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs text-text-muted">
              {delta.contributorsAppeared.length > 0 ? (
                <span>First seen: {delta.contributorsAppeared.join(", ")}</span>
              ) : null}
              {delta.contributorsLeft.length > 0 ? (
                <span>No longer active: {delta.contributorsLeft.join(", ")}</span>
              ) : null}
            </div>
          ) : null}

          <p className="text-xs text-text-muted">
            Movers and joins/leaves are best-effort -- only computed among each snapshot's own
            top-ranked files and contributors, not the full repository.
          </p>
        </div>
      )}
    </Card>
  );
}

function DeltaStat({ label, delta }: { label: string; delta: number }) {
  const sign = delta > 0 ? "+" : "";
  const colorClass =
    delta > 0 ? "text-diverging-improve" : delta < 0 ? "text-diverging-worsen" : "text-text-muted";
  return (
    <span>
      {label}:{" "}
      <span className={`font-semibold tabular-nums ${colorClass}`}>
        {sign}
        {delta.toLocaleString()}
      </span>
    </span>
  );
}

// --- 5. The scrubber -----------------------------------------------------------

function Scrubber({
  snapshots,
  position,
  onChange,
  playing,
  onTogglePlay,
}: {
  snapshots: TimelineSnapshotOut[];
  position: number;
  onChange: (position: number) => void;
  playing: boolean;
  onTogglePlay: () => void;
}) {
  const current = snapshots[position];
  return (
    <Card>
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={onTogglePlay}
          aria-label={playing ? "Pause" : "Play"}
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent text-accent-contrast hover:bg-accent-strong"
        >
          {playing ? "❚❚" : "▶"}
        </button>
        <input
          type="range"
          min={0}
          max={snapshots.length - 1}
          step={1}
          value={position}
          onChange={(e) => onChange(Number(e.target.value))}
          className="w-full accent-accent"
          aria-label="Timeline position"
        />
        <span className="w-28 shrink-0 text-right text-xs tabular-nums text-text-muted">
          {new Date(current.at_date).toLocaleDateString()}
        </span>
      </div>
      <div className="mt-1 flex justify-between text-[11px] text-text-muted">
        <span>{new Date(snapshots[0].at_date).toLocaleDateString()}</span>
        <span>
          Snapshot {position + 1} of {snapshots.length}
        </span>
        <span>{new Date(snapshots[snapshots.length - 1].at_date).toLocaleDateString()}</span>
      </div>
    </Card>
  );
}

// =============================================================================
// Compare tab (session 13's run-vs-run diff)
// =============================================================================

function CompareTab({ repoId, share }: { repoId: string; share?: string }) {
  const runs = useRuns(repoId, share);

  // Exactly one run is ever "ready" at a time -- every earlier successful
  // run becomes "superseded" the moment a newer one succeeds (Facts/Insight
  // split). Filtering to "ready" alone would mean no repository could ever
  // offer two runs to pick from -- a real bug in a previous implementation.
  // "running"/"failed" runs are excluded: no usable Insight data to diff.
  const completedRuns = (runs.data?.runs ?? []).filter(
    (r) => r.status === "ready" || r.status === "superseded",
  );
  const [runIdBefore, setRunIdBefore] = useState<string | undefined>(undefined);
  const [runIdAfter, setRunIdAfter] = useState<string | undefined>(undefined);

  useEffect(() => {
    if (runIdBefore || runIdAfter || completedRuns.length < 2) return;
    // useRuns returns newest first -- [0] is current, [1] is previous.
    setRunIdAfter(completedRuns[0].id);
    setRunIdBefore(completedRuns[1].id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [completedRuns.length]);

  const compare = useCompare(runIdBefore, runIdAfter);

  if (runs.isPending) return <LoadingState label="Loading runs…" />;
  if (runs.isError) return <ErrorState error={runs.error} onRetry={() => void runs.refetch()} />;

  if (completedRuns.length < 2) {
    return (
      <EmptyState
        title="Nothing to compare yet"
        message="This repository needs at least two completed analysis runs before they can be compared."
      />
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <RunPicker
        runs={completedRuns}
        runIdBefore={runIdBefore}
        runIdAfter={runIdAfter}
        onChangeBefore={setRunIdBefore}
        onChangeAfter={setRunIdAfter}
      />

      {!runIdBefore || !runIdAfter || runIdBefore === runIdAfter ? (
        <EmptyState title="Pick two different runs" />
      ) : compare.isPending ? (
        <LoadingState label="Comparing runs…" />
      ) : compare.isError ? (
        <ErrorState error={compare.error} onRetry={() => void compare.refetch()} />
      ) : (
        <CompareView data={compare.data} />
      )}
    </div>
  );
}

function RunPicker({
  runs,
  runIdBefore,
  runIdAfter,
  onChangeBefore,
  onChangeAfter,
}: {
  runs: AnalysisRunOut[];
  runIdBefore: string | undefined;
  runIdAfter: string | undefined;
  onChangeBefore: (id: string) => void;
  onChangeAfter: (id: string) => void;
}) {
  const runLabel = (r: AnalysisRunOut) =>
    `${new Date(r.started_at).toLocaleDateString()} (${r.head_sha.slice(0, 7)})`;

  return (
    <Card title="Compare runs">
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <label className="flex items-center gap-2">
          <span className="text-text-muted">From</span>
          <select
            value={runIdBefore ?? ""}
            onChange={(e) => onChangeBefore(e.target.value)}
            className="rounded-sm border border-border-interactive bg-bg-elevated px-2 py-1 text-sm text-text"
          >
            {runs.map((r) => (
              <option key={r.id} value={r.id}>
                {runLabel(r)}
              </option>
            ))}
          </select>
        </label>
        <span className="text-text-muted">→</span>
        <label className="flex items-center gap-2">
          <span className="text-text-muted">To</span>
          <select
            value={runIdAfter ?? ""}
            onChange={(e) => onChangeAfter(e.target.value)}
            className="rounded-sm border border-border-interactive bg-bg-elevated px-2 py-1 text-sm text-text"
          >
            {runs.map((r) => (
              <option key={r.id} value={r.id}>
                {runLabel(r)}
              </option>
            ))}
          </select>
        </label>
      </div>
    </Card>
  );
}

function CompareView({ data }: { data: CompareResponse }) {
  return (
    <div className="flex flex-col gap-4">
      {data.engine_version_differs ? (
        <HonestyNote
          variant="scope-limitation"
          text={`${HONESTY.compareEngineVersionDiffers} (engine version ${data.engine_version_before} → ${data.engine_version_after})`}
        />
      ) : null}

      <HeadlineStrip data={data} />

      <div className="grid gap-4 lg:grid-cols-3">
        <FindingsColumn
          title="Appeared"
          findings={data.findings.appeared}
          total={data.findings.appeared_total}
          tone="worsened"
        />
        <FindingsColumn
          title="Resolved"
          findings={data.findings.resolved}
          total={data.findings.resolved_total}
          tone="improved"
        />
        <FindingsColumn
          title="Persisted"
          findings={data.findings.persisted}
          total={data.findings.persisted_total}
          tone="neutral"
        />
      </div>

      <RiskMoversTable worsened={data.risk_movers_worsened} improved={data.risk_movers_improved} />

      <div className="grid gap-4 lg:grid-cols-2">
        <SubsystemChanges changes={data.subsystem_changes} />
        <ContributorChanges changes={data.contributor_changes} />
      </div>

      <CouplingChanges changes={data.coupling_changes} />

      <SecurityDiff data={data} />
    </div>
  );
}

function HeadlineStrip({ data }: { data: CompareResponse }) {
  return (
    <Card title="Since last run">
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
        {data.headline.map((item) => {
          const direction = headlineDirection(item);
          return (
            <div key={item.metric} className="flex flex-col gap-0.5">
              <span className="text-xs text-text-muted">{item.label}</span>
              <span
                className={`text-lg font-semibold tabular-nums ${DIRECTION_TEXT_CLASS[direction]}`}
              >
                {item.delta === null ? "—" : formatSignedDelta(item.delta)}
              </span>
              <span className="text-[11px] text-text-muted">
                {item.before?.toLocaleString() ?? "—"} → {item.after?.toLocaleString() ?? "—"}
              </span>
            </div>
          );
        })}
      </div>
    </Card>
  );
}

function FindingsColumn({
  title,
  findings,
  total,
  tone,
}: {
  title: string;
  findings: CompareFindingOut[];
  total: number;
  tone: "improved" | "worsened" | "neutral";
}) {
  return (
    <Card title={`${title} (${total})`} className={tone === "worsened" ? "ring-1 ring-danger" : ""}>
      {findings.length === 0 ? (
        <p className="text-sm text-text-muted">None.</p>
      ) : (
        <ul className="flex flex-col divide-y divide-border">
          {findings.map((f) => (
            <li key={f.signature} className="flex flex-col gap-1 py-2">
              <div className="flex items-center gap-2">
                <SeverityChip severity={f.severity} />
                <span className="truncate text-sm text-text-muted">{f.title}</span>
              </div>
              {f.file_path ? (
                <span className="truncate font-mono text-xs text-text-muted">{f.file_path}</span>
              ) : null}
            </li>
          ))}
        </ul>
      )}
      {total > findings.length ? (
        <p className="mt-2 text-xs text-text-muted">
          Showing {findings.length} of {total}.
        </p>
      ) : null}
    </Card>
  );
}

function RiskMoversTable({
  worsened,
  improved,
}: {
  worsened: RiskMoverOut[];
  improved: RiskMoverOut[];
}) {
  const rows = [
    ...worsened.map((m) => ({ ...m, tone: "worsened" as const })),
    ...improved.map((m) => ({ ...m, tone: "improved" as const })),
  ];

  return (
    <Card title="Risk movers" eyebrow="Files whose hotspot rank moved the most in either direction">
      {rows.length === 0 ? (
        <p className="text-sm text-text-muted">No file's rank moved meaningfully.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="text-xs uppercase tracking-wide text-text-muted">
                <th className="pb-2 pr-4 font-medium">File</th>
                <th className="pb-2 pr-4 font-medium">Rank</th>
                <th className="pb-2 pr-4 font-medium">Risk score</th>
                <th className="pb-2 font-medium">Max coupling</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {rows.map((m) => (
                <tr key={m.file_path}>
                  <td className="max-w-[260px] truncate py-2 pr-4 font-mono text-xs text-text-muted">
                    {m.file_path}
                  </td>
                  <td className={`py-2 pr-4 tabular-nums ${DIRECTION_TEXT_CLASS[m.tone]}`}>
                    {m.hotspot_rank_before ?? "—"} → {m.hotspot_rank_after ?? "—"}
                  </td>
                  <td className="py-2 pr-4 tabular-nums text-text-muted">
                    {(m.risk_score_before ?? 0).toFixed(2)} → {(m.risk_score_after ?? 0).toFixed(2)}
                  </td>
                  <td className="py-2 tabular-nums text-text-muted">
                    {m.max_coupling_degree_before.toFixed(2)} →{" "}
                    {m.max_coupling_degree_after.toFixed(2)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

function SubsystemChanges({ changes }: { changes: SubsystemChangeOut[] }) {
  return (
    <Card title="Subsystem changes">
      <HonestyNote variant="scope-limitation" text={HONESTY.subsystemIdentityInferredByOverlap} />
      {changes.length === 0 ? (
        <p className="mt-2 text-sm text-text-muted">
          No subsystem appeared, disappeared, merged, or split.
        </p>
      ) : (
        <ul className="mt-2 flex flex-col divide-y divide-border">
          {changes.map((c, i) => (
            <li key={`${c.kind}-${c.label}-${i}`} className="py-2 text-sm">
              <span className="font-medium text-text-muted">
                {SUBSYSTEM_CHANGE_COPY[c.kind]()}:
              </span>{" "}
              <span className="text-text-muted">{c.label}</span>
              <p className="mt-0.5 text-xs text-text-muted">{c.detail}</p>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function ContributorChanges({ changes }: { changes: ContributorChangeOut[] }) {
  return (
    <Card title="Contributor changes">
      {changes.length === 0 ? (
        <p className="text-sm text-text-muted">No contributor joined, left, or went quiet.</p>
      ) : (
        <ul className="flex flex-col gap-1">
          {changes.map((c, i) => (
            <li key={`${c.kind}-${c.name}-${i}`} className="text-sm text-text-muted">
              <span className="font-medium text-text-muted">{c.name}</span>{" "}
              {CONTRIBUTOR_CHANGE_COPY[c.kind]().toLowerCase()}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function CouplingChanges({ changes }: { changes: CouplingChangeOut[] }) {
  return (
    <Card title="Coupling changes">
      {changes.length === 0 ? (
        <p className="text-sm text-text-muted">
          No coupling pair appeared, strengthened, weakened, or vanished.
        </p>
      ) : (
        <ul className="flex flex-col divide-y divide-border">
          {changes.map((c, i) => (
            <li
              key={`${c.kind}-${c.file_a_path}-${c.file_b_path}-${i}`}
              className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm"
            >
              <span className="font-mono text-xs text-text-muted">
                {c.file_a_path} ↔ {c.file_b_path}
              </span>
              <span className="text-xs text-text-muted">
                {COUPLING_CHANGE_COPY[c.kind]()}
                {c.coupling_degree_before !== null || c.coupling_degree_after !== null
                  ? ` (${c.coupling_degree_before?.toFixed(2) ?? "—"} → ${c.coupling_degree_after?.toFixed(2) ?? "—"})`
                  : ""}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function SecurityDiff({ data }: { data: CompareResponse }) {
  return (
    <Card title="Security">
      <div className="flex flex-wrap gap-x-8 gap-y-2 text-sm">
        <span>
          Vulnerabilities introduced:{" "}
          <span className="font-semibold text-diverging-worsen">
            {data.security.vulnerabilities_introduced}
          </span>
        </span>
        <span>
          Vulnerabilities remediated:{" "}
          <span className="font-semibold text-diverging-improve">
            {data.security.vulnerabilities_remediated}
          </span>
        </span>
        <span>
          Secrets introduced (approximate):{" "}
          <span className="font-semibold text-diverging-worsen">
            {data.security.secrets_introduced}
          </span>
        </span>
      </div>
      {/* There is deliberately no `secrets_remediated` field -- secrets are
          Facts, not per-run, so that number has no honest basis. */}
      <p className="mt-2 text-xs text-text-muted">{data.security.secrets_caveat}</p>
    </Card>
  );
}
