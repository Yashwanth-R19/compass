import { useId, useMemo, useState } from "react";
import { useOutletContext, useSearchParams } from "react-router-dom";
import {
  useArchitecture,
  useBlastRadius,
  useCity,
  useCoupling,
  useFindings,
  useHiddenDeps,
  useModuleCoupling,
  useSubsystems,
} from "../../api/hooks";
import type { ModuleCouplingGranularity } from "../../api/types";
import { Card } from "../../components/ui/Card";
import { Table } from "../../components/ui/Table";
import { Badge } from "../../components/ui/Badge";
import { AnimatedList } from "../../reactbits/AnimatedList";
import { Expander } from "../../components/motion/Expander";
import { ErrorState } from "../../components/ErrorState";
import { FileDetailPanel } from "../../components/FileDetailPanel";
import { FilePicker } from "../../components/FilePicker";
import { HonestyNote } from "../../components/HonestyNote";
import { InfoTooltip } from "../../components/ui/InfoTooltip";
import { LoadingState } from "../../components/LoadingState";
import { Reveal } from "../../components/motion/Reveal";
import { SegmentedControl } from "../../components/ui/SegmentedControl";
import { StageGate } from "../../components/StageGate";
import { HONESTY, TOOLTIPS } from "../../content/explainability";
import { parseHiddenDependencyPair } from "../../lib/findingLinks";
import { fileName, formatPercent, formatScore } from "../../lib/format";
import { citySubsystemLabelById, toCityFiles, type CityFile } from "../../lib/cityFile";
import type { RepoOutletContext } from "../RepoLayout";

type ExploreView = "files" | "structure" | "impact";

function isExploreView(v: string | null): v is ExploreView {
  return v === "files" || v === "structure" || v === "impact";
}

// Neither /architecture's cycle/layering lists nor /coupling's pair list is
// capped server-side the way findings are -- a real repo (psf/requests: 224
// coupling pairs, 50-odd cycles) renders an unusably long, unbounded page
// without a client-side "summary first, long tail behind an expander" cut
// (found during this session's own end-to-end sweep against that exact repo).
const MAX_VISIBLE_CYCLES = 8;
const MAX_VISIBLE_LAYERING = 10;
const MAX_VISIBLE_COUPLING_PAIRS = 15;

/** `/repos/:id/explore` (rebuild spec section 4.3) -- "what's in it, and
 * what's connected to what." Replaces the deleted canvas map/graph/treemap
 * (D6/D14/D15) with a sortable file table, ranked evidence lists, and tiny
 * hand-authored inline SVG diagrams -- no canvas or graph library anywhere. */
export function ExploreSurfacePage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const urlView = searchParams.get("view");
  const [view, setView] = useState<ExploreView>(isExploreView(urlView) ? urlView : "files");

  function changeView(next: string) {
    setView(next as ExploreView);
    setSearchParams(
      (prev) => {
        const merged = new URLSearchParams(prev);
        merged.set("view", next);
        return merged;
      },
      { replace: true },
    );
  }

  const activeView = isExploreView(urlView) ? urlView : view;

  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm text-text-muted">
        The files in this repository, how they're structured and coupled, and what changing one of
        them could affect.
      </p>
      <SegmentedControl
        aria-label="Explore view"
        value={activeView}
        onValueChange={changeView}
        options={[
          { value: "files", label: "Files" },
          { value: "structure", label: "Structure" },
          { value: "impact", label: "Impact" },
        ]}
      />
      {activeView === "structure" ? (
        <StructureView />
      ) : activeView === "impact" ? (
        <ImpactView />
      ) : (
        <FilesView />
      )}
    </div>
  );
}

// =============================================================================
// Files -- the file-browser replacement for the deleted map (D14)
// =============================================================================

type FileSortKey = "path" | "loc" | "complexity" | "risk" | "churn" | "commits" | "modified";

