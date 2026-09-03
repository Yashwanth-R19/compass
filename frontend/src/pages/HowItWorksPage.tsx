import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  Boxes,
  FolderTree,
  GitBranch,
  GitCommitHorizontal,
  KeyRound,
  Link2,
  ListOrdered,
  Network,
  Save,
  ShieldAlert,
  Sparkles,
  Users,
  type LucideIcon,
} from "lucide-react";
import { WordReveal } from "../components/motion/WordReveal";
import { Reveal } from "../components/motion/Reveal";
import { Alert } from "../components/ui/Alert";
import { usePipeline, useWorkedExample } from "../api/hooks";
import { usePrefersReducedMotion } from "../hooks/usePrefersReducedMotion";
import {
  EMPTY_MESSAGES,
  NOT_AI_WRAPPER_POINTS,
  WHAT_COMPASS_DOES_NOT_DO,
} from "../content/explainability";
import type { PipelineStageOut, WorkedExampleResponse } from "../api/types";

const STAGE_ICON: Record<string, LucideIcon> = {
  clone: GitBranch,
  mine: GitCommitHorizontal,
  structure: FolderTree,
  persist_facts: Save,
  secrets: KeyRound,
  coupling: Link2,
  subsystems: Boxes,
  architecture: Network,
  risk: Sparkles,
  knowledge: Users,
  onboarding: FolderTree,
  security: ShieldAlert,
  rank: ListOrdered,
};

