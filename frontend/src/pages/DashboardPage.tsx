import { Link } from "react-router-dom";
import { useDeleteRepo, useMyRepos, useSubmitRepo } from "../api/hooks";
import { Alert } from "../components/ui/Alert";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
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

/** `/dashboard` (UI rebuild session 4, Part E) -- the caller's own
 * repositories: status, last-analysed time, health score, a re-analyse
 * button, and the confirm-gated delete that's the UI half of the
 * per-user repository cap (a user already at MAX_REPOS_PER_USER frees a
 * slot by removing one of their own repos here). */
export function DashboardPage() {
  const { data, isPending, isError, error, refetch } = useMyRepos();
  const resubmit = useSubmitRepo();
  const deleteRepo = useDeleteRepo();

  // The h1 stays on screen in every state (loading/error/empty/populated)
  // -- accessibility sweep, `page-has-heading-one`: this page used to
  // return early with EmptyState/ErrorState alone, which have no page-level
  // heading of their own, leaving an anonymous or logged-out visitor's
  // Dashboard with zero level-one headings.
  return (
    <div className="flex flex-col gap-4">
      <h1 className="font-display text-2xl text-text-heading">Your repositories</h1>

      {isPending ? (
        <LoadingState label="Loading your repositories…" />
      ) : isError ? (
        <ErrorState error={error} onRetry={() => void refetch()} />
      ) : data.repos.length === 0 ? (
        <EmptyState
          title="No repositories yet"
          message="Repositories you analyze while logged in show up here."
          action={
            <Link to="/">
              <Button variant="primary" size="sm">
                Analyze a repo
              </Button>
            </Link>
          }
        />
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2">
            {data.repos.map((repo) => {
              const health = repo.health_score !== null ? healthColor(repo.health_score) : null;
              return (
                <Card key={repo.id}>
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <Link
                        to={`/repos/${repo.id}/overview`}
                        className="truncate text-sm font-medium text-text hover:underline"
                      >
                        {repo.owner}/{repo.name}
                      </Link>
                      <p className="mt-1 text-xs text-text-muted">
                        {repo.is_private ? "Private" : "Public"} ·{" "}
                        {repo.latest_run_status
                          ? (RUN_STATUS_LABEL[repo.latest_run_status] ?? repo.latest_run_status)
                          : "No runs yet"}
                      </p>
                      {repo.analyzed_at ? (
                        <p className="mt-0.5 text-xs text-text-muted">
                          Last analyzed {new Date(repo.analyzed_at).toLocaleString()}
                        </p>
                      ) : null}
                    </div>
                    {health ? (
                      <span
                        className={`shrink-0 text-sm font-semibold tabular-nums ${health.text}`}
                      >
                        {formatScore(repo.health_score ?? 0, 0)}
                      </span>
                    ) : null}
                  </div>
                  <div className="mt-3 flex items-center gap-2">
                    <Button
                      variant="secondary"
                      size="sm"
                      disabled={resubmit.isPending}
                      onClick={() => resubmit.mutate(repo.url)}
                    >
                      Re-analyze
                    </Button>
                    {/* A real, permanent removal (backend cascades through
                        every Facts/Insight row), so this asks for
                        confirmation first. */}
                    <Button
                      variant="danger"
                      size="sm"
                      disabled={deleteRepo.isPending}
                      onClick={() => {
                        if (
                          window.confirm(
                            `Remove ${repo.owner}/${repo.name}? This permanently deletes its analysis data.`,
                          )
                        ) {
                          deleteRepo.mutate(repo.id);
                        }
                      }}
                    >
                      Remove
                    </Button>
                  </div>
                </Card>
              );
            })}
          </div>
          {deleteRepo.isError ? (
            <Alert variant="danger">
              {deleteRepo.error instanceof Error
                ? deleteRepo.error.message
                : "Couldn't remove that repository."}
            </Alert>
          ) : null}
        </>
      )}
    </div>
  );
}
