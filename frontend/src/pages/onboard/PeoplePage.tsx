import { useMemo, useState } from "react";
import { useOutletContext, useSearchParams } from "react-router-dom";
import { useContributors, useExpertise, useKnowledgeMap, useTruckFactor } from "../../api/hooks";
import type { ContributorOut } from "../../api/types";
import { Card } from "../../components/Card";
import { ContributorChip } from "../../components/ContributorChip";
import { EmptyState } from "../../components/EmptyState";
import { ErrorState } from "../../components/ErrorState";
import { FilePicker } from "../../components/FilePicker";
import { LoadingState } from "../../components/LoadingState";
import { StageGate } from "../../components/StageGate";
import { formatPercent } from "../../lib/format";
import type { RepoOutletContext } from "../RepoLayout";

/** Part E: three panes. The flagship "who do I ask" search sits first and
 * has to feel instant -- FilePicker's filtering is a synchronous in-memory
 * substring match (Part B.2), so the only latency between picking a file
 * and seeing its experts is the /expertise request itself.
 *
 * DISPLAY RULES (plan/RULES.md sec 11, non-negotiable): no full or masked
 * email is ever rendered on this page (Known Hazard #5 -- the API returns
 * masked forms, but even those are kept out of the DOM here entirely, not
 * just de-emphasized). No leaderboard styling -- no medals, no "#1", no
 * "top contributor" as a performance claim; contributor order is shown as a
 * plain list, and the words used are "principal author" / "expert" /
 * "knowledge distribution", never "productivity" or "score" (Known Hazard
 * #4). */
export function PeoplePage() {
  const { repo, share } = useOutletContext<RepoOutletContext>();
  const [searchParams] = useSearchParams();

  return (
    <div className="flex flex-col gap-6">
      <WhoDoIAskCard repoId={repo.id} share={share} initialPath={searchParams.get("path")} />
      <ContributorsCard repoId={repo.id} share={share} />
      <TruckFactorCard repoId={repo.id} share={share} />
    </div>
  );
}

// --- 1. Who do I ask ---------------------------------------------------------

function WhoDoIAskCard({
  repoId,
  share,
  initialPath,
}: {
  repoId: string;
  share?: string;
  initialPath: string | null;
}) {
  const knowledgeMap = useKnowledgeMap(repoId, share);
  const [selectedPath, setSelectedPath] = useState<string | null>(initialPath);
  const expertise = useExpertise(repoId, selectedPath ?? undefined, share);

  const paths = useMemo(() => {
    if (knowledgeMap.data?.kind !== "data") return [];
    return knowledgeMap.data.data.files.map((f) => f.file_path);
  }, [knowledgeMap.data]);

  return (
    <Card title="Who do I ask?" subtitle="Search for a file to see its experts">
      <div className="flex flex-col gap-4">
        <FilePicker paths={paths} onSelect={setSelectedPath} placeholder="Search files by path…" />

        {selectedPath ? (
          expertise.isPending ? (
            <LoadingState label="Loading experts…" />
          ) : expertise.isError ? (
            <ErrorState error={expertise.error} onRetry={() => void expertise.refetch()} />
          ) : expertise.data.kind === "pending" ? (
            <LoadingState label="Loading experts…" />
          ) : expertise.data.data.experts.length === 0 ? (
            <EmptyState
              title="No experts found"
              message="Nobody has enough sustained history on this file to qualify as an expert yet."
            />
          ) : (
            <ul className="divide-y divide-slate-100 dark:divide-slate-800">
              {expertise.data.data.experts.map((e) => (
                <li key={e.contributor_id} className="flex flex-wrap items-center gap-3 py-2.5">
                  <ContributorChip name={e.canonical_name} isStale={e.is_stale} />
                  {e.is_expert ? (
                    <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-400">
                      expert
                    </span>
                  ) : null}
                  <span className="text-xs text-ink-muted">
                    DOA {formatPercent(e.doa_normalized)}
                  </span>
                  <span className="text-xs text-ink-muted">{e.changes} changes</span>
                  <span className="text-xs text-ink-faint">
                    last touched {new Date(e.last_touched_at).toLocaleDateString()}
                  </span>
                </li>
              ))}
            </ul>
          )
        ) : (
          <p className="text-sm text-ink-faint">
            Pick a file above to see who has principal authorship over it.
          </p>
        )}
      </div>
    </Card>
  );
}

// --- 2. Contributors ---------------------------------------------------------

