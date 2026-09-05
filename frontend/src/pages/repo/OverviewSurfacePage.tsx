import { useMemo } from "react";
import { ArrowRight } from "lucide-react";
import { Link, useOutletContext } from "react-router-dom";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  useEntryPoints,
  useFormulas,
  useHealthHistory,
  usePassport,
  useRepoStatus,
  useRuns,
  useTruckFactor,
} from "../../api/hooks";
import { Card } from "../../components/ui/Card";
import { InfoTooltip } from "../../components/ui/InfoTooltip";
import { AnimatedList } from "../../reactbits/AnimatedList";
import { SpotlightCard } from "../../reactbits/SpotlightCard";
import { CountUp } from "../../components/motion/CountUp";
import { Reveal } from "../../components/motion/Reveal";
import { ContributorChip } from "../../components/ContributorChip";
import { HonestyNote } from "../../components/HonestyNote";
import { ScoreExplainer, type ScoreExplainerContribution } from "../../components/ScoreExplainer";
import { ScoreGauge } from "../../components/ScoreGauge";
import { StageGate } from "../../components/StageGate";
import { SubsystemBadge } from "../../components/SubsystemBadge";
import { ENTRY_POINT_KIND_COPY, FIRST_PR_COPY, FIRST_PR_LINK } from "../../lib/copy";
import { formatPercent, formatScore, healthColor, shortSha } from "../../lib/format";
import { CHROME, SEVERITY_COLOR, SUBSYSTEM_PALETTE, rechartsTheme } from "../../lib/chartTheme";
import { CALIBRATION_COPY, TOOLTIPS } from "../../content/explainability";
import type { FormulaGroupOut, PassportFirstPrItem, RepoPassportData } from "../../api/types";
import type { RepoOutletContext } from "../RepoLayout";

// Session 15: both this page's charts now draw from lib/chartTheme.ts, the
// single source every renderer in this app reads. Language shares reuse
// the SAME 14-colour categorical palette (lib/palette.ts) every other
// categorical view uses -- an ordered slice, not hashed, since shares are
// already sorted by size, so position IS the ranking.
const LANGUAGE_COLORS = SUBSYSTEM_PALETTE;
const CADENCE_BAR_COLOR = CHROME.inkMuted;
const MAX_HISTORY_RUNS = 15;

const DIFFICULTY_COMPONENT: Record<
  string,
  { label: string; constantName: string; tooltip: keyof typeof TOOLTIPS }
> = {
  subsystem_count: {
    label: "Subsystem count",
    constantName: "subsystem_count_weight",
    tooltip: "subsystemCount",
  },
  median_file_complexity: {
    label: "Median file complexity",
    constantName: "median_complexity_weight",
    tooltip: "medianComplexity",
  },
  doc_coverage: {
    label: "Documentation coverage",
    constantName: "doc_coverage_weight",
    tooltip: "docCoverage",
  },
  truck_factor: {
    label: "Truck factor",
    constantName: "truck_factor_weight",
    tooltip: "truckFactor",
  },
  max_dependency_depth: {
    label: "Max dependency depth",
    constantName: "max_dependency_depth_weight",
    tooltip: "maxDependencyDepth",
  },
};

function difficultyDetail(key: string, raw: number): string {
  switch (key) {
    case "subsystem_count":
      return `${Math.round(raw)} subsystem${Math.round(raw) === 1 ? "" : "s"} detected.`;
    case "median_file_complexity":
      return `Median cyclomatic complexity across scored files is ${raw.toFixed(1)}.`;
    case "doc_coverage":
      return `Documentation coverage scored ${formatPercent(raw)} (README presence/length, and a CONTRIBUTING file or docs directory).`;
    case "truck_factor":
      return `Truck factor is ${Math.round(raw)}.`;
    case "max_dependency_depth":
      return `The deepest import chain from any entry point runs ${Math.round(raw)} hop${Math.round(raw) === 1 ? "" : "s"} deep.`;
    default:
      return "";
  }
}

function calibrationText(calibration: string): string | null {
  return calibration === "heuristic" || calibration === "corpus"
    ? CALIBRATION_COPY[calibration]
    : null;
}

