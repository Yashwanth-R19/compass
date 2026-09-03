import { useState } from "react";
import { Link, useOutletContext, useSearchParams } from "react-router-dom";
import { useRepoStatus, useTour } from "../../api/hooks";
import type { TourStopOut } from "../../api/types";
import { Card } from "../../components/ui/Card";
import { InfoTooltip } from "../../components/ui/InfoTooltip";
import { MetricRow } from "../../components/MetricRow";
import { StageGate } from "../../components/StageGate";
import { SubsystemBadge } from "../../components/SubsystemBadge";
import { GlossaryPanel } from "./GlossaryPanel";
import { TOUR_REASON_COPY, type TourReasonDetail } from "../../lib/copy";
import { TOOLTIPS } from "../../content/explainability";
import { formatScore, formatPercent } from "../../lib/format";
import { isTourStopDone, setTourStopDone } from "../../lib/tourProgress";
import type { RepoOutletContext } from "../RepoLayout";

/** Merges the guided reading order with the repo-scoped glossary as a URL-
 * addressable side panel (`?panel=glossary`), never a full-page swap -- the
 * stepper stays visible either way. The "why this order" explainer is not
 * optional decoration -- being transparent about the algorithm (README,
 * then entry points, then breadth-first by centrality) is the whole
 * differentiator against an opaque chat suggestion, so it's rendered
 * unconditionally above the list, not tucked behind a toggle. */
export function TourPage() {
  const { repo, share } = useOutletContext<RepoOutletContext>();
  const [searchParams, setSearchParams] = useSearchParams();
  const glossaryOpen = searchParams.get("panel") === "glossary";
  const tour = useTour(repo.id, share);
  // Reuses RepoLayout's already-cached /status query (same queryKey) rather
  // than issuing a second network round trip -- needed only to resolve the
  // run id the tour-progress localStorage keys are scoped to.
  const status = useRepoStatus(repo.id, share);
  const runId = status.data?.current_run_id ?? status.data?.run_id ?? "unknown-run";

  function toggleGlossary() {
    setSearchParams(
      (prev) => {
        const merged = new URLSearchParams(prev);
        if (glossaryOpen) merged.delete("panel");
        else merged.set("panel", "glossary");
        return merged;
      },
      { replace: true },
    );
  }

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_340px]">
      <div className="flex min-w-0 flex-col gap-4">
        <WhyThisOrderPanel />
        <StageGate
          query={tour}
          loadingLabel="Computing the guided reading order…"
          emptyTitle="No tour stops yet"
          emptyMessage="This repo doesn't have enough structure (entry points, imports) to build a guided order."
          isEmpty={(data) => data.stops.length === 0}
        >
          {(data) => (
            <Card title="Guided reading order">
              <p className="mb-3 text-xs text-text-muted">
                Covers {data.subsystems_covered} of {data.of} subsystems
              </p>
              <ol className="flex flex-col">
                {data.stops.map((stop, i) => (
                  <TourStopItem
                    key={stop.position}
                    stop={stop}
                    repoId={repo.id}
                    runId={runId}
                    isLast={i === data.stops.length - 1}
                  />
                ))}
              </ol>
            </Card>
          )}
        </StageGate>
      </div>

      <div className="flex flex-col gap-4">
        {glossaryOpen ? (
          <GlossaryPanel repoId={repo.id} share={share} onClose={toggleGlossary} />
        ) : (
          <Card title="Domain glossary">
            <p className="mb-3 text-xs text-text-muted">
              This repository's own vocabulary — the words this codebase revolves around, mined from
              identifiers and file names. Distinct from the header glossary (top of the page), which
              explains Compass's own terms rather than this codebase's.
            </p>
            <button
              type="button"
              onClick={toggleGlossary}
              className="text-xs font-medium text-accent hover:underline"
            >
              Open glossary →
            </button>
          </Card>
        )}
      </div>
    </div>
  );
}