function ContributorsCard({ repoId, share }: { repoId: string; share?: string }) {
  const contributors = useContributors(repoId, share);

  return (
    <Card
      title="Contributors"
      subtitle="Ranked by activity — commit share, not a productivity score"
    >
      <StageGate
        query={contributors}
        loadingLabel="Loading contributors…"
        emptyTitle="No contributors found"
        isEmpty={(data) => data.contributors.length === 0}
      >
        {(data) => {
          const totalCommits = data.contributors.reduce((sum, c) => sum + c.commit_count, 0);
          return (
            <ul className="flex flex-col divide-y divide-slate-100 dark:divide-slate-800">
              {data.contributors.map((c) => (
                <ContributorRow
                  key={c.id}
                  contributor={c}
                  share={totalCommits > 0 ? c.commit_count / totalCommits : 0}
                />
              ))}
            </ul>
          );
        }}
      </StageGate>
    </Card>
  );
}

function ContributorRow({ contributor, share }: { contributor: ContributorOut; share: number }) {
  const [expanded, setExpanded] = useState(false);
  const otherAliases = contributor.aliases.filter((a) => a.name !== contributor.canonical_name);

  return (
    <li className="py-2.5">
      <div className="flex flex-wrap items-center gap-3">
        <ContributorChip
          name={contributor.canonical_name}
          isStale={contributor.is_stale}
          isBot={contributor.is_bot}
        />
        <div className="h-1.5 w-24 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
          <div
            className="h-full rounded-full bg-indigo-500"
            style={{ width: `${Math.round(share * 100)}%` }}
          />
        </div>
        <span className="text-xs tabular-nums text-ink-muted">
          {formatPercent(share)} of commits
        </span>
        <span className="text-xs text-ink-faint">
          active {new Date(contributor.first_commit_at).toLocaleDateString()}–
          {new Date(contributor.last_commit_at).toLocaleDateString()}
        </span>
        {otherAliases.length > 0 ? (
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="text-xs font-medium text-indigo-600 hover:underline dark:text-indigo-400"
          >
            {expanded ? "Hide" : "Show"} {otherAliases.length} merged{" "}
            {otherAliases.length === 1 ? "identity" : "identities"}
          </button>
        ) : null}
      </div>
      {expanded ? (
        <ul className="mt-1.5 ml-1 flex flex-wrap gap-2">
          {otherAliases.map((a) => (
            // Name only -- never the masked email either, even here in an
            // expandable, non-prominent detail (Known Hazard #5).
            <li
              key={a.name}
              className="rounded-full bg-slate-50 px-2 py-0.5 text-xs text-ink-muted dark:bg-slate-800/60"
            >
              {a.name}
            </li>
          ))}
        </ul>
      ) : null}
    </li>
  );
}

// --- 3. Truck factor ----------------------------------------------------------

function TruckFactorCard({ repoId, share }: { repoId: string; share?: string }) {
  const truckFactor = useTruckFactor(repoId, share);

  return (
    <Card title="Truck factor">
      <StageGate query={truckFactor} loadingLabel="Computing truck factor…">
        {(data) => (
          <div className="flex flex-col gap-3">
            <div className="flex items-baseline gap-2">
              <span className="text-3xl font-semibold tabular-nums text-ink">{data.value}</span>
              <span className="text-xs text-ink-faint">
                {data.value === 1 ? "person" : "people"}
              </span>
            </div>
            <p className="text-xs text-ink-muted">{data.interpretation}</p>
            {data.note ? (
              <p className="text-xs text-amber-600 dark:text-amber-400">{data.note}</p>
            ) : null}

            {data.removal_order.length > 0 ? (
              <ol className="flex flex-wrap items-center gap-x-1.5 gap-y-2 text-sm text-ink-muted">
                {data.removal_order.map((step, i) => (
                  <li key={step.contributor_id} className="flex items-center gap-1.5">
                    {i > 0 ? <span className="text-ink-faint">;</span> : null}
                    <span>
                      {i > 0 ? "also remove " : "remove "}
                      <span className="font-medium">{step.name}</span> →{" "}
                      <span className="tabular-nums">
                        {formatPercent(step.cumulative_orphan_ratio)}
                      </span>{" "}
                      of files orphaned
                    </span>
                  </li>
                ))}
              </ol>
            ) : null}

            <p className="text-xs text-ink-faint">
              {data.orphaned_file_count} of {data.total_files_considered} files currently have no
              non-stale expert{data.total_files_considered > 0 ? "" : " (no files were considered)"}
              .
            </p>
          </div>
        )}
      </StageGate>
    </Card>
  );
}