function constantValue(group: FormulaGroupOut | undefined, name: string): number | null {
  const c = group?.constants.find((c) => c.name === name);
  return typeof c?.value === "number" ? c.value : null;
}

/** `/repos/:id/overview` (rebuild spec section 4.1) -- the landing surface
 * for every repository. ONE `usePassport()` call drives almost every
 * section below: the passport payload already embeds `HealthEngine`'s row
 * (`data.health`) and the language breakdown (`data.identity.language_breakdown`),
 * so neither gets a second fetch. Every section gates on the SAME
 * "onboarding" stage through that one call. The run-history sparkline is
 * the one genuine exception -- it describes PAST runs, not this run's own
 * gate, so it renders independently and never blocks on the StageGate. */
export function OverviewSurfacePage() {
  const { repo, share } = useOutletContext<RepoOutletContext>();
  const passport = usePassport(repo.id, share);

  return (
    <div className="flex flex-col gap-6">
      <p className="text-sm text-text-muted">
        A one-page summary of what this repository is, how healthy it is, and what's worth knowing
        before you start reading code.
      </p>
      <StageGate query={passport} loadingLabel="Computing the repo passport…">
        {(data) => (
          <>
            <Reveal>
              <IdentityStrip data={data.data} repo={repo} share={share} />
            </Reveal>
            <Reveal delay={0.04}>
              <DifficultyCard
                difficulty={data.onboarding_difficulty}
                breakdown={data.difficulty_breakdown}
                calibration={data.calibration}
              />
            </Reveal>
            <div id="health" className="scroll-mt-6">
              <Reveal delay={0.08}>
                <HealthCard data={data.data} calibration={data.data.health.calibration} />
              </Reveal>
            </div>
            <Reveal delay={0.1}>
              <HealthHistorySparkline repoId={repo.id} share={share} />
            </Reveal>
            <Reveal delay={0.12}>
              <ThreeThingsCard items={data.data.first_pr} repoId={repo.id} />
            </Reveal>
            <Reveal delay={0.14}>
              <ScaleAndCadenceCard data={data.data} />
            </Reveal>
            <Reveal delay={0.16}>
              <TeamShapeCard data={data.data} repoId={repo.id} share={share} />
            </Reveal>
            <Reveal delay={0.18}>
              <ShapeCard data={data.data} repoId={repo.id} share={share} />
            </Reveal>
          </>
        )}
      </StageGate>
    </div>
  );
}

// --- 1. Identity strip -----------------------------------------------------