function FilesView() {
  const { repo, share } = useOutletContext<RepoOutletContext>();
  const subsystems = useSubsystems(repo.id, true, share);
  const city = useCity(repo.id, share);
  const [selected, setSelected] = useState<string | null>(null);
  const [sort, setSort] = useState<{ key: FileSortKey; direction: "asc" | "desc" }>({
    key: "risk",
    direction: "desc",
  });

  function changeSort(key: string) {
    setSort((prev) =>
      prev.key === key
        ? { key: key as FileSortKey, direction: prev.direction === "asc" ? "desc" : "asc" }
        : { key: key as FileSortKey, direction: "desc" },
    );
  }

  function sortFiles(files: CityFile[]): CityFile[] {
    const dir = sort.direction === "asc" ? 1 : -1;
    const copy = [...files];
    copy.sort((a, b) => {
      switch (sort.key) {
        case "path":
          return dir * a.path.localeCompare(b.path);
        case "loc":
          return dir * (a.loc - b.loc);
        case "complexity":
          return dir * (a.complexity - b.complexity);
        case "risk":
          return dir * ((a.riskScore ?? -1) - (b.riskScore ?? -1));
        case "churn":
          return dir * (a.churnWeighted - b.churnWeighted);
        case "commits":
          return dir * (a.commitCount - b.commitCount);
        case "modified":
          return dir * (a.lastModifiedAt - b.lastModifiedAt);
        default:
          return 0;
      }
    });
    return copy;
  }

  return (
    <StageGate
      query={subsystems}
      loadingLabel="Loading subsystems…"
      emptyTitle="No subsystems detected"
      emptyMessage="This repository doesn't have enough structural or coupling data to partition into subsystems yet."
    >
      {(subsystemData) => (
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start">
          <Reveal as="div" className="lg:w-64 lg:shrink-0">
            <Card
              title="Subsystems"
              action={<InfoTooltip label="What is a subsystem?" text={TOOLTIPS.subsystem} />}
            >
              <AnimatedList
                items={subsystemData.subsystems}
                keyFor={(s) => s.label}
                className="flex flex-col divide-y divide-border"
                renderItem={(s) => (
                  <div className="flex flex-col gap-1 py-2 text-sm">
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-medium text-text">{s.label}</span>
                      <span className="cp-stat text-xs text-text-muted">{s.file_count} files</span>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <div className="h-1 w-full overflow-hidden rounded-full bg-bg-inset">
                        <div
                          className="h-full rounded-full bg-accent"
                          style={{ width: `${Math.round(s.cohesion * 100)}%` }}
                        />
                      </div>
                      <InfoTooltip label="What is cohesion?" text={TOOLTIPS.cohesion} />
                    </div>
                  </div>
                )}
              />
            </Card>
          </Reveal>

          <div className="min-w-0 flex-1">
            <StageGate
              query={city}
              loadingLabel="Loading file metrics…"
              emptyTitle="No files"
              emptyMessage="This repository has no non-deleted files to show at HEAD."
              isEmpty={(data) => data.files.rows.length === 0}
            >
              {(cityData) => {
                const files = sortFiles(toCityFiles(cityData));
                const labelById = citySubsystemLabelById(cityData);
                const selectedFile = files.find((f) => f.path === selected);
                return (
                  <Reveal delay={0.05} className="flex flex-col gap-4">
                    <Card
                      title="Files"
                      eyebrow={`${files.length} files — click a column to sort`}
                      action={
                        <FilePicker
                          paths={files.map((f) => f.path)}
                          onSelect={setSelected}
                          placeholder="Jump to file…"
                        />
                      }
                    >
                      <Table
                        rowKey={(f) => f.path}
                        rows={files}
                        emptyMessage="No files."
                        sort={sort}
                        onSortChange={changeSort}
                        columns={[
                          {
                            key: "path",
                            header: "Path",
                            sortable: true,
                            render: (f) => (
                              <button
                                type="button"
                                onClick={() => setSelected(f.path)}
                                className="max-w-[320px] truncate text-left font-mono text-xs text-accent hover:underline"
                                title={f.path}
                              >
                                {f.path}
                              </button>
                            ),
                          },
                          {
                            key: "loc",
                            header: "LOC",
                            numeric: true,
                            align: "right",
                            sortable: true,
                            render: (f) => f.loc.toLocaleString(),
                          },
                          {
                            key: "complexity",
                            header: "Complexity",
                            tooltip: TOOLTIPS.complexity,
                            numeric: true,
                            align: "right",
                            sortable: true,
                            render: (f) => formatScore(f.complexity, 1),
                          },
                          {
                            key: "risk",
                            header: "Risk",
                            tooltip: TOOLTIPS.riskScore,
                            numeric: true,
                            align: "right",
                            sortable: true,
                            render: (f) => (f.riskScore != null ? formatPercent(f.riskScore) : "—"),
                          },
                          {
                            key: "churn",
                            header: "Churn",
                            tooltip: TOOLTIPS.churnWeighted,
                            numeric: true,
                            align: "right",
                            sortable: true,
                            render: (f) => formatScore(f.churnWeighted, 0),
                          },
                          {
                            key: "commits",
                            header: "Commits",
                            numeric: true,
                            align: "right",
                            sortable: true,
                            render: (f) => f.commitCount.toLocaleString(),
                          },
                          {
                            key: "modified",
                            header: "Last modified",
                            tooltip: TOOLTIPS.recency,
                            align: "right",
                            sortable: true,
                            render: (f) => new Date(f.lastModifiedAt * 1000).toLocaleDateString(),
                          },
                        ]}
                      />
                    </Card>

                    {selectedFile ? (
                      <FileDetailPanel
                        repoId={repo.id}
                        path={selectedFile.path}
                        loc={selectedFile.loc}
                        complexity={selectedFile.complexity}
                        riskScore={selectedFile.riskScore}
                        subsystemLabel={
                          selectedFile.subsystemId != null
                            ? (labelById.get(selectedFile.subsystemId) ?? null)
                            : null
                        }
                        onClose={() => setSelected(null)}
                      />
                    ) : null}
                  </Reveal>
                );
              }}
            </StageGate>
          </div>
        </div>
      )}
    </StageGate>
  );
}

