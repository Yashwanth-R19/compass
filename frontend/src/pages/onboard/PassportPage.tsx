import { useMemo } from "react";
import { Link, useOutletContext } from "react-router-dom";
import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useEntryPoints, usePassport, useTruckFactor } from "../../api/hooks";
import { Card } from "../../components/Card";
import { ContributorChip } from "../../components/ContributorChip";
import { HeuristicNote } from "../../components/HeuristicNote";
import { NarrativeBlock } from "../../components/NarrativeBlock";
import { ScoreGauge } from "../../components/ScoreGauge";
import { StageGate } from "../../components/StageGate";
import { SubsystemBadge } from "../../components/SubsystemBadge";
import { ENTRY_POINT_KIND_COPY, FIRST_PR_COPY, FIRST_PR_LINK } from "../../lib/copy";
import { formatPercent, formatScore, healthColor } from "../../lib/format";
import type { PassportFirstPrItem, RepoPassportData } from "../../api/types";
import type { RepoOutletContext } from "../RepoLayout";

// One local palette for this page's two charts (Known Hazard #7) -- Recharts
// needs literal color props, it never inherits Tailwind/CSS custom
// properties, so every hex value used on this page lives here and nowhere
// else.
const LANGUAGE_COLORS = [
  "#6366f1",
  "#0ea5e9",
  "#10b981",
  "#f59e0b",
  "#ec4899",
  "#8b5cf6",
  "#64748b",
];
const CADENCE_BAR_COLOR = "#6366f1";

const DIFFICULTY_COMPONENT_LABEL: Record<string, string> = {
  subsystem_count: "Subsystem count",
  median_file_complexity: "Median file complexity",
  doc_coverage: "Documentation coverage",
  truck_factor: "Truck factor",
  max_dependency_depth: "Max dependency depth",
};

export function PassportPage() {
  const { repo, share } = useOutletContext<RepoOutletContext>();
  const passport = usePassport(repo.id, share);

  return (
    <StageGate query={passport} loadingLabel="Computing the repo passport…">
      {(data) => (
        <div className="flex flex-col gap-6">
          <IdentityStrip data={data.data} repoId={repo.id} />
          <DifficultyCard
            difficulty={data.onboarding_difficulty}
            breakdown={data.difficulty_breakdown}
            calibration={data.calibration}
          />
          <ThreeThingsCard items={data.data.first_pr} repoId={repo.id} />
          <ScaleAndCadenceCard data={data.data} />
          <TeamShapeCard data={data.data} repoId={repo.id} share={share} />
          <ShapeCard data={data.data} repoId={repo.id} share={share} />
          <HealthCard data={data.data} calibration={data.calibration} />
          <NarrativeBlock surface="passport" />
        </div>
      )}
    </StageGate>
  );
}

// --- 1. Identity strip -----------------------------------------------------

