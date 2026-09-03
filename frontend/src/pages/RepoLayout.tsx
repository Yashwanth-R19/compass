import { useState } from "react";
import {
  Navigate,
  NavLink,
  Outlet,
  useLocation,
  useParams,
  useSearchParams,
} from "react-router-dom";
import {
  useCreateShareLink,
  useMe,
  useRepo,
  useRepoStatus,
  useRevokeShareLink,
  useRuns,
  useSubmitRepo,
} from "../api/hooks";
import { ApiError } from "../api/client";
import { LoadingState } from "../components/LoadingState";
import { ErrorState } from "../components/ErrorState";
import { EmptyState } from "../components/EmptyState";
import { Button } from "../components/ui/Button";
import { Input } from "../components/ui/Input";
import { Alert } from "../components/ui/Alert";
import { useToast } from "../components/ui/Toast";
import type { RepoOut, StageName, StageOut, StageStatus } from "../api/types";

/**
 * The eight repository surfaces (rebuild spec section 4.1) -- real routes,
 * `NavLink`s, so deep-linking, the back button, and every existing share
 * link keep working. This REPLACES the outgoing Onboard/Audit dual-mode
 * system entirely: there is no mode switcher any more, and the old
 * `compass:mode` localStorage key is no longer read or written anywhere
 * in this codebase.
 */
const REPO_TABS = [
  { to: "overview", label: "Overview" },
  { to: "map", label: "Map" },
  { to: "tour", label: "Tour" },
  { to: "people", label: "People" },
  { to: "findings", label: "Findings" },
  { to: "risk", label: "Risk" },
  { to: "structure", label: "Structure" },
  { to: "evolution", label: "Evolution" },
];

/** The bare `/repos/:repoId` index route always lands on Overview now --
 * there is no "last used mode" to remember any more (that concept no
 * longer exists), so unlike the outgoing dual-mode system this needs no
 * localStorage read at all. Preserves the query string (a `?share=` in
 * particular) across the redirect. */
export function RepoIndexRedirect() {
  const { repoId } = useParams<{ repoId: string }>();
  const location = useLocation();
  return <Navigate to={`/repos/${repoId}/overview${location.search}`} replace />;
}

/**
 * Builds a redirect target from an ABSOLUTE `/repos/${repoId}/...` path
 * (rebuild spec section 4.3 -- never a relative `to`, which a `<Navigate>`
 * rendered as a leaf route's own element resolves against a different
 * base than a `NavLink` inside a layout route). `target` is the suffix
 * after `/repos/${repoId}/` and may itself carry a fixed `?query` and/or
 * `#hash` (e.g. `"tour?panel=glossary"`, `"overview#health"`) --
 * `location.search`'s own params (a `?share=` above all) are merged in
 * underneath the target's own fixed params, which win on any conflict,
 * rather than the two strings being blindly concatenated (which would
 * produce an invalid double `?` the moment both the incoming location AND
 * the fixed target carry a query string).
 */
function buildRedirectTarget(
  repoId: string | undefined,
  target: string,
  incomingSearch: string,
): string {
  const hashIndex = target.indexOf("#");
  const hash = hashIndex >= 0 ? target.slice(hashIndex) : "";
  const withoutHash = hashIndex >= 0 ? target.slice(0, hashIndex) : target;

  const queryIndex = withoutHash.indexOf("?");
  const path = queryIndex >= 0 ? withoutHash.slice(0, queryIndex) : withoutHash;
  const targetQuery = queryIndex >= 0 ? withoutHash.slice(queryIndex + 1) : "";

  const merged = new URLSearchParams(incomingSearch);
  for (const [key, value] of new URLSearchParams(targetQuery)) {
    merged.set(key, value);
  }
  const mergedString = merged.toString();
  return `/repos/${repoId}/${path}${mergedString ? `?${mergedString}` : ""}${hash}`;
}

/** Every one of the rebuild spec's 23 required redirects (section 4.2)
 * renders through this one component -- `to` is the fixed target suffix
 * (see `buildRedirectTarget` above). Covers both the pre-consolidation
 * dual-mode paths (`onboard/*`/`audit/*`/bare `compare`) and the
 * session-02 legacy share-link paths (`coupling`/`architecture`/`risk`),
 * which must keep working indefinitely -- they are still-live links,
 * not a one-time migration aid. */