// =============================================================================
// Structure -- three ranked lists, no canvas (D15)
// =============================================================================

function StructureView() {
  return (
    <div className="flex flex-col gap-4">
      <Reveal>
        <CyclesAndLayeringCard />
      </Reveal>
      <Reveal delay={0.05}>
        <CouplingPairsCard />
      </Reveal>
    </div>
  );
}

function CyclesAndLayeringCard() {
  const { repo, share } = useOutletContext<RepoOutletContext>();
  const architecture = useArchitecture(repo.id, share);

  return (
    <StageGate
      query={architecture}
      loadingLabel="Loading architecture…"
      emptyTitle="No cycles or layering violations"
      emptyMessage="No circular dependencies or layering violations were detected."
    >
      {(data) => {
        const visibleUnreferenced = 10;
        const restUnreferenced = data.unreferenced_files.slice(visibleUnreferenced);
        const visibleCycles = data.cycles.slice(0, MAX_VISIBLE_CYCLES);
        const restCycles = data.cycles.slice(MAX_VISIBLE_CYCLES);
        const visibleLayering = data.layering_violations.slice(0, MAX_VISIBLE_LAYERING);
        const restLayering = data.layering_violations.slice(MAX_VISIBLE_LAYERING);
        return (
          <div className="flex flex-col gap-4">
            <Card
              title="Cycles & layering"
              eyebrow={`${data.cycles.length} cycle${data.cycles.length === 1 ? "" : "s"} · ${data.layering_violations.length} layering violation${data.layering_violations.length === 1 ? "" : "s"}`}
              action={<InfoTooltip label="What is a cycle?" text={TOOLTIPS.cycle} />}
            >
              {data.cycles.length === 0 && data.layering_violations.length === 0 ? (
                <p className="py-4 text-center text-sm text-text-muted">
                  No circular dependencies or layering violations detected.
                </p>
              ) : (
                <div className="flex flex-col divide-y divide-border text-sm">
                  {visibleCycles.length > 0 ? (
                    <AnimatedList
                      items={visibleCycles}
                      keyFor={(_c, i) => `cycle-${i}`}
                      className="flex flex-col divide-y divide-border"
                      renderItem={(c) => <CycleRow files={c.files} severity={c.severity} />}
                    />
                  ) : null}
                  {restCycles.length > 0 ? (
                    <Expander
                      className="py-2"
                      trigger={`${restCycles.length} more cycle${restCycles.length === 1 ? "" : "s"}`}
                    >
                      <ul className="flex flex-col divide-y divide-border pt-1">
                        {restCycles.map((c, i) => (
                          <li key={`cycle-rest-${i}`}>
                            <CycleRow files={c.files} severity={c.severity} />
                          </li>
                        ))}
                      </ul>
                    </Expander>
                  ) : null}
                  {visibleLayering.length > 0 ? (
                    <AnimatedList
                      items={visibleLayering}
                      keyFor={(_v, i) => `layer-${i}`}
                      className="flex flex-col divide-y divide-border"
                      renderItem={(v) => (
                        <div className="flex items-center gap-2 py-2">
                          <Badge tone={v.severity}>{v.kind}</Badge>
                          <span className="truncate font-mono text-xs text-text-muted">
                            {v.from_path} → {v.to_path}
                          </span>
                        </div>
                      )}
                    />
                  ) : null}
                  {restLayering.length > 0 ? (
                    <Expander
                      className="py-2"
                      trigger={`${restLayering.length} more layering violation${restLayering.length === 1 ? "" : "s"}`}
                    >
                      <ul className="flex flex-col divide-y divide-border pt-1">
                        {restLayering.map((v, i) => (
                          <li key={`layer-rest-${i}`} className="flex items-center gap-2 py-2">
                            <Badge tone={v.severity}>{v.kind}</Badge>
                            <span className="truncate font-mono text-xs text-text-muted">
                              {v.from_path} → {v.to_path}
                            </span>
                          </li>
                        ))}
                      </ul>
                    </Expander>
                  ) : null}
                </div>
              )}
              {data.layering_violations.length > 0 ? (
                <HonestyNote
                  variant="scope-limitation"
                  text={HONESTY.layeringHeuristicConservative}
                  className="mt-2"
                />
              ) : null}
            </Card>

            {data.unreferenced_files.length > 0 ? (
              <Card
                title="Unreferenced files"
                eyebrow={`${data.unreferenced_files.length} file${data.unreferenced_files.length === 1 ? "" : "s"} with no detected structural edge`}
              >
                {/* NOT a finding -- no severity chip, no rank, never routed
                    through FindingItem. Dead-code detection was cut from
                    this product; this list is honestly informational. */}
                <p className="mb-2 text-xs text-text-muted">{data.unreferenced_files_caveat}</p>
                <ul className="flex flex-col gap-1">
                  {data.unreferenced_files.slice(0, visibleUnreferenced).map((f) => (
                    <li
                      key={f.file_path}
                      className="flex items-center justify-between gap-2 font-mono text-xs text-text-muted"
                    >
                      <span className="truncate">{f.file_path}</span>
                      <span className="shrink-0 tabular-nums">{f.loc.toLocaleString()} LOC</span>
                    </li>
                  ))}
                </ul>
                {restUnreferenced.length > 0 ? (
                  <Expander
                    className="mt-2"
                    trigger={`${restUnreferenced.length} more unreferenced file${restUnreferenced.length === 1 ? "" : "s"}`}
                  >
                    <ul className="flex flex-col gap-1 pt-1">
                      {restUnreferenced.map((f) => (
                        <li
                          key={f.file_path}
                          className="flex items-center justify-between gap-2 font-mono text-xs text-text-muted"
                        >
                          <span className="truncate">{f.file_path}</span>
                          <span className="shrink-0 tabular-nums">
                            {f.loc.toLocaleString()} LOC
                          </span>
                        </li>
                      ))}
                    </ul>
                  </Expander>
                ) : null}
              </Card>
            ) : null}
          </div>
        );
      }}
    </StageGate>
  );
}

