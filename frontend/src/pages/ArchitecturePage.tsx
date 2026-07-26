import { useMemo, useState } from "react";
import { useOutletContext } from "react-router-dom";
import ForceGraph2D from "react-force-graph-2d";
import { useArchitecture } from "../api/hooks";
import { Card } from "../components/Card";
import { GraphCanvas } from "../components/GraphCanvas";
import { GraphCapNotice } from "../components/GraphCapNotice";
import { LoadingState } from "../components/LoadingState";
import { ErrorState } from "../components/ErrorState";
import { EmptyState } from "../components/EmptyState";
import { useCappedGraph, type CappableEdge, type CappableNode } from "../hooks/useGraphCap";
import { SEVERITY_CLASSES, SEVERITY_LABEL, fileName } from "../lib/format";
import type { RepoOutletContext } from "./RepoLayout";

interface ArchEdge extends CappableEdge {
  inCycle: boolean;
}

const CYCLE_COLOR = "#ef4444"; // red-500
const NORMAL_COLOR = "#6366f1"; // indigo-500
const DIMMED_COLOR = "rgba(148, 163, 184, 0.25)"; // slate-400 @ low opacity

export function ArchitecturePage() {
  const { repo } = useOutletContext<RepoOutletContext>();
  const arch = useArchitecture(repo.id);
  const [selectedNode, setSelectedNode] = useState<string | null>(null);

  const { cycleNodeIds, cycleEdgeKeys } = useMemo(() => {
    const nodeIds = new Set<string>();
    const edgeKeys = new Set<string>();
    for (const cycle of arch.data?.cycles ?? []) {
      for (let i = 0; i < cycle.files.length; i++) {
        const a = cycle.files[i];
        const b = cycle.files[(i + 1) % cycle.files.length];
        nodeIds.add(a);
        edgeKeys.add(`${a}->${b}`);
      }
    }
    return { cycleNodeIds: nodeIds, cycleEdgeKeys: edgeKeys };
  }, [arch.data]);

  const { nodes, edges } = useMemo(() => {
    if (!arch.data) return { nodes: [] as CappableNode[], edges: [] as ArchEdge[] };
    const builtEdges: ArchEdge[] = arch.data.edges.map((e) => ({
      source: e.from_path,
      target: e.to_path,
      weight: 1,
      inCycle: cycleEdgeKeys.has(`${e.from_path}->${e.to_path}`),
    }));
    return { nodes: arch.data.nodes.map((id) => ({ id })), edges: builtEdges };
  }, [arch.data, cycleEdgeKeys]);

  const capped = useCappedGraph(nodes, edges);

  const selectedEdges = useMemo(() => {
    if (!selectedNode || !arch.data) return [];
    return arch.data.edges.filter(
      (e) => e.from_path === selectedNode || e.to_path === selectedNode,
    );
  }, [selectedNode, arch.data]);

  if (arch.isPending) return <LoadingState label="Loading architecture graph…" />;
  if (arch.isError) return <ErrorState error={arch.error} onRetry={() => void arch.refetch()} />;
  if (arch.data.nodes.length === 0) {
    return (
      <EmptyState
        title="No structural graph yet"
        message="No import edges were found for this repo's supported languages."
      />
    );
  }

  return (
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
                if (selectedNode && id === selectedNode) return "#0ea5e9";
                return cycleNodeIds.has(id) ? CYCLE_COLOR : "#475569";
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
              <p className="text-sm text-slate-400 dark:text-slate-500">No import edges.</p>
            ) : (
              <ul className="space-y-1.5 text-sm">
                {selectedEdges.map((e) => (
                  <li
                    key={`${e.from_path}->${e.to_path}`}
                    className="text-slate-600 dark:text-slate-300"
                  >
                    {e.from_path === selectedNode ? (
                      <>
                        imports <span className="font-medium">{fileName(e.to_path)}</span>
                      </>
                    ) : (
                      <>
                        imported by <span className="font-medium">{fileName(e.from_path)}</span>
                      </>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </Card>
        ) : null}

        <Card title="Cycles" subtitle={`${arch.data.cycles.length} found`}>
          {arch.data.cycles.length === 0 ? (
            <p className="text-sm text-slate-400 dark:text-slate-500">
              No circular dependencies. 🎉
            </p>
          ) : (
            <ul className="space-y-2 text-sm">
              {arch.data.cycles.map((c, i) => (
                <li key={i}>
                  <span
                    className={`mr-1.5 inline-flex items-center rounded-full px-1.5 py-0.5 text-[10px] font-medium ring-1 ring-inset ${SEVERITY_CLASSES[c.severity]}`}
                  >
                    {SEVERITY_LABEL[c.severity]}
                  </span>
                  <span className="text-slate-600 dark:text-slate-300">
                    {c.files.map(fileName).join(" → ")}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card
          title="Layering violations"
          subtitle={`${arch.data.layering_violations.length} found`}
        >
          {arch.data.layering_violations.length === 0 ? (
            <p className="text-sm text-slate-400 dark:text-slate-500">No layering violations.</p>
          ) : (
            <ul className="space-y-2 text-sm">
              {arch.data.layering_violations.map((v, i) => (
                <li key={i}>
                  <span
                    className={`mr-1.5 inline-flex items-center rounded-full px-1.5 py-0.5 text-[10px] font-medium ring-1 ring-inset ${SEVERITY_CLASSES[v.severity]}`}
                  >
                    {SEVERITY_LABEL[v.severity]}
                  </span>
                  <span className="text-slate-600 dark:text-slate-300">
                    {fileName(v.from_path)} → {fileName(v.to_path)}{" "}
                    <span className="text-slate-400 dark:text-slate-500">({v.kind})</span>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  );
}
