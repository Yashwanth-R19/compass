import { useMemo, useState } from "react";
import { Link, useOutletContext, useSearchParams } from "react-router-dom";
import {
  useContributors,
  useExpertise,
  useGlossary,
  useKnowledgeMap,
  useRepoStatus,
  useTour,
  useTruckFactor,
} from "../../api/hooks";
import type { ContributorOut, ExpertEntryOut, GlossaryTermOut, TourStopOut } from "../../api/types";
import { Card } from "../../components/ui/Card";
import { InfoTooltip } from "../../components/ui/InfoTooltip";
import { SegmentedControl } from "../../components/ui/SegmentedControl";
import { ContributorChip } from "../../components/ContributorChip";
import { EmptyState } from "../../components/EmptyState";
import { ErrorState } from "../../components/ErrorState";
import { Expander } from "../../components/motion/Expander";
import { FilePicker } from "../../components/FilePicker";
import { HonestyNote } from "../../components/HonestyNote";
import { LoadingState } from "../../components/LoadingState";
import {
  ScoreExplainer,
  type ScoreExplainerAlsoMeasuredValue,
} from "../../components/ScoreExplainer";
import { AnimatedList } from "../../reactbits/AnimatedList";
import { Reveal } from "../../components/motion/Reveal";
import { StageGate } from "../../components/StageGate";
import { SubsystemBadge } from "../../components/SubsystemBadge";
import { TOUR_REASON_COPY, type TourReasonDetail } from "../../lib/copy";
import { HONESTY, TOOLTIPS } from "../../content/explainability";
import { markChecklistFlag } from "../../lib/checklist";
import { formatPercent, formatScore } from "../../lib/format";
import { isTourStopDone, setTourStopDone } from "../../lib/tourProgress";
import type { RepoOutletContext } from "../RepoLayout";

type GuideView = "tour" | "glossary" | "people";

function isGuideView(v: string | null): v is GuideView {
  return v === "tour" || v === "glossary" || v === "people";
}

const MAX_VISIBLE_CONTRIBUTORS = 25;

/** `/repos/:id/guide` (rebuild spec section 4.2) -- "how do I get into this
 * codebase, and who do I ask." Merges the former Tour, Glossary, and People
 * surfaces behind one `?view=` switch. plan/RULES.md section 11 is a HARD
 * requirement across all three views: no email is ever rendered, masked or
 * otherwise; no rank numerals or "top contributor" framing -- the
 * vocabulary throughout is knowledge DISTRIBUTION ("principal author",
 * "expert", "concentration"), never performance. */
export function GuideSurfacePage() {
  const { repo, share } = useOutletContext<RepoOutletContext>();
  const [searchParams, setSearchParams] = useSearchParams();
  const urlView = searchParams.get("view");
  const [view, setView] = useState<GuideView>(isGuideView(urlView) ? urlView : "tour");

  function changeView(next: string) {
    setView(next as GuideView);
    setSearchParams(
      (prev) => {
        const merged = new URLSearchParams(prev);
        merged.set("view", next);
        return merged;
      },
      { replace: true },
    );
  }

  const activeView = isGuideView(urlView) ? urlView : view;

  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm text-text-muted">
        A guided place to start reading, this codebase's own vocabulary, and who has principal
        knowledge of a given file.
      </p>
      <SegmentedControl
        aria-label="Guide view"
        value={activeView}
        onValueChange={changeView}
        options={[
          { value: "tour", label: "Tour" },
          { value: "glossary", label: "Glossary" },
          { value: "people", label: "People" },
        ]}
      />
      {activeView === "glossary" ? (
        <GlossaryView repoId={repo.id} share={share} />
      ) : activeView === "people" ? (
        <PeopleView repoId={repo.id} share={share} />
      ) : (
        <TourView repoId={repo.id} share={share} />
      )}
    </div>
  );
}

// =============================================================================
// Tour
// =============================================================================