function CycleRow({ files, severity }: { files: string[]; severity: "low" | "med" | "high" }) {
  return (
    <div className="flex flex-col gap-2 py-3 sm:flex-row sm:items-center">
      <CycleDiagram files={files} />
      <div className="min-w-0 flex-1">
        <Expander
          trigger={
            <span className="flex flex-wrap items-center gap-2">
              <Badge tone={severity}>cycle</Badge>
              <span className="text-xs text-text-muted">
                {files.length} file{files.length === 1 ? "" : "s"}
              </span>
            </span>
          }
        >
          <ul className="mt-1.5 flex flex-col gap-0.5 pb-1">
            {files.map((f) => (
              <li key={f} className="truncate font-mono text-xs text-text-muted">
                {f}
              </li>
            ))}
          </ul>
        </Expander>
      </div>
    </div>
  );
}

/** A hand-authored inline SVG, per rebuild spec section 5.5 -- no graph
 * library. Nodes on a circle, arrows in cycle order, basenames only (the
 * full path lives in the row beside it). `aria-hidden` -- purely a
 * supplement, never the only carrier of the information. */
function CycleDiagram({ files }: { files: string[] }) {
  const markerId = useId();
  const shown = files.slice(0, 5);
  const extra = files.length - shown.length;
  const cx = 60;
  const cy = 40;
  const r = 24;
  const nodes = shown.map((f, i) => {
    const angle = (i / shown.length) * Math.PI * 2 - Math.PI / 2;
    return {
      x: cx + r * Math.cos(angle),
      y: cy + r * Math.sin(angle),
      label: truncateLabel(fileName(f)),
    };
  });

  return (
    <svg
      viewBox="0 0 120 90"
      width={130}
      height={98}
      aria-hidden="true"
      className="shrink-0 self-center sm:self-start"
    >
      <defs>
        <marker
          id={`arrow-${markerId}`}
          viewBox="0 0 8 8"
          refX="6"
          refY="4"
          markerWidth="5"
          markerHeight="5"
          orient="auto-start-reverse"
        >
          <path d="M0,0 L8,4 L0,8 z" fill="var(--color-border-strong)" />
        </marker>
      </defs>
      {nodes.map((n, i) => {
        const next = nodes[(i + 1) % nodes.length];
        const dx = next.x - n.x;
        const dy = next.y - n.y;
        const dist = Math.hypot(dx, dy) || 1;
        const ux = dx / dist;
        const uy = dy / dist;
        const pad = 6;
        return (
          <line
            key={i}
            x1={n.x + ux * pad}
            y1={n.y + uy * pad}
            x2={next.x - ux * pad}
            y2={next.y - uy * pad}
            stroke="var(--color-border-strong)"
            strokeWidth={1}
            markerEnd={`url(#arrow-${markerId})`}
          />
        );
      })}
      {nodes.map((n, i) => (
        <g key={i}>
          <circle cx={n.x} cy={n.y} r={4} fill="var(--color-accent)" />
          <text
            x={n.x}
            y={n.y + (n.y >= cy ? 15 : -8)}
            textAnchor="middle"
            fontFamily="var(--font-mono)"
            fontSize="9"
            fill="var(--color-text-muted)"
          >
            {n.label}
          </text>
        </g>
      ))}
      {extra > 0 ? (
        <text
          x={cx}
          y={cy + 3}
          textAnchor="middle"
          fontFamily="var(--font-mono)"
          fontSize="9"
          fill="var(--color-text-muted)"
        >
          +{extra} more
        </text>
      ) : null}
    </svg>
  );
}

