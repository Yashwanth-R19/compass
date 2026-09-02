import { useEffect, useMemo, useState } from "react";
import { useOutletContext, useSearchParams } from "react-router-dom";
import ForceGraph2D from "react-force-graph-2d";
import { useArchitecture, useSubsystems } from "../../api/hooks";
import { Card } from "../../components/Card";
import { GraphCanvas } from "../../components/GraphCanvas";
import { GraphCapNotice } from "../../components/GraphCapNotice";
import { StageGate } from "../../components/StageGate";
import { useCappedGraph, type CappableEdge, type CappableNode } from "../../hooks/useGraphCap";
import { SEVERITY_CLASSES, SEVERITY_LABEL, fileName } from "../../lib/format";
import { colorForSubsystem } from "../../lib/subsystemColors";
import { CHROME, SEVERITY_COLOR } from "../../lib/chartTheme";
import type { RepoOutletContext } from "../RepoLayout";

interface ArchEdge extends CappableEdge {
  inCycle: boolean;
}

const CYCLE_COLOR = SEVERITY_COLOR.high;
const SELECTED_COLOR = CHROME.signal;
const NORMAL_COLOR = CHROME.inkMuted;
const DIMMED_COLOR = CHROME.border;

/** Pure, so it's testable without rendering a canvas (Known Hazard #4 / Part
 * D: "extend the anti-drift test to cover this view"). Priority: an
 * explicit selection always wins (it's what the user is looking at); a
 * cycle is the next most important thing to see, so it keeps its own fixed
 * color even over a subsystem's; everything else colors by subsystem via
 * `lib/subsystemColors.ts::colorForSubsystem` -- the SAME function and the
 * SAME label the onboard map and the 3D city resolve a subsystem's color
 * from, so a subsystem reads as the same color in every view. */
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

export function ArchitecturePage() {
  const { repo, share } = useOutletContext<RepoOutletContext>();
  const arch = useArchitecture(repo.id, share);
  const subsystems = useSubsystems(repo.id, true, share);
  const [searchParams] = useSearchParams();
  const [selectedNode, setSelectedNode] = useState<string | null>(searchParams.get("file"));

  useEffect(() => {
    const target = searchParams.get("file");
    if (target) setSelectedNode(target);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams.get("file")]);

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
                      // react-force-graph mutates source/target from a path string
                      // into the resolved node object once the simulation starts,
                      // even though our own graph data typed them as strings.
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
                      setSelectedNode((current) => (current === id ? null : id));
                    }}
                    onBackgroundClick={() => setSelectedNode(null)}
                  />
                )}
              </GraphCanvas>
              <p className="mt-2 text-xs text-ink-faint">
                Node color follows subsystem — the same palette as the Onboard map and 3D city. Red
                marks a cycle; the selected node is highlighted in blue.
              </p>
            </Card>

            <div className="flex flex-col gap-4">
              {selectedNode ? (
                <Card
                  title="Selected file"
                  subtitle={selectedNode}
                  action={
                    <button
                      type="button"
                      onClick={() => setSelectedNode(null)}
                      className="text-xs text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
                    >
                      Clear
                    </button>
                  }
                >
                  {selectedEdges.length === 0 ? (
                    <p className="text-sm text-ink-faint">No import edges.</p>
                  ) : (
                    <ul className="space-y-1.5 text-sm">
                      {selectedEdges.map((e) => (
                        <li key={`${e.from_path}->${e.to_path}`} className="text-ink-muted">
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

              <Card title="Cycles" subtitle={`${data.cycles.length} found`}>
                {data.cycles.length === 0 ? (
                  <p className="text-sm text-ink-faint">No circular dependencies. 🎉</p>
                ) : (
                  <ul className="space-y-2 text-sm">
                    {data.cycles.map((c, i) => (
                      <li key={i}>
                        <span
                          className={`mr-1.5 inline-flex items-center rounded-full px-1.5 py-0.5 text-[10px] font-medium ring-1 ring-inset ${SEVERITY_CLASSES[c.severity]}`}
                        >
                          {SEVERITY_LABEL[c.severity]}
                        </span>
                        <span className="text-ink-muted">{c.files.map(fileName).join(" → ")}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </Card>

              <Card
                title="Layering violations"
                subtitle={`${data.layering_violations.length} found`}
              >
                {data.layering_violations.length === 0 ? (
                  <p className="text-sm text-ink-faint">No layering violations.</p>
                ) : (
                  <ul className="space-y-2 text-sm">
                    {data.layering_violations.map((v, i) => (
                      <li key={i}>
                        <span
                          className={`mr-1.5 inline-flex items-center rounded-full px-1.5 py-0.5 text-[10px] font-medium ring-1 ring-inset ${SEVERITY_CLASSES[v.severity]}`}
                        >
                          {SEVERITY_LABEL[v.severity]}
                        </span>
                        <span className="text-ink-muted">
                          {fileName(v.from_path)} → {fileName(v.to_path)}{" "}
                          <span className="text-ink-faint">({v.kind})</span>
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
              never FindingItem/SeverityChip): a plain informational list with
              its own caveat, since a file appearing here may just mean
              Compass doesn't parse how it's reached (Known Hazard #6). */}
          <Card
            title="Unreferenced files"
            subtitle={`${data.unreferenced_files.length} file${data.unreferenced_files.length === 1 ? "" : "s"} with no detected structural reference`}
          >
            <p className="mb-3 rounded-md bg-slate-50 px-3 py-2 text-xs text-ink-muted dark:bg-slate-800/60">
              {data.unreferenced_files_caveat}
            </p>
            {data.unreferenced_files.length === 0 ? (
              <p className="text-sm text-ink-faint">
                Every file has at least one detected structural reference.
              </p>
            ) : (
              <ul className="flex max-h-64 flex-col divide-y divide-slate-100 overflow-y-auto text-sm dark:divide-slate-800">
                {data.unreferenced_files.map((f) => (
                  <li key={f.file_path} className="flex items-center justify-between gap-2 py-1.5">
                    <span className="truncate font-mono text-xs text-ink-muted" title={f.file_path}>
                      {f.file_path}
                    </span>
                    <span className="shrink-0 text-xs text-ink-faint">
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