function IdentityStrip({
  data,
  repo,
  share,
}: {
  data: RepoPassportData;
  repo: RepoOutletContext["repo"];
  share?: string;
}) {
  const { identity, cadence } = data;
  const runs = useRuns(repo.id, share);
  const status = useRepoStatus(repo.id, share);
  const currentRun = runs.data?.runs.find((r) => r.id === status.data?.current_run_id);

  const totalFiles = Object.values(identity.language_breakdown).reduce((a, b) => a + b, 0);
  const languageShares = Object.entries(identity.language_breakdown)
    .map(([language, count]) => ({ language, share: totalFiles > 0 ? count / totalFiles : 0 }))
    .sort((a, b) => b.share - a.share);

  return (
    <Card
      title={`${identity.owner}/${identity.name}`}
      action={
        // There is no canvas-based city or map any more (D6/D14) -- Explore's
        // sortable file table is where "look at the actual files" now lives.
        <Link
          to={`/repos/${repo.id}/explore`}
          className="text-xs font-medium text-accent hover:underline"
        >
          Explore the codebase →
        </Link>
      }
    >
      <div className="flex flex-col gap-3">
        <p className="font-mono text-xs text-text-muted">{identity.url}</p>
        <div className="flex flex-wrap items-center gap-2 text-sm text-text-muted">
          <span className="font-medium text-text">{identity.primary_language}</span>
          <span className="text-text-muted/50">·</span>
          <span>{identity.license_spdx ?? "No detected license"}</span>
          <span className="text-text-muted/50">·</span>
          <span className="font-mono">{shortSha(currentRun?.head_sha)}</span>
          <span className="text-text-muted/50">·</span>
          <span>
            Analysed {repo.analyzed_at ? new Date(repo.analyzed_at).toLocaleString() : "unknown"}
          </span>
          {repo.is_showcase ? (
            <span className="inline-flex items-center rounded-full border border-accent-border bg-accent-bg px-2 py-0.5 text-xs font-medium text-accent">
              Showcase
            </span>
          ) : null}
          {cadence.is_dormant ? (
            <span className="inline-flex items-center rounded-full border border-warning bg-warning-bg px-2 py-0.5 text-xs font-medium text-warning">
              Dormant
            </span>
          ) : null}
          {!identity.has_readme ? (
            <span className="inline-flex items-center rounded-full border border-border px-2 py-0.5 text-xs font-medium text-text-muted">
              No README
            </span>
          ) : null}
        </div>

        {languageShares.length > 0 ? (
          <div className="flex flex-col gap-1.5">
            <div className="flex h-2.5 w-full overflow-hidden rounded-full bg-bg-inset">
              {languageShares.map((l, i) => (
                <div
                  key={l.language}
                  style={{
                    width: `${l.share * 100}%`,
                    backgroundColor: LANGUAGE_COLORS[i % LANGUAGE_COLORS.length],
                  }}
                  title={`${l.language}: ${formatPercent(l.share)}`}
                />
              ))}
            </div>
            <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-text-muted">
              {languageShares.map((l, i) => (
                <span key={l.language} className="inline-flex items-center gap-1">
                  <span
                    className="h-2 w-2 rounded-full"
                    style={{ backgroundColor: LANGUAGE_COLORS[i % LANGUAGE_COLORS.length] }}
                  />
                  {l.language} {formatPercent(l.share)}
                </span>
              ))}
            </div>
          </div>
        ) : null}
      </div>
    </Card>
  );
}

// --- 2. Onboarding difficulty -----------------------------------------------

function DifficultyCard({
  difficulty,
  breakdown,
  calibration,
}: {
  difficulty: number;
  breakdown: Record<string, { raw: number; normalized: number; weight: number }>;
  calibration: string;
}) {
  // healthColor is a "high = good" scale -- difficulty is the opposite
  // ("high = hard, should read as alarming"), so it's fed the inverted
  // value purely for colour classification. No new colour system, this
  // reuses the exact same tokens /health already uses.
  const colors = healthColor(100 - difficulty);
  const calText = calibrationText(calibration);

  const contributions: ScoreExplainerContribution[] = Object.entries(breakdown).map(([key, v]) => {
    const meta = DIFFICULTY_COMPONENT[key] ?? { label: key, constantName: key, tooltip: undefined };
    return {
      constantName: meta.constantName,
      label: meta.label,
      tooltip: meta.tooltip,
      normalizedValue: v.normalized,
      detail: difficultyDetail(key, v.raw),
    };
  });

  return (
    <Card
      title="Onboarding difficulty"
      action={
        <InfoTooltip label="What is onboarding difficulty?" text={TOOLTIPS.onboardingDifficulty} />
      }
    >
      <div className="flex flex-col gap-3">
        <p className="text-xs text-text-muted">Higher means harder to get productive in quickly.</p>
        <div className="flex items-baseline gap-2">
          <span className={`cp-stat text-3xl font-semibold ${colors.text}`}>
            <CountUp to={Math.round(difficulty)} />
          </span>
          <span className="cp-label">/ 100</span>
        </div>
        {calText ? <HonestyNote variant="calibration" text={calText} /> : null}
        <div className="flex h-3 w-full overflow-hidden rounded-full bg-bg-inset">
          {Object.entries(breakdown).map(([key, v]) => (
            <div
              key={key}
              className={colors.bar}
              style={{
                width: `${Math.max(0, v.weight * v.normalized) * 100}%`,
                opacity: 0.4 + v.weight,
              }}
              title={`${DIFFICULTY_COMPONENT[key]?.label ?? key}: raw ${formatScore(v.raw, 2)}, weight ${formatPercent(v.weight)}`}
            />
          ))}
        </div>
        <ScoreExplainer
          formulaKey="onboarding_difficulty"
          calibration={calibration}
          contributions={contributions}
        />
      </div>
    </Card>
  );
}

