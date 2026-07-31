import { NavLink, Outlet, useParams } from "react-router-dom";
import { useRepo, useRepoStatus } from "../api/hooks";
import { LoadingState } from "../components/LoadingState";
import { ErrorState } from "../components/ErrorState";
import { EmptyState } from "../components/EmptyState";
import type { RepoOut, StageName, StageOut, StageStatus } from "../api/types";

const TABS = [
  { to: "overview", label: "Overview" },
  { to: "coupling", label: "Coupling" },
  { to: "architecture", label: "Architecture" },
  { to: "risk", label: "Risk" },
];

const REPO_STATUS_LABEL: Record<string, string> = {
  pending: "Queued",
  mining: "Mining commit history…",
  analyzing: "Running analysis…",
  ready: "Ready",
  failed: "Failed",
};

const STAGE_LABEL: Record<StageName, string> = {
  clone: "Clone",
  mine: "Mine",
  structure: "Structure",
  persist_facts: "Persist",
  coupling: "Coupling",
  architecture: "Architecture",
  overlay: "Overlay",
  risk: "Risk",
  health: "Health",
  rank: "Rank",
};

// The one summary field worth surfacing as a pill's number, per stage --
// each stage's summary JSONB carries several fields (see app/engines/*.py's
// return dicts), but the pill only has room for one.
const STAGE_SUMMARY_KEY: Partial<Record<StageName, string>> = {
  mine: "commits",
  structure: "dependencies",
  persist_facts: "commits",
  coupling: "pairs_found",
  architecture: "cycles_found",
  overlay: "hidden_dependencies_found",
  risk: "findings_emitted",
  health: "score",
  rank: "findings_ranked",
};

const STAGE_STATUS_CLASSES: Record<StageStatus, string> = {
  pending: "bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400",
  running: "bg-indigo-100 text-indigo-700 dark:bg-indigo-500/10 dark:text-indigo-400 animate-pulse",
  done: "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-400",
  failed: "bg-red-100 text-red-700 dark:bg-red-500/10 dark:text-red-400",
  skipped: "bg-slate-100 text-slate-400 dark:bg-slate-800 dark:text-slate-500",
};

export type RepoOutletContext = { repo: RepoOut };

export function RepoLayout() {
  const { repoId } = useParams<{ repoId: string }>();
  const { data: repo, isPending, isError, error, refetch } = useRepo(repoId);
  const status = useRepoStatus(repoId);

  if (isPending) return <LoadingState label="Loading repo…" />;
  if (isError) return <ErrorState error={error} onRetry={() => void refetch()} />;

  const tabClass = ({ isActive }: { isActive: boolean }) =>
    `border-b-2 px-1 py-2.5 text-sm font-medium transition-colors ${
      isActive
        ? "border-indigo-600 text-indigo-600 dark:border-indigo-400 dark:text-indigo-400"
        : "border-transparent text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200"
    }`;

  const displayStatus = status.data?.repo_status ?? repo.status;
  // A run has NEVER succeeded for this repo until current_run_id is set --
  // distinct from run_id/run_status, which reflect the LATEST run
  // regardless of outcome. Only the never-succeeded + latest-failed
  // combination should block the whole view; a failed RE-analysis must
  // keep showing the previous good run's tabs (Part C step 7 / the manual
  // checklist's "repo page still shows the previous run's data").
  const neverSucceeded = !status.data?.current_run_id;
  const blockingFailure = neverSucceeded && status.data?.run_status === "failed";
  const showTabs = Boolean(status.data?.run_id) && !blockingFailure;

  return (
    <div className="flex flex-col gap-6">
      <div>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
              {repo.owner}/{repo.name}
            </h1>
            <a
              href={repo.url}
              target="_blank"
              rel="noreferrer"
              className="text-xs text-slate-500 hover:underline dark:text-slate-400"
            >
              {repo.url}
            </a>
          </div>
          <span
            className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium ${
              displayStatus === "ready"
                ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-400"
                : displayStatus === "failed"
                  ? "bg-red-100 text-red-700 dark:bg-red-500/10 dark:text-red-400"
                  : "bg-indigo-100 text-indigo-700 dark:bg-indigo-500/10 dark:text-indigo-400"
            }`}
          >
            {REPO_STATUS_LABEL[displayStatus] ?? displayStatus}
          </span>
        </div>

        {status.data && status.data.stages.length > 0 ? (
          <div className="mt-4 flex flex-wrap gap-1.5">
            {status.data.stages.map((s) => (
              <StagePill key={s.name} stage={s} />
            ))}
          </div>
        ) : null}

        {!neverSucceeded && status.data?.run_status === "failed" ? (
          <p className="mt-3 rounded-md bg-red-50 px-3 py-2 text-xs text-red-700 dark:bg-red-500/10 dark:text-red-400">
            The latest re-analysis failed
            {status.data.run_error ? `: ${status.data.run_error}` : "."} Showing the most recent
            successful run below.
          </p>
        ) : null}

        {showTabs ? (
          <nav className="mt-4 flex gap-5 border-b border-slate-200 dark:border-slate-800">
            {TABS.map((tab) => (
              <NavLink key={tab.to} to={tab.to} className={tabClass}>
                {tab.label}
              </NavLink>
            ))}
          </nav>
        ) : null}
      </div>

      {showTabs ? (
        <Outlet context={{ repo } satisfies RepoOutletContext} />
      ) : blockingFailure ? (
        <EmptyState
          title="Analysis failed"
          message={
            status.data?.run_error ??
            "Something went wrong while analyzing this repo. Try submitting it again from the home page."
          }
        />
      ) : (
        <LoadingState label="Starting analysis…" />
      )}
    </div>
  );
}

function StagePill({ stage }: { stage: StageOut }) {
  const summaryValue = stageSummaryValue(stage);
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${STAGE_STATUS_CLASSES[stage.status]}`}
      title={stage.error ?? undefined}
    >
      {STAGE_LABEL[stage.name]}
      {summaryValue !== null ? (
        <span className="tabular-nums opacity-80">{summaryValue}</span>
      ) : null}
    </span>
  );
}

function stageSummaryValue(stage: StageOut): string | null {
  if (!stage.summary) return null;
  const key = STAGE_SUMMARY_KEY[stage.name];
  if (!key) return null;
  const value = stage.summary[key];
  if (typeof value !== "number") return null;
  return Math.round(value).toLocaleString();
}
