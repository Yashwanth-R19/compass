import { useMemo, useState } from "react";
import { useOutletContext, useSearchParams } from "react-router-dom";
import { useContributors, useExpertise, useKnowledgeMap, useTruckFactor } from "../../api/hooks";
import type { ContributorOut, ExpertEntryOut } from "../../api/types";
import { Card } from "../../components/ui/Card";
import { InfoTooltip } from "../../components/ui/InfoTooltip";
import { ContributorChip } from "../../components/ContributorChip";
import { EmptyState } from "../../components/EmptyState";
import { ErrorState } from "../../components/ErrorState";
import { FilePicker } from "../../components/FilePicker";
import { HonestyNote } from "../../components/HonestyNote";
import { LoadingState } from "../../components/LoadingState";
import {
  ScoreExplainer,
  type ScoreExplainerAlsoMeasuredValue,
} from "../../components/ScoreExplainer";
import { StageGate } from "../../components/StageGate";
import { formatPercent } from "../../lib/format";
import { markChecklistFlag } from "../../lib/checklist";
import { HONESTY, TOOLTIPS } from "../../content/explainability";
import type { RepoOutletContext } from "../RepoLayout";

/** Knowledge distribution across the repository's contributors (UI rebuild
 * session 3, Part D). plan/RULES.md section 11 is a HARD requirement here:
 *
 * - No email, masked or full, is ever rendered anywhere on this page --
 *   `ContributorChip` and every element below only ever read `.canonical_name`/
 *   `.name`, never `.canonical_email_masked`/`.email_masked`, so there is no
 *   field through which one could accidentally render (see
 *   PeoplePage.test.tsx's dedicated no-"@" assertion).
 * - Framing is knowledge distribution, never performance evaluation --
 *   "principal author", "expert", "knowledge concentration", never
 *   "productivity" or "top contributor" as a ranking claim. Contributor
 *   order is a plain list by commit count (activity), with no medals, no
 *   "#1", no rank numerals at all (rule V7: numerals only where the
 *   backend genuinely ranked something the user should act on -- and a
 *   knowledge-distribution list is explicitly not that).
 */
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

  const experts: ExpertEntryOut[] =
    expertise.data?.kind === "data" ? expertise.data.data.experts : [];
  const topExpert = experts[0];
  const alsoMeasured: ScoreExplainerAlsoMeasuredValue[] | undefined = topExpert
    ? [
        { label: "Changes to this file", value: String(topExpert.changes) },
        {
          label: "Last touched",
          value: new Date(topExpert.last_touched_at).toLocaleDateString(),
        },
        { label: "Contributor is stale", value: topExpert.is_stale ? "yes" : "no" },
      ]
    : undefined;

  return (
    <Card
      title="Who do I ask?"
      action={<InfoTooltip label="What is an expert?" text={TOOLTIPS.expert} />}
    >
      <p className="mb-3 text-xs text-text-muted">Search for a file to see its experts.</p>
      <HonestyNote
        variant="scope-limitation"
        text={HONESTY.botsExcludedFromAuthorship}
        className="mb-3"
      />
      <div className="flex flex-col gap-4">
        <FilePicker
          paths={paths}
          onSelect={(path) => {
            setSelectedPath(path);
            markChecklistFlag("asked_who_to_ask");
          }}
          placeholder="Search files by path…"
        />

        {selectedPath ? (
          expertise.isPending ? (
            <LoadingState label="Loading experts…" />
          ) : expertise.isError ? (
            <ErrorState error={expertise.error} onRetry={() => void expertise.refetch()} />
          ) : expertise.data.kind === "pending" ? (
            <LoadingState label="Loading experts…" />
          ) : experts.length === 0 ? (
            <EmptyState
              title="No experts found"
              message="Nobody has enough sustained history on this file to qualify as an expert yet -- or the file has only ever been touched by a bot, which is never scored as an expert."
            />
          ) : (
            <>
              <ul className="divide-y divide-border">
                {experts.map((e) => (
                  <li key={e.contributor_id} className="flex flex-wrap items-center gap-3 py-2.5">
                    <ContributorChip name={e.canonical_name} isStale={e.is_stale} />
                    {e.is_expert ? (
                      <span className="rounded-full border border-accent-border bg-accent-bg px-2 py-0.5 text-xs font-medium text-accent">
                        expert
                      </span>
                    ) : null}
                    <span className="flex items-center gap-1 text-xs text-text-muted">
                      DOA {formatPercent(e.doa_normalized)}
                      <InfoTooltip
                        label="What is degree of authorship?"
                        text={TOOLTIPS.degreeOfAuthorship}
                      />
                    </span>
                    <span className="text-xs text-text-muted">{e.changes} changes</span>
                    <span className="text-xs text-text-muted">
                      last touched {new Date(e.last_touched_at).toLocaleDateString()}
                    </span>
                  </li>
                ))}
              </ul>
              <ScoreExplainer
                formulaKey="expertise"
                contributions={[]}
                alsoMeasured={alsoMeasured}
              />
            </>
          )
        ) : (
          <p className="text-sm text-text-muted">
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
    <Card title="Contributors">
      <p className="mb-2 text-xs text-text-muted">
        Ranked by activity — commit share, not a productivity score.
      </p>
      <div className="mb-3 flex flex-col gap-1.5">
        <HonestyNote variant="scope-limitation" text={HONESTY.identityMergingIsRuleBasedNotFuzzy} />
        <HonestyNote variant="confidence-caveat" text={HONESTY.staleMeasuredAgainstRepoActivity} />
      </div>
      <StageGate
        query={contributors}
        loadingLabel="Loading contributors…"
        emptyTitle="No contributors found"
        emptyMessage="This repository has no commit history to derive contributors from."
        isEmpty={(data) => data.contributors.length === 0}
      >
        {(data) => {
          const totalCommits = data.contributors.reduce((sum, c) => sum + c.commit_count, 0);
          return (
            <ul className="flex flex-col divide-y divide-border">
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
        <div className="h-1.5 w-24 overflow-hidden rounded-full bg-bg-inset">
          <div
            className="h-full rounded-full bg-accent"
            style={{ width: `${Math.round(share * 100)}%` }}
          />
        </div>
        <span className="text-xs tabular-nums text-text-muted">
          {formatPercent(share)} of commits
        </span>
        <span className="text-xs text-text-muted">
          active {new Date(contributor.first_commit_at).toLocaleDateString()}–
          {new Date(contributor.last_commit_at).toLocaleDateString()}
        </span>
        {otherAliases.length > 0 ? (
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="text-xs font-medium text-accent hover:underline"
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
            // expandable, non-prominent detail (plan/RULES.md sec 11.2).
            <li
              key={a.name}
              className="rounded-full border border-border px-2 py-0.5 text-xs text-text-muted"
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
    <Card
      title="Truck factor"
      action={<InfoTooltip label="What is truck factor?" text={TOOLTIPS.truckFactor} />}
    >
      <StageGate query={truckFactor} loadingLabel="Computing truck factor…">
        {(data) => (
          <div className="flex flex-col gap-3">
            <div className="flex items-baseline gap-2">
              <span className="cp-stat text-3xl font-semibold text-text">{data.value}</span>
              <span className="text-xs text-text-muted">
                {data.value === 1 ? "person" : "people"}
              </span>
            </div>
            <p className="text-xs text-text-muted">{data.interpretation}</p>
            {data.note ? <p className="text-xs text-warning">{data.note}</p> : null}

            {data.removal_order.length > 0 ? (
              <ol className="flex flex-wrap items-center gap-x-1.5 gap-y-2 text-sm text-text-muted">
                {data.removal_order.map((step, i) => (
                  <li key={step.contributor_id} className="flex items-center gap-1.5">
                    {i > 0 ? <span className="text-text-muted/50">;</span> : null}
                    <span>
                      {i > 0 ? "also remove " : "remove "}
                      <span className="font-medium text-text">{step.name}</span> →{" "}
                      <span className="tabular-nums">
                        {formatPercent(step.cumulative_orphan_ratio)}
                      </span>{" "}
                      of files orphaned
                    </span>
                  </li>
                ))}
              </ol>
            ) : null}

            <p className="text-xs text-text-muted">
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