// --- 3. Health ---------------------------------------------------------------

const RISK_PENALTY_WEIGHT_NAME = "risk_penalty_weight";
const CYCLE_PENALTY_PER_CYCLE_NAME = "cycle_penalty_per_cycle";
const CYCLE_PENALTY_CAP_NAME = "cycle_penalty_cap";
const HIDDEN_DEP_PENALTY_PER_PAIR_NAME = "hidden_dep_penalty_per_pair";
const HIDDEN_DEP_PENALTY_CAP_NAME = "hidden_dep_penalty_cap";

function HealthCard({ data, calibration }: { data: RepoPassportData; calibration: string }) {
  const { health } = data;
  const formulas = useFormulas();
  const healthGroup = formulas.data?.groups.find((g) => g.key === "health");
  const calText = calibrationText(calibration);

  const riskWeight = constantValue(healthGroup, RISK_PENALTY_WEIGHT_NAME);
  const cyclePerCycle = constantValue(healthGroup, CYCLE_PENALTY_PER_CYCLE_NAME);
  const cycleCap = constantValue(healthGroup, CYCLE_PENALTY_CAP_NAME);
  const hiddenPerPair = constantValue(healthGroup, HIDDEN_DEP_PENALTY_PER_PAIR_NAME);
  const hiddenCap = constantValue(healthGroup, HIDDEN_DEP_PENALTY_CAP_NAME);

  const contributions: ScoreExplainerContribution[] = [
    {
      constantName: RISK_PENALTY_WEIGHT_NAME,
      label: "High-risk files",
      tooltip: "highRiskRatio",
      normalizedValue: health.high_risk_ratio,
      detail: `${formatPercent(health.high_risk_ratio)} of scored files have a risk score at or above the high-risk threshold.`,
    },
    {
      constantName: CYCLE_PENALTY_PER_CYCLE_NAME,
      label: "Circular dependencies",
      tooltip: "cycle",
      normalizedValue:
        cyclePerCycle && cycleCap
          ? Math.min(health.cycle_count, cycleCap / cyclePerCycle)
          : health.cycle_count,
      detail: `${health.cycle_count} circular import chain${health.cycle_count === 1 ? "" : "s"} detected.`,
    },
    {
      constantName: HIDDEN_DEP_PENALTY_PER_PAIR_NAME,
      label: "Hidden dependencies",
      tooltip: "hiddenDependency",
      normalizedValue:
        hiddenPerPair && hiddenCap
          ? Math.min(health.hidden_dependency_count, hiddenCap / hiddenPerPair)
          : health.hidden_dependency_count,
      detail: `${health.hidden_dependency_count} pair${health.hidden_dependency_count === 1 ? "" : "s"} of files change together with no structural edge between them.`,
    },
  ];

  return (
    <Card
      title="Health"
      action={<InfoTooltip label="What is the health score?" text={TOOLTIPS.healthScore} />}
    >
      <div className="flex flex-col gap-4">
        <p className="text-xs text-text-muted">
          Composite of high-risk files, circular dependencies, and hidden dependencies.
        </p>
        <div className="flex flex-col items-center gap-4 sm:flex-row sm:items-start sm:justify-around">
          <ScoreGauge score={health.score} />
          <div className="flex flex-col gap-3">
            {calText ? <HonestyNote variant="calibration" text={calText} /> : null}
            <dl className="grid grid-cols-3 gap-4 text-center text-xs">
              <div>
                <dt className="flex items-center justify-center gap-1 text-text-muted">
                  High-risk files
                  <InfoTooltip label="What is high-risk ratio?" text={TOOLTIPS.highRiskRatio} />
                </dt>
                <dd className="font-medium text-text">{formatPercent(health.high_risk_ratio)}</dd>
              </div>
              <div>
                <dt className="flex items-center justify-center gap-1 text-text-muted">
                  Cycles
                  <InfoTooltip label="What is a cycle?" text={TOOLTIPS.cycle} />
                </dt>
                <dd className="font-medium text-text">{health.cycle_count}</dd>
              </div>
              <div>
                <dt className="flex items-center justify-center gap-1 text-text-muted">
                  Hidden deps
                  <InfoTooltip
                    label="What is a hidden dependency?"
                    text={TOOLTIPS.hiddenDependency}
                  />
                </dt>
                <dd className="font-medium text-text">{health.hidden_dependency_count}</dd>
              </div>
            </dl>
          </div>
        </div>

        {healthGroup && riskWeight != null ? (
          <HealthWaterfall
            score={health.score}
            highRiskRatio={health.high_risk_ratio}
            cycleCount={health.cycle_count}
            hiddenDependencyCount={health.hidden_dependency_count}
            riskWeight={riskWeight}
            cyclePerCycle={cyclePerCycle ?? 0}
            cycleCap={cycleCap ?? 0}
            hiddenPerPair={hiddenPerPair ?? 0}
            hiddenCap={hiddenCap ?? 0}
          />
        ) : (
          <p className="text-xs text-text-muted">
            {formulas.isPending
              ? "Loading the score breakdown…"
              : "The score breakdown isn't available right now — the score itself above is still accurate."}
          </p>
        )}

        <ScoreExplainer formulaKey="health" contributions={contributions} />
      </div>
    </Card>
  );
}

