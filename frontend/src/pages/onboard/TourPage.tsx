import { useState } from "react";
import { Link, useOutletContext } from "react-router-dom";
import { useRepoStatus, useTour } from "../../api/hooks";
import type { TourStopOut } from "../../api/types";
import { Card } from "../../components/Card";
import { MetricRow } from "../../components/MetricRow";
import { StageGate } from "../../components/StageGate";
import { SubsystemBadge } from "../../components/SubsystemBadge";
import { TOUR_REASON_COPY, type TourReasonDetail } from "../../lib/copy";
import { formatScore, formatPercent } from "../../lib/format";
import { isTourStopDone, setTourStopDone } from "../../lib/tourProgress";
import type { RepoOutletContext } from "../RepoLayout";

/** A guided reading list, presented as a vertical stepper (Part D). The
 * "why this order" explainer is not optional decoration -- being transparent
 * about the algorithm (README, then entry points, then breadth-first by
 * centrality) is the whole differentiator against an opaque chat
 * suggestion, so it's rendered unconditionally above the list, not tucked
 * behind a toggle. */
export function TourPage() {
  const { repo, share } = useOutletContext<RepoOutletContext>();
  const tour = useTour(repo.id, share);
  // Reuses RepoLayout's already-cached /status query (same queryKey) rather
  // than issuing a second network round trip -- needed only to resolve the
  // run id the tour-progress localStorage keys are scoped to.
  const status = useRepoStatus(repo.id, share);
  const runId = status.data?.current_run_id ?? status.data?.run_id ?? "unknown-run";

  return (
    <div className="flex flex-col gap-4">
      <WhyThisOrderPanel />
      <StageGate
        query={tour}
        loadingLabel="Computing the guided reading order…"
        emptyTitle="No tour stops yet"
        emptyMessage="This repo doesn't have enough structure (entry points, imports) to build a guided order."
        isEmpty={(data) => data.stops.length === 0}
      >
        {(data) => (
          <Card
            title="Guided reading order"
            subtitle={`Covers ${data.subsystems_covered} of ${data.of} subsystems`}
          >
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
  );
}

function WhyThisOrderPanel() {
  return (
    <Card title="Why this order">
      <p className="text-sm text-slate-600 dark:text-slate-300">
        This isn't a guess. The README comes first, if there is one. Then detected entry points
        (where a web server, CLI, or UI actually starts), ranked by how confidently they were
        detected. Everything else follows in breadth-first order through the dependency graph,
        starting from those entry points and expanding outward one import-hop at a time — within
        each hop, files more broadly relied on across the codebase (higher PageRank) come first. A
        subsystem with no representative in the capped list gets one swapped back in, so every
        subsystem is at least touched once.
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
    <li
      className={`flex gap-3 py-3 ${isLast ? "" : "border-b border-slate-100 dark:border-slate-800"}`}
    >
      <div className="flex flex-col items-center pt-0.5">
        <input
          type="checkbox"
          checked={done}
          onChange={toggleDone}
          aria-label={`Mark ${stop.file_path} as read`}
          className="h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500 dark:border-slate-600"
        />
      </div>
      <div className="flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs font-medium text-slate-400 dark:text-slate-500">
            #{stop.position}
          </span>
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className={`truncate font-mono text-sm hover:underline ${done ? "text-slate-400 line-through dark:text-slate-600" : "text-slate-800 dark:text-slate-200"}`}
            title={stop.file_path}
          >
            {stop.file_path}
          </button>
          <SubsystemBadge label={stop.subsystem_label} />
        </div>
        <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">
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
              },
              {
                label: "risk",
                value: detail.risk_score != null ? formatPercent(detail.risk_score) : "—",
              },
              { label: "expert", value: detail.top_expert ?? "none" },
            ]}
          />
        </div>

        {expanded ? (
          <div className="mt-2 flex flex-col gap-1.5 rounded-md bg-slate-50 p-3 text-xs text-slate-600 dark:bg-slate-800/60 dark:text-slate-300">
            <p>
              Last touched:{" "}
              {detail.last_touched_at
                ? new Date(detail.last_touched_at).toLocaleDateString()
                : "unknown"}
            </p>
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
              to={`/repos/${repoId}/onboard/people?path=${encodeURIComponent(stop.file_path)}`}
              className="w-fit font-medium text-indigo-600 hover:underline dark:text-indigo-400"
            >
              See who knows this file →
            </Link>
            <Link
              to={`/repos/${repoId}/onboard/impact?path=${encodeURIComponent(stop.file_path)}`}
              className="w-fit font-medium text-indigo-600 hover:underline dark:text-indigo-400"
            >
              See its blast radius →
            </Link>
          </div>
        ) : null}
      </div>
    </li>
  );
}
