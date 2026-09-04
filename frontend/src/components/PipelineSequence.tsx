import { useEffect, useRef, useState } from "react";
import { Check, X, Minus } from "lucide-react";
import { usePipeline, useRepoStatus } from "../api/hooks";
import { STAGE_LABEL, STAGE_SUMMARY_KEY } from "../pages/RepoLayout";
import { usePrefersReducedMotion } from "../hooks/usePrefersReducedMotion";
import type { PipelineStageOut, StageName, StageOut, StageStatus } from "../api/types";

const RUN_TERMINAL: ReadonlySet<string> = new Set(["ready", "failed", "superseded"]);

function stageSummaryLine(stage: StageOut): string | null {
  if (!stage.summary) return null;
  const key = STAGE_SUMMARY_KEY[stage.name];
  if (!key) return null;
  const value = stage.summary[key];
  if (typeof value !== "number") return null;
  return `${Math.round(value).toLocaleString()} ${key.replace(/_/g, " ")}`;
}

type Merged = { pipeline: PipelineStageOut; status: StageOut | undefined };

/**
 * The one showpiece (rebuild spec section 6.3) -- the live analysis
 * pipeline, rendered from real data end to end: stage names/order/kind/
 * engines/descriptions from `GET /meta/pipeline`, never hardcoded; live
 * progress from `useRepoStatus`'s own polling. The running stage's
 * indeterminate bar is the ONLY looping animation permitted anywhere in
 * this app, and only while a stage is genuinely running.
 *
 * `compact`: a slim single-line progress strip (RepoLayout's header, while
 * a run is active) instead of the full vertical timeline (the /welcome
 * flow and the landing page after a submit, where this IS the page).
 */
export function PipelineSequence({
  repoId,
  share,
  compact = false,
  onDone,
}: {
  repoId: string | undefined;
  share?: string;
  compact?: boolean;
  onDone?: (runStatus: string) => void;
}) {
  const pipeline = usePipeline();
  const status = useRepoStatus(repoId, share);
  const reducedMotion = usePrefersReducedMotion();

  const runStatus = status.data?.run_status;
  const isTerminal = Boolean(runStatus && RUN_TERMINAL.has(runStatus));

  // Auto-collapses the moment a run reaches a terminal status DURING this
  // component's own lifetime -- an already-finished run mounted fresh
  // (e.g. a page reload) renders collapsed immediately, no false "just
  // completed" animation for something that finished before this component
  // ever existed.
  const [collapsed, setCollapsed] = useState(isTerminal);
  const everRunning = useRef(false);
  useEffect(() => {
    if (runStatus === "running") everRunning.current = true;
  }, [runStatus]);
  useEffect(() => {
    if (isTerminal && everRunning.current) {
      setCollapsed(true);
      onDone?.(runStatus!);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isTerminal, runStatus]);

  if (pipeline.isPending || status.isPending) {
    return (
      <div className="flex items-center gap-2 text-xs text-text-muted">
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-border-strong motion-reduce:animate-none" />
        Loading the pipeline…
      </div>
    );
  }
  if (pipeline.isError || !pipeline.data || !status.data) {
    return <p className="text-xs text-text-muted">The pipeline status couldn't be loaded.</p>;
  }

  const byName = new Map(status.data.stages.map((s) => [s.name, s]));
  const merged: Merged[] = pipeline.data.stages
    .slice()
    .sort((a, b) => a.order - b.order)
    .map((p) => ({ pipeline: p, status: byName.get(p.name as StageName) }));

  if (collapsed) {
    return (
      <CollapsedSummary
        merged={merged}
        runStatus={runStatus ?? "running"}
        onExpand={() => setCollapsed(false)}
      />
    );
  }

  if (compact) {
    return <CompactStrip merged={merged} />;
  }

  return (
    <ol className="flex flex-col">
      {merged.map(({ pipeline: p, status: s }) => (
        <StageRow key={p.name} stage={p} status={s} reducedMotion={reducedMotion} />
      ))}
    </ol>
  );
}

function CollapsedSummary({
  merged,
  runStatus,
  onExpand,
}: {
  merged: Merged[];
  runStatus: string;
  onExpand: () => void;
}) {
  const failed = merged.filter((m) => m.status?.status === "failed").length;
  const done = merged.filter((m) => m.status?.status === "done").length;
  const label =
    runStatus === "failed"
      ? "Analysis failed"
      : `Analysis complete — ${done} of ${merged.length} stages ran` +
        (failed > 0 ? `, ${failed} optional stage${failed === 1 ? "" : "s"} failed` : "");

  return (
    <button
      type="button"
      onClick={onExpand}
      className={`flex w-full items-center justify-between gap-2 rounded-sm border px-3 py-2 text-left text-xs transition-colors hover:bg-bg-inset ${
        runStatus === "failed" ? "border-danger text-danger" : "border-success text-success"
      }`}
    >
      <span className="font-medium">{label}</span>
      <span className="text-text-muted">Show pipeline</span>
    </button>
  );
}

function CompactStrip({ merged }: { merged: Merged[] }) {
  const runningIndex = merged.findIndex((m) => m.status?.status === "running");
  const current = runningIndex >= 0 ? merged[runningIndex] : null;
  const doneCount = merged.filter(
    (m) => m.status?.status === "done" || m.status?.status === "skipped",
  ).length;

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center justify-between gap-2 text-xs text-text-muted">
        <span>
          {current
            ? `Running ${STAGE_LABEL[current.pipeline.name as StageName] ?? current.pipeline.name}…`
            : `${doneCount} of ${merged.length} stages`}
        </span>
        <span className="cp-stat">
          {doneCount}/{merged.length}
        </span>
      </div>
      <div className="flex gap-0.5">
        {merged.map(({ pipeline: p, status: s }) => (
          // No pulse on the running segment -- the accent fill colour plus
          // the "Running <stage>…" label above it already say which stage
          // is active; this strip is a secondary, compact presentation, not
          // a second place for the app's one sanctioned loop to appear.
          <div
            key={p.name}
            title={STAGE_LABEL[p.name as StageName] ?? p.name}
            className={`h-1.5 flex-1 rounded-full ${stageBarClass(s?.status)}`}
          />
        ))}
      </div>
    </div>
  );
}