function TourView({ repoId, share }: { repoId: string; share?: string }) {
  const tour = useTour(repoId, share);
  // Reuses RepoLayout's already-cached /status query (same queryKey) rather
  // than issuing a second network round trip -- needed only to resolve the
  // run id the tour-progress localStorage keys are scoped to.
  const status = useRepoStatus(repoId, share);
  const runId = status.data?.current_run_id ?? status.data?.run_id ?? "unknown-run";

  return (
    <div className="flex flex-col gap-4">
      <Reveal>
        <WhyThisOrderPanel />
      </Reveal>
      <StageGate
        query={tour}
        loadingLabel="Computing the guided reading order…"
        emptyTitle="No tour stops yet"
        emptyMessage="This repo doesn't have enough structure (entry points, imports) to build a guided order."
        isEmpty={(data) => data.stops.length === 0}
      >
        {(data) => (
          <Reveal delay={0.05}>
            <Card title="Guided reading order">
              <p className="mb-3 text-xs text-text-muted">
                Covers {data.subsystems_covered} of {data.of} subsystems
              </p>
              <AnimatedList
                items={data.stops}
                keyFor={(stop) => stop.position}
                className="flex flex-col"
                renderItem={(stop, i) => (
                  <TourStopItem
                    stop={stop}
                    repoId={repoId}
                    runId={runId}
                    isLast={i === data.stops.length - 1}
                  />
                )}
              />
            </Card>
          </Reveal>
        )}
      </StageGate>
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
  const [done, setDone] = useState(() => isTourStopDone(repoId, runId, stop.file_path));
  const detail = stop.reason_detail as TourReasonDetail;

  function toggleDone(e: React.ChangeEvent<HTMLInputElement>) {
    const next = e.target.checked;
    setDone(next);
    setTourStopDone(repoId, runId, stop.file_path, next);
  }

  return (
    <div className={`flex gap-3 py-3 ${isLast ? "" : "border-b border-border"}`}>
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
          <span
            className={`truncate font-mono text-sm ${done ? "text-text-muted line-through" : "text-text"}`}
            title={stop.file_path}
          >
            {stop.file_path}
          </span>
          <SubsystemBadge label={stop.subsystem_label} />
        </div>
        <p className="mt-0.5 text-xs text-text-muted">
          {TOUR_REASON_COPY[stop.reason_code](detail)}
        </p>

        <Expander
          className="mt-1.5"
          trigger={
            <span className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-text-muted">
              <span>in-deg {detail.in_degree ?? 0}</span>
              <span>LOC {detail.loc ?? "—"}</span>
              <span>
                complexity {detail.complexity != null ? formatScore(detail.complexity, 1) : "—"}
              </span>
              <span>risk {detail.risk_score != null ? formatPercent(detail.risk_score) : "—"}</span>
              <span>expert {detail.top_expert ?? "none"}</span>
            </span>
          }
        >
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
              to={`/repos/${repoId}/guide?view=people&path=${encodeURIComponent(stop.file_path)}`}
              className="w-fit font-medium text-accent hover:underline"
            >
              See who knows this file →
            </Link>
            <Link
              to={`/repos/${repoId}/explore?view=impact&path=${encodeURIComponent(stop.file_path)}`}
              className="w-fit font-medium text-accent hover:underline"
            >
              See its blast radius →
            </Link>
          </div>
        </Expander>
      </div>
    </div>
  );
}

// =============================================================================
// Glossary
// =============================================================================

function GlossaryView({ repoId, share }: { repoId: string; share?: string }) {
  const glossary = useGlossary(repoId, share);

  return (
    <StageGate
      query={glossary}
      loadingLabel="Extracting domain vocabulary…"
      emptyTitle="No terms extracted"
      emptyMessage="Not enough named symbols or file stems were found to build a glossary."
      isEmpty={(data) => data.terms.length === 0}
    >
      {(data) => (
        <Reveal>
          <div className="flex flex-col gap-3">
            {/* GlossaryResponse.limitation, rendered verbatim -- never
                paraphrased. This extracts vocabulary, not definitions. */}
            <HonestyNote variant="scope-limitation" text={data.limitation} />
            <p className="text-xs text-text-muted">
              This is this repository's own vocabulary, distinct from the header glossary (⌘K or the
              header button), which explains Compass's own terms.
            </p>
            <Card
              title="Domain vocabulary"
              eyebrow={`${data.terms.length} term${data.terms.length === 1 ? "" : "s"}, ranked by how much this codebase revolves around them`}
              action={
                <InfoTooltip
                  label="What is the glossary term score?"
                  text={TOOLTIPS.glossaryTermScore}
                />
              }
            >
              <AnimatedList
                items={data.terms}
                keyFor={(term) => term.term}
                className="flex flex-col divide-y divide-border"
                renderItem={(term) => <GlossaryTermRow term={term} repoId={repoId} />}
              />
            </Card>
          </div>
        </Reveal>
      )}
    </StageGate>
  );
}