export function LegacyRedirect({ to }: { to: string }) {
  const { repoId } = useParams<{ repoId: string }>();
  const location = useLocation();
  return <Navigate to={buildRedirectTarget(repoId, to, location.search)} replace />;
}

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
  secrets: "Secrets",
  coupling: "Coupling",
  subsystems: "Subsystems",
  architecture: "Architecture",
  risk: "Risk",
  knowledge: "Knowledge",
  onboarding: "Onboarding",
  security: "Security",
  rank: "Rank",
};

// The one summary field worth surfacing as a pill's number, per stage --
// each stage's summary JSONB carries several fields, but the pill only has
// room for one.
const STAGE_SUMMARY_KEY: Partial<Record<StageName, string>> = {
  mine: "commits",
  structure: "dependencies",
  persist_facts: "commits",
  secrets: "hits_found",
  coupling: "pairs_found",
  subsystems: "subsystems",
  architecture: "cycles_found",
  risk: "findings_emitted",
  knowledge: "contributors",
  onboarding: "stops",
  security: "vulnerabilities_found",
  rank: "findings_ranked",
};

const STAGE_STATUS_CLASSES: Record<StageStatus, string> = {
  pending: "border-border text-text-muted",
  running: "border-accent text-accent",
  done: "border-success text-success",
  // A failed OPTIONAL stage (security) renders exactly the same danger
  // tone as any other failed stage -- the run-level distinction (whole run
  // failed vs. one optional stage failed while the run still reached
  // "ready") is carried by the surrounding run-status banner below, not by
  // a softened pill colour, so a failed stage is never visually implied to
  // be "fine really."
  failed: "border-danger text-danger",
  skipped: "border-border text-text-muted",
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
  const runs = useRuns(repoId, share);

  if (isPending) return <LoadingState label="Loading repo…" />;
  if (isError) return <ErrorState error={error} onRetry={() => void refetch()} />;

  const tabClass = ({ isActive }: { isActive: boolean }) =>
    `cp-label -mb-px shrink-0 border-b-2 px-0.5 py-2.5 transition-colors ${
      isActive ? "border-accent text-text" : "border-transparent hover:text-text"
    }`;

  const displayStatus = status.data?.repo_status ?? repo.status;
  // A run has NEVER succeeded for this repo until current_run_id is set --
  // distinct from run_id/run_status, which reflect the LATEST run
  // regardless of outcome. Only the never-succeeded + latest-failed
  // combination should block the whole view; a failed RE-analysis must
  // keep showing the previous good run's tabs.
  const neverSucceeded = !status.data?.current_run_id;
  const blockingFailure = neverSucceeded && status.data?.run_status === "failed";
  const showTabs = Boolean(status.data?.run_id) && !blockingFailure;

  const statusTone =
    displayStatus === "ready"
      ? "border-success text-success"
      : displayStatus === "failed"
        ? "border-danger text-danger"
        : "border-accent text-accent";

  return (
    <div className="flex min-w-0 flex-col gap-6">
      <div>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="font-mono text-lg font-semibold text-text-heading">
              {repo.owner}/{repo.name}
            </h1>
            <a
              href={repo.url}
              target="_blank"
              rel="noreferrer"
              className="break-all text-xs text-text-muted hover:underline"
            >
              {repo.url}
            </a>
          </div>
          <div className="flex items-center gap-2">
            <span
              className={`inline-flex items-center rounded-xs border px-2.5 py-1 text-xs font-medium ${statusTone}`}
            >
              {REPO_STATUS_LABEL[displayStatus] ?? displayStatus}
            </span>
            {(runs.data?.runs.length ?? 0) >= 2 ? <CompareLink /> : null}
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
          <p className="mt-3 border-l-2 border-danger py-1.5 pl-3 text-xs text-text-muted">
            The latest re-analysis failed
            {status.data.run_error ? `: ${status.data.run_error}` : "."} Showing the most recent
            successful run below.
          </p>
        ) : null}

        {status.data?.facts_archived ? <ArchivedBanner repoUrl={repo.url} /> : null}

        {showTabs ? (
          // The tab nav scrolls WITHIN itself (overflow-x-auto, shrink-0
          // items) rather than widening the page body -- verified at a
          // 360px viewport (Part K).
          <nav
            aria-label="Repository sections"
            className="mt-4 flex gap-5 overflow-x-auto border-b border-border"
          >
            {REPO_TABS.map((tab) => (
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

/** Session 16, Part B: a repo whose Facts app/jobs/eviction.py wiped for
 * being unvisited past FACTS_TTL_DAYS. The current run's Insight (health/
 * risk/passport/...) is still intact and most pages keep working -- this
 * is a persistent notice, not a blocking error page. Re-analysing
 * re-clones and clears the archived flag. */
function ArchivedBanner({ repoUrl }: { repoUrl: string }) {
  const submitRepo = useSubmitRepo();
  return (
    <Alert variant="info" className="mt-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span>
          Analysis archived — this repo hasn&apos;t been visited in a while, so its raw commit
          history was cleared to save storage. Metrics from the last analysis still show below;
          re-analyse to explore file-level detail again.
        </span>
        <Button
          type="button"
          variant="secondary"
          size="sm"
          onClick={() => submitRepo.mutate(repoUrl)}
          disabled={submitRepo.isPending}
        >
          {submitRepo.isPending ? "Re-analysing…" : "Re-analyse"}
        </Button>
      </div>
    </Alert>
  );
}

function StagePill({ stage }: { stage: StageOut }) {
  const summaryValue = stageSummaryValue(stage);
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-xs border px-2 py-0.5 text-xs font-medium ${STAGE_STATUS_CLASSES[stage.status]} ${
        // The only permitted looping animation in the app (rule M2): the
        // in-flight leg of the live analysis stage pill, only while a run
        // is actually running.
        stage.status === "running" ? "animate-pulse motion-reduce:animate-none" : ""
      }`}
      title={stage.error ?? undefined}
    >
      {STAGE_LABEL[stage.name]}
      {summaryValue !== null ? <span className="cp-stat">{summaryValue}</span> : null}
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

/** A header entry point to run-vs-run compare, shown only when the repo
 * has >= 2 runs -- not part of the tab bar itself (compare is a
 * cross-run view, not one of the eight surfaces), reached via
 * `evolution?tab=compare` (the "evolution" surface's own Compare
 * segment). */
function CompareLink() {
  return (
    <NavLink
      to="evolution?tab=compare"
      className={({ isActive }) =>
        `inline-flex items-center rounded-xs border px-2.5 py-1 text-xs font-medium transition-colors ${
          isActive
            ? "border-accent bg-accent text-accent-contrast"
            : "border-border text-text-muted hover:bg-bg-inset"
        }`
      }
    >
      Compare
    </NavLink>
  );
}

/** Creates/copies/revokes a share link for the repo's current run. Only a
 * run's link is ever created (never one for the repo as a whole), and
 * only the repository's own owner can actually create or revoke one. */
function ShareButton({ runId }: { runId: string }) {
  const createShare = useCreateShareLink();
  const revokeShare = useRevokeShareLink();
  const [link, setLink] = useState<string | null>(null);
  const showToast = useToast();

  async function handleShare() {
    const result = await createShare.mutateAsync(runId);
    const shareUrl = `${window.location.origin}/shared/${result.slug}`;
    setLink(shareUrl);
    try {
      await navigator.clipboard.writeText(shareUrl);
      showToast("Link copied to clipboard");
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
      <Button
        type="button"
        variant="secondary"
        size="sm"
        onClick={() => void handleShare()}
        disabled={createShare.isPending}
      >
        {createShare.isPending ? "Creating link…" : "Share"}
      </Button>
      {link ? (
        <>
          <Input
            readOnly
            value={link}
            onFocus={(e) => e.currentTarget.select()}
            className="w-56 py-1"
          />
          <button
            type="button"
            onClick={handleRevoke}
            className="text-xs text-danger hover:underline"
          >
            Revoke
          </button>
        </>
      ) : null}
      {createShare.isError ? (
        <span className="text-xs text-danger">
          {createShare.error instanceof ApiError
            ? createShare.error.message
            : "Couldn't create link."}
        </span>
      ) : null}
    </div>
  );
}