function truncateLabel(label: string): string {
  return label.length > 14 ? `${label.slice(0, 13)}…` : label;
}

/** A hand-authored inline SVG for a two-file (or two-module) relationship
 * (section 5.5) -- solid when a structural edge is known to exist, dashed
 * and warning-coloured for a pair that changes together with NO import
 * between them. */
function PairDiagram({
  labelA,
  labelB,
  hidden,
}: {
  labelA: string;
  labelB: string;
  hidden: boolean | null;
}) {
  const ax = 20;
  const bx = 110;
  const y = 40;
  const stroke = hidden ? "var(--color-warning)" : "var(--color-border-strong)";
  return (
    <svg viewBox="0 0 130 80" width={130} height={80} aria-hidden="true" className="shrink-0">
      <line
        x1={ax + 6}
        y1={y}
        x2={bx - 6}
        y2={y}
        stroke={stroke}
        strokeWidth={1}
        strokeDasharray={hidden ? "3 3" : undefined}
      />
      <circle cx={ax} cy={y} r={4} fill="var(--color-accent)" />
      <circle cx={bx} cy={y} r={4} fill="var(--color-accent)" />
      <text
        x={ax}
        y={y - 10}
        textAnchor="middle"
        fontFamily="var(--font-mono)"
        fontSize="9"
        fill="var(--color-text-muted)"
      >
        {truncateLabel(labelA)}
      </text>
      <text
        x={bx}
        y={y - 10}
        textAnchor="middle"
        fontFamily="var(--font-mono)"
        fontSize="9"
        fill="var(--color-text-muted)"
      >
        {truncateLabel(labelB)}
      </text>
    </svg>
  );
}

// --- Coupling pairs, unified across file/directory/subsystem grain --------

interface CouplingRow {
  key: string;
  labelA: string;
  labelB: string;
  degree: number;
  sharedRevs: number;
  /** null = unknown at this grain (directory -- no honest way to check,
   * see HONESTY.directoryGrainHasNoStructuralCrossReference). */
  hidden: boolean | null;
}

