import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useJob, useSubmitRepo } from "../api/hooks";
import { ApiError } from "../api/client";

const JOB_STAGE_LABEL: Record<string, string> = {
  queued: "Queued…",
  running: "Analyzing…",
};

export function HomePage() {
  const [url, setUrl] = useState("");
  const [submission, setSubmission] = useState<{ repoId: string; jobId: string } | null>(null);
  const navigate = useNavigate();

  const submitRepo = useSubmitRepo();
  const { data: job } = useJob(submission?.jobId);

  useEffect(() => {
    if (job?.status === "done" && submission) {
      navigate(`/repos/${submission.repoId}/overview`);
    }
  }, [job?.status, submission, navigate]);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!url.trim()) return;
    submitRepo.mutate(url.trim(), {
      onSuccess: (res) => setSubmission({ repoId: res.repo_id, jobId: res.job_id }),
    });
  }

  const isWorking = submission && job && job.status !== "done" && job.status !== "failed";
  const submitError = submitRepo.error instanceof ApiError ? submitRepo.error.message : submitRepo.error?.message;

  return (
    <div className="mx-auto flex max-w-xl flex-col items-center gap-8 py-16 text-center">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900 dark:text-slate-100">
          Compass
        </h1>
        <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">
          Mine a GitHub repository's full commit history for hidden change-coupling, calibrated risk, and
          architecture insight — computed deterministically, not guessed by an AI reading the current tree.
        </p>
      </div>

      <form onSubmit={handleSubmit} className="flex w-full flex-col gap-3 sm:flex-row">
        <input
          type="text"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://github.com/owner/repo"
          disabled={Boolean(isWorking)}
          className="flex-1 rounded-md border border-slate-300 px-3 py-2 text-sm outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 disabled:bg-slate-100 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:disabled:bg-slate-800"
        />
        <button
          type="submit"
          disabled={Boolean(isWorking) || submitRepo.isPending}
          className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {submitRepo.isPending ? "Submitting…" : "Analyze"}
        </button>
      </form>

      {submitError ? <p className="text-sm text-red-600 dark:text-red-400">{submitError}</p> : null}

      {submission && job ? (
        <div className="w-full rounded-lg border border-slate-200 bg-white p-5 text-left dark:border-slate-800 dark:bg-slate-900">
          <div className="flex items-center justify-between text-sm">
            <span className="font-medium text-slate-700 dark:text-slate-300">
              {job.status === "failed" ? "Analysis failed" : JOB_STAGE_LABEL[job.status] ?? job.status}
            </span>
            <span className="text-slate-400 dark:text-slate-500">{job.progress}%</span>
          </div>
          <div className="mt-2 h-2 w-full overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
            <div
              className={`h-full rounded-full transition-all duration-500 ${job.status === "failed" ? "bg-red-500" : "bg-indigo-600"}`}
              style={{ width: `${job.status === "failed" ? 100 : job.progress}%` }}
            />
          </div>
          {job.status === "failed" ? (
            <div className="mt-3">
              <p className="text-sm text-red-600 dark:text-red-400">{job.error ?? "Unknown error."}</p>
              <button
                type="button"
                onClick={() => setSubmission(null)}
                className="mt-2 text-sm font-medium text-indigo-600 hover:underline dark:text-indigo-400"
              >
                Try a different repo
              </button>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
