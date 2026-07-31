import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useSubmitRepo } from "../api/hooks";
import { ApiError } from "../api/client";

export function HomePage() {
  const [url, setUrl] = useState("");
  const navigate = useNavigate();

  const submitRepo = useSubmitRepo();

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!url.trim()) return;
    // Navigate the instant the repo/job rows exist -- RepoLayout takes over
    // from there and polls /repos/{id}/status, which is what makes the
    // stage pills appear within ~2 seconds instead of staring at this page
    // until the whole analysis finishes (Phase 02 progressive reveal).
    submitRepo.mutate(url.trim(), {
      onSuccess: (res) => navigate(`/repos/${res.repo_id}/overview`),
    });
  }

  const submitError =
    submitRepo.error instanceof ApiError ? submitRepo.error.message : submitRepo.error?.message;

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

      {submitError ? <p className="text-sm text-red-600 dark:text-red-400">{submitError}</p> : null}
    </div>
  );
}
