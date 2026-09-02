import { useMemo } from "react";
import { useOutletContext } from "react-router-dom";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useHealth, useHealthHistory, useRisk, useRuns } from "../../api/hooks";
import { Card } from "../../components/Card";
import { HeuristicNote } from "../../components/HeuristicNote";
import { ScoreGauge } from "../../components/ScoreGauge";
import { StageGate } from "../../components/StageGate";
import { CHROME, SEVERITY_COLOR, SUBSYSTEM_PALETTE, rechartsTheme } from "../../lib/chartTheme";
import type { HealthResponse } from "../../api/types";
import type { RepoOutletContext } from "../RepoLayout";

// Session 15: every colour on this page now comes from lib/chartTheme.ts,
// the single source Recharts (which needs explicit colour props -- Known
// Hazard #7) shares with the other three renderers.
const LANGUAGE_COLORS = SUBSYSTEM_PALETTE;

// Mirrors app/engines/health.py's own module-level constants VERBATIM, for
// DISPLAY purposes only -- this page never recomputes the score itself
// (that stays server-side), it only decomposes the three inputs
// `/health` already returns into the same penalty terms the backend already
// applied, so the waterfall can show HOW 100 became `score` instead of just
// asserting the number. HEURISTIC, not locked (RULES.md sec 3) -- if
// health.py's weights ever change, these must change with them.
const RISK_PENALTY_WEIGHT = 40.0;
const CYCLE_PENALTY_PER_CYCLE = 6.0;
const CYCLE_PENALTY_CAP = 30.0;
const HIDDEN_DEP_PENALTY_PER_PAIR = 3.0;
const HIDDEN_DEP_PENALTY_CAP = 30.0;

const MAX_HISTORY_RUNS = 15;

export function HealthPage() {
  const { repo, share } = useOutletContext<RepoOutletContext>();
  const health = useHealth(repo.id, share);
  const risk = useRisk(repo.id, share);

  const riskData = risk.data?.kind === "data" ? risk.data.data : undefined;

  const languageMix = useMemo(() => {
    if (!riskData) return [];
    const counts = new Map<string, number>();
    for (const file of riskData.files) {
      counts.set(file.language, (counts.get(file.language) ?? 0) + 1);
    }
    return [...counts.entries()]
      .map(([name, value]) => ({ name, value }))
      .sort((a, b) => b.value - a.value);
  }, [riskData]);

  return (
    <div className="flex flex-col gap-6">
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <Card
          title="Health score"
          subtitle="Composite of risk, cycles, and hidden dependencies"
          className="lg:col-span-1"
        >
          <StageGate query={health} loadingLabel="Computing health…">
            {(data) => (
              <div className="flex flex-col items-center gap-4">
                <ScoreGauge score={data.score} />
                <HeuristicNote
                  message="Heuristic score — not yet corpus-calibrated. Weights are documented, literature-informed defaults (see master-context.md §8.1), not a statistically fitted model."
                  calibration={data.calibration}
                />
                <dl className="grid w-full grid-cols-3 gap-2 text-center text-xs">
                  <div>
                    <dt className="text-ink-faint">High-risk files</dt>
                    <dd className="font-medium text-ink-muted">
                      {Math.round(data.high_risk_ratio * 100)}%
                    </dd>
                  </div>
                  <div>
                    <dt className="text-ink-faint">Cycles</dt>
                    <dd className="font-medium text-ink-muted">{data.cycle_count}</dd>
                  </div>
                  <div>
                    <dt className="text-ink-faint">Hidden deps</dt>
                    <dd className="font-medium text-ink-muted">{data.hidden_dependency_count}</dd>
                  </div>
                </dl>
              </div>
            )}
          </StageGate>
        </Card>

        <Card title="Repo vitals" className="lg:col-span-2">
          <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
            <dl className="grid grid-cols-2 gap-4 text-sm">
              <div>
                <dt className="text-ink-faint">Commits analyzed</dt>
                <dd className="text-xl font-semibold text-ink">{repo.commit_count}</dd>
              </div>
              <div>
                <dt className="text-ink-faint">Files</dt>
                <dd className="text-xl font-semibold text-ink">{repo.file_count}</dd>
              </div>
              <div>
                <dt className="text-ink-faint">Default branch</dt>
                <dd className="text-sm font-medium text-ink-muted">{repo.default_branch ?? "—"}</dd>
              </div>
              <div>
                <dt className="text-ink-faint">Last analyzed</dt>
                <dd className="text-sm font-medium text-ink-muted">
                  {repo.analyzed_at ? new Date(repo.analyzed_at).toLocaleString() : "—"}
                </dd>
              </div>
            </dl>
            <div className="h-40">
              <StageGate
                query={risk}
                loadingLabel="Loading language mix…"
                emptyTitle="No language data"
                isEmpty={() => languageMix.length === 0}
              >
                {() => (
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie
                        data={languageMix}
                        dataKey="value"
                        nameKey="name"
                        innerRadius={32}
                        outerRadius={56}
                        paddingAngle={2}
                      >
                        {languageMix.map((entry, i) => (
                          <Cell
                            key={entry.name}
                            fill={LANGUAGE_COLORS[i % LANGUAGE_COLORS.length]}
                          />
                        ))}
                      </Pie>
                      <Tooltip formatter={(value, name) => [`${value} files`, String(name)]} />
                      <Legend
                        verticalAlign="middle"
                        align="right"
                        layout="vertical"
                        iconSize={8}
                        wrapperStyle={{ fontSize: 12 }}
                      />
                    </PieChart>
                  </ResponsiveContainer>
                )}
              </StageGate>
            </div>
          </div>
        </Card>
      </div>

      <StageGate query={health} loadingLabel="Computing health…">
        {(data) => <HealthWaterfall data={data} />}
      </StageGate>

      <HealthHistorySparkline repoId={repo.id} share={share} />
    </div>
  );
}

