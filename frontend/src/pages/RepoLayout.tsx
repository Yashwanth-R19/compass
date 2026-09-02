import { useEffect, useState } from "react";
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
import { useToast } from "../components/ui/Toast";
import type { RepoOut, StageName, StageOut, StageStatus } from "../api/types";

// Session 08, Part A: the product has two primary modes, switched at the top
// of every repo page and remembered across visits. Each tab's `to` is
// relative to RepoLayout's own route ("repos/:repoId") -- NavLink here is
// rendered directly in this component's JSX, never inside a further-nested
// Route element, so plain relative segments resolve the same way the
// pre-dual-mode TABS list always did.
export type RepoMode = "onboard" | "audit";

const MODE_STORAGE_KEY = "compass:mode";

const ONBOARD_TABS = [
  { to: "onboard/passport", label: "Passport" },
  { to: "onboard/tour", label: "Tour" },
  { to: "onboard/people", label: "People" },
  { to: "onboard/glossary", label: "Glossary" },
  { to: "onboard/map", label: "Map" },
  { to: "onboard/impact", label: "Impact" },
  { to: "onboard/evolution", label: "Evolution" },
];

// findings/coupling/architecture/risk/security/hygiene/health -- fleshed out
// in session 11 (security + hygiene are new tabs this session; the other
// five moved the pre-existing pages into this shell in session 08).
const AUDIT_TABS = [
  { to: "audit/findings", label: "Findings" },
  { to: "audit/coupling", label: "Coupling" },
  { to: "audit/architecture", label: "Architecture" },
  { to: "audit/risk", label: "Risk" },
  { to: "audit/security", label: "Security" },
  { to: "audit/hygiene", label: "Hygiene" },
  { to: "audit/health", label: "Health" },
  { to: "audit/benchmark", label: "Benchmark" },
];

function modeFromPathname(pathname: string): RepoMode | null {
  if (/\/onboard(\/|$)/.test(pathname)) return "onboard";
  if (/\/audit(\/|$)/.test(pathname)) return "audit";
  return null;
}

function readStoredMode(): RepoMode {
  try {
    return window.localStorage.getItem(MODE_STORAGE_KEY) === "audit" ? "audit" : "onboard";
  } catch {
    // Private window / blocked site data -- default to Onboard, same as a
    // genuinely first-time visitor (Part A: "default to Onboard on a first
    // visit").
    return "onboard";
  }
}

function storeMode(mode: RepoMode) {
  try {
    window.localStorage.setItem(MODE_STORAGE_KEY, mode);
  } catch {
    // Nothing to do -- the switch still works for this visit, it just won't
    // be remembered for the next one.
  }
}

/** The bare `/repos/:repoId` index route -- lands on whichever mode was last
 * used (Onboard by default, Part A), preserving `?share=`/any other query
 * string so a share link still works after the redirect. */
export function RepoIndexRedirect() {
  const { repoId } = useParams<{ repoId: string }>();
  const location = useLocation();
  const mode = readStoredMode();
  const target = mode === "audit" ? "audit/findings" : "onboard/passport";
  return <Navigate to={`/repos/${repoId}/${target}${location.search}`} replace />;
}

/** Session 02 shipped share links pointing at the pre-dual-mode paths
 * (`/repos/:id/overview|coupling|architecture|risk`) -- breaking them here
 * would be a regression a user actually notices (Known Hazard #1), so every
 * one of those paths keeps working via an explicit redirect to its new
 * home, preserving `?share=`. Absolute target paths (not a relative `to`)
 * deliberately sidestep any ambiguity in how relative resolution treats a
 * `<Navigate>` rendered as a LEAF route's own element (a different context
 * than the tab NavLinks above, which resolve relative to the layout
 * route). */
export function LegacyRedirect({ to }: { to: string }) {
  const { repoId } = useParams<{ repoId: string }>();
  const location = useLocation();
  return <Navigate to={`/repos/${repoId}/${to}${location.search}`} replace />;
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
  pending: "border-border text-ink-faint",
  running: "border-signal text-signal",
  done: "border-conf-high text-conf-high",
  failed: "border-sev-high text-sev-high",
  skipped: "border-border text-ink-faint",
};

export type RepoOutletContext = {
  repo: RepoOut;
  share?: string;
};

