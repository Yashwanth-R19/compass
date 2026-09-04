import { useEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import {
  Boxes,
  ExternalLink,
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
import { InfoTooltip } from "../components/ui/InfoTooltip";
import { usePipeline, useWorkedExample, useFormulas } from "../api/hooks";
import { usePrefersReducedMotion } from "../hooks/usePrefersReducedMotion";
import { EMPTY_MESSAGES, NOT_AI_WRAPPER_POINTS } from "../content/explainability";
import { FORMULA_COPY, TOOLTIPS } from "../content/explainability";
import {
  CELL_SIZE_GATE_NOTE,
  CORPUS_DESCRIPTION,
  CORPUS_REPO_LIST_PATH,
  CORPUS_REPO_LIST_URL,
  LIMITATIONS,
  METHODS_INTRO,
  METHODS_SECTIONS,
  REPRODUCIBILITY_CHANGES,
  REPRODUCIBILITY_GUARANTEE,
} from "../content/methods";
import type {
  FormulaGroupOut,
  FormulaStatus,
  PipelineStageOut,
  WorkedExampleResponse,
} from "../api/types";

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

// Every FormulaGroup's honesty label gets its OWN three-tone treatment here
// -- deliberately never Badge's severity tones (high/med/low), which would
// imply a ranking between locked/heuristic/cited that doesn't exist. The
// three statuses are different KINDS of claim, not different SEVERITIES.
const STATUS_LABEL: Record<FormulaStatus, string> = {
  locked: "Locked",
  heuristic: "Heuristic",
  cited: "Cited",
};

const STATUS_CLASS: Record<FormulaStatus, string> = {
  locked: "border-text-heading text-text-heading",
  heuristic: "border-warning text-warning",
  cited: "border-info text-info",
};

const STATUS_EXPLAINER: Record<FormulaStatus, string> = {
  locked:
    "A fixed product decision — the same formula and weights on every repository, never tuned.",
  heuristic:
    "A documented, adjustable starting point Compass chose — a considered guess, not a proven model.",
  cited:
    "Taken directly from published research and implemented as specified, not adjusted by Compass.",
};

function section(id: string) {
  return METHODS_SECTIONS.find((s) => s.id === id);
}

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
 * The merged explanation page (D12) — /how-it-works absorbs /methods
 * entirely. One scroll-driven narrative, four movements: the argument for
 * why this isn't an AI wrapper, the real thirteen-stage pipeline with one
 * worked example's real numbers, the reference half (#methods — every
 * formula's live constants and honesty label, plus calibration), and a
 * closing, deliberately uncomfortable limitations list. `/methods` redirects
 * here with `#methods` (see App.tsx); pages/MethodsPage.tsx no longer
 * exists.
 *
 * Every number on this page comes from `GET /meta/pipeline`,
 * `GET /meta/worked-example`, or `GET /meta/formulas` at request time. All
 * three requests can independently fail — the page must still render a
 * coherent, fully-worded result with no blank section and no literal
 * "undefined" (verified against a dev server with no backend running at
 * all): every section below degrades to a plain-English unavailable note
 * rather than disappearing or rendering half of a sentence.
 */
export function HowItWorksPage() {
  const pipeline = usePipeline();
  const workedExample = useWorkedExample();
  const formulas = useFormulas();
  const reducedMotion = usePrefersReducedMotion();
  const location = useLocation();

  // `pipeline.data?.stages` is a stable array reference from react-query
  // for as long as the underlying data hasn't changed -- depend on THAT,
  // not on a `?? []`-derived local, which would be a new array literal
  // (and therefore a new effect dependency) on every render while pending.
  const stagesData = pipeline.data?.stages;
  const stages = stagesData ?? [];
  const [activeStage, setActiveStage] = useState<string | null>(null);
  const sectionRefs = useRef<Record<string, HTMLElement | null>>({});
  const methodsRef = useRef<HTMLElement | null>(null);

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

  // React Router's client-side navigation does not perform the browser's
  // native hash-scroll (that only fires on a real, full-document
  // navigation) -- without this, every `<Link to="/how-it-works#methods">`
  // elsewhere in the app (HomePage, FindingsSurfacePage's benchmark teaser,
  // the /methods legacy redirect) would land at the top of the page instead
  // of the reference section it promises.
  //
  // Re-fires as each of the three independent requests settles (not just
  // once, on mount) -- found necessary by this session's own end-to-end
  // pass: scrolling to `#methods` immediately, while `pipeline`/
  // `workedExample`/`formulas` are all still pending, targets the section's
  // position when the page above it is still mostly empty loading text.
  // Real content (pipeline stages, formula cards) then renders in and
  // pushes `#methods` hundreds of pixels further down, leaving the already-
  // finished scroll well short of the target. Re-running this effect on
  // every pending -> settled transition re-issues `scrollIntoView` against
  // the CURRENT layout each time, so the last run (once everything has
  // loaded) always lands correctly regardless of load order/timing.
  useEffect(() => {
    if (location.hash === "#methods") {
      methodsRef.current?.scrollIntoView({
        behavior: reducedMotion ? "auto" : "smooth",
        block: "start",
      });
    }
  }, [
    location.hash,
    reducedMotion,
    pipeline.isPending,
    workedExample.isPending,
    formulas.isPending,
  ]);

  function jumpTo(name: string) {
    sectionRefs.current[name]?.scrollIntoView({
      behavior: reducedMotion ? "auto" : "smooth",
      block: "start",
    });
  }

  const example = workedExample.data;
  const groups = formulas.data?.groups ?? [];
  const activeProvider = formulas.data?.active_baseline_provider;
  const alsoMeasuredGroups = groups
    .map((g) => ({ group: g, copy: FORMULA_COPY[g.key] }))
    .filter((x) => x.copy?.alsoMeasured?.length);

  return (
    <div className="py-10">
      <p className="cp-label mb-2">How Compass works</p>
      <WordReveal
        text="Compass, explained"
        tag="h1"
        className="font-display text-4xl font-medium tracking-tight text-text-heading"
      />
      <Reveal delay={0.2}>
        <p className="mt-4 max-w-2xl text-lg leading-normal text-text-muted">
          Compass computes intelligence about a repository from its own commit history —
          deterministically, and without ever asking a language model what the code means. This page
          is the full account: the argument for why that matters, the actual pipeline that produces
          every number, the formulas behind them with their real live constants, and where the
          product honestly falls short.
        </p>
      </Reveal>

      {/* Movement 1 -- what Compass is, and why it isn't an AI wrapper. ---- */}
      <Reveal delay={0.1}>
        <section className="mt-12">
          <p className="cp-label mb-2">Not an AI wrapper</p>
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

      {/* Movement 2 -- the real thirteen-stage pipeline. ------------------ */}
      <section className="mt-16 border-t border-border pt-10">
        <p className="cp-label mb-2">The pipeline</p>
        <h2 className="font-display text-2xl text-text-heading">
          Thirteen stages, in the order they actually ran
        </h2>
        <p className="mt-2 max-w-2xl text-sm leading-relaxed text-text-muted">
          Not a description of what the pipeline is supposed to do — what it actually did the last
          time it ran on the repository below.
        </p>

        {!workedExample.isPending && !example ? (
          <Reveal delay={0.05}>
            <Alert variant="neutral" className="mt-6">
              {EMPTY_MESSAGES.workedExampleUnavailable}
            </Alert>
          </Reveal>
        ) : null}

        {example ? (
          <Reveal delay={0.05}>
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

        <div className="mt-8 flex flex-col gap-8 lg:flex-row lg:items-start lg:gap-12">
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
                    exampleLine={
                      example ? (STAGE_EXAMPLE_LINE[stage.name]?.(example) ?? null) : null
                    }
                    registerRef={(el) => {
                      sectionRefs.current[stage.name] = el;
                    }}
                  />
                ))}
              </div>
            )}
          </div>
        </div>
      </section>

      {/* Movement 3 -- #methods, the reference half. ---------------------- */}
      <section
        id="methods"
        ref={methodsRef}
        className="scroll-mt-20 mt-16 border-t border-border pt-10"
      >
        <p className="cp-label mb-2">Reference</p>
        <h2 className="font-display text-2xl text-text-heading">Methods</h2>
        <p className="mt-2 max-w-2xl text-sm leading-relaxed text-text-muted">{METHODS_INTRO}</p>

        {/* 3.1 -- every formula, its live constants, its honesty label. */}
        <div className="mt-10">
          <p className="cp-label mb-1">{section("scores")?.eyebrow}</p>
          <h3 className="font-display text-xl text-text-heading">{section("scores")?.title}</h3>
          <p className="mt-2 max-w-2xl text-sm leading-relaxed text-text-muted">
            {section("scores")?.body}
          </p>

          {formulas.isPending ? (
            <p className="mt-6 text-sm text-text-muted">Loading the live formula values…</p>
          ) : groups.length === 0 ? (
            <Alert variant="neutral" className="mt-6">
              {EMPTY_MESSAGES.formulasUnavailable}
            </Alert>
          ) : (
            <div className="mt-6 grid grid-cols-1 gap-6 md:grid-cols-2">
              {groups.map((group) => (
                <FormulaGroupCard key={group.key} group={group} />
              ))}
            </div>
          )}
        </div>

        {/* 3.2 -- calibration: heuristic vs. corpus, active provider, the
            cell-size gate, the checked-in corpus repo list. */}
        <div className="mt-12">
          <p className="cp-label mb-1">{section("calibration")?.eyebrow}</p>
          <h3 className="font-display text-xl text-text-heading">
            {section("calibration")?.title}
          </h3>
          <p className="mt-2 max-w-2xl text-sm leading-relaxed text-text-muted">
            {section("calibration")?.body}
          </p>
          {activeProvider ? (
            <p className="mt-3 text-sm text-text">
              This deployment is currently configured to use the{" "}
              <span className="font-mono font-medium text-accent">{activeProvider}</span> provider.
            </p>
          ) : null}
          <p className="mt-4 max-w-2xl text-sm leading-relaxed text-text-muted">
            {CORPUS_DESCRIPTION}
          </p>
          <a
            href={CORPUS_REPO_LIST_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-3 flex w-fit items-center gap-1.5 font-mono text-sm text-accent hover:underline"
          >
            <ExternalLink size={13} aria-hidden="true" />
            {CORPUS_REPO_LIST_PATH}
          </a>
          <p className="mt-4 max-w-2xl text-sm leading-relaxed text-text-muted">
            {CELL_SIZE_GATE_NOTE}
          </p>
        </div>

        {/* 3.3 -- measured but deliberately not scored. */}
        {alsoMeasuredGroups.length > 0 ? (
          <div className="mt-12">
            <p className="cp-label mb-1">{section("also-measured")?.eyebrow}</p>
            <h3 className="font-display text-xl text-text-heading">
              {section("also-measured")?.title}
            </h3>
            <p className="mt-2 max-w-2xl text-sm leading-relaxed text-text-muted">
              {section("also-measured")?.body}
            </p>
            <div className="mt-6 flex flex-col gap-5">
              {alsoMeasuredGroups.map(({ group, copy }) => (
                <div key={group.key}>
                  <h4 className="font-display text-base text-text-heading">{group.label}</h4>
                  {copy?.alsoMeasuredNote ? (
                    <p className="mt-1 text-xs text-text-muted">{copy.alsoMeasuredNote}</p>
                  ) : null}
                  <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1.5">
                    {copy?.alsoMeasured?.map((item) => (
                      <li key={item.label} className="flex items-center gap-1 text-xs text-text">
                        {item.label}
                        {item.tooltip ? (
                          <InfoTooltip
                            label={`What is ${item.label}?`}
                            text={TOOLTIPS[item.tooltip]}
                          />
                        ) : null}
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          </div>
        ) : null}

        {/* 3.4 -- reproducibility: the guarantee, and what legitimately
            moves the numbers. */}
        <div className="mt-12">
          <p className="cp-label mb-1">{section("reproducibility")?.eyebrow}</p>
          <h3 className="font-display text-xl text-text-heading">
            {section("reproducibility")?.title}
          </h3>
          <p className="mt-2 max-w-2xl text-sm leading-relaxed text-text-muted">
            {section("reproducibility")?.body}
          </p>
          <p className="mt-4 max-w-2xl text-sm leading-relaxed text-text">
            {REPRODUCIBILITY_GUARANTEE}
          </p>
          <dl className="mt-4 flex flex-col gap-3">
            {REPRODUCIBILITY_CHANGES.map((c) => (
              <div
                key={c.cause}
                className="grid grid-cols-1 gap-1 sm:grid-cols-[220px_1fr] sm:gap-4"
              >
                <dt className="text-xs font-medium text-text-heading">{c.cause}</dt>
                <dd className="text-xs leading-relaxed text-text-muted">{c.effect}</dd>
              </div>
            ))}
          </dl>
        </div>
      </section>

      {/* Movement 4 -- what Compass deliberately does not do. ------------- */}
      <Reveal delay={0.1}>
        <section className="mt-16 border-t border-border pt-10">
          <p className="cp-label mb-2">{section("limitations")?.eyebrow}</p>
          <h2 className="font-display text-2xl text-text-heading">
            {section("limitations")?.title}
          </h2>
          <p className="mt-2 max-w-2xl text-sm leading-relaxed text-text-muted">
            {section("limitations")?.body}
          </p>
          <ul className="mt-6 flex flex-col gap-3">
            {LIMITATIONS.map((item) => (
              <li key={item} className="flex gap-2 text-sm leading-relaxed text-text-muted">
                <span
                  className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-warning"
                  aria-hidden="true"
                />
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </section>
      </Reveal>
    </div>
  );
}

function FormulaGroupCard({ group }: { group: FormulaGroupOut }) {
  return (
    <div className="rounded-lg border border-border bg-bg-elevated p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h4 className="font-display text-lg text-text-heading">{group.label}</h4>
        <span
          className={`cp-label rounded-full border px-2 py-0.5 ${STATUS_CLASS[group.status]}`}
          title={STATUS_EXPLAINER[group.status]}
        >
          {STATUS_LABEL[group.status]}
        </span>
      </div>
      <p className="mt-1 text-xs text-text-muted">{STATUS_EXPLAINER[group.status]}</p>
      <p className="mt-3 font-mono text-xs leading-relaxed text-text">{group.formula}</p>
      {group.citation ? (
        <p className="mt-2 text-xs italic text-text-muted">{group.citation}</p>
      ) : null}
      <dl className="mt-4 flex flex-col gap-1.5">
        {group.constants.map((c) => (
          <div key={c.name} className="flex items-baseline justify-between gap-3">
            <dt className="font-mono text-xs text-text-muted">{c.name}</dt>
            <dd className="tabular-nums font-mono text-xs text-text">{c.value}</dd>
          </div>
        ))}
      </dl>
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
          {/* h3, not h2 -- this section nests under Movement 2's own h2
              ("Thirteen stages..."); a stage card is a subsection of the
              pipeline, not a sibling of it. */}
          <h3 className="font-display text-xl text-text-heading">{stage.name}</h3>
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