function CouplingPairsCard() {
  const { repo, share } = useOutletContext<RepoOutletContext>();
  const [searchParams, setSearchParams] = useSearchParams();
  const urlGranularity = searchParams.get("granularity");
  const [granularity, setGranularity] = useState<"file" | ModuleCouplingGranularity>(
    urlGranularity === "file" || urlGranularity === "directory" || urlGranularity === "subsystem"
      ? urlGranularity
      : "file",
  );
  const [hiddenOnly, setHiddenOnly] = useState(searchParams.get("hiddenOnly") === "1");

  const fileCoupling = useCoupling(repo.id, granularity === "file" ? share : undefined);
  const hiddenDeps = useHiddenDeps(repo.id, granularity === "file" ? share : undefined);
  const moduleCoupling = useModuleCoupling(
    repo.id,
    granularity === "subsystem" ? "subsystem" : "directory",
    granularity === "file" ? undefined : share,
  );
  // Best-effort cross-reference for the subsystem grain's hidden flag --
  // ModuleCouplingEngine emits its own "hidden_dependency" findings for
  // subsystem pairs (title "Hidden dependency: A <-> B (subsystems)"), but
  // that findings list is capped, so a pair genuinely below the coupling
  // finding's own threshold or rank cutoff may still be a real hidden
  // dependency without appearing here -- this flag is therefore an
  // under-count, never a false positive.
  const hiddenFindings = useFindings(repo.id, "hidden_dependency", share);

  function changeGranularity(next: string) {
    setGranularity(next as "file" | ModuleCouplingGranularity);
    setSearchParams(
      (prev) => {
        const merged = new URLSearchParams(prev);
        merged.set("granularity", next);
        return merged;
      },
      { replace: true },
    );
  }

  const hiddenFileKeys = useMemo(() => {
    if (hiddenDeps.data?.kind !== "data") return new Set<string>();
    return new Set(hiddenDeps.data.data.pairs.map((p) => pairKey(p.file_a_path, p.file_b_path)));
  }, [hiddenDeps.data]);

  const hiddenSubsystemKeys = useMemo(() => {
    if (hiddenFindings.data?.kind !== "data") return new Set<string>();
    const keys = new Set<string>();
    for (const f of hiddenFindings.data.data.findings) {
      const pair = parseHiddenDependencyPair(f.title);
      if (pair) keys.add(pairKey(pair[0], pair[1]));
    }
    return keys;
  }, [hiddenFindings.data]);

  const rows: CouplingRow[] | null = useMemo(() => {
    if (granularity === "file") {
      if (fileCoupling.data?.kind !== "data") return null;
      return fileCoupling.data.data.pairs.map((p) => ({
        key: pairKey(p.file_a_path, p.file_b_path),
        labelA: fileName(p.file_a_path),
        labelB: fileName(p.file_b_path),
        degree: p.coupling_degree,
        sharedRevs: p.shared_revs,
        hidden: hiddenFileKeys.has(pairKey(p.file_a_path, p.file_b_path)),
      }));
    }
    if (moduleCoupling.data?.kind !== "data") return null;
    return moduleCoupling.data.data.pairs.map((p) => ({
      key: pairKey(p.module_a, p.module_b),
      labelA: p.module_a,
      labelB: p.module_b,
      degree: p.coupling_degree,
      sharedRevs: p.shared_revs,
      hidden:
        granularity === "subsystem"
          ? hiddenSubsystemKeys.has(pairKey(p.module_a, p.module_b))
          : null,
    }));
  }, [granularity, fileCoupling.data, moduleCoupling.data, hiddenFileKeys, hiddenSubsystemKeys]);

  const activeQuery = granularity === "file" ? fileCoupling : moduleCoupling;
  const filterDisabled = granularity === "directory";
  const visibleRows = hiddenOnly && !filterDisabled ? (rows ?? []).filter((r) => r.hidden) : rows;

  return (
    <Card
      title="Coupling pairs"
      eyebrow="Files, directories, or subsystems that change together"
      action={
        <div className="flex flex-wrap items-center gap-3">
          <SegmentedControl
            aria-label="Coupling granularity"
            value={granularity}
            onValueChange={changeGranularity}
            options={[
              { value: "file", label: "File" },
              { value: "directory", label: "Directory" },
              { value: "subsystem", label: "Subsystem" },
            ]}
          />
          <label
            className={`flex items-center gap-1.5 text-xs ${filterDisabled ? "text-text-muted/50" : "text-text-muted"}`}
          >
            <input
              type="checkbox"
              checked={hiddenOnly && !filterDisabled}
              disabled={filterDisabled}
              onChange={(e) => setHiddenOnly(e.target.checked)}
              className="h-3.5 w-3.5 accent-accent"
            />
            No import only
          </label>
          <InfoTooltip label="What is coupling degree?" text={TOOLTIPS.couplingDegree} />
          {granularity !== "file" ? (
            <InfoTooltip
              label={`What is ${granularity} coupling?`}
              text={TOOLTIPS.moduleCoupling}
            />
          ) : null}
        </div>
      }
    >
      {filterDisabled ? (
        <HonestyNote
          variant="scope-limitation"
          text={HONESTY.directoryGrainHasNoStructuralCrossReference}
          className="mb-2"
        />
      ) : null}
      <CouplingPairsBody
        isPending={activeQuery.isPending}
        isError={activeQuery.isError}
        error={activeQuery.error}
        onRetry={() => void activeQuery.refetch()}
        // `rows` is derived from `activeQuery.data` above but typed
        // uniformly across the two response shapes (file vs.
        // directory/subsystem) -- `null` here means "not resolved to real
        // data yet" (still 202-pending), distinct from an empty array.
        rows={rows}
        visibleRows={visibleRows}
        hiddenOnly={hiddenOnly}
      />
    </Card>
  );
}