function IdentityStrip({ data, repoId }: { data: RepoPassportData; repoId: string }) {
  const { identity, scale, cadence } = data;
  const totalFiles = Object.values(identity.language_breakdown).reduce((a, b) => a + b, 0);
  const languageShares = Object.entries(identity.language_breakdown)
    .map(([language, count]) => ({ language, share: totalFiles > 0 ? count / totalFiles : 0 }))
    .sort((a, b) => b.share - a.share);

  return (
    <Card
      title={`${identity.owner}/${identity.name}`}
      subtitle={identity.url}
      action={
        <Link
          to={`/repos/${repoId}/onboard/city`}
          className="text-xs font-medium text-indigo-600 hover:underline dark:text-indigo-400"
        >
          Explore in 3D city →
        </Link>
      }
    >
      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-2 text-sm text-slate-600 dark:text-slate-300">
          <span className="font-medium text-slate-900 dark:text-slate-100">
            {identity.primary_language}
          </span>
          <span className="text-slate-300 dark:text-slate-600">·</span>
          <span>{identity.license_spdx ?? "No detected license"}</span>
          <span className="text-slate-300 dark:text-slate-600">·</span>
          <span>{Math.round(scale.age_days)} days old</span>
          <span className="text-slate-300 dark:text-slate-600">·</span>
          <span>
            Last active{" "}
            {scale.last_commit_at ? new Date(scale.last_commit_at).toLocaleDateString() : "unknown"}
          </span>
          {cadence.is_dormant ? (
            <span className="inline-flex items-center rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700 dark:bg-amber-500/10 dark:text-amber-400">
              Dormant
            </span>
          ) : null}
          {!identity.has_readme ? (
            <span className="inline-flex items-center rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-500 dark:bg-slate-800 dark:text-slate-400">
              No README
            </span>
          ) : null}
        </div>

        {languageShares.length > 0 ? (
          <div className="flex flex-col gap-1.5">
            <div className="flex h-2.5 w-full overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
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
            <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-slate-500 dark:text-slate-400">
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
  // healthColor is a "high = good, green" scale -- difficulty is the
  // opposite ("high = hard, should read as alarming"), so it's fed the
  // inverted value purely for color classification. No new color system is
  // introduced; this reuses the exact same tokens /health already uses.
  const colors = healthColor(100 - difficulty);
  const components = Object.entries(breakdown).map(([key, v]) => ({
    key,
    label: DIFFICULTY_COMPONENT_LABEL[key] ?? key,
    contribution: v.weight * v.normalized,
    ...v,
  }));

  return (
    <Card title="Onboarding difficulty" subtitle="Higher means harder to get productive in quickly">
      <div className="flex flex-col gap-3">
        <div className="flex items-baseline gap-2">
          <span className={`text-3xl font-semibold tabular-nums ${colors.text}`}>
            {Math.round(difficulty)}
          </span>
          <span className="text-xs text-slate-400 dark:text-slate-500">/ 100</span>
        </div>
        <HeuristicNote calibration={calibration} />
        <div className="flex h-3 w-full overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
          {components.map((c) => (
            <div
              key={c.key}
              className={colors.bar}
              style={{ width: `${Math.max(0, c.contribution) * 100}%`, opacity: 0.4 + c.weight }}
              title={`${c.label}: raw ${formatScore(c.raw, 2)}, weight ${formatPercent(c.weight)}`}
            />
          ))}
        </div>
        <dl className="grid grid-cols-1 gap-x-4 gap-y-1.5 text-xs sm:grid-cols-2">
          {components.map((c) => (
            <div key={c.key} className="flex items-center justify-between gap-2">
              <dt className="text-slate-500 dark:text-slate-400">{c.label}</dt>
              <dd className="tabular-nums text-slate-700 dark:text-slate-200">
                raw {formatScore(c.raw, 2)} · weight {formatPercent(c.weight)}
              </dd>
            </div>
          ))}
        </dl>
      </div>
    </Card>
  );
}

// --- 3. Three things to know ------------------------------------------------

function ThreeThingsCard({ items, repoId }: { items: PassportFirstPrItem[]; repoId: string }) {
  return (
    <Card title="Three things to know" subtitle="The most actionable facts this analysis surfaced">
      {items.length === 0 ? (
        <p className="text-sm text-slate-400 dark:text-slate-500">
          Nothing stood out sharply enough to flag here.
        </p>
      ) : (
        <ul className="flex flex-col gap-3">
          {items.map((item) => (
            <li key={item.code} className="flex items-start justify-between gap-3">
              <p className="text-sm text-slate-700 dark:text-slate-200">
                {FIRST_PR_COPY[item.code](item.params)}
              </p>
              <Link
                to={`/repos/${repoId}/${FIRST_PR_LINK[item.code]}`}
                className="shrink-0 text-xs font-medium text-indigo-600 hover:underline dark:text-indigo-400"
              >
                View →
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

// --- 4. Scale and cadence ---------------------------------------------------

function ScaleAndCadenceCard({ data }: { data: RepoPassportData }) {
  const { scale, cadence } = data;
  // No backend endpoint returns a real commit-count time series (only these
  // three cumulative recency windows), so a literal "lifetime sparkline"
  // would have to fabricate intermediate data points -- something this
  // product's whole premise forbids. This bar chart shows exactly the real
  // numbers available instead of inventing a false level of detail; see
  // plan/STATE.md's session 08 entry for the full reasoning.
  const cadenceBars = [
    { window: "Last 30d", commits: cadence.commits_last_30d },
    { window: "Last 90d", commits: cadence.commits_last_90d },
    { window: "Last 365d", commits: cadence.commits_last_365d },
  ];

  return (
    <Card title="Scale and cadence">
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
                tick={{ fontSize: 11 }}
                axisLine={false}
                tickLine={false}
              />
              <Tooltip formatter={(value) => [`${value} commits`, ""]} />
              <Bar dataKey="commits" fill={CADENCE_BAR_COLOR} radius={3} barSize={14} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
      {cadence.longest_gap_days > 0 ? (
        <p className="mt-3 text-xs text-slate-400 dark:text-slate-500">
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
      <dt className="text-slate-400 dark:text-slate-500">{label}</dt>
      <dd className="text-lg font-semibold text-slate-900 dark:text-slate-100">
        {value.toLocaleString()}
      </dd>
    </div>
  );
}

// --- 5. Team shape -----------------------------------------------------------

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
  // is the one extra fetch on this page beyond usePassport (Known Hazard
  // #6 is about not re-fetching what passport ALREADY contains; the
  // removal sequence genuinely isn't in that payload).
  const truckFactor = useTruckFactor(repoId, share);

  return (
    <Card title="Team shape">
      <div className="flex flex-col gap-4">
        <div className="flex items-center gap-6">
          <div>
            <p className="text-3xl font-semibold tabular-nums text-slate-900 dark:text-slate-100">
              {team.truck_factor}
            </p>
            <p className="text-xs text-slate-400 dark:text-slate-500">Truck factor</p>
          </div>
          <dl className="grid grid-cols-3 gap-4 text-sm">
            <Stat label="Active" value={team.active_contributors} />
            <Stat label="Stale" value={team.stale_contributors} />
            <div>
              <dt className="text-slate-400 dark:text-slate-500">Bot commits</dt>
              <dd className="text-lg font-semibold text-slate-900 dark:text-slate-100">
                {formatPercent(team.bot_commit_ratio)}
              </dd>
            </div>
          </dl>
        </div>

        {truckFactor.data?.kind === "data" && truckFactor.data.data.removal_order.length > 0 ? (
          <div>
            <p className="mb-1.5 text-xs font-medium text-slate-500 dark:text-slate-400">
              Removal sequence — this project's own knowledge-risk measure, not an individual
              ranking
            </p>
            <ol className="flex flex-wrap items-center gap-1.5 text-xs text-slate-600 dark:text-slate-300">
              {truckFactor.data.data.removal_order.slice(0, 5).map((step, i) => (
                <li key={step.contributor_id} className="flex items-center gap-1.5">
                  {i > 0 ? <span className="text-slate-300 dark:text-slate-600">→</span> : null}
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
            <p className="mb-1.5 text-xs font-medium text-slate-500 dark:text-slate-400">
              Top contributors by share of commits
            </p>
            <ul className="flex flex-col gap-1.5">
              {team.top_contributors.map((c) => (
                <li key={c.name} className="flex items-center gap-2">
                  <ContributorChip name={c.name} isStale={c.is_stale} />
                  <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
                    <div
                      className="h-full rounded-full bg-indigo-500"
                      style={{ width: `${Math.round(c.share * 100)}%` }}
                    />
                  </div>
                  <span className="w-10 shrink-0 text-right text-xs tabular-nums text-slate-500 dark:text-slate-400">
                    {formatPercent(c.share)}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>
    </Card>
  );
}

// --- 6. Shape ----------------------------------------------------------------

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
  // `evidence` rule string Part C.6 asks to show verbatim, which only the
  // dedicated /entry-points endpoint returns.
  const entryPoints = useEntryPoints(repoId, share);
  const evidenceByPath = useMemo(() => {
    if (entryPoints.data?.kind !== "data") return new Map<string, string>();
    return new Map(entryPoints.data.data.entry_points.map((e) => [e.file_path, e.evidence]));
  }, [entryPoints.data]);

  return (
    <Card title="Shape" subtitle={`Modularity ${formatScore(shape.modularity, 2)}`}>
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <div>
          <p className="mb-1.5 text-xs font-medium text-slate-500 dark:text-slate-400">
            Subsystems
          </p>
          <ul className="flex flex-col gap-2">
            {shape.subsystems.map((s) => (
              <li key={s.label} className="flex items-center gap-2 text-sm">
                <SubsystemBadge label={s.label} />
                <span className="text-xs text-slate-400 dark:text-slate-500">
                  {s.file_count} files
                </span>
                <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
                  <div
                    className="h-full rounded-full bg-emerald-500"
                    style={{ width: `${Math.round(s.cohesion * 100)}%` }}
                  />
                </div>
                <span className="w-10 shrink-0 text-right text-xs tabular-nums text-slate-500 dark:text-slate-400">
                  {formatPercent(s.cohesion)}
                </span>
              </li>
            ))}
          </ul>
        </div>

        <div>
          <p className="mb-1.5 text-xs font-medium text-slate-500 dark:text-slate-400">
            Entry points
          </p>
          <ul className="flex flex-col gap-2 text-sm">
            {shape.entry_points.map((e) => (
              <li key={e.path} className="flex flex-col gap-0.5">
                <div className="flex items-center gap-2">
                  <span className="truncate font-mono text-xs text-slate-700 dark:text-slate-300">
                    {e.path}
                  </span>
                  <span className="shrink-0 rounded-full bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium text-slate-500 dark:bg-slate-800 dark:text-slate-400">
                    {ENTRY_POINT_KIND_COPY[e.kind]()}
                  </span>
                </div>
                {evidenceByPath.get(e.path) ? (
                  <p className="text-xs text-slate-400 dark:text-slate-500">
                    {evidenceByPath.get(e.path)}
                  </p>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      </div>

      {hotspots.top_risk_files.length > 0 ? (
        <div className="mt-4 border-t border-slate-100 pt-4 dark:border-slate-800">
          <p className="mb-1.5 text-xs font-medium text-slate-500 dark:text-slate-400">
            Top risk files · {formatPercent(hotspots.churn_concentration)} of churn is concentrated
            in the busiest 10% of files
          </p>
          <ul className="flex flex-col gap-1 text-xs">
            {hotspots.top_risk_files.map((f) => (
              <li key={f.path} className="flex items-center justify-between gap-2">
                <span className="truncate font-mono text-slate-600 dark:text-slate-300">
                  {f.path}
                </span>
                <span className="shrink-0 tabular-nums text-slate-400 dark:text-slate-500">
                  {formatScore(f.risk_score)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </Card>
  );
}

// --- 7. Health ---------------------------------------------------------------

function HealthCard({ data, calibration }: { data: RepoPassportData; calibration: string }) {
  const { health } = data;

  return (
    <Card title="Health" subtitle="Composite of risk, cycles, and hidden dependencies">
      <div className="flex flex-col items-center gap-4 sm:flex-row sm:items-start sm:justify-around">
        <ScoreGauge score={health.score} />
        <div className="flex flex-col gap-3">
          <HeuristicNote calibration={calibration} />
          <dl className="grid grid-cols-3 gap-4 text-center text-xs">
            <div>
              <dt className="text-slate-400 dark:text-slate-500">High-risk files</dt>
              <dd className="font-medium text-slate-700 dark:text-slate-200">
                {formatPercent(health.high_risk_ratio)}
              </dd>
            </div>
            <div>
              <dt className="text-slate-400 dark:text-slate-500">Cycles</dt>
              <dd className="font-medium text-slate-700 dark:text-slate-200">
                {health.cycle_count}
              </dd>
            </div>
            <div>
              <dt className="text-slate-400 dark:text-slate-500">Hidden deps</dt>
              <dd className="font-medium text-slate-700 dark:text-slate-200">
                {health.hidden_dependency_count}
              </dd>
            </div>
          </dl>
        </div>
      </div>
    </Card>
  );
}
