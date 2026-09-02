import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  useMe,
  useMyRepos,
  usePortfolio,
  usePortfolioQueue,
  useSubmitPortfolio,
} from "../api/hooks";
import { Card } from "../components/Card";
import { EmptyState } from "../components/EmptyState";
import { ErrorState } from "../components/ErrorState";
import { LoadingState } from "../components/LoadingState";
import { formatScore, healthColor } from "../lib/format";
import { colorForSubsystem } from "../lib/subsystemColors";

const DISTRIBUTION_METRICS: { key: string; label: string }[] = [
  { key: "risk_score", label: "Risk score" },
  { key: "complexity", label: "Complexity" },
  { key: "max_coupling_degree", label: "Max coupling degree" },
  { key: "health_score", label: "Health score" },
  { key: "onboarding_difficulty", label: "Onboarding difficulty" },
];

function SubmitForm() {
  const submit = useSubmitPortfolio();
  const [text, setText] = useState("");

  const urls = text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);

  return (
    <Card
      title="Analyze several repositories"
      subtitle="One GitHub URL per line -- up to 50 at a time. Submissions are queued and run a few at a time, never all at once."
    >
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={"https://github.com/owner/repo-one\nhttps://github.com/owner/repo-two"}
        rows={4}
        className="w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-xs text-slate-800 placeholder:text-slate-400 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
      />
      <div className="mt-3 flex items-center gap-3">
        <button
          type="button"
          disabled={urls.length === 0 || urls.length > 50 || submit.isPending}
          onClick={() => submit.mutate(urls, { onSuccess: () => setText("") })}
          className="rounded-md bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {submit.isPending ? "Queuing…" : `Queue ${urls.length || ""} repositories`}
        </button>
        {urls.length > 50 ? (
          <span className="text-xs text-red-600 dark:text-red-400">Max 50 URLs per batch.</span>
        ) : null}
      </div>
      {submit.data ? (
        <div className="mt-3 flex flex-col gap-1 text-xs">
          {submit.data.queued.length > 0 ? (
            <p className="text-emerald-600 dark:text-emerald-400">
              Queued {submit.data.queued.length}.
            </p>
          ) : null}
          {submit.data.skipped.length > 0 ? (
            <p className="text-slate-500 dark:text-slate-400">
              Skipped {submit.data.skipped.length} (already analyzed at the current commit).
            </p>
          ) : null}
          {submit.data.errors.length > 0 ? (
            <div className="text-red-600 dark:text-red-400">
              {submit.data.errors.map((e) => (
                <p key={e.url}>
                  {e.url}: {e.reason}
                </p>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
      {submit.isError ? (
        <p className="mt-2 text-xs text-red-600 dark:text-red-400">
          {submit.error instanceof Error ? submit.error.message : "Failed to queue repositories."}
        </p>
      ) : null}
    </Card>
  );
}

function QueueStatus() {
  const queue = usePortfolioQueue(true);
  if (queue.isPending || !queue.data || queue.data.items.length === 0) return null;

  return (
    <Card
      title="Your queue"
      subtitle={`Up to ${queue.data.max_concurrent_runs} run at once, round-robin across every user's queue -- not first-come-first-served.`}
    >
      <ul className="flex flex-col gap-2 text-xs">
        {queue.data.items.map((item) => (
          <li key={item.run_id} className="flex items-center justify-between gap-3">
            <span className="truncate text-slate-700 dark:text-slate-300">{item.repo_url}</span>
            <span className="shrink-0 text-slate-500 dark:text-slate-400">
              {item.status === "running"
                ? "Analyzing…"
                : item.position != null
                  ? `Queued, ${item.position - 1} ahead of you` +
                    (item.estimated_wait_seconds
                      ? ` (~${Math.round(item.estimated_wait_seconds / 60)}m)`
                      : "")
                  : "Queued"}
            </span>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function LanguageActivityChart({ activity }: { activity: Record<string, Record<string, number>> }) {
  const years = Object.keys(activity).sort();
  const languages = useMemo(() => {
    const set = new Set<string>();
    for (const byLang of Object.values(activity)) {
      for (const lang of Object.keys(byLang)) set.add(lang);
    }
    return [...set].sort();
  }, [activity]);

  if (years.length === 0) return null;

  const rows = years.map((year) => {
    const row: Record<string, number | string> = { year };
    for (const lang of languages) row[lang] = activity[year]?.[lang] ?? 0;
    return row;
  });

  return (
    <Card
      title="Language activity over time"
      subtitle="Lines added per year, by language -- a skill timeline, not a snapshot of current LOC."
    >
      <div className="h-56 w-full">
        <ResponsiveContainer>
          <AreaChart data={rows}>
            <CartesianGrid
              strokeDasharray="3 3"
              className="stroke-slate-200 dark:stroke-slate-800"
            />
            <XAxis dataKey="year" tick={{ fontSize: 11 }} />
            <YAxis tick={{ fontSize: 11 }} />
            <Tooltip />
            {languages.map((lang) => (
              <Area
                key={lang}
                type="monotone"
                dataKey={lang}
                stackId="1"
                stroke={colorForSubsystem(lang)}
                fill={colorForSubsystem(lang)}
                fillOpacity={0.6}
              />
            ))}
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </Card>
  );
}

function DistributionCard({
  distributions,
  label,
  highlightRepoId,
}: {
  distributions: Record<
    string,
    {
      summary: { min: number; median: number; max: number; count: number };
      by_repo: Record<string, number>;
    }
  >;
  label: string;
  highlightRepoId: string | null;
}) {
  return (
    <Card title="Pooled distributions" subtitle={label}>
      <div className="flex flex-col gap-3">
        {DISTRIBUTION_METRICS.map(({ key, label: metricLabel }) => {
          const dist = distributions[key];
          if (!dist || dist.summary.count === 0) return null;
          const { min, median, max } = dist.summary;
          const range = max - min || 1;
          const highlighted = highlightRepoId ? dist.by_repo[highlightRepoId] : undefined;
          return (
            <div key={key}>
              <div className="mb-1 flex items-center justify-between text-xs">
                <span className="text-slate-600 dark:text-slate-300">{metricLabel}</span>
                <span className="tabular-nums text-slate-400 dark:text-slate-500">
                  {formatScore(min, 2)} – {formatScore(max, 2)} (median {formatScore(median, 2)})
                </span>
              </div>
              <div className="relative h-2 rounded-full bg-slate-100 dark:bg-slate-800">
                <div
                  className="absolute top-0 h-2 w-0.5 bg-slate-400 dark:bg-slate-500"
                  style={{ left: `${((median - min) / range) * 100}%` }}
                />
                {highlighted != null ? (
                  <div
                    className="absolute -top-0.5 h-3 w-1 rounded-full bg-indigo-500"
                    style={{ left: `${((highlighted - min) / range) * 100}%` }}
                    title={`This repository: ${formatScore(highlighted, 2)}`}
                  />
                ) : null}
              </div>
            </div>
          );
        })}
      </div>
    </Card>
  );
}

export function PortfolioPage() {
  const me = useMe();
  const myRepos = useMyRepos(1, 100);
  const portfolio = usePortfolio(Boolean(me.data));
  const [highlightRepoId, setHighlightRepoId] = useState<string | null>(null);

  if (me.isPending) return <LoadingState label="Loading…" />;
  if (!me.data) {
    return (
      <EmptyState
        title="Log in to use your portfolio"
        message="Connect a GitHub account to analyze several repositories at once and see metrics pooled across all of them."
      />
    );
  }

  if (portfolio.isPending) return <LoadingState label="Loading your portfolio…" />;
  if (portfolio.isError) {
    return <ErrorState error={portfolio.error} onRetry={() => void portfolio.refetch()} />;
  }
  const data = portfolio.data;

  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-lg font-semibold text-slate-900 dark:text-slate-100">Portfolio</h1>

      <SubmitForm />
      <QueueStatus />

      {data.repository_count === 0 ? (
        <EmptyState
          title="No analyzed repositories yet"
          message="Repositories with a completed analysis, owned by your account, show up here."
        />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
            {[
              ["Repositories", data.totals.repositories],
              ["Files", data.totals.files.toLocaleString()],
              ["Lines of code", data.totals.loc.toLocaleString()],
              ["Commits", data.totals.commits.toLocaleString()],
              ["Contributors", data.totals.contributors],
            ].map(([label, value]) => (
              <Card key={label as string} className="text-center">
                <p className="text-xl font-semibold tabular-nums text-slate-900 dark:text-slate-100">
                  {value}
                </p>
                <p className="text-xs text-slate-500 dark:text-slate-400">{label}</p>
              </Card>
            ))}
          </div>

          <LanguageActivityChart activity={data.language_activity_by_year} />

          <Card
            title="Your repositories"
            subtitle="Click a repository to mark it in the distributions below."
          >
            <div className="grid gap-3 sm:grid-cols-2">
              {myRepos.data?.repos.map((repo) => {
                const health = repo.health_score != null ? healthColor(repo.health_score) : null;
                const difficulty =
                  data.pooled_distributions.onboarding_difficulty?.by_repo[repo.id];
                return (
                  <button
                    key={repo.id}
                    type="button"
                    onClick={() => setHighlightRepoId(repo.id === highlightRepoId ? null : repo.id)}
                    className={`rounded-lg border p-3 text-left text-xs transition-colors ${
                      highlightRepoId === repo.id
                        ? "border-indigo-400 bg-indigo-50 dark:border-indigo-500 dark:bg-indigo-500/10"
                        : "border-slate-200 hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-800/50"
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <Link
                        to={`/repos/${repo.id}/onboard/passport`}
                        onClick={(e) => e.stopPropagation()}
                        className="truncate font-medium text-slate-800 hover:underline dark:text-slate-100"
                      >
                        {repo.owner}/{repo.name}
                      </Link>
                      {health ? (
                        <span className={`shrink-0 font-semibold tabular-nums ${health.text}`}>
                          {formatScore(repo.health_score ?? 0, 0)}
                        </span>
                      ) : null}
                    </div>
                    {difficulty != null ? (
                      <p className="mt-1 text-slate-400 dark:text-slate-500">
                        Onboarding difficulty {formatScore(difficulty, 0)}
                      </p>
                    ) : null}
                  </button>
                );
              })}
            </div>
          </Card>

          <DistributionCard
            distributions={data.pooled_distributions}
            label={data.pooled_distribution_label}
            highlightRepoId={highlightRepoId}
          />

          <Card
            title="Shared across repositories"
            subtitle="Dependencies used by more than one of your repositories."
          >
            {data.cross_repo_patterns.shared_dependencies.length === 0 ? (
              <p className="text-xs text-slate-400 dark:text-slate-500">
                No dependency appears in more than one of your repositories yet.
              </p>
            ) : (
              <ul className="flex flex-col gap-1 text-xs">
                {data.cross_repo_patterns.shared_dependencies.map((d) => (
                  <li key={`${d.ecosystem}:${d.package_name}`} className="flex justify-between">
                    <span className="text-slate-700 dark:text-slate-300">
                      {d.package_name} <span className="text-slate-400">({d.ecosystem})</span>
                    </span>
                    <span className="text-slate-400 dark:text-slate-500">
                      {d.repository_count} repositories
                    </span>
                  </li>
                ))}
              </ul>
            )}
            {data.cross_repo_patterns.vulnerable_shared_dependencies.length > 0 ? (
              <div className="mt-3 border-t border-slate-100 pt-3 dark:border-slate-800">
                <p className="mb-1 text-xs font-medium text-red-600 dark:text-red-400">
                  Vulnerable and shared
                </p>
                <ul className="flex flex-col gap-1 text-xs">
                  {data.cross_repo_patterns.vulnerable_shared_dependencies.map((d) => (
                    <li key={`${d.ecosystem}:${d.package_name}`} className="flex justify-between">
                      <span className="text-slate-700 dark:text-slate-300">
                        {d.package_name} <span className="text-slate-400">({d.ecosystem})</span>
                      </span>
                      <span className="text-red-500 dark:text-red-400">
                        {d.repository_count} repositories · {d.max_severity}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </Card>

          <Card title="Portfolio health">
            <dl className="grid grid-cols-2 gap-3 text-xs sm:grid-cols-4">
              <div>
                <dt className="text-slate-400 dark:text-slate-500">Average health</dt>
                <dd className="font-medium text-slate-700 dark:text-slate-200">
                  {data.portfolio_health.average_health_score != null
                    ? formatScore(data.portfolio_health.average_health_score, 0)
                    : "—"}
                </dd>
              </div>
              <div>
                <dt className="text-slate-400 dark:text-slate-500">Dormant</dt>
                <dd className="font-medium text-slate-700 dark:text-slate-200">
                  {data.portfolio_health.dormant_repository_ids.length}
                </dd>
              </div>
              <div>
                <dt className="text-slate-400 dark:text-slate-500">Truck factor 1</dt>
                <dd className="font-medium text-slate-700 dark:text-slate-200">
                  {data.portfolio_health.truck_factor_one_repository_ids.length}
                </dd>
              </div>
              <div>
                <dt className="text-slate-400 dark:text-slate-500">Unresolved high-severity</dt>
                <dd className="font-medium text-slate-700 dark:text-slate-200">
                  {data.portfolio_health.repositories_with_unresolved_high_severity_ids.length}
                </dd>
              </div>
            </dl>
          </Card>
        </>
      )}
    </div>
  );
}
