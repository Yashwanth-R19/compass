import { Link } from "react-router-dom";
import { useMyRepos, useSubmitRepo } from "../api/hooks";
import { Card } from "../components/Card";
import { EmptyState } from "../components/EmptyState";
import { ErrorState } from "../components/ErrorState";
import { LoadingState } from "../components/LoadingState";
import { formatScore, healthColor } from "../lib/format";

const RUN_STATUS_LABEL: Record<string, string> = {
  running: "Analyzing…",
  ready: "Ready",
  failed: "Failed",
  superseded: "Ready",
};

export function DashboardPage() {
  const { data, isPending, isError, error, refetch } = useMyRepos();
  const resubmit = useSubmitRepo();

  if (isPending) return <LoadingState label="Loading your repositories…" />;
  if (isError) return <ErrorState error={error} onRetry={() => void refetch()} />;

  if (data.repos.length === 0) {
    return (
      <EmptyState
        title="No repositories yet"
        message="Repositories you analyze while logged in show up here."
        action={
          <Link
            to="/"
            className="rounded-md bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-700"
          >
            Analyze a repo
          </Link>
        }
      />
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
        Your repositories
      </h1>
      <div className="grid gap-3 sm:grid-cols-2">
        {data.repos.map((repo) => {
          const health = repo.health_score !== null ? healthColor(repo.health_score) : null;
          return (
            <Card key={repo.id}>
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <Link
                    to={`/repos/${repo.id}/overview`}
                    className="truncate text-sm font-medium text-slate-900 hover:underline dark:text-slate-100"
                  >
                    {repo.owner}/{repo.name}
                  </Link>
                  <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                    {repo.is_private ? "Private" : "Public"} ·{" "}
                    {repo.latest_run_status
                      ? (RUN_STATUS_LABEL[repo.latest_run_status] ?? repo.latest_run_status)
                      : "No runs yet"}
                  </p>
                  {repo.analyzed_at ? (
                    <p className="mt-0.5 text-xs text-slate-400 dark:text-slate-500">
                      Last analyzed {new Date(repo.analyzed_at).toLocaleString()}
                    </p>
                  ) : null}
                </div>
                {health ? (
                  <span className={`shrink-0 text-sm font-semibold tabular-nums ${health.text}`}>
                    {formatScore(repo.health_score ?? 0, 0)}
                  </span>
                ) : null}
              </div>
              <button
                type="button"
                disabled={resubmit.isPending}
                onClick={() => resubmit.mutate(repo.url)}
                className="mt-3 rounded-md border border-slate-200 px-2.5 py-1 text-xs font-medium text-slate-600 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
              >
                Re-analyze
              </button>
            </Card>
          );
        })}
      </div>
    </div>
  );
}