function CouplingPairsBody({
  isPending,
  isError,
  error,
  onRetry,
  rows,
  visibleRows,
  hiddenOnly,
}: {
  isPending: boolean;
  isError: boolean;
  error: unknown;
  onRetry: () => void;
  rows: CouplingRow[] | null;
  visibleRows: CouplingRow[] | null;
  hiddenOnly: boolean;
}) {
  if (isPending) return <LoadingState label="Loading coupling…" />;
  if (isError) return <ErrorState error={error} onRetry={onRetry} />;
  if (rows === null) return <LoadingState label="Loading coupling…" />;

  const visible = visibleRows ?? [];
  if (visible.length === 0) {
    return (
      <p className="py-6 text-center text-sm text-text-muted">
        {hiddenOnly
          ? "No pair at this granularity changes together with no import between them."
          : "No pairs above the coupling threshold."}
      </p>
    );
  }

  const shown = visible.slice(0, MAX_VISIBLE_COUPLING_PAIRS);
  const rest = visible.slice(MAX_VISIBLE_COUPLING_PAIRS);

  return (
    <div className="flex flex-col divide-y divide-border">
      <AnimatedList
        items={shown}
        keyFor={(r) => r.key}
        className="flex flex-col divide-y divide-border"
        renderItem={(r) => <CouplingPairRow row={r} />}
      />
      {rest.length > 0 ? (
        <Expander
          className="py-2"
          trigger={`${rest.length} more pair${rest.length === 1 ? "" : "s"}`}
        >
          <ul className="flex flex-col divide-y divide-border pt-1">
            {rest.map((r) => (
              <li key={r.key}>
                <CouplingPairRow row={r} />
              </li>
            ))}
          </ul>
        </Expander>
      ) : null}
    </div>
  );
}

function CouplingPairRow({ row: r }: { row: CouplingRow }) {
  return (
    <div className="flex flex-col gap-2 py-3 sm:flex-row sm:items-center">
      <PairDiagram labelA={r.labelA} labelB={r.labelB} hidden={r.hidden} />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="truncate font-mono text-xs text-text-muted">
            {r.labelA} ↔ {r.labelB}
          </span>
          {r.hidden ? (
            <span title={TOOLTIPS.hiddenDependency}>
              <Badge tone="med">no import</Badge>
            </span>
          ) : null}
        </div>
        <div className="mt-1 flex items-center gap-3 text-xs text-text-muted">
          <span className="cp-stat">{formatPercent(r.degree)} degree</span>
          <span>
            {r.sharedRevs} shared rev{r.sharedRevs === 1 ? "" : "s"}
          </span>
        </div>
      </div>
    </div>
  );
}

function pairKey(a: string, b: string): string {
  return [a, b].sort().join("|");
}

// =============================================================================
// Impact -- blast radius, ?path= and ?depth= deep-linkable
// =============================================================================

const DEPTH_OPTIONS = [1, 2, 3, 4, 5, 6];

