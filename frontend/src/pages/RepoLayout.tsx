import { useState } from "react";
import { NavLink, Outlet, useParams, useSearchParams } from "react-router-dom";
import {
  useCreateShareLink,
  useMe,
  useRepo,
  useRepoStatus,
  useRevokeShareLink,
} from "../api/hooks";
import { ApiError } from "../api/client";
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
  subsystems: "Subsystems",
  architecture: "Architecture",
  risk: "Risk",
  knowledge: "Knowledge",
  onboarding: "Onboarding",
  rank: "Rank",
};

// The one summary field worth surfacing as a pill's number, per stage --
// each stage's summary JSONB carries several fields (see app/engines/*.py's
// return dicts), but the pill only has room for one. Session 04: "overlay"
// folded into "architecture" (still reads its own hidden-dependency count,
// alongside architecture's own cycles_found, but a pill only shows one key,
// so cycles_found -- the FIRST engine in that stage's tuple -- keeps its
// spot here); "subsystems" is new. Session 06: the standalone "health" stage
// folded into "onboarding" (TourEngine -> GlossaryEngine -> HealthEngine ->
// PassportEngine, all merged into one summary dict) -- "stops", the first
// engine's own key, keeps the pill's spot the same way "cycles_found" did.
const STAGE_SUMMARY_KEY: Partial<Record<StageName, string>> = {
  mine: "commits",
  structure: "dependencies",
  persist_facts: "commits",
  coupling: "pairs_found",
  subsystems: "subsystems",
  architecture: "cycles_found",
  risk: "findings_emitted",
  knowledge: "contributors",
  onboarding: "stops",
  rank: "findings_ranked",
};

const STAGE_STATUS_CLASSES: Record<StageStatus, string> = {
  pending: "bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400",
  running: "bg-indigo-100 text-indigo-700 dark:bg-indigo-500/10 dark:text-indigo-400 animate-pulse",
  done: "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-400",
  failed: "bg-red-100 text-red-700 dark:bg-red-500/10 dark:text-red-400",
  skipped: "bg-slate-100 text-slate-400 dark:bg-slate-800 dark:text-slate-500",
};

export type RepoOutletContext = {
  repo: RepoOut;
  share?: string;
};

export function RepoLayout() {
  const { repoId } = useParams<{ repoId: string }>();
  const [searchParams] = useSearchParams();
  const share = searchParams.get("share") ?? undefined;

  const { data: repo, isPending, isError, error, refetch } = useRepo(repoId, share);
  const status = useRepoStatus(repoId, share);
  const me = useMe();

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
          <div className="flex items-center gap-2">
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
            {me.data && status.data?.current_run_id ? (
              <ShareButton runId={status.data.current_run_id} />
            ) : null}
          </div>
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
        <Outlet context={{ repo, share } satisfies RepoOutletContext} />
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

/** Creates/copies/revokes a share link for the repo's current run. Only a
 * run's link is ever created (never one for the repo as a whole -- see
 * CLAUDE.md's "a share link grants access to one run" note), and only the
 * repository's own owner can actually create or revoke one -- a 403 from
 * either action just surfaces inline rather than needing its own state
 * machine, since that's already a rare, self-explanatory case for someone
 * who isn't the owner but happens to see this button while it's still
 * mid-render for their own dashboard. */
function ShareButton({ runId }: { runId: string }) {
  const createShare = useCreateShareLink();
  const revokeShare = useRevokeShareLink();
  const [link, setLink] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  async function handleShare() {
    const result = await createShare.mutateAsync(runId);
    const shareUrl = `${window.location.origin}/shared/${result.slug}`;
    setLink(shareUrl);
    try {
      await navigator.clipboard.writeText(shareUrl);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard access denied/unavailable -- the link is still shown
      // inline below for the user to copy by hand.
    }
  }

  function handleRevoke() {
    revokeShare.mutate(runId, { onSuccess: () => setLink(null) });
  }

  return (
    <div className="flex items-center gap-2">
      <button
        type="button"
        onClick={() => void handleShare()}
        disabled={createShare.isPending}
        className="rounded-md border border-slate-200 px-2.5 py-1 text-xs font-medium text-slate-600 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
      >
        {createShare.isPending ? "Creating link…" : "Share"}
      </button>
      {link ? (
        <>
          <input
            readOnly
            value={link}
            onFocus={(e) => e.currentTarget.select()}
            className="w-56 rounded-md border border-slate-200 bg-slate-50 px-2 py-1 text-xs text-slate-600 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300"
          />
          {copied ? (
            <span className="text-xs text-emerald-600 dark:text-emerald-400">Copied</span>
          ) : null}
          <button
            type="button"
            onClick={handleRevoke}
            className="text-xs text-red-600 hover:underline dark:text-red-400"
          >
            Revoke
          </button>
        </>
      ) : null}
      {createShare.isError ? (
        <span className="text-xs text-red-600 dark:text-red-400">
          {createShare.error instanceof ApiError
            ? createShare.error.message
            : "Couldn't create link."}
        </span>
      ) : null}
    </div>
  );
}
