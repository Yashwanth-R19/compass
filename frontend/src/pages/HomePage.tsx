import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMe, useMyGithubRepos, useSubmitRepo } from "../api/hooks";
import { ApiError, RateLimitedError, githubLoginUrl } from "../api/client";
import { Button } from "../components/ui/Button";
import { Input } from "../components/ui/Input";
import { Badge } from "../components/ui/Badge";

/**
 * Session 16 populates real curated example repositories here (their own
 * repo id + a one-line description of what's interesting about the
 * analysis). Until then this renders as a labelled, honestly-empty slot --
 * never fabricated data, and never silently absent either, per this
 * session's own "not computed yet" vs. "computed and empty" discipline
 * applied to a fixture set instead of a live query.
 */
const SHOWCASE_SLOTS = 3;

export function HomePage() {
  const [url, setUrl] = useState("");
  const navigate = useNavigate();

  const me = useMe();
  const submitRepo = useSubmitRepo();
  const hasRepoScope = Boolean(me.data?.has_repo_scope);
  const githubRepos = useMyGithubRepos(hasRepoScope);

  function submitUrl(targetUrl: string) {
    if (!targetUrl.trim()) return;
    // Navigate the instant the repo/job rows exist -- RepoLayout takes over
    // from there and polls /repos/{id}/status, which is what makes the
    // stage pills appear within ~2 seconds instead of staring at this page
    // until the whole analysis finishes (Phase 02 progressive reveal).
    submitRepo.mutate(targetUrl.trim(), {
      onSuccess: (res) => navigate(`/repos/${res.repo_id}/overview`),
    });
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    submitUrl(url);
  }

  const submitError = submitRepo.error;

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-12 py-12">
      <div className="flex flex-col items-center gap-6 text-center">
        <div>
          <p className="cp-label">Deterministic repository analysis</p>
          <h1 className="mt-2 font-mono text-3xl font-semibold tracking-tight text-ink">Compass</h1>
          <p className="mx-auto mt-3 max-w-lg text-sm text-ink-muted">
            Mines a repository&apos;s full commit history for hidden change-coupling, calibrated
            risk, and architecture — computed the same way every time, never guessed by a model
            reading the current tree.
          </p>
        </div>

        <form onSubmit={handleSubmit} className="flex w-full max-w-xl flex-col gap-2 sm:flex-row">
          <Input
            type="text"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://github.com/owner/repo"
            disabled={submitRepo.isPending}
            className="flex-1 font-mono"
          />
          <Button type="submit" variant="primary" disabled={submitRepo.isPending}>
            {submitRepo.isPending ? "Submitting…" : "Analyze"}
          </Button>
        </form>

        {submitError ? <SubmitErrorNotice error={submitError} /> : null}

        {me.data && !hasRepoScope ? (
          <p className="text-xs text-ink-muted">
            Want to analyze a private repository?{" "}
            <a
              href={githubLoginUrl("repo", "/")}
              className="font-medium text-signal hover:underline"
            >
              Connect private repositories
            </a>
            .
          </p>
        ) : null}
      </div>

      <section>
        <p className="cp-label mb-3">Showcase repositories</p>
        <div className="grid grid-cols-1 gap-px border border-border bg-border sm:grid-cols-3">
          {Array.from({ length: SHOWCASE_SLOTS }).map((_, i) => (
            <div key={i} className="flex min-h-28 flex-col justify-between bg-surface p-4">
              <span className="text-xs text-ink-faint">
                Reserved for a curated example analysis.
              </span>
              <span className="cp-label">Coming soon</span>
            </div>
          ))}
        </div>
      </section>

      {hasRepoScope ? (
        <section>
          <p className="cp-label mb-2">Or pick from your GitHub repositories</p>
          {githubRepos.isPending ? (
            <p className="text-xs text-ink-faint">Loading…</p>
          ) : githubRepos.isError ? (
            <p className="text-xs text-sev-high">
              {githubRepos.error instanceof ApiError
                ? githubRepos.error.message
                : "Couldn't load your GitHub repositories."}
            </p>
          ) : (
            <div className="max-h-56 overflow-y-auto border border-border">
              {githubRepos.data.repos.length === 0 ? (
                <p className="px-3 py-2 text-xs text-ink-faint">
                  No repositories found on your GitHub account.
                </p>
              ) : (
                githubRepos.data.repos.map((repo) => (
                  <button
                    key={repo.full_name}
                    type="button"
                    disabled={submitRepo.isPending}
                    onClick={() => submitUrl(`https://github.com/${repo.full_name}`)}
                    className="flex w-full items-center justify-between gap-2 border-b border-border px-3 py-2 text-left text-xs last:border-b-0 hover:bg-surface-2 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    <span className="truncate font-mono text-ink-muted">{repo.full_name}</span>
                    {repo.private ? <Badge tone="neutral">Private</Badge> : null}
                  </button>
                ))
              )}
              {githubRepos.data.truncated ? (
                <p className="px-3 py-2 text-[10px] text-ink-faint">
                  Showing your first 300 repositories, sorted by most recently pushed.
                </p>
              ) : null}
            </div>
          )}
        </section>
      ) : null}
    </div>
  );
}

function SubmitErrorNotice({ error }: { error: unknown }) {
  if (error instanceof RateLimitedError) {
    const resetLabel =
      error.retryAfterSeconds >= 60
        ? `${Math.ceil(error.retryAfterSeconds / 60)} minute${error.retryAfterSeconds >= 120 ? "s" : ""}`
        : `${error.retryAfterSeconds} second${error.retryAfterSeconds === 1 ? "" : "s"}`;
    return (
      <p className="text-sm text-conf-low">
        You&apos;ve hit the analysis limit for now. Try again in about {resetLabel}.
      </p>
    );
  }

  const message = error instanceof ApiError ? error.message : "Something went wrong.";
  return <p className="text-sm text-sev-high">{message}</p>;
}
