import { useMemo } from "react";

export interface CappableNode {
  id: string;
}

export interface CappableEdge {
  source: string;
  target: string;
  weight: number;
}

export interface CappedGraph<N extends CappableNode, E extends CappableEdge> {
  nodes: N[];
  edges: E[];
  totalNodes: number;
  totalEdges: number;
  nodesCapped: boolean;
  edgesCapped: boolean;
}

const DEFAULT_MAX_NODES = 150;
const DEFAULT_MAX_EDGES = 400;
/** Large public repos can produce thousands of coupling/import edges even
 * after the node cap -- a dense-but-small node set can still have a huge
 * edge count -- so edges get their own independent cap, by weight, same as
 * nodes are capped by degree. Both caps are required, not optional (Release
 * A6 frontend spec): rendering everything freezes the browser tab. */

/** Sum of incident edge weights per node id -- used to rank which nodes
 * "matter most" when a graph is too big to render in full. */
function degreeByNode(edges: CappableEdge[]): Map<string, number> {
  const degree = new Map<string, number>();
  for (const edge of edges) {
    degree.set(edge.source, (degree.get(edge.source) ?? 0) + edge.weight);
    degree.set(edge.target, (degree.get(edge.target) ?? 0) + edge.weight);
  }
  return degree;
}

/** Client-side sort+slice that keeps a force-graph view responsive on large
 * repos: nodes are capped to the top `maxNodes` by total incident edge
 * weight (coupling_degree, or 1 per structural edge), then edges are capped
 * to those surviving nodes and, if still too many, to the top `maxEdges` by
 * weight. Shared by the Coupling and Architecture graph views so the exact
 * same cap logic and "showing top N of M" note applies to both.
 */
export function capGraphByDegree<N extends CappableNode, E extends CappableEdge>(
  nodes: N[],
  edges: E[],
  options: { maxNodes?: number; maxEdges?: number } = {},
): CappedGraph<N, E> {
  const maxNodes = options.maxNodes ?? DEFAULT_MAX_NODES;
  const maxEdges = options.maxEdges ?? DEFAULT_MAX_EDGES;

  const totalNodes = nodes.length;
  const totalEdges = edges.length;
  const nodesCapped = totalNodes > maxNodes;

  let keptNodes = nodes;
  if (nodesCapped) {
    const degree = degreeByNode(edges);
    keptNodes = [...nodes]
      .sort((a, b) => (degree.get(b.id) ?? 0) - (degree.get(a.id) ?? 0))
      .slice(0, maxNodes);
  }

  const keepIds = new Set(keptNodes.map((n) => n.id));
  let keptEdges = edges.filter((e) => keepIds.has(e.source) && keepIds.has(e.target));

  const edgesCapped = keptEdges.length > maxEdges;
  if (edgesCapped) {
    keptEdges = [...keptEdges].sort((a, b) => b.weight - a.weight).slice(0, maxEdges);
  }

  return { nodes: keptNodes, edges: keptEdges, totalNodes, totalEdges, nodesCapped, edgesCapped };
}

export function useCappedGraph<N extends CappableNode, E extends CappableEdge>(
  nodes: N[],
  edges: E[],
  options: { maxNodes?: number; maxEdges?: number } = {},
): CappedGraph<N, E> {
  return useMemo(
    () => capGraphByDegree(nodes, edges, options),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [nodes, edges, options.maxNodes, options.maxEdges],
  );
}
