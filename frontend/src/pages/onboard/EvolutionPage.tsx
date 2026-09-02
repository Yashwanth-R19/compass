import { useEffect, useMemo, useState } from "react";
import { useOutletContext } from "react-router-dom";
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
import { useTimeline } from "../../api/hooks";
import type { TimelineBounds, TimelineSnapshotOut } from "../../api/types";
import { Card } from "../../components/Card";
import { StageGate } from "../../components/StageGate";
import { usePrefersReducedMotion } from "../../hooks/usePrefersReducedMotion";
import { colorForSubsystem } from "../../lib/subsystemColors";
import { CHROME, SUBSYSTEM_PALETTE, rechartsTheme } from "../../lib/chartTheme";
import {
  contributorBandData,
  fixedDomain,
  hotspotBarDomain,
  snapshotDelta,
} from "../../lib/timeline";
import type { RepoOutletContext } from "../RepoLayout";

const NEUTRAL_LINE = CHROME.inkFaint;

const STEP_MS = 800;

/** Session 13, Part F: scrub through a repository's history on a FIXED
 * scale, so motion is meaningful rather than a rescaling artifact. Every
 * chart's axis domain in this file comes from `data.bounds` (the API's
 * server-computed min/max across every snapshot), never from the currently
 * displayed snapshot's own values -- see lib/timeline.ts's fixedDomain/
 * hotspotBarDomain for the one place that contract is enforced. */
export function EvolutionPage() {
  const { repo, share } = useOutletContext<RepoOutletContext>();
  const timeline = useTimeline(repo.id, share);

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
      <NotCoveredNote covers={covers} notCovered={notCovered} />

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

// --- The "what we do not sample historically" note -- visible, not buried --

function NotCoveredNote({ covers, notCovered }: { covers: string[]; notCovered: string }) {
  return (
    <Card>
      <p className="text-xs font-semibold uppercase tracking-wide text-amber-700 dark:text-amber-400">
        History-derived only
      </p>
      <p className="mt-1 text-sm text-ink-muted">{notCovered}</p>
      <p className="mt-2 text-xs text-ink-faint">
        Sampled at every point below: {covers.join(", ")}.
      </p>
    </Card>
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
      subtitle="Fixed scale -- each chart's axis never changes as you scrub"
    >
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-5">
        {METRIC_LINES.map((m) => (
          <div key={m.key} className="flex flex-col gap-1">
            <span className="cp-label">{m.label}</span>
            <div className="h-24">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={snapshots} margin={{ top: 4, right: 4, bottom: 0, left: 4 }}>
                  <XAxis dataKey="position" hide />
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
            <span className="cp-stat text-sm font-semibold text-ink">
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
      subtitle="Top files by cumulative churn at this point -- NOT the full risk formula (complexity isn't sampled historically)"
    >
      {rows.length === 0 ? (
        <p className="py-6 text-center text-sm text-ink-faint">
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
      subtitle="Commit share among active contributors, trailing 90-day window"
    >
      {names.length === 0 ? (
        <p className="py-6 text-center text-sm text-ink-faint">
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
                  stroke={
                    name === "Other" ? NEUTRAL_LINE : colorForSubsystem(`contributor:${name}`)
                  }
                  fill={name === "Other" ? NEUTRAL_LINE : colorForSubsystem(`contributor:${name}`)}
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
    <Card title="What changed here" subtitle={new Date(current.at_date).toLocaleDateString()}>
      {delta === null ? (
        <p className="text-sm text-ink-faint">
          This is the first sampled point -- nothing to compare against yet.
        </p>
      ) : (
        <div className="flex flex-col gap-3 text-sm">
          <div className="flex flex-wrap gap-x-6 gap-y-1 text-ink-muted">
            <DeltaStat label="Files" delta={delta.filesDelta} />
            <DeltaStat label="Commits" delta={delta.commitsDelta} />
            <DeltaStat label="Churn" delta={delta.churnDelta} />
            <DeltaStat label="Active contributors" delta={delta.contributorsDelta} />
          </div>

          {delta.topChurnMovers.length > 0 ? (
            <div>
              <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-ink-faint">
                Biggest churn movers
              </h3>
              <ul className="flex flex-col gap-0.5">
                {delta.topChurnMovers.map((m) => (
                  <li
                    key={m.path}
                    className="flex justify-between gap-2 font-mono text-xs text-ink-muted"
                  >
                    <span className="truncate">{m.path}</span>
                    <span className="shrink-0 tabular-nums text-amber-600 dark:text-amber-400">
                      +{m.churnDelta.toLocaleString()}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {delta.contributorsAppeared.length > 0 || delta.contributorsLeft.length > 0 ? (
            <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs text-ink-muted">
              {delta.contributorsAppeared.length > 0 ? (
                <span>First seen: {delta.contributorsAppeared.join(", ")}</span>
              ) : null}
              {delta.contributorsLeft.length > 0 ? (
                <span>No longer active: {delta.contributorsLeft.join(", ")}</span>
              ) : null}
            </div>
          ) : null}

          <p className="text-xs text-ink-faint">
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
    delta > 0
      ? "text-emerald-600 dark:text-emerald-400"
      : delta < 0
        ? "text-red-600 dark:text-red-400"
        : "text-ink-muted";
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
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-indigo-600 text-white hover:bg-indigo-500"
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
          className="w-full accent-indigo-600"
          aria-label="Timeline position"
        />
        <span className="w-28 shrink-0 text-right text-xs tabular-nums text-ink-muted">
          {new Date(current.at_date).toLocaleDateString()}
        </span>
      </div>
      <div className="mt-1 flex justify-between text-[11px] text-ink-faint">
        <span>{new Date(snapshots[0].at_date).toLocaleDateString()}</span>
        <span>
          Snapshot {position + 1} of {snapshots.length}
        </span>
        <span>{new Date(snapshots[snapshots.length - 1].at_date).toLocaleDateString()}</span>
      </div>
    </Card>
  );
}