function WhyThisOrderPanel() {
  return (
    <Card title="Why this order">
      <p className="text-sm text-text-muted">
        This isn't a guess. The README comes first, if there is one. Then detected entry points
        (where a web server, CLI, or UI actually starts), ranked by how confidently they were
        detected. Everything else follows in breadth-first order through the dependency graph,
        starting from those entry points and expanding outward one import-hop at a time — within
        each hop, files more broadly relied on across the codebase (higher PageRank) come first. A
        subsystem with no representative in the capped list gets one swapped back in, so every
        subsystem is at least touched once. On a repository with few or no detected imports, this
        whole ordering degrades to a plain PageRank-desc sort — that is the expected behaviour on an
        import-sparse repo, not a bug.
      </p>
    </Card>
  );
}

function TourStopItem({
  stop,
  repoId,
  runId,
  isLast,
}: {
  stop: TourStopOut;
  repoId: string;
  runId: string;
  isLast: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const [done, setDone] = useState(() => isTourStopDone(repoId, runId, stop.file_path));
  const detail = stop.reason_detail as TourReasonDetail;

  function toggleDone(e: React.ChangeEvent<HTMLInputElement>) {
    const next = e.target.checked;
    setDone(next);
    setTourStopDone(repoId, runId, stop.file_path, next);
  }

  return (
    <li className={`flex gap-3 py-3 ${isLast ? "" : "border-b border-border"}`}>
      <div className="flex flex-col items-center pt-0.5">
        <input
          type="checkbox"
          checked={done}
          onChange={toggleDone}
          aria-label={`Mark ${stop.file_path} as read`}
          className="h-4 w-4 border-border-strong accent-accent"
        />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="cp-label">#{stop.position}</span>
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className={`truncate font-mono text-sm hover:underline ${done ? "text-text-muted line-through" : "text-text"}`}
            title={stop.file_path}
          >
            {stop.file_path}
          </button>
          <SubsystemBadge label={stop.subsystem_label} />
        </div>
        <p className="mt-0.5 text-xs text-text-muted">
          {TOUR_REASON_COPY[stop.reason_code](detail)}
        </p>
        <div className="mt-1.5">
          <MetricRow
            items={[
              { label: "in-deg", value: detail.in_degree ?? 0 },
              { label: "LOC", value: detail.loc ?? "—" },
              {
                label: "complexity",
                value: detail.complexity != null ? formatScore(detail.complexity, 1) : "—",
                tooltip: "complexity",
              },
              {
                label: "risk",
                value: detail.risk_score != null ? formatPercent(detail.risk_score) : "—",
                tooltip: "riskScore",
              },
              { label: "expert", value: detail.top_expert ?? "none", tooltip: "principalAuthor" },
            ]}
          />
        </div>

        {expanded ? (
          <div className="mt-2 flex flex-col gap-1.5 border-l-2 border-border-strong bg-bg-inset p-3 text-xs text-text-muted">
            <p>
              Last touched:{" "}
              {detail.last_touched_at
                ? new Date(detail.last_touched_at).toLocaleDateString()
                : "unknown"}
            </p>
            {detail.pagerank != null ? (
              <p className="flex items-center gap-1">
                Centrality (PageRank) {formatScore(detail.pagerank, 3)}
                <InfoTooltip label="What is centrality?" text={TOOLTIPS.centrality} />
              </p>
            ) : null}
            {detail.reasons ? (
              <p>
                Also qualified as:{" "}
                {Object.keys(detail.reasons)
                  .filter((code) => code !== stop.reason_code)
                  .map(
                    (code) =>
                      TOUR_REASON_COPY[code as keyof typeof TOUR_REASON_COPY]?.(detail) ?? code,
                  )
                  .join(" · ") || "no other rules"}
              </p>
            ) : null}
            <Link
              to={`/repos/${repoId}/people?path=${encodeURIComponent(stop.file_path)}`}
              className="w-fit font-medium text-accent hover:underline"
            >
              See who knows this file →
            </Link>
            <Link
              to={`/repos/${repoId}/structure?view=impact&path=${encodeURIComponent(stop.file_path)}`}
              className="w-fit font-medium text-accent hover:underline"
            >
              See its blast radius →
            </Link>
          </div>
        ) : null}
      </div>
    </li>
  );
}