function formatScore(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

/** One concrete, real line per stage built from the worked example's
 * already-persisted figures — never computed or estimated here. A stage
 * whose own distinctive figures are unavailable (null) for this run simply
 * has no line at all; a stage with no distinctive figure of its own
 * (clone, persist_facts) never had one to begin with. */
const STAGE_EXAMPLE_LINE: Record<string, (w: WorkedExampleResponse) => string | null> = {
  mine: (w) =>
    w.commit_count != null
      ? `This stage streamed ${w.commit_count.toLocaleString()} commits from the repository's full history.`
      : null,
  structure: (w) =>
    w.file_count != null && w.symbol_count != null && w.dependency_edge_count != null
      ? `This stage found ${w.file_count.toLocaleString()} files, ${w.symbol_count.toLocaleString()} symbol declarations, and ${w.dependency_edge_count.toLocaleString()} import edges.`
      : null,
  secrets: (w) =>
    w.secret_hit_count != null
      ? `This stage scanned the full commit history and found ${w.secret_hit_count.toLocaleString()} potential secret${w.secret_hit_count === 1 ? "" : "s"}.`
      : null,
  coupling: (w) =>
    w.coupling_pair_count != null
      ? `This stage found ${w.coupling_pair_count.toLocaleString()} file pairs meeting the change-coupling threshold.`
      : null,
  subsystems: (w) =>
    w.subsystem_count != null
      ? `This stage partitioned the repository into ${w.subsystem_count} subsystem${w.subsystem_count === 1 ? "" : "s"}${
          w.subsystem_labels?.length ? `: ${w.subsystem_labels.join(", ")}.` : "."
        }`
      : null,
  architecture: (w) =>
    w.cycle_count != null && w.hidden_dependency_count != null && w.entry_point_count != null
      ? `This stage found ${w.cycle_count} circular dependency chain${w.cycle_count === 1 ? "" : "s"}, ${w.hidden_dependency_count} hidden dependency pair${w.hidden_dependency_count === 1 ? "" : "s"}, and ${w.entry_point_count} entry point${w.entry_point_count === 1 ? "" : "s"}.`
      : null,
  risk: (w) =>
    w.hotspot_count != null
      ? `This stage flagged ${w.hotspot_count} file${w.hotspot_count === 1 ? "" : "s"} as a risk hotspot.`
      : null,
  knowledge: (w) =>
    w.contributor_count != null && w.truck_factor != null
      ? `This stage identified ${w.contributor_count} contributor${w.contributor_count === 1 ? "" : "s"} and a truck factor of ${w.truck_factor}.`
      : null,
  onboarding: (w) =>
    w.tour_stop_count != null && w.glossary_term_count != null && w.health_score != null
      ? `This stage built a ${w.tour_stop_count}-stop reading order, a ${w.glossary_term_count}-term glossary, and a health score of ${formatScore(w.health_score)}${
          w.onboarding_difficulty != null
            ? ` (onboarding difficulty ${formatScore(w.onboarding_difficulty)})`
            : ""
        }.`
      : null,
  security: (w) =>
    w.vulnerability_count != null
      ? `This stage checked declared dependencies against OSV.dev and found ${w.vulnerability_count} vulnerabilit${w.vulnerability_count === 1 ? "y" : "ies"}.`
      : null,
  rank: (w) =>
    w.finding_count != null
      ? `This stage ranked ${w.finding_count} finding${w.finding_count === 1 ? "" : "s"} into one ordered stream.`
      : null,
};

/**
 * A scrollytelling walkthrough of the REAL thirteen-stage pipeline
 * (`GET /meta/pipeline`), with one real repository's numbers
 * (`GET /meta/worked-example`) threaded through every stage. Both are
 * fetched live, never hardcoded — see plan/UI_REBUILD_SESSIONS.md section
 * 5.4's single-source-of-truth rule, applied here to the pipeline shape
 * itself as well as to formula constants.
 *
 * Must render fully with the worked example unavailable (no showcase
 * repository has reached a ready run yet) — every stage still renders its
 * description; only the concrete example line is omitted, per-stage.
 */
export function HowItWorksPage() {
  const pipeline = usePipeline();
  const workedExample = useWorkedExample();
  const reducedMotion = usePrefersReducedMotion();

  // `pipeline.data?.stages` is a stable array reference from react-query
  // for as long as the underlying data hasn't changed -- depend on THAT,
  // not on a `?? []`-derived local, which would be a new array literal
  // (and therefore a new effect dependency) on every render while pending.
  const stagesData = pipeline.data?.stages;
  const stages = stagesData ?? [];
  const [activeStage, setActiveStage] = useState<string | null>(null);
  const sectionRefs = useRef<Record<string, HTMLElement | null>>({});

  useEffect(() => {
    if (!stagesData || stagesData.length === 0) return;
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            const name = entry.target.getAttribute("data-stage-name");
            if (name) setActiveStage(name);
          }
        }
      },
      { rootMargin: "-15% 0px -70% 0px", threshold: 0 },
    );
    for (const stage of stagesData) {
      const el = sectionRefs.current[stage.name];
      if (el) observer.observe(el);
    }
    return () => observer.disconnect();
  }, [stagesData]);

  function jumpTo(name: string) {
    sectionRefs.current[name]?.scrollIntoView({
      behavior: reducedMotion ? "auto" : "smooth",
      block: "start",
    });
  }

  const example = workedExample.data;

  return (
    <div className="py-10">
      <p className="cp-label mb-2">Pipeline</p>
      <WordReveal
        text="How Compass works"
        tag="h1"
        className="font-display text-4xl font-medium tracking-tight text-text-heading"
      />
      <Reveal delay={0.2}>
        <p className="mt-4 max-w-2xl text-lg leading-normal text-text-muted">
          The actual thirteen stages Compass runs, in order, with real numbers from one real
          analysis — not a description of what the pipeline is supposed to do, but what it actually
          did the last time it ran on the repository below.
        </p>
      </Reveal>

      {!workedExample.isPending && !example ? (
        <Reveal delay={0.25}>
          <Alert variant="neutral" className="mt-6">
            {EMPTY_MESSAGES.workedExampleUnavailable}
          </Alert>
        </Reveal>
      ) : null}

      {example ? (
        <Reveal delay={0.25}>
          <p className="mt-6 text-sm text-text-muted">
            Worked example:{" "}
            <Link
              to={`/repos/${example.repo.id}/overview`}
              className="font-mono text-accent hover:underline"
            >
              {example.repo.owner}/{example.repo.name}
            </Link>{" "}
            — every figure below is real, and you can open the live analysis to verify it.
          </p>
        </Reveal>
      ) : null}

      <div className="mt-10 flex flex-col gap-8 lg:flex-row lg:items-start lg:gap-12">
        {/* Sticky scroll-spy stepper -- collapses to a horizontal scrolling
            strip above the content on narrow viewports. */}
        <nav
          aria-label="Pipeline stages"
          className="top-20 flex gap-1 overflow-x-auto pb-2 lg:sticky lg:w-48 lg:shrink-0 lg:flex-col lg:overflow-visible lg:pb-0"
        >
          {stages.map((stage, i) => {
            const isActive = activeStage === stage.name;
            return (
              <button
                key={stage.name}
                type="button"
                onClick={() => jumpTo(stage.name)}
                className={`shrink-0 whitespace-nowrap rounded-sm px-2.5 py-1.5 text-left text-xs transition-colors lg:whitespace-normal ${
                  isActive
                    ? "bg-accent-bg font-medium text-accent"
                    : "text-text-muted hover:bg-bg-inset hover:text-text"
                }`}
              >
                <span className="tabular-nums text-text-muted">{i + 1}.</span> {stage.name}
              </button>
            );
          })}
        </nav>

        <div className="min-w-0 flex-1">
          {pipeline.isPending ? (
            <p className="text-sm text-text-muted">Loading the pipeline…</p>
          ) : stages.length === 0 ? (
            <Alert variant="neutral">{EMPTY_MESSAGES.pipelineUnavailable}</Alert>
          ) : (
            <div className="flex flex-col gap-10">
              {stages.map((stage, i) => (
                <StageSection
                  key={stage.name}
                  stage={stage}
                  index={i}
                  exampleLine={example ? (STAGE_EXAMPLE_LINE[stage.name]?.(example) ?? null) : null}
                  registerRef={(el) => {
                    sectionRefs.current[stage.name] = el;
                  }}
                />
              ))}
            </div>
          )}
        </div>
      </div>

      <Reveal delay={0.1}>
        <section className="mt-16 border-t border-border pt-10">
          <p className="cp-label mb-2">Why this is not an AI wrapper</p>
          <h2 className="font-display text-2xl text-text-heading">
            The pipeline never asks a model what the code means
          </h2>
          <ul className="mt-4 flex flex-col gap-3">
            {NOT_AI_WRAPPER_POINTS.map((point) => (
              <li key={point} className="flex gap-2 text-sm leading-relaxed text-text-muted">
                <span
                  className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-accent"
                  aria-hidden="true"
                />
                <span>{point}</span>
              </li>
            ))}
          </ul>
        </section>
      </Reveal>

      <Reveal delay={0.15}>
        <section className="mt-10 border-t border-border pt-10">
          <p className="cp-label mb-2">Honesty</p>
          <h2 className="font-display text-2xl text-text-heading">
            What Compass deliberately does not do
          </h2>
          <ul className="mt-4 flex flex-col gap-3">
            {WHAT_COMPASS_DOES_NOT_DO.map((point) => (
              <li key={point} className="flex gap-2 text-sm leading-relaxed text-text-muted">
                <span
                  className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-border-strong"
                  aria-hidden="true"
                />
                <span>{point}</span>
              </li>
            ))}
          </ul>
        </section>
      </Reveal>
    </div>
  );
}

