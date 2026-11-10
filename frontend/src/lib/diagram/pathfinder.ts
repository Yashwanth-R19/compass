import type { VisibleEdge } from "./visible";

export interface PathResult {
  nodes: string[];
  edges: string[];
  direction: "forward" | "reverse";
}

function bfs(edges: VisibleEdge[], from: string, to: string): Omit<PathResult, "direction"> | null {
  if (from === to) return null;
  const adjacency = new Map<string, { next: string; edgeId: string }[]>();
  for (const e of edges) {
    if (e.kind !== "import") continue;
    const list = adjacency.get(e.source) ?? [];
    list.push({ next: e.target, edgeId: e.id });
    adjacency.set(e.source, list);
  }
  for (const list of adjacency.values()) {
    list.sort((a, b) => (a.next < b.next ? -1 : a.next > b.next ? 1 : 0));
  }

  const previous = new Map<string, { node: string; edgeId: string }>();
  const queue: string[] = [from];
  const seen = new Set([from]);
  while (queue.length > 0) {
    const current = queue.shift() as string;
    if (current === to) break;
    for (const { next, edgeId } of adjacency.get(current) ?? []) {
      if (seen.has(next)) continue;
      seen.add(next);
      previous.set(next, { node: current, edgeId });
      queue.push(next);
    }
  }
  if (!seen.has(to)) return null;

  const nodes = [to];
  const edgeIds: string[] = [];
  let cursor = to;
  while (cursor !== from) {
    const step = previous.get(cursor);
    if (!step) return null;
    edgeIds.push(step.edgeId);
    nodes.push(step.node);
    cursor = step.node;
  }
  return { nodes: nodes.reverse(), edges: edgeIds.reverse() };
}

/** Shortest import path over the edges currently on screen (directed: A
 * imports ... imports B). Neighbours are visited in id order, so the same
 * graph always yields the same path. Tries the reverse direction before
 * giving up. */
export function findPath(edges: VisibleEdge[], from: string, to: string): PathResult | null {
  const forward = bfs(edges, from, to);
  if (forward) return { ...forward, direction: "forward" };
  const reverse = bfs(edges, to, from);
  if (reverse) return { ...reverse, direction: "reverse" };
  return null;
}