function stageBarClass(status: StageStatus | undefined): string {
  switch (status) {
    case "done":
      return "bg-success";
    case "running":
      return "bg-accent";
    case "failed":
      return "bg-danger";
    case "skipped":
      return "bg-border-strong";
    default:
      return "bg-bg-inset";
  }
}

function StageMarker({ status }: { status: StageStatus | undefined }) {
  const base = "flex h-6 w-6 shrink-0 items-center justify-center rounded-full border-2";
  if (status === "done") {
    return (
      <span className={`${base} border-success bg-success-bg text-success`}>
        <Check size={13} aria-hidden="true" />
      </span>
    );
  }
  if (status === "failed") {
    return (
      <span className={`${base} border-danger bg-danger-bg text-danger`}>
        <X size={13} aria-hidden="true" />
      </span>
    );
  }
  if (status === "skipped") {
    return (
      <span className={`${base} border-border-strong bg-bg-inset text-text-muted`}>
        <Minus size={13} aria-hidden="true" />
      </span>
    );
  }
  if (status === "running") {
    // No pulse/ping here -- the row's own indeterminate bar (StageRow,
    // sourced from the single shared `pipeline-indeterminate` keyframe) is
    // this app's one sanctioned looping animation. A second, independently
    // animating ring on the marker right next to it would be the same
    // "running" signal said twice, competing for attention instead of
    // reinforcing it -- decorative motion, not communicative.
    return (
      <span className={`${base} border-accent bg-accent-bg text-accent`}>
        <span className="h-2 w-2 rounded-full bg-accent" />
      </span>
    );
  }
  return <span className={`${base} border-border bg-bg-inset`} />;
}

function StageRow({
  stage,
  status,
  reducedMotion,
}: {
  stage: PipelineStageOut;
  status: StageOut | undefined;
  reducedMotion: boolean;
}) {
  const s = status?.status;
  const summaryLine = status ? stageSummaryLine(status) : null;
  const isRunning = s === "running";

  return (
    <li className="relative flex gap-3 pb-6 last:pb-0">
      {/* The connecting vertical line -- a plain border, no animation. */}
      <span
        aria-hidden="true"
        className="absolute left-3 top-6 h-full w-px -translate-x-1/2 bg-border last:hidden"
      />
      <StageMarker status={s} />
      <div className="min-w-0 flex-1 pt-0.5">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-medium text-text-heading">
            {STAGE_LABEL[stage.name as StageName] ?? stage.name}
          </span>
          <span
            className={`cp-label rounded-full border px-1.5 py-0 ${
              stage.kind === "fact"
                ? "border-border-strong text-text-muted"
                : "border-accent-border text-accent"
            }`}
          >
            {stage.kind}
          </span>
          {stage.optional ? (
            <span className="cp-label rounded-full border border-warning px-1.5 py-0 text-warning">
              optional
            </span>
          ) : null}
          {isRunning ? (
            <span className="h-1 w-16 overflow-hidden rounded-full bg-bg-inset">
              <span
                className={`block h-full w-1/3 rounded-full bg-accent ${
                  reducedMotion ? "" : "animate-[pipeline-indeterminate_1.1s_ease-in-out_infinite]"
                }`}
              />
            </span>
          ) : null}
        </div>
        <p className="mt-0.5 text-xs text-text-muted">
          {s === "skipped"
            ? "Facts unchanged since the last run — reused."
            : s === "failed" && stage.optional
              ? (status?.error ?? "This optional stage failed; the run continued anyway.")
              : stage.description}
        </p>
        {summaryLine && (s === "done" || s === "skipped") ? (
          <p className="mt-0.5 text-xs text-text">{summaryLine}</p>
        ) : null}
      </div>
    </li>
  );
}
