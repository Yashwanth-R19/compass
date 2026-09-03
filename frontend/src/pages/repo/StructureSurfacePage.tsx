import { useEffect, useMemo, useState } from "react";
import { useOutletContext, useSearchParams } from "react-router-dom";
import ForceGraph2D from "react-force-graph-2d";
import {
  useArchitecture,
  useBlastRadius,
  useCoupling,
  useHiddenDeps,
  useKnowledgeMap,
  useModuleCoupling,
  useSubsystems,
} from "../../api/hooks";
import type {
  BlastRadiusAffectedFileOut,
  BlastRadiusResponse,
  ModuleCouplingGranularity,
} from "../../api/types";
import { Card } from "../../components/ui/Card";
import { EmptyState } from "../../components/EmptyState";
import { ErrorState } from "../../components/ErrorState";
import { EvidenceLink } from "../../components/EvidenceLink";
import { FilePicker } from "../../components/FilePicker";
import { GraphCanvas } from "../../components/GraphCanvas";
import { GraphCapNotice } from "../../components/GraphCapNotice";
import { HonestyNote } from "../../components/HonestyNote";
import { InfoTooltip } from "../../components/ui/InfoTooltip";
import { LoadingState } from "../../components/LoadingState";
import { PartialResultNotice } from "../../components/PartialResultNotice";
import { ScoreExplainer } from "../../components/ScoreExplainer";
import { SegmentedControl } from "../../components/ui/SegmentedControl";
import { StageGate } from "../../components/StageGate";
import { HONESTY, TOOLTIPS } from "../../content/explainability";
import { useCappedGraph, type CappableEdge, type CappableNode } from "../../hooks/useGraphCap";
import { SEVERITY_CLASSES, SEVERITY_LABEL, fileName, formatPercent } from "../../lib/format";
import { colorForSubsystem } from "../../lib/subsystemColors";
import { CHROME, SEVERITY_COLOR } from "../../lib/chartTheme";
import type { RepoOutletContext } from "../RepoLayout";

type StructureView = "architecture" | "coupling" | "impact";

function isStructureView(v: string | null): v is StructureView {
  return v === "architecture" || v === "coupling" || v === "impact";
}

/**
 * `/repos/:id/structure` (UI rebuild session 4, Part C) -- merges the
 * former Architecture, Coupling, and Impact pages behind
 * `?view=architecture|coupling|impact`.
 */