function StageSection({
  stage,
  index,
  exampleLine,
  registerRef,
}: {
  stage: PipelineStageOut;
  index: number;
  exampleLine: string | null;
  registerRef: (el: HTMLElement | null) => void;
}) {
  const Icon = STAGE_ICON[stage.name] ?? Sparkles;
  return (
    <Reveal as="div">
      <section
        ref={registerRef}
        data-stage-name={stage.name}
        id={`stage-${stage.name}`}
        className="scroll-mt-24"
      >
        <div className="flex items-center gap-2.5">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-border bg-bg-inset">
            <Icon size={15} className="text-accent" aria-hidden="true" />
          </span>
          <span className="tabular-nums text-xs text-text-muted">
            {String(index + 1).padStart(2, "0")}
          </span>
          {/* h2, not h3 -- this is the only heading level between the
              page's own h1 and this stage card; skipping straight to h3
              was a real heading-order violation this session's own
              accessibility sweep caught. */}
          <h2 className="font-display text-xl text-text-heading">{stage.name}</h2>
          <span
            className={`cp-label rounded-full border px-2 py-0.5 ${
              stage.kind === "fact"
                ? "border-border-strong text-text-muted"
                : "border-accent-border text-accent"
            }`}
          >
            {stage.kind}
          </span>
          {stage.optional ? (
            <span className="cp-label rounded-full border border-warning px-2 py-0.5 text-warning">
              optional
            </span>
          ) : null}
        </div>
        <p className="mt-2 max-w-2xl text-sm leading-relaxed text-text-muted">
          {stage.description}
        </p>
        {stage.engines.length > 0 ? (
          <p className="mt-1.5 font-mono text-xs text-text-muted">{stage.engines.join(" → ")}</p>
        ) : null}
        {exampleLine ? <p className="mt-2 max-w-2xl text-sm text-text">{exampleLine}</p> : null}
      </section>
    </Reveal>
  );
}
