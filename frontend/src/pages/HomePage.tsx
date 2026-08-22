import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMe, useMyGithubRepos, useSubmitRepo } from "../api/hooks";
import { ApiError, RateLimitedError, githubLoginUrl } from "../api/client";

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
    <div className="mx-auto flex max-w-xl flex-col items-center gap-8 py-16 text-center">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900 dark:text-slate-100">
          Compass
        </h1>
        <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">
          Mine a GitHub repository's full commit history for hidden change-coupling, calibrated
          risk, and architecture insight — computed deterministically, not guessed by an AI reading
          the current tree.
        </p>
      </div>

      <form onSubmit={handleSubmit} className="flex w-full flex-col gap-3 sm:flex-row">
        <input
          type="text"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://github.com/owner/repo"
          disabled={submitRepo.isPending}
          className="flex-1 rounded-md border border-slate-300 px-3 py-2 text-sm outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 disabled:bg-slate-100 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:disabled:bg-slate-800"
        />
        <button
          type="submit"
          disabled={submitRepo.isPending}
          className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {submitRepo.isPending ? "Submitting…" : "Analyze"}
        </button>
      </form>

      {submitError ? <SubmitErrorNotice error={submitError} /> : null}

      {me.data && !hasRepoScope ? (
        <p className="text-xs text-slate-500 dark:text-slate-400">
          Want to analyze a private repository?{" "}
          <a
            href={githubLoginUrl("repo", "/")}
            className="font-medium text-indigo-600 hover:underline dark:text-indigo-400"
          >
            Connect private repositories
          </a>
          .
        </p>
      ) : null}

      {hasRepoScope ? (
        <div className="w-full text-left">
          <p className="mb-2 text-xs font-medium text-slate-500 dark:text-slate-400">
            Or pick from your GitHub repositories
          </p>
          {githubRepos.isPending ? (
            <p className="text-xs text-slate-400 dark:text-slate-500">Loading…</p>
          ) : githubRepos.isError ? (
            <p className="text-xs text-red-600 dark:text-red-400">
              {githubRepos.error instanceof ApiError
                ? githubRepos.error.message
                : "Couldn't load your GitHub repositories."}
            </p>
          ) : (
            <div className="max-h-56 overflow-y-auto rounded-md border border-slate-200 dark:border-slate-800">
              {githubRepos.data.repos.length === 0 ? (
                <p className="px-3 py-2 text-xs text-slate-400 dark:text-slate-500">
                  No repositories found on your GitHub account.
                </p>
              ) : (
                githubRepos.data.repos.map((repo) => (
                  <button
                    key={repo.full_name}
                    type="button"
                    disabled={submitRepo.isPending}
                    onClick={() => submitUrl(`https://github.com/${repo.full_name}`)}
                    className="flex w-full items-center justify-between gap-2 border-b border-slate-100 px-3 py-2 text-left text-xs last:border-b-0 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-800 dark:hover:bg-slate-800"
                  >
                    <span className="truncate text-slate-700 dark:text-slate-200">
                      {repo.full_name}
                    </span>
                    {repo.private ? (
                      <span className="shrink-0 rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-medium text-slate-500 dark:bg-slate-800 dark:text-slate-400">
                        Private
                      </span>
                    ) : null}
                  </button>
                ))
              )}
              {githubRepos.data.truncated ? (
                <p className="px-3 py-2 text-[10px] text-slate-400 dark:text-slate-500">
                  Showing your first 300 repositories, sorted by most recently pushed.
                </p>
              ) : null}
            </div>
          )}
        </div>
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
      <p className="text-sm text-amber-600 dark:text-amber-400">
        You've hit the analysis limit for now. Try again in about {resetLabel}.
      </p>
    );
  }

  const message = error instanceof ApiError ? error.message : "Something went wrong.";
  return <p className="text-sm text-red-600 dark:text-red-400">{message}</p>;
}