export function StructureSurfacePage() {
  const { repo, share } = useOutletContext<RepoOutletContext>();
  const [searchParams, setSearchParams] = useSearchParams();
  const urlView = searchParams.get("view");
  const [view, setView] = useState<StructureView>(
    isStructureView(urlView) ? urlView : "architecture",
  );

  useEffect(() => {
    if (isStructureView(urlView)) setView(urlView);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [urlView]);

  // A `?pair=` deep link from a hidden_dependency finding always means file
  // grain on Coupling -- forcing the view here too, since a file-pair
  // signature only ever means file grain.
  useEffect(() => {
    if (searchParams.get("pair")) setView("coupling");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams.get("pair")]);

  function changeView(next: string) {
    setView(next as StructureView);
    setSearchParams(
      (prev) => {
        const merged = new URLSearchParams(prev);
        merged.set("view", next);
        return merged;
      },
      { replace: true },
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <SegmentedControl
        aria-label="Structure view"
        value={view}
        onValueChange={changeView}
        options={[
          { value: "architecture", label: "Architecture" },
          { value: "coupling", label: "Coupling" },
          { value: "impact", label: "Impact" },
        ]}
      />
      {view === "coupling" ? (
        <CouplingView repoId={repo.id} share={share} />
      ) : view === "impact" ? (
        <ImpactView repoId={repo.id} repoUrl={repo.url} share={share} />
      ) : (
        <ArchitectureView repoId={repo.id} share={share} />
      )}
    </div>
  );
}

// --- Architecture view ---------------------------------------------------------

interface ArchEdge extends CappableEdge {
  inCycle: boolean;
}

const CYCLE_COLOR = SEVERITY_COLOR.high;
const SELECTED_COLOR = CHROME.signal;
const NORMAL_COLOR = CHROME.inkMuted;
const DIMMED_COLOR = CHROME.border;

/** Pure, so it's testable without rendering a canvas (Known Hazard #4).
 * Priority: an explicit selection always wins; a cycle is the next most
 * important thing to see, so it keeps its own fixed colour even over a
 * subsystem's; everything else colors by subsystem via
 * `lib/subsystemColors.ts::colorForSubsystem` -- the SAME function and the
 * SAME label the Map surface and the 3D city resolve a subsystem's colour
 * from, so a subsystem reads as the same colour in every view. */
export function resolveNodeColor(
  id: string,
  {
    selectedNode,
    inCycle,
    subsystemLabel,
  }: { selectedNode: string | null; inCycle: boolean; subsystemLabel: string | null | undefined },
): string {
  if (selectedNode && id === selectedNode) return SELECTED_COLOR;
  if (inCycle) return CYCLE_COLOR;
  return colorForSubsystem(subsystemLabel);
}

function ArchitectureView({ repoId, share }: { repoId: string; share?: string }) {
  const arch = useArchitecture(repoId, share);
  const subsystems = useSubsystems(repoId, true, share);
  const [searchParams, setSearchParams] = useSearchParams();
  const [selectedNode, setSelectedNode] = useState<string | null>(searchParams.get("file"));

  useEffect(() => {
    const target = searchParams.get("file");
    if (target) setSelectedNode(target);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams.get("file")]);

  function select(id: string | null) {
    setSelectedNode(id);
    setSearchParams(
      (prev) => {
        const merged = new URLSearchParams(prev);
        if (id) merged.set("file", id);
        else merged.delete("file");
        return merged;
      },
      { replace: true },
    );
  }

  const archData = arch.data?.kind === "data" ? arch.data.data : undefined;

  const pathSubsystemLabel = useMemo(() => {
    const map = new Map<string, string>();
    if (subsystems.data?.kind !== "data") return map;
    for (const s of subsystems.data.data.subsystems) {
      for (const m of s.members ?? []) map.set(m.file_path, s.label);
    }
    return map;
  }, [subsystems.data]);

  const { cycleNodeIds, cycleEdgeKeys } = useMemo(() => {
    const nodeIds = new Set<string>();
    const edgeKeys = new Set<string>();
    for (const cycle of archData?.cycles ?? []) {
      for (let i = 0; i < cycle.files.length; i++) {
        const a = cycle.files[i];
        const b = cycle.files[(i + 1) % cycle.files.length];
        nodeIds.add(a);
        edgeKeys.add(`${a}->${b}`);
      }
    }
    return { cycleNodeIds: nodeIds, cycleEdgeKeys: edgeKeys };
  }, [archData]);

  const { nodes, edges } = useMemo(() => {
    if (!archData) return { nodes: [] as CappableNode[], edges: [] as ArchEdge[] };
    const builtEdges: ArchEdge[] = archData.edges.map((e) => ({
      source: e.from_path,
      target: e.to_path,
      weight: 1,
      inCycle: cycleEdgeKeys.has(`${e.from_path}->${e.to_path}`),
    }));
    return { nodes: archData.nodes.map((id) => ({ id })), edges: builtEdges };
  }, [archData, cycleEdgeKeys]);

  const capped = useCappedGraph(nodes, edges);

  const selectedEdges = useMemo(() => {
    if (!selectedNode || !archData) return [];
    return archData.edges.filter((e) => e.from_path === selectedNode || e.to_path === selectedNode);
  }, [selectedNode, archData]);

  return (
    <StageGate
      query={arch}
      loadingLabel="Loading architecture graph…"
      emptyTitle="No structural graph yet"
      emptyMessage="No import edges were found for this repo's supported languages."
      isEmpty={(data) => data.nodes.length === 0}
    >
      {(data) => (
        <div className="flex flex-col gap-4">
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_320px]">
            <Card>
              <GraphCapNotice
                nodesCapped={capped.nodesCapped}
                edgesCapped={capped.edgesCapped}
                shownNodes={capped.nodes.length}
                totalNodes={capped.totalNodes}
              />
              <GraphCanvas>
                {({ width, height }) => (
                  <ForceGraph2D
                    graphData={{ nodes: capped.nodes, links: capped.edges }}
                    width={width}
                    height={height}
                    backgroundColor="rgba(0,0,0,0)"
                    nodeRelSize={4}
                    nodeLabel={(n) => (n as CappableNode).id}
                    nodeColor={(n) => {
                      const id = (n as CappableNode).id;
                      return resolveNodeColor(id, {
                        selectedNode,
                        inCycle: cycleNodeIds.has(id),
                        subsystemLabel: pathSubsystemLabel.get(id),
                      });
                    }}
                    linkColor={(l) => {
                      const link = l as unknown as ArchEdge;
                      // react-force-graph mutates source/target from a path
                      // string into the resolved node object once the
                      // simulation starts, even though our own graph data
                      // typed them as strings.
                      const rawSource = (l as { source?: unknown }).source;
                      const rawTarget = (l as { target?: unknown }).target;
                      const sourceId =
                        typeof rawSource === "string" ? rawSource : (rawSource as CappableNode).id;
                      const targetId =
                        typeof rawTarget === "string" ? rawTarget : (rawTarget as CappableNode).id;
                      if (selectedNode && sourceId !== selectedNode && targetId !== selectedNode)
                        return DIMMED_COLOR;
                      return link.inCycle ? CYCLE_COLOR : NORMAL_COLOR;
                    }}
                    linkDirectionalArrowLength={4}
                    linkDirectionalArrowRelPos={1}
                    linkWidth={(l) => ((l as unknown as ArchEdge).inCycle ? 2 : 1)}
                    onNodeClick={(n) => {
                      const id = (n as CappableNode).id;
                      select(selectedNode === id ? null : id);
                    }}
                    onBackgroundClick={() => select(null)}
                  />
                )}
              </GraphCanvas>
              <p className="mt-2 text-xs text-text-muted">
                Node colour follows subsystem — the same palette as the Map surface and the 3D city.
                Red marks a cycle; the selected node is highlighted in accent.
              </p>
            </Card>

            <div className="flex flex-col gap-4">
              {selectedNode ? (
                <Card
                  title="Selected file"
                  eyebrow={selectedNode}
                  action={
                    <button
                      type="button"
                      onClick={() => select(null)}
                      className="text-xs text-text-muted hover:text-text"
                    >
                      Clear
                    </button>
                  }
                >
                  {selectedEdges.length === 0 ? (
                    <p className="text-sm text-text-muted">No import edges.</p>
                  ) : (
                    <ul className="space-y-1.5 text-sm">
                      {selectedEdges.map((e) => (
                        <li key={`${e.from_path}->${e.to_path}`} className="text-text-muted">
                          {e.from_path === selectedNode ? (
                            <>
                              imports <span className="font-medium">{fileName(e.to_path)}</span>
                            </>
                          ) : (
                            <>
                              imported by{" "}
                              <span className="font-medium">{fileName(e.from_path)}</span>
                            </>
                          )}
                        </li>
                      ))}
                    </ul>
                  )}
                </Card>
              ) : null}

              <Card title="Cycles" eyebrow={`${data.cycles.length} found`}>
                {data.cycles.length === 0 ? (
                  <p className="text-sm text-text-muted">No circular dependencies.</p>
                ) : (
                  <ul className="space-y-2 text-sm">
                    {data.cycles.map((c, i) => (
                      <li key={i}>
                        <span
                          className={`mr-1.5 inline-flex items-center rounded-xs px-1.5 py-0.5 text-[10px] font-medium ${SEVERITY_CLASSES[c.severity]}`}
                        >
                          {SEVERITY_LABEL[c.severity]}
                        </span>
                        <span className="text-text-muted">{c.files.map(fileName).join(" → ")}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </Card>

              <Card
                title="Layering violations"
                eyebrow={`${data.layering_violations.length} found`}
              >
                <HonestyNote
                  variant="scope-limitation"
                  text={HONESTY.layeringHeuristicConservative}
                />
                {data.layering_violations.length === 0 ? (
                  <p className="mt-2 text-sm text-text-muted">No layering violations found.</p>
                ) : (
                  <ul className="mt-2 space-y-2 text-sm">
                    {data.layering_violations.map((v, i) => (
                      <li key={i}>
                        <span
                          className={`mr-1.5 inline-flex items-center rounded-xs px-1.5 py-0.5 text-[10px] font-medium ${SEVERITY_CLASSES[v.severity]}`}
                        >
                          {SEVERITY_LABEL[v.severity]}
                        </span>
                        <span className="text-text-muted">
                          {fileName(v.from_path)} → {fileName(v.to_path)}{" "}
                          <span className="text-text-muted">({v.kind})</span>
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </Card>
            </div>
          </div>

          {/* Session 07's honest, free replacement for dead-code detection --
              deliberately NOT rendered as findings (no severity, no rank,
              never FindingItem/SeverityChip): a plain informational list
              with its own caveat, since a file appearing here may just mean
              Compass doesn't parse how it's reached. */}
          <Card
            title="Unreferenced files"
            eyebrow={`${data.unreferenced_files.length} file${data.unreferenced_files.length === 1 ? "" : "s"} with no detected structural reference`}
          >
            <p className="mb-3 rounded-md bg-bg-inset px-3 py-2 text-xs text-text-muted">
              {data.unreferenced_files_caveat}
            </p>
            {data.unreferenced_files.length === 0 ? (
              <p className="text-sm text-text-muted">
                Every file has at least one detected structural reference.
              </p>
            ) : (
              <ul
                tabIndex={0}
                aria-label="Unreferenced files, scrollable"
                className="flex max-h-64 flex-col divide-y divide-border overflow-y-auto text-sm"
              >
                {data.unreferenced_files.map((f) => (
                  <li key={f.file_path} className="flex items-center justify-between gap-2 py-1.5">
                    <span
                      className="truncate font-mono text-xs text-text-muted"
                      title={f.file_path}
                    >
                      {f.file_path}
                    </span>
                    <span className="shrink-0 text-xs text-text-muted">
                      {f.loc.toLocaleString()} LOC
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      )}
    </StageGate>
  );
}

// --- Coupling view ---------------------------------------------------------------

type Granularity = ModuleCouplingGranularity | "file";

interface CouplingEdge extends CappableEdge {
  isHidden: boolean;
  sharedRevs: number;
  confidence: string;
}
interface CouplingPair {
  a: string;
  b: string;
  coupling_degree: number;
  shared_revs: number;
  avg_revs: number;
  confidence: string;
  hidden: boolean;
}

const HIDDEN_COLOR = SEVERITY_COLOR.med;

function pairKey(a: string, b: string): string {
  return [a, b].sort().join("|");
}

/** Cross-references `/module-coupling?granularity=subsystem` (the LOCKED
 * formula, read straight) against `/architecture`'s file-level structural
 * edges aggregated up to subsystem pairs -- a plain existence check ("does
 * ANY import cross this subsystem pair"), legitimate to compute
 * client-side because it's a count, not the coupling_degree formula itself.
 * Directory granularity has no equivalent -- the backend's directory
 * truncation depth isn't known to the frontend. */
function useStructuralSubsystemPairs(repoId: string, share?: string): Set<string> {
  const subsystems = useSubsystems(repoId, true, share);
  const architecture = useArchitecture(repoId, share);

  return useMemo(() => {
    const pairs = new Set<string>();
    if (subsystems.data?.kind !== "data" || architecture.data?.kind !== "data") return pairs;

    const pathLabel = new Map<string, string>();
    for (const s of subsystems.data.data.subsystems) {
      for (const m of s.members ?? []) pathLabel.set(m.file_path, s.label);
    }
    for (const e of architecture.data.data.edges) {
      const from = pathLabel.get(e.from_path);
      const to = pathLabel.get(e.to_path);
      if (from && to && from !== to) pairs.add(pairKey(from, to));
    }
    return pairs;
  }, [subsystems.data, architecture.data]);
}

function CouplingView({ repoId, share }: { repoId: string; share?: string }) {
  const [searchParams] = useSearchParams();
  const [granularity, setGranularity] = useState<Granularity>("subsystem");
  const [hiddenOnly, setHiddenOnly] = useState(false);
  const [highlightPair, setHighlightPair] = useState<[string, string] | null>(null);

  // A hidden_dependency finding's deep link (lib/findingLinks.ts) arrives as
  // `?view=coupling&pair=a|b&hiddenOnly=1` -- that pair is always a FILE
  // pair (the signature convention for a file-level hidden_dependency
  // finding), so landing here forces file granularity.
  useEffect(() => {
    const pairParam = searchParams.get("pair");
    const hiddenParam = searchParams.get("hiddenOnly");
    if (pairParam) {
      const [a, b] = pairParam.split("|");
      if (a && b) {
        setGranularity("file");
        setHighlightPair([a, b]);
      }
    }
    if (hiddenParam === "1") setHiddenOnly(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams.get("pair"), searchParams.get("hiddenOnly")]);

  const moduleCoupling = useModuleCoupling(
    repoId,
    granularity === "file" ? "directory" : granularity,
    share,
  );
  const fileCoupling = useCoupling(repoId, share);
  const hiddenDeps = useHiddenDeps(repoId, share);
  const structuralSubsystemPairs = useStructuralSubsystemPairs(repoId, share);

  const isLoading =
    granularity === "file"
      ? fileCoupling.isPending || fileCoupling.data?.kind === "pending"
      : moduleCoupling.isPending || moduleCoupling.data?.kind === "pending";
  const isError = granularity === "file" ? fileCoupling.isError : moduleCoupling.isError;

  const { pairs, lowConfidence } = useMemo((): {
    pairs: CouplingPair[];
    lowConfidence: boolean;
  } => {
    if (granularity === "file") {
      if (fileCoupling.data?.kind !== "data") return { pairs: [], lowConfidence: false };
      const hiddenKeys = new Set(
        hiddenDeps.data?.kind === "data"
          ? hiddenDeps.data.data.pairs.map((p) => pairKey(p.file_a_path, p.file_b_path))
          : [],
      );
      return {
        pairs: fileCoupling.data.data.pairs.map((p) => ({
          a: p.file_a_path,
          b: p.file_b_path,
          coupling_degree: p.coupling_degree,
          shared_revs: p.shared_revs,
          avg_revs: p.avg_revs,
          confidence: p.confidence,
          hidden: hiddenKeys.has(pairKey(p.file_a_path, p.file_b_path)),
        })),
        lowConfidence: fileCoupling.data.data.low_confidence,
      };
    }
    if (moduleCoupling.data?.kind !== "data") return { pairs: [], lowConfidence: false };
    return {
      pairs: moduleCoupling.data.data.pairs.map((p) => ({
        a: p.module_a,
        b: p.module_b,
        coupling_degree: p.coupling_degree,
        shared_revs: p.shared_revs,
        avg_revs: p.avg_revs,
        confidence: p.confidence,
        hidden:
          granularity === "subsystem" &&
          !structuralSubsystemPairs.has(pairKey(p.module_a, p.module_b)),
      })),
      lowConfidence: moduleCoupling.data.data.low_confidence,
    };
  }, [
    granularity,
    fileCoupling.data,
    moduleCoupling.data,
    hiddenDeps.data,
    structuralSubsystemPairs,
  ]);

  const visiblePairs = hiddenOnly ? pairs.filter((p) => p.hidden) : pairs;
  const topPair = visiblePairs[0];

  const { nodes, edges } = useMemo(() => {
    const nodeIds = new Set<string>();
    const builtEdges: CouplingEdge[] = visiblePairs.map((p) => {
      nodeIds.add(p.a);
      nodeIds.add(p.b);
      return {
        source: p.a,
        target: p.b,
        weight: p.coupling_degree,
        sharedRevs: p.shared_revs,
        isHidden: p.hidden,
        confidence: p.confidence,
      };
    });
    return { nodes: [...nodeIds].map((id) => ({ id })), edges: builtEdges };
  }, [visiblePairs]);

  const capped = useCappedGraph(nodes, edges);

  if (isError) {
    return (
      <Card>
        <p className="text-sm text-danger">Couldn't load coupling data.</p>
      </Card>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <SegmentedControl
        aria-label="Coupling granularity"
        value={granularity}
        onValueChange={(g) => setGranularity(g as Granularity)}
        options={[
          { value: "subsystem", label: "Subsystem" },
          { value: "directory", label: "Directory" },
          { value: "file", label: "File" },
        ]}
      />

      <Card
        eyebrow="Change coupling"
        title="coupling_degree"
        action={<InfoTooltip label="What is coupling_degree?" text={TOOLTIPS.couplingDegree} />}
      >
        <ScoreExplainer
          formulaKey="coupling"
          contributions={[]}
          alsoMeasured={
            topPair
              ? [
                  {
                    label: "Shared revisions (top pair)",
                    value: String(topPair.shared_revs),
                    tooltip: "sharedRevisions",
                  },
                  {
                    label: "Average revisions (top pair)",
                    value: formatScoreLike(topPair.avg_revs),
                    tooltip: "avgRevisions",
                  },
                  { label: "Confidence hint (top pair)", value: topPair.confidence },
                ]
              : []
          }
        />
        {granularity !== "file" ? (
          <p className="mt-2 flex items-center gap-1 text-xs text-text-muted">
            {TOOLTIPS.moduleCoupling}
          </p>
        ) : null}
        {lowConfidence ? (
          <HonestyNote
            variant="confidence-caveat"
            text={HONESTY.couplingLowConfidence}
            className="mt-2"
          />
        ) : null}
      </Card>

      {isLoading ? (
        <Card>
          <p className="py-8 text-center text-sm text-text-muted">Loading coupling data…</p>
        </Card>
      ) : pairs.length === 0 ? (
        <Card>
          <p className="py-8 text-center text-sm text-text-muted">
            No coupling pairs found at this granularity yet.
          </p>
        </Card>
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_360px]">
          <Card>
            <div className="mb-2 flex flex-wrap items-center justify-between gap-3">
              <GraphCapNotice
                nodesCapped={capped.nodesCapped}
                edgesCapped={capped.edgesCapped}
                shownNodes={capped.nodes.length}
                totalNodes={capped.totalNodes}
              />
              {granularity !== "directory" ? (
                <label className="flex shrink-0 items-center gap-2 text-xs text-text-muted">
                  <input
                    type="checkbox"
                    checked={hiddenOnly}
                    onChange={(e) => setHiddenOnly(e.target.checked)}
                    className="accent-accent"
                  />
                  Hidden dependencies only
                </label>
              ) : (
                <span className="max-w-xs text-xs text-text-muted">
                  {HONESTY.directoryGrainHasNoStructuralCrossReference}
                </span>
              )}
            </div>
            <GraphCanvas>
              {({ width, height }) => (
                <ForceGraph2D
                  graphData={{ nodes: capped.nodes, links: capped.edges }}
                  width={width}
                  height={height}
                  backgroundColor="rgba(0,0,0,0)"
                  nodeRelSize={4}
                  nodeLabel={(n) => (n as CappableNode).id}
                  nodeColor={(n) => {
                    const id = (n as CappableNode).id;
                    if (highlightPair && (id === highlightPair[0] || id === highlightPair[1]))
                      return CHROME.signal;
                    return granularity === "subsystem" ? colorForSubsystem(id) : CHROME.inkMuted;
                  }}
                  linkColor={(l) =>
                    (l as unknown as CouplingEdge).isHidden ? HIDDEN_COLOR : NORMAL_COLOR
                  }
                  linkWidth={(l) => {
                    const edge = l as unknown as CouplingEdge;
                    return edge.isHidden ? 2 + edge.weight * 4 : 0.5 + edge.weight * 4;
                  }}
                  linkLineDash={(l) => ((l as unknown as CouplingEdge).isHidden ? [6, 3] : null)}
                  linkLabel={(l) => {
                    const link = l as unknown as CouplingEdge;
                    return `${formatPercent(link.weight)} coupled, ${link.sharedRevs} shared commits${link.isHidden ? " — hidden dependency" : ""}`;
                  }}
                />
              )}
            </GraphCanvas>
          </Card>

          <Card
            title="Ranked pairs"
            eyebrow={`${visiblePairs.length} of ${pairs.length}${hiddenOnly ? " (hidden only)" : ""}`}
          >
            <ul
              tabIndex={0}
              aria-label="Ranked coupling pairs, scrollable"
              className="max-h-[480px] divide-y divide-border overflow-y-auto text-sm"
            >
              {visiblePairs.map((p) => {
                const isTarget =
                  highlightPair &&
                  pairKey(p.a, p.b) === pairKey(highlightPair[0], highlightPair[1]);
                return (
                  <li
                    key={pairKey(p.a, p.b)}
                    className={`py-2 ${isTarget ? "rounded bg-accent-bg px-1.5" : ""}`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate font-medium text-text-muted">
                        {granularity === "file" ? fileName(p.a) : p.a} ↔{" "}
                        {granularity === "file" ? fileName(p.b) : p.b}
                      </span>
                      {p.hidden ? (
                        <span className="shrink-0 rounded-full bg-warning-bg px-1.5 py-0.5 text-[10px] font-medium text-warning">
                          hidden
                        </span>
                      ) : null}
                    </div>
                    <p className="text-xs text-text-muted">
                      {formatPercent(p.coupling_degree)} coupled · {p.shared_revs} shared commits ·{" "}
                      {p.confidence} confidence
                    </p>
                  </li>
                );
              })}
            </ul>
          </Card>
        </div>
      )}
    </div>
  );
}

function formatScoreLike(value: number): string {
  return value.toFixed(1);
}

// --- Impact view -----------------------------------------------------------------

const MIN_DEPTH = 1;
const MAX_DEPTH = 6;
const DEFAULT_DEPTH = 3;

function clampDepth(value: number): number {
  return Math.min(MAX_DEPTH, Math.max(MIN_DEPTH, value));
}

function ImpactView({
  repoId,
  repoUrl,
  share,
}: {
  repoId: string;
  repoUrl: string;
  share?: string;
}) {
  const [searchParams, setSearchParams] = useSearchParams();
  const knowledgeMap = useKnowledgeMap(repoId, share);

  const [selectedPath, setSelectedPath] = useState<string | null>(searchParams.get("path"));
  const [depth, setDepth] = useState(
    clampDepth(Number(searchParams.get("depth")) || DEFAULT_DEPTH),
  );

  const blastRadius = useBlastRadius(repoId, selectedPath ?? undefined, depth, share);

  const paths = useMemo(() => {
    if (knowledgeMap.data?.kind !== "data") return [];
    return knowledgeMap.data.data.files.map((f) => f.file_path);
  }, [knowledgeMap.data]);

  // Merges into the surface's OWN `view` param (and any other param already
  // present) rather than replacing the whole query string -- unlike the
  // pre-rebuild ImpactPage, which called `setSearchParams({...})` with a
  // plain object and silently wiped `view` as a side effect.
  function patch(next: Record<string, string>) {
    setSearchParams(
      (prev) => {
        const merged = new URLSearchParams(prev);
        for (const [k, v] of Object.entries(next)) merged.set(k, v);
        return merged;
      },
      { replace: true },
    );
  }

  function selectPath(path: string) {
    setSelectedPath(path);
    patch({ path, depth: String(depth) });
  }

  function changeDepth(next: number) {
    const clamped = clampDepth(next);
    setDepth(clamped);
    if (selectedPath) patch({ path: selectedPath, depth: String(clamped) });
  }

  return (
    <div className="flex flex-col gap-4">
      <Card title="Impact explorer" eyebrow="Pick a file to see what it affects">
        <FilePicker paths={paths} onSelect={selectPath} placeholder="Search files by path…" />
      </Card>

      {!selectedPath ? (
        <EmptyState
          title="Pick a file"
          message="Select a file above to see its structural and historical blast radius."
        />
      ) : blastRadius.isPending ? (
        <LoadingState label="Computing blast radius…" />
      ) : blastRadius.isError ? (
        <ErrorState error={blastRadius.error} onRetry={() => void blastRadius.refetch()} />
      ) : blastRadius.data.kind === "pending" ? (
        <LoadingState label="Computing blast radius…" />
      ) : (
        <BlastRadiusResult
          data={blastRadius.data.data}
          repoUrl={repoUrl}
          depth={depth}
          onDepthChange={changeDepth}
        />
      )}
    </div>
  );
}

function BlastRadiusResult({
  data,
  repoUrl,
  depth,
  onDepthChange,
}: {
  data: BlastRadiusResponse;
  repoUrl: string;
  depth: number;
  onDepthChange: (depth: number) => void;
}) {
  return (
    <div className="flex flex-col gap-4">
      <DepthSlider depth={depth} onChange={onDepthChange} />

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Headline
          label="Files affected"
          value={data.total_affected_count.toLocaleString()}
          tooltip="blastRadius"
        />
        <Headline label="% of repository" value={formatPercent(data.percentage_of_repo_files)} />
        <Headline
          label="Subsystems touched"
          value={data.subsystems_touched.length.toLocaleString()}
        />
        <Headline label="Reviewers needed" value={data.experts_to_review.length.toLocaleString()} />
      </div>

      {/* The money output: coupled-but-not-imported, FIRST and visually
          distinct -- this is the non-obvious result and the whole reason
          blast radius exists as a feature, not a footnote below the two
          "obvious" lists. */}
      <Card
        title="Coupled but NOT imported"
        eyebrow="Changes with this file historically, with no import connecting them at all"
        action={
          <InfoTooltip label="What is surprising_affected?" text={TOOLTIPS.surprisingAffected} />
        }
        className="border-2 border-warning ring-2 ring-warning-bg"
      >
        {data.surprising_affected.length === 0 ? (
          <p className="text-sm text-text-muted">
            Nothing surprising -- every historically co-changed file is also structurally connected.
          </p>
        ) : (
          <ul className="flex flex-col divide-y divide-border">
            {data.surprising_affected.map((f) => (
              <AffectedFileRow key={f.file_path} file={f} showCoupling />
            ))}
          </ul>
        )}
      </Card>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card
          title="Imports you, directly or transitively"
          eyebrow={`${data.structural_affected.length} files`}
        >
          <PartialResultNotice
            shown={data.structural_affected.length}
            total={data.structural_affected.length}
            itemLabel="structurally affected files"
            capped={data.depth_capped || data.node_cap_engaged}
          />
          {data.structural_affected.length === 0 ? (
            <p className="text-sm text-text-muted">No structural dependents.</p>
          ) : (
            <ul
              tabIndex={0}
              aria-label="Structurally affected files, scrollable"
              className="flex max-h-96 flex-col divide-y divide-border overflow-y-auto"
            >
              {data.structural_affected.map((f) => (
                <AffectedFileRow key={f.file_path} file={f} showHops />
              ))}
            </ul>
          )}
        </Card>

        <Card
          title="Changes with you historically"
          eyebrow={`${data.historical_affected.length} files`}
        >
          {data.historical_affected.length === 0 ? (
            <p className="text-sm text-text-muted">No strong historical coupling.</p>
          ) : (
            <ul
              tabIndex={0}
              aria-label="Historically affected files, scrollable"
              className="flex max-h-96 flex-col divide-y divide-border overflow-y-auto"
            >
              {data.historical_affected.map((f) => (
                <AffectedFileRow key={f.file_path} file={f} showCoupling />
              ))}
            </ul>
          )}
        </Card>
      </div>

      {data.historical_evidence.length > 0 ? (
        <Card
          title="Historical evidence"
          eyebrow={`Of ${data.commits_touching_path} commits touching this file`}
        >
          <ul className="flex flex-col divide-y divide-border text-sm">
            {data.historical_evidence.map((e) => (
              <li key={e.affected_path} className="flex flex-col gap-1 py-2.5">
                <p className="text-text-muted">
                  Of the {data.commits_touching_path} commits touching this file,{" "}
                  <span className="font-medium">{e.shared_commit_count}</span> (
                  {formatPercent(e.shared_commit_percentage)}) also touched{" "}
                  <span className="font-mono text-xs">{e.affected_path}</span>
                </p>
                <div className="flex flex-wrap gap-1.5">
                  {e.example_shas.map((sha) => (
                    <EvidenceLink key={sha} repoUrl={repoUrl} sha={sha} />
                  ))}
                </div>
              </li>
            ))}
          </ul>
        </Card>
      ) : null}
    </div>
  );
}

function AffectedFileRow({
  file,
  showHops = false,
  showCoupling = false,
}: {
  file: BlastRadiusAffectedFileOut;
  showHops?: boolean;
  showCoupling?: boolean;
}) {
  return (
    <li className="flex items-center justify-between gap-2 py-2 text-sm">
      <span className="truncate font-mono text-xs text-text-muted" title={file.file_path}>
        {file.file_path}
      </span>
      <span className="shrink-0 text-xs text-text-muted">
        {showHops && file.hop_distance != null
          ? `${file.hop_distance} hop${file.hop_distance === 1 ? "" : "s"}`
          : null}
        {showCoupling && file.coupling_degree != null ? formatPercent(file.coupling_degree) : null}
      </span>
    </li>
  );
}

function Headline({
  label,
  value,
  tooltip,
}: {
  label: string;
  value: string;
  tooltip?: keyof typeof TOOLTIPS;
}) {
  return (
    <div className="rounded-lg border border-border bg-bg-elevated p-3">
      <p className="flex items-center gap-1 text-xs text-text-muted">
        {label}
        {tooltip ? <InfoTooltip label={`What is ${label}?`} text={TOOLTIPS[tooltip]} /> : null}
      </p>
      <p className="text-xl font-semibold tabular-nums text-text">{value}</p>
    </div>
  );
}

function DepthSlider({ depth, onChange }: { depth: number; onChange: (depth: number) => void }) {
  return (
    <label className="flex items-center gap-3 text-xs text-text-muted">
      Depth
      <input
        type="range"
        min={MIN_DEPTH}
        max={MAX_DEPTH}
        step={1}
        value={depth}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-40 accent-accent"
      />
      <span className="tabular-nums font-medium text-text">{depth}</span>
    </label>
  );
}
