import { describe, expect, it } from "vitest";
import { capGraphByDegree, type CappableEdge, type CappableNode } from "./useGraphCap";

// No test file existed for this hook before session 09 despite CLAUDE.md's
// "extend the session-08 tests" instruction assuming one did -- written
// here from scratch, covering the capping behaviour every graph page
// (Coupling, Architecture, and session 09's codebase-map subsystem graph)
// depends on.

function makeChain(n: number): { nodes: CappableNode[]; edges: CappableEdge[] } {
  const nodes: CappableNode[] = Array.from({ length: n }, (_, i) => ({ id: `n${i}` }));
  const edges: CappableEdge[] = [];
  for (let i = 0; i < n - 1; i++) {
    edges.push({ source: `n${i}`, target: `n${i + 1}`, weight: 1 });
  }
  return { nodes, edges };
}

describe("capGraphByDegree", () => {
  it("does not cap when under both limits -- returns every node and edge", () => {
    const { nodes, edges } = makeChain(10);
    const result = capGraphByDegree(nodes, edges, { maxNodes: 150, maxEdges: 400 });
    expect(result.nodes).toHaveLength(10);
    expect(result.edges).toHaveLength(9);
    expect(result.nodesCapped).toBe(false);
    expect(result.edgesCapped).toBe(false);
    expect(result.totalNodes).toBe(10);
    expect(result.totalEdges).toBe(9);
  });

  it("caps nodes to the top maxNodes by total incident edge weight", () => {
    // A star graph: the hub has the highest degree and must always survive
    // the cap; leaves with no edges at all must be the first dropped.
    const nodes: CappableNode[] = [
      { id: "hub" },
      { id: "leaf1" },
      { id: "leaf2" },
      { id: "isolated1" },
      { id: "isolated2" },
    ];
    const edges: CappableEdge[] = [
      { source: "hub", target: "leaf1", weight: 5 },
      { source: "hub", target: "leaf2", weight: 3 },
    ];
    const result = capGraphByDegree(nodes, edges, { maxNodes: 3, maxEdges: 400 });
    expect(result.nodesCapped).toBe(true);
    expect(result.nodes.map((n) => n.id).sort()).toEqual(["hub", "leaf1", "leaf2"]);
    expect(result.totalNodes).toBe(5);
  });

  it("drops edges whose endpoints were capped away, even without hitting maxEdges", () => {
    const nodes: CappableNode[] = [{ id: "a" }, { id: "b" }, { id: "c" }];
    const edges: CappableEdge[] = [
      { source: "a", target: "b", weight: 10 },
      { source: "b", target: "c", weight: 1 },
    ];
    // Cap to 2 nodes -- "a" (weight 10) and "b" (weight 11) survive, "c"
    // (weight 1) is dropped, which must also drop the b-c edge.
    const result = capGraphByDegree(nodes, edges, { maxNodes: 2, maxEdges: 400 });
    expect(result.nodes.map((n) => n.id).sort()).toEqual(["a", "b"]);
    expect(result.edges).toEqual([{ source: "a", target: "b", weight: 10 }]);
  });

  it("caps edges to the top maxEdges by weight once nodes survive the node cap", () => {
    const nodes: CappableNode[] = [{ id: "a" }, { id: "b" }, { id: "c" }, { id: "d" }];
    const edges: CappableEdge[] = [
      { source: "a", target: "b", weight: 1 },
      { source: "a", target: "c", weight: 5 },
      { source: "a", target: "d", weight: 3 },
    ];
    const result = capGraphByDegree(nodes, edges, { maxNodes: 150, maxEdges: 2 });
    expect(result.edgesCapped).toBe(true);
    expect(result.edges).toHaveLength(2);
    expect(result.edges.map((e) => e.weight).sort((a, b) => b - a)).toEqual([5, 3]);
  });

  it("uses the documented defaults (150 nodes / 400 edges) when no options are given", () => {
    const { nodes, edges } = makeChain(200);
    const result = capGraphByDegree(nodes, edges);
    expect(result.nodesCapped).toBe(true);
    expect(result.nodes).toHaveLength(150);
  });

  it("handles an empty graph without error", () => {
    const result = capGraphByDegree([], []);
    expect(result).toEqual({
      nodes: [],
      edges: [],
      totalNodes: 0,
      totalEdges: 0,
      nodesCapped: false,
      edgesCapped: false,
    });
  });
});