export function RepoLayout() {
  const { repoId } = useParams<{ repoId: string }>();
  const [searchParams] = useSearchParams();
  const share = searchParams.get("share") ?? undefined;
  const location = useLocation();

  const { data: repo, isPending, isError, error, refetch } = useRepo(repoId, share);
  const status = useRepoStatus(repoId, share);
  const me = useMe();
  const runs = useRuns(repoId, share);

  const mode = modeFromPathname(location.pathname) ?? readStoredMode();

  // Persists whichever mode the URL actually reflects, so switching modes
  // via a tab click, a pasted link, or the switcher itself all count the
  // same way toward "the last mode used" (Part A).
  useEffect(() => {
    const detected = modeFromPathname(location.pathname);
    if (detected) storeMode(detected);
  }, [location.pathname]);

  if (isPending) return <LoadingState label="Loading repo…" />;
  if (isError) return <ErrorState error={error} onRetry={() => void refetch()} />;

  const tabClass = ({ isActive }: { isActive: boolean }) =>
    `cp-label -mb-px border-b-2 px-0.5 py-2.5 transition-colors ${
      isActive ? "border-signal text-ink" : "border-transparent hover:text-ink"
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

  const statusTone =
    displayStatus === "ready"
      ? "border-conf-high text-conf-high"
      : displayStatus === "failed"
        ? "border-sev-high text-sev-high"
        : "border-signal text-signal";

  return (
    <div className="flex flex-col gap-6">
      <div>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="font-mono text-lg font-semibold text-ink">
              {repo.owner}/{repo.name}
            </h1>
            <a
              href={repo.url}
              target="_blank"
              rel="noreferrer"
              className="text-xs text-ink-muted hover:underline"
            >
              {repo.url}
            </a>
          </div>
          <div className="flex items-center gap-2">
            <span
              className={`inline-flex items-center border px-2.5 py-1 text-xs font-medium ${statusTone}`}
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
          <p className="mt-3 border-l-2 border-sev-high py-1.5 pl-3 text-xs text-ink-muted">
            The latest re-analysis failed
            {status.data.run_error ? `: ${status.data.run_error}` : "."} Showing the most recent
            successful run below.
          </p>
        ) : null}

        {status.data?.facts_archived ? <ArchivedBanner repoUrl={repo.url} /> : null}

        {showTabs ? (
          <>
            <ModeSwitcher mode={mode} />
            {/* Audit mode's 8 tabs don't fit in 360px -- scrolls horizontally
                INSIDE the nav rather than widening the whole page body (no
                page may scroll horizontally itself). */}
            <nav
              aria-label="Repository sections"
              className="mt-3 flex gap-5 overflow-x-auto border-b border-border"
            >
              {(mode === "audit" ? AUDIT_TABS : ONBOARD_TABS).map((tab) => (
                <NavLink key={tab.to} to={tab.to} className={(a) => `shrink-0 ${tabClass(a)}`}>
                  {tab.label}
                </NavLink>
              ))}
            </nav>
          </>
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

/** The primary Onboard/Audit switcher (Part A) -- sits above the tab bar in
 * both modes. Always jumps to the target mode's own default tab; it does
 * not try to remember a per-mode "last sub-tab" (out of scope for this
 * session's function-and-IA-only mandate). A neutral ink/paper inversion
 * for the active segment, not the signal accent -- this is chrome
 * (navigation), not a data value or the page's one primary action. */
function ModeSwitcher({ mode }: { mode: RepoMode }) {
  const modeButtonClass = (active: boolean) =>
    `cp-label px-3 py-1.5 transition-colors ${
      active ? "bg-ink text-bg" : "hover:bg-surface-2 hover:text-ink"
    }`;

  return (
    <div className="inline-flex items-center border border-border">
      <NavLink to="onboard/passport" className={() => modeButtonClass(mode === "onboard")}>
        Onboard
      </NavLink>
      <NavLink to="audit/findings" className={() => modeButtonClass(mode === "audit")}>
        Audit
      </NavLink>
    </div>
  );
}

/** Session 16, Part B: a repo whose Facts app/jobs/eviction.py wiped for
 * being unvisited past FACTS_TTL_DAYS. The current run's Insight (health/
 * risk/passport/...) is still intact and most pages keep working -- this is
 * a persistent notice, not a blocking error page, per the session's own
 * "not an error, not an empty page" rule. Re-analysing (the same
 * `useSubmitRepo` mutation the home page and dashboard both already use)
 * re-clones and clears the archived flag. */
function ArchivedBanner({ repoUrl }: { repoUrl: string }) {
  const submitRepo = useSubmitRepo();
  return (
    <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-l-2 border-signal bg-surface-2 py-1.5 pl-3 pr-3 text-xs">
      <span className="text-ink-muted">
        Analysis archived — this repo hasn&apos;t been visited in a while, so its raw commit history
        was cleared to save storage. Metrics from the last analysis still show below; re-analyse to
        explore file-level detail again.
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
  );
}

function StagePill({ stage }: { stage: StageOut }) {
  const summaryValue = stageSummaryValue(stage);
  return (
    <span
      className={`inline-flex items-center gap-1.5 border px-2 py-0.5 text-xs font-medium ${STAGE_STATUS_CLASSES[stage.status]} ${
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

/** Session 13, Part G: "add a compare entry point to the repo header
 * whenever a repository has >= 2 runs" -- not part of either mode's tab bar
 * (compare isn't Onboard or Audit content, it's a third, cross-run view), so
 * a plain header link is the entry point rather than a tab. */
function CompareLink() {
  return (
    <NavLink
      to="compare"
      className={({ isActive }) =>
        `inline-flex items-center border px-2.5 py-1 text-xs font-medium transition-colors ${
          isActive
            ? "border-signal bg-signal text-signal-ink"
            : "border-border text-ink-muted hover:bg-surface-2"
        }`
      }
    >
      Compare
    </NavLink>
  );
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
            className="text-xs text-sev-high hover:underline"
          >
            Revoke
          </button>
        </>
      ) : null}
      {createShare.isError ? (
        <span className="text-xs text-sev-high">
          {createShare.error instanceof ApiError
            ? createShare.error.message
            : "Couldn't create link."}
        </span>
      ) : null}
    </div>
  );
}