function GlossaryTermRow({ term, repoId }: { term: GlossaryTermOut; repoId: string }) {
  return (
    <div className="py-2.5">
      <Expander
        trigger={
          <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <span className="font-mono text-sm font-medium text-text">{term.term}</span>
            <span className="text-xs text-text-muted">
              {term.occurrences} occurrence{term.occurrences === 1 ? "" : "s"}
            </span>
            <span className="text-xs text-text-muted">
              spans {term.subsystem_spread} subsystem{term.subsystem_spread === 1 ? "" : "s"}
            </span>
          </span>
        }
      >
        <div className="mt-1.5 ml-1 flex flex-col gap-2">
          {term.defining_paths.length > 0 ? (
            <ul className="flex flex-col gap-1">
              {term.defining_paths.map((path) => (
                <li key={path}>
                  <Link
                    to={`/repos/${repoId}/guide?view=people&path=${encodeURIComponent(path)}`}
                    className="font-mono text-xs text-text-muted hover:text-accent hover:underline"
                  >
                    {path}
                  </Link>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-xs text-text-muted">No defining file found for this term.</p>
          )}
          <ScoreExplainer formulaKey="glossary_term_score" contributions={[]} />
        </div>
      </Expander>
    </div>
  );
}

// =============================================================================
// People
// =============================================================================

function PeopleView({ repoId, share }: { repoId: string; share?: string }) {
  const [searchParams] = useSearchParams();

  return (
    <div className="flex flex-col gap-6">
      <Reveal>
        <WhoDoIAskCard repoId={repoId} share={share} initialPath={searchParams.get("path")} />
      </Reveal>
      <Reveal delay={0.05}>
        <ContributorsCard repoId={repoId} share={share} />
      </Reveal>
      <Reveal delay={0.1}>
        <TruckFactorCard repoId={repoId} share={share} />
      </Reveal>
    </div>
  );
}

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
              <AnimatedList
                items={experts}
                keyFor={(e) => e.contributor_id}
                className="divide-y divide-border"
                renderItem={(e) => (
                  <div className="flex flex-wrap items-center gap-3 py-2.5">
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
                  </div>
                )}
              />
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
          const shareOf = (c: ContributorOut) =>
            totalCommits > 0 ? c.commit_count / totalCommits : 0;
          // /contributors returns every resolved identity, uncapped -- a
          // widely-contributed-to repo (psf/requests: 731) renders an
          // unusably long page without this cut (found during this
          // session's own end-to-end sweep against that exact repo).
          const visible = data.contributors.slice(0, MAX_VISIBLE_CONTRIBUTORS);
          const rest = data.contributors.slice(MAX_VISIBLE_CONTRIBUTORS);
          return (
            <>
              <AnimatedList
                items={visible}
                keyFor={(c) => c.id}
                className="flex flex-col divide-y divide-border"
                renderItem={(c) => <ContributorRow contributor={c} share={shareOf(c)} />}
              />
              {rest.length > 0 ? (
                <Expander
                  className="py-2"
                  trigger={`${rest.length} more contributor${rest.length === 1 ? "" : "s"}`}
                >
                  <ul className="flex flex-col divide-y divide-border pt-1">
                    {rest.map((c) => (
                      <li key={c.id}>
                        <ContributorRow contributor={c} share={shareOf(c)} />
                      </li>
                    ))}
                  </ul>
                </Expander>
              ) : null}
            </>
          );
        }}
      </StageGate>
    </Card>
  );
}

function ContributorRow({ contributor, share }: { contributor: ContributorOut; share: number }) {
  const otherAliases = contributor.aliases.filter((a) => a.name !== contributor.canonical_name);

  const row = (
    <div className="flex flex-wrap items-center gap-3 py-2.5">
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
        <span className="cp-label rounded-full border border-border px-1.5 py-0.5 text-text-muted">
          {otherAliases.length} more alias{otherAliases.length === 1 ? "" : "es"}
        </span>
      ) : null}
    </div>
  );

  if (otherAliases.length === 0) return row;

  return (
    <Expander trigger={row}>
      <p className="mb-1.5 text-xs text-text-muted">
        {otherAliases.length} merged {otherAliases.length === 1 ? "identity" : "identities"}
      </p>
      <ul className="ml-1 flex flex-wrap gap-2 pb-2">
        {otherAliases.map((a, i) => (
          // Name only -- never the masked email either, even here in an
          // expandable, non-prominent detail (plan/RULES.md sec 11.2). Two
          // aliases can share a display name (same name, different email
          // merged into this identity), so the key is index-qualified.
          <li
            key={`${a.name}-${i}`}
            className="rounded-full border border-border px-2 py-0.5 text-xs text-text-muted"
          >
            {a.name}
          </li>
        ))}
      </ul>
    </Expander>
  );
}

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
            {/* The fixed interpretation string, rendered verbatim -- never
                paraphrased (plan/RULES.md sec 11.4). */}
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
