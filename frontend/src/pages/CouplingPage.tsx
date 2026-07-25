import { useMemo, useState } from "react";
import { useOutletContext } from "react-router-dom";
import ForceGraph2D from "react-force-graph-2d";
import { useCoupling, useHiddenDeps } from "../api/hooks";
import { Card } from "../components/Card";
import { GraphCanvas } from "../components/GraphCanvas";
import { GraphCapNotice } from "../components/GraphCapNotice";
import { LoadingState } from "../components/LoadingState";
import { ErrorState } from "../components/ErrorState";
import { EmptyState } from "../components/EmptyState";
import { useCappedGraph, type CappableEdge, type CappableNode } from "../hooks/useGraphCap";
import { fileName, formatPercent } from "../lib/format";
import type { RepoOutletContext } from "./RepoLayout";

interface CouplingEdge extends CappableEdge {
  isHidden: boolean;
  sharedRevs: number;
}

const HIDDEN_COLOR = "#f97316"; // amber-500
const NORMAL_COLOR = "#6366f1"; // indigo-500

export function CouplingPage() {
  const { repo } = useOutletContext<RepoOutletContext>();
  const coupling = useCoupling(repo.id);
  const hiddenDeps = useHiddenDeps(repo.id);
  const [highlightHidden, setHighlightHidden] = useState(true);

  const hiddenPairKeys = useMemo(() => {
    if (!hiddenDeps.data) return new Set<string>();
    return new Set(hiddenDeps.data.pairs.map((p) => [p.file_a_path, p.file_b_path].sort().join("|")));
  }, [hiddenDeps.data]);

  const { nodes, edges } = useMemo(() => {
    if (!coupling.data) return { nodes: [] as CappableNode[], edges: [] as CouplingEdge[] };
    const nodeIds = new Set<string>();
    const builtEdges: CouplingEdge[] = coupling.data.pairs.map((p) => {
      nodeIds.add(p.file_a_path);
      nodeIds.add(p.file_b_path);
      return {
        source: p.file_a_path,
        target: p.file_b_path,
        weight: p.coupling_degree,
        sharedRevs: p.shared_revs,
        isHidden: hiddenPairKeys.has([p.file_a_path, p.file_b_path].sort().join("|")),
      };
    });
    return { nodes: [...nodeIds].map((id) => ({ id })), edges: builtEdges };
  }, [coupling.data, hiddenPairKeys]);

  const capped = useCappedGraph(nodes, edges);

  if (coupling.isPending) return <LoadingState label="Loading coupling data…" />;
  if (coupling.isError) return <ErrorState error={coupling.error} onRetry={() => void coupling.refetch()} />;
  if (coupling.data.pairs.length === 0) {
    return (
      <EmptyState
        title="No coupling pairs found"
        message="Either this repo doesn't have enough shared-revision history yet, or no two files consistently change together."
      />
    );
  }

  return (
    <div className="flex flex-col gap-4">
      {coupling.data.low_confidence ? (
        <p className="rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-700 dark:bg-amber-500/10 dark:text-amber-400">
          Low confidence: this repo doesn't have much analyzed history yet, so the small-repo fallback threshold
          was used. Treat these pairs as directional signal, not certainty.
        </p>
      ) : null}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_320px]">
        <Card>
          <div className="mb-2 flex items-center justify-between gap-3">
            <GraphCapNotice
              nodesCapped={capped.nodesCapped}
              edgesCapped={capped.edgesCapped}
              shownNodes={capped.nodes.length}
              totalNodes={capped.totalNodes}
            />
            <label className="flex shrink-0 items-center gap-2 text-xs text-slate-600 dark:text-slate-300">
              <input
                type="checkbox"
                checked={highlightHidden}
                onChange={(e) => setHighlightHidden(e.target.checked)}
                className="rounded border-slate-300 text-indigo-600 focus:ring-indigo-500 dark:border-slate-600"
              />
              Highlight hidden dependencies
            </label>
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
                nodeColor={() => "#475569"}
                linkColor={(l) => (highlightHidden && (l as unknown as CouplingEdge).isHidden ? HIDDEN_COLOR : NORMAL_COLOR)}
                linkWidth={(l) => 0.5 + (l as unknown as CouplingEdge).weight * 4}
                linkLabel={(l) => {
                  const link = l as unknown as CouplingEdge;
                  return `${formatPercent(link.weight)} coupled, ${link.sharedRevs} shared commits`;
                }}
              />
            )}
          </GraphCanvas>
        </Card>

        <Card title="Ranked pairs" subtitle={`${coupling.data.pairs.length} total`}>
          <ul className="max-h-[480px] divide-y divide-slate-100 overflow-y-auto text-sm dark:divide-slate-800">
            {coupling.data.pairs.map((p) => {
              const isHidden = hiddenPairKeys.has([p.file_a_path, p.file_b_path].sort().join("|"));
              return (
                <li key={`${p.file_a_path}|${p.file_b_path}`} className="py-2">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium text-slate-700 dark:text-slate-200">
                      {fileName(p.file_a_path)} ↔ {fileName(p.file_b_path)}
                    </span>
                    {isHidden ? (
                      <span className="shrink-0 rounded-full bg-amber-100 px-1.5 py-0.5 text-[10px] font-medium text-amber-700 dark:bg-amber-500/10 dark:text-amber-400">
                        hidden
                      </span>
                    ) : null}
                  </div>
                  <p className="text-xs text-slate-400 dark:text-slate-500">
                    {formatPercent(p.coupling_degree)} coupled · {p.shared_revs} shared commits · {p.confidence}{" "}
                    confidence
                  </p>
                </li>
              );
            })}
          </ul>
        </Card>
      </div>
    </div>
  );
}