function ImpactView() {
  const { repo, share } = useOutletContext<RepoOutletContext>();
  const [searchParams, setSearchParams] = useSearchParams();
  const path = searchParams.get("path") ?? undefined;
  const depth = Number(searchParams.get("depth") ?? "3");
  const city = useCity(repo.id, share);
  const blastRadius = useBlastRadius(repo.id, path, depth, share);

  const allPaths = useMemo(
    () => (city.data?.kind === "data" ? toCityFiles(city.data.data).map((f) => f.path) : []),
    [city.data],
  );

  function selectPath(next: string) {
    setSearchParams(
      (prev) => {
        const merged = new URLSearchParams(prev);
        merged.set("view", "impact");
        merged.set("path", next);
        return merged;
      },
      { replace: true },
    );
  }

  function changeDepth(next: number) {
    setSearchParams(
      (prev) => {
        const merged = new URLSearchParams(prev);
        merged.set("depth", String(next));
        return merged;
      },
      { replace: true },
    );
  }

  return (
    <Reveal>
      <Card
        title="Blast radius"
        eyebrow="What could be affected by changing one file"
        action={<InfoTooltip label="What is blast radius?" text={TOOLTIPS.blastRadius} />}
      >
        <div className="flex flex-wrap items-center gap-3">
          <FilePicker paths={allPaths} onSelect={selectPath} placeholder="Pick a file…" />
          {path ? (
            <label className="flex items-center gap-1.5 text-xs text-text-muted">
              Depth
              <select
                value={depth}
                onChange={(e) => changeDepth(Number(e.target.value))}
                className="rounded-sm border border-border-interactive bg-bg-elevated px-2 py-1 text-xs text-text"
              >
                {DEPTH_OPTIONS.map((d) => (
                  <option key={d} value={d}>
                    {d}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
        </div>

        {!path ? (
          <p className="mt-4 py-6 text-center text-sm text-text-muted">
            Pick a file above to see its blast radius.
          </p>
        ) : (
          <div className="mt-4">
            <StageGate
              query={blastRadius}
              loadingLabel="Computing blast radius…"
              emptyTitle="No affected files"
              emptyMessage="No files were found to be structurally or historically affected by this file."
            >
              {(data) => (
                <div className="flex flex-col gap-4">
                  {/* The flagship insight of the whole product: rendered
                      FIRST, above the two obvious lists, visually distinct. */}
                  {data.surprising_affected.length > 0 ? (
                    <div className="rounded-md border-2 border-warning bg-warning-bg p-3">
                      <h3 className="cp-label mb-2 flex items-center gap-1.5 text-warning">
                        Coupled but never imported ({data.surprising_affected.length})
                        <InfoTooltip
                          label="What does 'coupled but never imported' mean?"
                          text={TOOLTIPS.surprisingAffected}
                        />
                      </h3>
                      <AnimatedList
                        items={data.surprising_affected}
                        keyFor={(f) => f.file_path}
                        className="flex flex-col gap-1"
                        renderItem={(f) => (
                          <div className="flex items-center justify-between gap-2 font-mono text-xs text-text">
                            <span className="truncate">{f.file_path}</span>
                            {f.coupling_degree != null ? (
                              <span className="shrink-0 tabular-nums text-warning">
                                {formatPercent(f.coupling_degree)}
                              </span>
                            ) : null}
                          </div>
                        )}
                      />
                    </div>
                  ) : null}

                  <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                    <div>
                      <h3 className="cp-label mb-1.5 text-text-muted">
                        Imports this file ({data.structural_affected.length})
                      </h3>
                      <AnimatedList
                        items={data.structural_affected}
                        keyFor={(f) => f.file_path}
                        className="flex flex-col gap-1"
                        renderItem={(f) => (
                          <p className="truncate font-mono text-xs text-text-muted">
                            {f.file_path}
                          </p>
                        )}
                      />
                    </div>
                    <div>
                      <h3 className="cp-label mb-1.5 text-text-muted">
                        Changes with this file ({data.historical_affected.length})
                      </h3>
                      <AnimatedList
                        items={data.historical_affected}
                        keyFor={(f) => f.file_path}
                        className="flex flex-col gap-1"
                        renderItem={(f) => (
                          <p className="truncate font-mono text-xs text-text-muted">
                            {f.file_path}
                          </p>
                        )}
                      />
                    </div>
                  </div>

                  {data.depth_capped || data.node_cap_engaged ? (
                    <p className="text-xs text-text-muted">
                      {data.depth_capped ? "Stopped at the maximum depth. " : ""}
                      {data.node_cap_engaged ? "Stopped at the maximum node count. " : ""}
                      This may not be the complete blast radius.
                    </p>
                  ) : null}
                </div>
              )}
            </StageGate>
          </div>
        )}
      </Card>
    </Reveal>
  );
}