/** "A composite score that does not explain itself is exactly the kind of
 * opaque number this project exists to be better than." Every constant
 * here is read live from GET /meta/formulas (the caller), never mirrored
 * into this file -- the score itself is never recomputed client-side; this
 * only decomposes the three penalty terms the SERVER already applied into
 * a 100 -> score waterfall, and the final bar renders the server's own
 * `score` value verbatim. If the live constants haven't resolved, the
 * caller skips this component entirely rather than falling back to a
 * hardcoded copy of the weights. */
function HealthWaterfall({
  score,
  highRiskRatio,
  cycleCount,
  hiddenDependencyCount,
  riskWeight,
  cyclePerCycle,
  cycleCap,
  hiddenPerPair,
  hiddenCap,
}: {
  score: number;
  highRiskRatio: number;
  cycleCount: number;
  hiddenDependencyCount: number;
  riskWeight: number;
  cyclePerCycle: number;
  cycleCap: number;
  hiddenPerPair: number;
  hiddenCap: number;
}) {
  const riskPenalty = Math.min(100, riskWeight * highRiskRatio);
  const cyclePenalty = Math.min(cycleCap, cyclePerCycle * cycleCount);
  const hiddenPenalty = Math.min(hiddenCap, hiddenPerPair * hiddenDependencyCount);

  const steps: { name: string; delta: number }[] = [
    { name: "Start", delta: 100 },
    { name: `Risk (${Math.round(highRiskRatio * 100)}% high-risk)`, delta: -riskPenalty },
    { name: `Cycles (×${cycleCount})`, delta: -cyclePenalty },
    { name: `Hidden deps (×${hiddenDependencyCount})`, delta: -hiddenPenalty },
  ];

  let running = 100;
  const bars = [{ name: "Start", base: 0, value: 100, isPenalty: false }];
  for (const s of steps.slice(1)) {
    const before = running;
    running = Math.max(0, running + s.delta);
    const base = Math.min(before, running);
    const value = Math.abs(running - before);
    bars.push({ name: s.name, base, value, isPenalty: s.delta < 0 });
  }
  bars.push({ name: "Final score", base: 0, value: score, isPenalty: false });

  return (
    <div>
      <p className="cp-label mb-2 text-text-muted">
        How the score was reached — a waterfall from 100 down to the final score
      </p>
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
                  bar.isPenalty ? `-${numeric.toFixed(1)}` : numeric.toFixed(1),
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
    </div>
  );
}

