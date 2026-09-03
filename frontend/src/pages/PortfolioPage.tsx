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
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { EmptyState } from "../components/EmptyState";
import { ErrorState } from "../components/ErrorState";
import { HonestyNote } from "../components/HonestyNote";
import { LoadingState } from "../components/LoadingState";
import { formatScore, healthColor } from "../lib/format";
import { colorForSubsystem } from "../lib/subsystemColors";
import { rechartsTheme } from "../lib/chartTheme";

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
      eyebrow="One GitHub URL per line -- up to 50 at a time. Submissions are queued and run a few at a time, never all at once."
    >
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={"https://github.com/owner/repo-one\nhttps://github.com/owner/repo-two"}
        rows={4}
        className="w-full rounded-sm border border-border-interactive bg-bg-elevated px-3 py-2 text-xs text-text placeholder:text-text-muted"
      />
      <div className="mt-3 flex items-center gap-3">
        <Button
          variant="primary"
          size="sm"
          disabled={urls.length === 0 || urls.length > 50 || submit.isPending}
          onClick={() => submit.mutate(urls, { onSuccess: () => setText("") })}
        >
          {submit.isPending ? "Queuing…" : `Queue ${urls.length || ""} repositories`}
        </Button>
        {urls.length > 50 ? (
          <span className="text-xs text-danger">Max 50 URLs per batch.</span>
        ) : null}
      </div>
      {submit.data ? (
        <div className="mt-3 flex flex-col gap-1 text-xs">
          {submit.data.queued.length > 0 ? (
            <p className="text-diverging-improve">Queued {submit.data.queued.length}.</p>
          ) : null}
          {submit.data.skipped.length > 0 ? (
            <p className="text-text-muted">
              Skipped {submit.data.skipped.length} (already analyzed at the current commit).
            </p>
          ) : null}
          {submit.data.errors.length > 0 ? (
            <div className="text-danger">
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
        <p className="mt-2 text-xs text-danger">
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
      eyebrow={`Up to ${queue.data.max_concurrent_runs} run at once, round-robin across every user's queue -- not first-come-first-served.`}
    >
      <ul className="flex flex-col gap-2 text-xs">
        {queue.data.items.map((item) => (
          <li key={item.run_id} className="flex items-center justify-between gap-3">
            <span className="truncate text-text-muted">{item.repo_url}</span>
            <span className="shrink-0 text-text-muted">
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
      eyebrow="Lines added per year, by language -- a skill timeline, not a snapshot of current LOC."
    >
      <div className="h-56 w-full">
        <ResponsiveContainer>
          <AreaChart data={rows}>
            <CartesianGrid {...rechartsTheme.grid} />
            <XAxis
              dataKey="year"
              tick={rechartsTheme.axis.tick}
              stroke={rechartsTheme.axis.stroke}
            />
            <YAxis tick={rechartsTheme.axis.tick} stroke={rechartsTheme.axis.stroke} />
            <Tooltip {...rechartsTheme.tooltip} />
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
    <Card title="Pooled distributions">
      {/* This is the one genuine overclaim risk in this product: a
          corpus-relative comparison (the repo-scoped Benchmark tab) sits
          one surface away, and the two must never be conflated. This
          label -- rendered verbatim from the API -- is what keeps them
          apart. */}
      <HonestyNote variant="scope-limitation" text={label} />
      <div className="mt-3 flex flex-col gap-3">
        {DISTRIBUTION_METRICS.map(({ key, label: metricLabel }) => {
          const dist = distributions[key];
          if (!dist || dist.summary.count === 0) return null;
          const { min, median, max } = dist.summary;
          const range = max - min || 1;
          const highlighted = highlightRepoId ? dist.by_repo[highlightRepoId] : undefined;
          return (
            <div key={key}>
              <div className="mb-1 flex items-center justify-between text-xs">
                <span className="text-text-muted">{metricLabel}</span>
                <span className="tabular-nums text-text-muted">
                  {formatScore(min, 2)} – {formatScore(max, 2)} (median {formatScore(median, 2)})
                </span>
              </div>
              <div className="relative h-2 rounded-full bg-bg-inset">
                <div
                  className="absolute top-0 h-2 w-0.5 bg-border-strong"
                  style={{ left: `${((median - min) / range) * 100}%` }}
                />
                {highlighted != null ? (
                  <div
                    className="absolute -top-0.5 h-3 w-1 rounded-full bg-accent"
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

/** `/portfolio` (UI rebuild session 4, Part E) -- cross-repository pooled
 * view. Logged-out visitors see a plain empty state that makes NO
 * request (`usePortfolio`'s `enabled` flag stays false until `useMe()`
 * resolves a real user). */
export function PortfolioPage() {
  const me = useMe();
  const myRepos = useMyRepos(1, 100);
  const portfolio = usePortfolio(Boolean(me.data));
  const [highlightRepoId, setHighlightRepoId] = useState<string | null>(null);

  // The h1 stays on screen in every state -- accessibility sweep,
  // `page-has-heading-one`: this page used to return early with
  // LoadingState/EmptyState/ErrorState alone (none of which carry a
  // page-level heading), leaving a logged-out visitor's Portfolio with
  // zero level-one headings.
  if (me.isPending) {
    return (
      <div className="flex flex-col gap-6">
        <h1 className="font-display text-2xl text-text-heading">Portfolio</h1>
        <LoadingState label="Loading…" />
      </div>
    );
  }
  if (!me.data) {
    return (
      <div className="flex flex-col gap-6">
        <h1 className="font-display text-2xl text-text-heading">Portfolio</h1>
        <EmptyState
          title="Log in to use your portfolio"
          message="Connect a GitHub account to analyze several repositories at once and see metrics pooled across all of them."
        />
      </div>
    );
  }

  if (portfolio.isPending) {
    return (
      <div className="flex flex-col gap-6">
        <h1 className="font-display text-2xl text-text-heading">Portfolio</h1>
        <LoadingState label="Loading your portfolio…" />
      </div>
    );
  }
  if (portfolio.isError) {
    return (
      <div className="flex flex-col gap-6">
        <h1 className="font-display text-2xl text-text-heading">Portfolio</h1>
        <ErrorState error={portfolio.error} onRetry={() => void portfolio.refetch()} />
      </div>
    );
  }
  const data = portfolio.data;

  return (
    <div className="flex flex-col gap-6">
      <h1 className="font-display text-2xl text-text-heading">Portfolio</h1>

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
                <p className="text-xl font-semibold tabular-nums text-text">{value}</p>
                <p className="text-xs text-text-muted">{label}</p>
              </Card>
            ))}
          </div>

          <LanguageActivityChart activity={data.language_activity_by_year} />

          <Card
            title="Your repositories"
            eyebrow="Click a repository to mark it in the distributions below."
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
                        ? "border-accent bg-accent-bg"
                        : "border-border hover:bg-bg-inset"
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <Link
                        to={`/repos/${repo.id}/overview`}
                        onClick={(e) => e.stopPropagation()}
                        className="truncate font-medium text-text hover:underline"
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
                      <p className="mt-1 text-text-muted">
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
            eyebrow="Dependencies used by more than one of your repositories."
          >
            {data.cross_repo_patterns.shared_dependencies.length === 0 ? (
              <p className="text-xs text-text-muted">
                No dependency appears in more than one of your repositories yet.
              </p>
            ) : (
              <ul className="flex flex-col gap-1 text-xs">
                {data.cross_repo_patterns.shared_dependencies.map((d) => (
                  <li key={`${d.ecosystem}:${d.package_name}`} className="flex justify-between">
                    <span className="text-text-muted">
                      {d.package_name} <span className="text-text-muted">({d.ecosystem})</span>
                    </span>
                    <span className="text-text-muted">{d.repository_count} repositories</span>
                  </li>
                ))}
              </ul>
            )}
            {data.cross_repo_patterns.vulnerable_shared_dependencies.length > 0 ? (
              <div className="mt-3 border-t border-border pt-3">
                <p className="mb-1 text-xs font-medium text-danger">Vulnerable and shared</p>
                <ul className="flex flex-col gap-1 text-xs">
                  {data.cross_repo_patterns.vulnerable_shared_dependencies.map((d) => (
                    <li key={`${d.ecosystem}:${d.package_name}`} className="flex justify-between">
                      <span className="text-text-muted">
                        {d.package_name} <span className="text-text-muted">({d.ecosystem})</span>
                      </span>
                      <span className="text-danger">
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
                <dt className="text-text-muted">Average health</dt>
                <dd className="font-medium text-text-muted">
                  {data.portfolio_health.average_health_score != null
                    ? formatScore(data.portfolio_health.average_health_score, 0)
                    : "—"}
                </dd>
              </div>
              <div>
                <dt className="text-text-muted">Dormant</dt>
                <dd className="font-medium text-text-muted">
                  {data.portfolio_health.dormant_repository_ids.length}
                </dd>
              </div>
              <div>
                <dt className="text-text-muted">Truck factor 1</dt>
                <dd className="font-medium text-text-muted">
                  {data.portfolio_health.truck_factor_one_repository_ids.length}
                </dd>
              </div>
              <div>
                <dt className="text-text-muted">Unresolved high-severity</dt>
                <dd className="font-medium text-text-muted">
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