/** "A composite score that does not explain itself is exactly the kind of
 * opaque number this project exists to be better than" (Part F). Reads the
 * SAME formula health.py documents (mirrored above, display-only) to turn
 * the three inputs `/health` already returns into a 100 → score waterfall,
 * rather than asserting the final number on its own. */
function HealthWaterfall({ data }: { data: HealthResponse }) {
  const riskPenalty = Math.min(100, RISK_PENALTY_WEIGHT * data.high_risk_ratio);
  const cyclePenalty = Math.min(CYCLE_PENALTY_CAP, CYCLE_PENALTY_PER_CYCLE * data.cycle_count);
  const hiddenPenalty = Math.min(
    HIDDEN_DEP_PENALTY_CAP,
    HIDDEN_DEP_PENALTY_PER_PAIR * data.hidden_dependency_count,
  );

  const steps: { name: string; delta: number }[] = [
    { name: "Start", delta: 100 },
    { name: `Risk (${Math.round(data.high_risk_ratio * 100)}% high-risk)`, delta: -riskPenalty },
    { name: `Cycles (×${data.cycle_count})`, delta: -cyclePenalty },
    { name: `Hidden deps (×${data.hidden_dependency_count})`, delta: -hiddenPenalty },
  ];

  let running = 0;
  const bars = steps.map((s) => {
    const before = running;
    running = Math.max(0, running + s.delta);
    const base = Math.min(before, running);
    const value = Math.abs(running - before);
    return { name: s.name, base, value, isPenalty: s.delta < 0 };
  });
  bars.push({ name: `Final score`, base: 0, value: data.score, isPenalty: false });

  return (
    <Card
      title="How the score was reached"
      subtitle="A waterfall from 100 down to the final score — every penalty term shown, not just asserted"
    >
      <div className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={bars} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
            <CartesianGrid {...rechartsTheme.grid} />
            <XAxis
              dataKey="name"
              tick={rechartsTheme.axis.tick}
              stroke={rechartsTheme.axis.stroke}
              interval={0}
              angle={-10}
              textAnchor="end"
              height={50}
            />
            <YAxis
              domain={[0, 100]}
              tick={rechartsTheme.axis.tick}
              stroke={rechartsTheme.axis.stroke}
            />
            <Tooltip
              {...rechartsTheme.tooltip}
              formatter={(value, name, item) => {
                if (name !== "value") return [null, null];
                const bar = item.payload as { isPenalty: boolean };
                const numeric = Number(value ?? 0);
                return [
                  bar.isPenalty ? `-${formatOne(numeric)}` : formatOne(numeric),
                  bar.isPenalty ? "penalty" : "value",
                ];
              }}
            />
            <Bar dataKey="base" stackId="waterfall" fill="transparent" />
            <Bar dataKey="value" stackId="waterfall">
              {bars.map((b, i) => (
                <Cell key={i} fill={b.isPenalty ? SEVERITY_COLOR.high : CHROME.signal} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </Card>
  );
}

function formatOne(value: number): string {
  return value.toFixed(1);
}

/** A run-history sparkline of the health score (Part F) -- the data has
 * existed since the Facts/Insight split (every past run's own `/health` is
 * still readable by `run_id`); session 13 builds the full compare view on
 * top of it. There is no bulk "health history" endpoint, so this fires one
 * `/health?run_id=` request per past READY run (useHealthHistory), capped
 * at the most recent MAX_HISTORY_RUNS so a long-lived repo doesn't fire
 * dozens of requests. */
function HealthHistorySparkline({ repoId, share }: { repoId: string; share?: string }) {
  const runs = useRuns(repoId, share);

  const readyRunIds = useMemo(() => {
    if (!runs.data) return [];
    return [...runs.data.runs]
      .filter((r) => r.status === "ready")
      .sort((a, b) => Date.parse(a.started_at) - Date.parse(b.started_at))
      .slice(-MAX_HISTORY_RUNS)
      .map((r) => r.id);
  }, [runs.data]);

  const runsById = useMemo(() => {
    const map = new Map<string, string>();
    for (const r of runs.data?.runs ?? []) map.set(r.id, r.started_at);
    return map;
  }, [runs.data]);

  const historyQueries = useHealthHistory(repoId, readyRunIds, share);

  const points = useMemo(() => {
    return readyRunIds
      .map((runId, i) => {
        const result = historyQueries[i]?.data;
        if (result?.kind !== "data") return null;
        return {
          runId,
          started_at: runsById.get(runId) ?? "",
          score: result.data.score,
        };
      })
      .filter((p): p is { runId: string; started_at: string; score: number } => p !== null);
  }, [readyRunIds, historyQueries, runsById]);

  if (runs.isPending || (readyRunIds.length > 0 && points.length === 0)) {
    return (
      <Card title="Health over time">
        <p className="py-6 text-center text-sm text-ink-faint">Loading run history…</p>
      </Card>
    );
  }

  if (points.length < 2) {
    return (
      <Card title="Health over time" subtitle="Score across past analysis runs">
        <p className="py-6 text-center text-sm text-ink-faint">
          Not enough completed runs yet to chart a trend.
        </p>
      </Card>
    );
  }

  return (
    <Card
      title="Health over time"
      subtitle={`Score across the last ${points.length} completed runs`}
    >
      <div className="h-40">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={points} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
            <CartesianGrid {...rechartsTheme.grid} />
            <XAxis
              dataKey="started_at"
              tickFormatter={(v: string) => new Date(v).toLocaleDateString()}
              tick={rechartsTheme.axis.tick}
              stroke={rechartsTheme.axis.stroke}
            />
            <YAxis
              domain={[0, 100]}
              tick={rechartsTheme.axis.tick}
              stroke={rechartsTheme.axis.stroke}
            />
            <Tooltip
              {...rechartsTheme.tooltip}
              labelFormatter={(v) => new Date(String(v)).toLocaleString()}
              formatter={(value) => [Math.round(Number(value ?? 0)), "score"]}
            />
            <Line
              type="monotone"
              dataKey="score"
              stroke={CHROME.signal}
              strokeWidth={2}
              dot={{ r: 3 }}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </Card>
  );
}