/** A run-history sparkline of the health score -- the data has existed
 * since the Facts/Insight split (every past run's own `/health` is still
 * readable by `run_id`); session 13 built the full compare view on top of
 * it. There is no bulk "health history" endpoint, so this fires one
 * `/health?run_id=` request per past READY run (useHealthHistory), capped
 * at the most recent MAX_HISTORY_RUNS. Deliberately outside the passport's
 * own StageGate -- it describes past runs, not this run's own gate, and
 * must never block on it. */
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
        return { runId, started_at: runsById.get(runId) ?? "", score: result.data.score };
      })
      .filter((p): p is { runId: string; started_at: string; score: number } => p !== null);
  }, [readyRunIds, historyQueries, runsById]);

  if (runs.isPending || (readyRunIds.length > 0 && points.length === 0)) {
    return (
      <Card title="Health over time">
        <p className="py-6 text-center text-sm text-text-muted">Loading run history…</p>
      </Card>
    );
  }

  if (points.length < 2) {
    return (
      <Card title="Health over time">
        <p className="py-6 text-center text-sm text-text-muted">
          Not enough completed runs yet to chart a trend — analyse this repository again later to
          start one.
        </p>
      </Card>
    );
  }

  return (
    <Card title="Health over time">
      <p className="mb-2 text-xs text-text-muted">
        Score across the last {points.length} completed runs
      </p>
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

// --- 4. Three things to know ------------------------------------------------

function ThreeThingsCard({ items, repoId }: { items: PassportFirstPrItem[]; repoId: string }) {
  return (
    <Card title="Three things to know">
      <p className="mb-3 text-xs text-text-muted">
        The most actionable facts this analysis surfaced.
      </p>
      {items.length === 0 ? (
        <p className="text-sm text-text-muted">
          Nothing stood out sharply enough to flag here — a quiet result, not a missing one.
        </p>
      ) : (
        // "Three things" reads as three things -- a row of small cards
        // states that shape directly, rather than a plain stacked list
        // that happens to have three rows.
        <AnimatedList
          items={items}
          keyFor={(item) => item.code}
          className="grid grid-cols-1 gap-3 sm:grid-cols-3"
          renderItem={(item) => (
            <Link
              to={`/repos/${repoId}/${FIRST_PR_LINK[item.code]}`}
              className="group block h-full"
            >
              <SpotlightCard className="flex h-full flex-col justify-between gap-3 rounded-md border border-border bg-bg-inset p-3 transition-colors group-hover:border-accent-border">
                <p className="text-sm text-text">{FIRST_PR_COPY[item.code](item.params)}</p>
                <span className="inline-flex items-center gap-1 text-xs font-medium text-accent">
                  View
                  <ArrowRight
                    size={12}
                    aria-hidden="true"
                    className="transition-transform group-hover:translate-x-0.5"
                  />
                </span>
              </SpotlightCard>
            </Link>
          )}
        />
      )}
    </Card>
  );
}

// --- 5. Scale and cadence ---------------------------------------------------

function ScaleAndCadenceCard({ data }: { data: RepoPassportData }) {
  const { scale, cadence } = data;
  // No backend endpoint returns a real commit-count time series (only these
  // three cumulative recency windows), so a literal "lifetime sparkline"
  // would have to fabricate intermediate data points -- something this
  // product's whole premise forbids. This bar chart shows exactly the real
  // numbers available instead of inventing a false level of detail.
  const cadenceBars = [
    { window: "Last 30d", commits: cadence.commits_last_30d },
    { window: "Last 90d", commits: cadence.commits_last_90d },
    { window: "Last 365d", commits: cadence.commits_last_365d },
  ];

  return (
    <Card
      title="Scale and cadence"
      action={<InfoTooltip label="What is commit cadence?" text={TOOLTIPS.commitCadence} />}
    >
      <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
        <dl className="grid grid-cols-3 gap-4 text-sm">
          <Stat label="Files" value={scale.files} />
          <Stat label="LOC" value={scale.loc} />
          <Stat label="Commits" value={scale.commits} />
          <Stat label="Contributors" value={scale.contributors} />
          <Stat label="Subsystems" value={scale.subsystems} />
          <Stat label="Active days" value={cadence.active_days} />
        </dl>
        <div className="h-32">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={cadenceBars} layout="vertical" margin={{ left: 8, right: 16 }}>
              <XAxis type="number" hide />
              <YAxis
                type="category"
                dataKey="window"
                width={64}
                tick={rechartsTheme.axis.tick}
                axisLine={false}
                tickLine={false}
              />
              <Tooltip {...rechartsTheme.tooltip} formatter={(value) => [`${value} commits`, ""]} />
              <Bar dataKey="commits" fill={CADENCE_BAR_COLOR} radius={0} barSize={14} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
      {cadence.longest_gap_days > 0 ? (
        <p className="mt-3 text-xs text-text-muted">
          Longest gap between commits: {Math.round(cadence.longest_gap_days)} days · median{" "}
          {formatScore(cadence.median_commits_per_active_week, 1)} commits per active week.
        </p>
      ) : null}
    </Card>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <dt className="cp-label">{label}</dt>
      <dd className="cp-stat text-lg font-semibold text-text">
        <CountUp to={value} />
      </dd>
    </div>
  );
}

// --- 6. Team shape -----------------------------------------------------------

function TeamShapeCard({
  data,
  repoId,
  share,
}: {
  data: RepoPassportData;
  repoId: string;
  share?: string;
}) {
  const { team } = data;
  // The passport payload only carries the truck-factor NUMBER
  // (data.team.truck_factor) -- the explainable removal sequence lives on
  // the dedicated /truck-factor endpoint, which passport never embeds. This
  // is the one extra fetch on this page beyond usePassport.
  const truckFactor = useTruckFactor(repoId, share);

  return (
    <Card
      title="Team shape"
      action={<InfoTooltip label="What is truck factor?" text={TOOLTIPS.truckFactor} />}
    >
      <div className="flex flex-col gap-4">
        <div className="flex items-center gap-6">
          <div>
            <p className="cp-stat text-3xl font-semibold text-text">
              <CountUp to={team.truck_factor} />
            </p>
            <p className="cp-label">Truck factor</p>
          </div>
          <dl className="grid grid-cols-3 gap-4 text-sm">
            <Stat label="Active" value={team.active_contributors} />
            <Stat label="Stale" value={team.stale_contributors} />
            <div>
              <dt className="cp-label flex items-center gap-1">
                Bot commits
                <InfoTooltip label="What is bot commit ratio?" text={TOOLTIPS.botCommitRatio} />
              </dt>
              <dd className="cp-stat text-lg font-semibold text-text">
                {formatPercent(team.bot_commit_ratio)}
              </dd>
            </div>
          </dl>
        </div>

        {truckFactor.data?.kind === "data" && truckFactor.data.data.removal_order.length > 0 ? (
          <div>
            <p className="mb-1.5 text-xs font-medium text-text-muted">
              Removal sequence — this project's own knowledge-risk measure, not an individual
              ranking
            </p>
            <ol className="flex flex-wrap items-center gap-1.5 text-xs text-text-muted">
              {truckFactor.data.data.removal_order.slice(0, 5).map((step, i) => (
                <li key={step.contributor_id} className="flex items-center gap-1.5">
                  {i > 0 ? <span className="text-text-muted/50">→</span> : null}
                  <span>
                    remove {step.name}{" "}
                    <span className="tabular-nums">
                      {formatPercent(step.cumulative_orphan_ratio)}
                    </span>{" "}
                    orphaned
                  </span>
                </li>
              ))}
            </ol>
          </div>
        ) : null}

        {team.top_contributors.length > 0 ? (
          <div>
            <p className="mb-1.5 text-xs font-medium text-text-muted">
              Contributors by share of commits — activity, not a performance ranking
            </p>
            <AnimatedList
              items={team.top_contributors}
              // PassportTopContributor carries no id (a deliberately minimal
              // shape) and two distinct contributors can share a display
              // name -- index-qualify the key so React never warns about a
              // collision.
              keyFor={(c, i) => `${c.name}-${i}`}
              className="flex flex-col gap-1.5"
              renderItem={(c) => (
                <div className="flex items-center gap-2">
                  <ContributorChip name={c.name} isStale={c.is_stale} />
                  <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-bg-inset">
                    <div
                      className="h-full rounded-full bg-accent"
                      style={{ width: `${Math.round(c.share * 100)}%` }}
                    />
                  </div>
                  <span className="w-10 shrink-0 text-right text-xs tabular-nums text-text-muted">
                    {formatPercent(c.share)}
                  </span>
                </div>
              )}
            />
          </div>
        ) : null}
      </div>
    </Card>
  );
}

// --- 7. Shape ----------------------------------------------------------------

function ShapeCard({
  data,
  repoId,
  share,
}: {
  data: RepoPassportData;
  repoId: string;
  share?: string;
}) {
  const { shape, hotspots } = data;
  // Same reasoning as the truck-factor fetch above -- passport's
  // PassportEntryPointSummary only carries {path, kind}, never the literal
  // `evidence` rule string, which only the dedicated /entry-points endpoint
  // returns.
  const entryPoints = useEntryPoints(repoId, share);
  const evidenceByPath = useMemo(() => {
    if (entryPoints.data?.kind !== "data") return new Map<string, string>();
    return new Map(entryPoints.data.data.entry_points.map((e) => [e.file_path, e.evidence]));
  }, [entryPoints.data]);

  return (
    <Card title="Shape">
      <p className="mb-3 flex items-center gap-1.5 text-xs text-text-muted">
        <span>Modularity {formatScore(shape.modularity, 2)}</span>
        <InfoTooltip label="What is modularity?" text={TOOLTIPS.modularity} />
      </p>
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <div>
          <p className="mb-1.5 flex items-center gap-1 text-xs font-medium text-text-muted">
            Subsystems
            <InfoTooltip label="What is a subsystem?" text={TOOLTIPS.subsystem} />
          </p>
          <AnimatedList
            items={shape.subsystems}
            keyFor={(s) => s.label}
            className="flex flex-col gap-2"
            renderItem={(s) => (
              <div className="flex items-center gap-2 text-sm">
                <SubsystemBadge label={s.label} />
                <span className="text-xs text-text-muted">{s.file_count} files</span>
                <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-bg-inset">
                  <div
                    className="h-full rounded-full bg-accent"
                    style={{ width: `${Math.round(s.cohesion * 100)}%` }}
                  />
                </div>
                <span className="w-10 shrink-0 text-right text-xs tabular-nums text-text-muted">
                  {formatPercent(s.cohesion)}
                </span>
              </div>
            )}
          />
        </div>

        <div>
          <p className="mb-1.5 flex items-center gap-1 text-xs font-medium text-text-muted">
            Entry points
            <InfoTooltip label="What is an entry point?" text={TOOLTIPS.entryPoint} />
          </p>
          <AnimatedList
            items={shape.entry_points}
            keyFor={(e) => e.path}
            className="flex flex-col gap-2 text-sm"
            renderItem={(e) => (
              <div className="flex flex-col gap-0.5">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="min-w-0 truncate font-mono text-xs text-text-muted">
                    {e.path}
                  </span>
                  <span className="rounded-full border border-border px-1.5 py-0.5 text-[10px] font-medium text-text-muted">
                    {ENTRY_POINT_KIND_COPY[e.kind]()}
                  </span>
                </div>
                {evidenceByPath.get(e.path) ? (
                  <p className="text-xs text-text-muted">{evidenceByPath.get(e.path)}</p>
                ) : null}
              </div>
            )}
          />
        </div>
      </div>

      {hotspots.top_risk_files.length > 0 ? (
        <div className="mt-4 border-t border-border pt-4">
          <p className="mb-1.5 flex items-center gap-1 text-xs font-medium text-text-muted">
            Top risk files
            <InfoTooltip label="What is risk score?" text={TOOLTIPS.riskScore} />
            <span className="text-text-muted/50">·</span>
            {formatPercent(hotspots.churn_concentration)} of churn is concentrated in the busiest
            10% of files
          </p>
          <AnimatedList
            items={hotspots.top_risk_files}
            keyFor={(f) => f.path}
            className="flex flex-col gap-1 text-xs"
            renderItem={(f) => (
              <div className="flex items-center justify-between gap-2">
                <span className="truncate font-mono text-text-muted">{f.path}</span>
                <span className="shrink-0 tabular-nums text-text-muted">
                  {formatScore(f.risk_score)}
                </span>
              </div>
            )}
          />
        </div>
      ) : null}
    </Card>
  );
}
