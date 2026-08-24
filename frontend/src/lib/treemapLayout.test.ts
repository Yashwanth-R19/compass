import { describe, expect, it } from "vitest";
import { layoutTreemap, type TreemapNode } from "./treemapLayout";

function overlaps(
  a: { x: number; y: number; width: number; height: number },
  b: typeof a,
): boolean {
  const EPS = 1e-6;
  return (
    a.x + a.width > b.x + EPS &&
    b.x + b.width > a.x + EPS &&
    a.y + a.height > b.y + EPS &&
    b.y + b.height > a.y + EPS
  );
}

describe("layoutTreemap", () => {
  const nodes: TreemapNode[] = [
    { id: "a", value: 400 },
    { id: "b", value: 300 },
    { id: "c", value: 200 },
    { id: "d", value: 100 },
  ];

  it("is deterministic -- the same input produces a deep-equal output across 10 calls", () => {
    const first = layoutTreemap(nodes, 800, 600);
    for (let i = 0; i < 10; i++) {
      expect(layoutTreemap(nodes, 800, 600)).toEqual(first);
    }
  });

  it("is deterministic regardless of input order (sorts internally)", () => {
    const shuffled = [nodes[2], nodes[0], nodes[3], nodes[1]];
    const a = layoutTreemap(nodes, 800, 600);
    const b = layoutTreemap(shuffled, 800, 600);
    expect(b).toEqual(a);
  });

  it("lays out every node, none dropped", () => {
    const rects = layoutTreemap(nodes, 800, 600);
    expect(rects.map((r) => r.id).sort()).toEqual(["a", "b", "c", "d"]);
  });

  it("returns an empty array for no nodes or a zero-size container", () => {
    expect(layoutTreemap([], 800, 600)).toEqual([]);
    expect(layoutTreemap(nodes, 0, 600)).toEqual([]);
  });

  it("areas are proportional to value within tolerance (no minSize floor engaged)", () => {
    // A large container relative to minSize keeps the area floor from ever
    // engaging, so proportionality should hold closely (padding accounts
    // for the remaining small deviation).
    const rects = layoutTreemap(nodes, 1000, 1000, { padding: 1, minSize: 2 });
    const totalValue = nodes.reduce((s, n) => s + n.value, 0);
    const totalArea = rects.reduce((s, r) => s + r.width * r.height, 0);
    for (const n of nodes) {
      const rect = rects.find((r) => r.id === n.id)!;
      const expectedShare = n.value / totalValue;
      const actualShare = (rect.width * rect.height) / totalArea;
      expect(actualShare).toBeGreaterThan(expectedShare - 0.05);
      expect(actualShare).toBeLessThan(expectedShare + 0.05);
    }
  });

  it("no two rectangles overlap", () => {
    const dense: TreemapNode[] = Array.from({ length: 25 }, (_, i) => ({
      id: `n${i}`,
      value: Math.max(1, (i * 37) % 97),
    }));
    const rects = layoutTreemap(dense, 500, 400, { padding: 1, minSize: 4 });
    for (let i = 0; i < rects.length; i++) {
      for (let j = i + 1; j < rects.length; j++) {
        expect(overlaps(rects[i], rects[j])).toBe(false);
      }
    }
  });

  it("enforces a minimum side length for a tiny value among much larger ones, without overlapping", () => {
    // A realistic-magnitude skew (30:1 -- well within the range a real
    // repo's LOC distribution can produce), not an adversarial one -- the
    // area floor is a best-effort guarantee for real data, not a proof for
    // arbitrary ratios (see treemapLayout.ts's own comment on this).
    const skewed: TreemapNode[] = [
      { id: "huge", value: 3000 },
      { id: "tiny", value: 100 },
    ];
    const rects = layoutTreemap(skewed, 800, 600, { minSize: 10, padding: 1 });
    const tiny = rects.find((r) => r.id === "tiny")!;
    expect(tiny.width).toBeGreaterThanOrEqual(9); // small floating-point slack
    expect(tiny.height).toBeGreaterThanOrEqual(9);
    expect(overlaps(rects[0], rects[1])).toBe(false);
  });
});
