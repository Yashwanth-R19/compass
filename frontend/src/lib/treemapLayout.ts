import { hierarchy, treemap, treemapSquarify } from "d3-hierarchy";

export interface TreemapNode {
  id: string;
  value: number;
}

export interface LaidOutRect {
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
  value: number;
}

export interface TreemapOptions {
  /** Gap between adjacent rectangles, in the same units as width/height. */
  padding?: number;
  /** Minimum side length a rectangle is guaranteed to have -- see the
   * area-floor comment below for how this is enforced without breaking the
   * no-overlap guarantee. */
  minSize?: number;
}

const DEFAULT_PADDING = 1;
const DEFAULT_MIN_SIZE = 3;

interface TreemapLeafDatum extends TreemapNode {
  effectiveValue: number;
}

interface TreemapRootDatum {
  children: TreemapLeafDatum[];
}

/**
 * Squarified treemap (session 09, Part B) -- a thin, deterministic wrapper
 * around d3-hierarchy's own `treemapSquarify` tiling, which is what keeps
 * rectangles close to square instead of the long, unreadable corridors a
 * naive slice-and-dice layout produces (CLAUDE.md: "what makes both the map
 * treemap and the city legible").
 *
 * FLAT, one level per call, by design: a caller that needs a multi-level
 * hierarchy (the directory treemap's drill-down, the city's
 * district-then-building nesting) calls this once per level rather than
 * handing it a nested tree -- see `cityLayout.ts`, which lays out districts
 * with one call and then each district's buildings with a second per
 * district, and `MapPage`'s directory treemap, which re-calls this with the
 * newly-selected directory's immediate children on every drill-in. This
 * keeps the function itself simple, and it's exactly what "reused by the
 * city" (Part F) means in practice.
 *
 * Pure: no React, no DOM -- safe to unit test in isolation and safe to move
 * behind a Web Worker later if city rendering ever needs one.
 */
export function layoutTreemap(
  nodes: TreemapNode[],
  width: number,
  height: number,
  opts: TreemapOptions = {},
): LaidOutRect[] {
  if (nodes.length === 0 || width <= 0 || height <= 0) return [];

  const padding = opts.padding ?? DEFAULT_PADDING;
  const minSize = opts.minSize ?? DEFAULT_MIN_SIZE;

  // d3's squarified tiling is order-sensitive: the SAME set of nodes fed in
  // a different order produces a different (still valid, but visually
  // different) arrangement -- the map/city would rearrange itself on every
  // reload if the caller's own data ordering weren't guaranteed (it usually
  // isn't -- an API response, a Map, or an object all have no ordering
  // contract). Sorted explicitly HERE, not at the call site, per the Known
  // Hazard's own instruction ("sort explicitly inside layoutTreemap, not at
  // the call site"). Value desc, id asc tiebreak -- the same
  // (rank-metric-desc, identifier-asc) convention every other capped/ranked
  // list in this codebase uses for determinism.
  const sorted = [...nodes].sort((a, b) => b.value - a.value || a.id.localeCompare(b.id));

  // A minimum-AREA floor applied to the VALUE fed into d3, not a post-layout
  // clamp on the resulting rectangle: if a tiny node's true value were fed
  // straight to d3, its rectangle could legally come back as a sliver too
  // small to click (Part B: "a 5-line file is still clickable"). Clamping
  // its width/height AFTER layout instead would grow it into a neighbour's
  // already-computed space and break the no-overlap guarantee (Part G:
  // "no two buildings overlap"). Flooring the value before layout avoids
  // that entirely -- d3's own squarified tiling never overlaps by
  // construction for any set of positive inputs, so a floored value simply
  // gets a bigger (but still non-overlapping) share of the container.
  //
  // Best-effort, not a hard geometric guarantee: this floors AREA
  // (minSize*minSize), and squarify is free to allocate that area as one
  // long axis spanning the whole container and a short axis far under
  // minSize -- provably possible only when one value is many orders of
  // magnitude larger than everything else, well beyond any realistic
  // same-repo LOC spread once IGNORE_DIRS-filtered vendor/build output is
  // already excluded upstream (app/ingestion/miner.py). Treated as
  // sufficient for real data, not proven for arbitrary adversarial input.
  const totalValue = sorted.reduce((sum, n) => sum + Math.max(n.value, 0), 0);
  const area = Math.max(width * height, 1);
  const minValue = totalValue > 0 ? (minSize * minSize * totalValue) / area : 1;
  const withFloors: TreemapLeafDatum[] = sorted.map((n) => ({
    ...n,
    effectiveValue: Math.max(n.value, minValue, 1e-9),
  }));

  const root: TreemapRootDatum = { children: withFloors };
  const h = hierarchy<TreemapRootDatum | TreemapLeafDatum>(root, (d) =>
    "children" in d ? d.children : undefined,
  ).sum((d) => ("effectiveValue" in d ? d.effectiveValue : 0));

  const laidOut = treemap<TreemapRootDatum | TreemapLeafDatum>()
    .tile(treemapSquarify)
    .size([width, height])
    .paddingInner(padding)(h);

  return laidOut.leaves().map((leaf) => {
    const data = leaf.data as TreemapLeafDatum;
    return {
      id: data.id,
      x: leaf.x0 ?? 0,
      y: leaf.y0 ?? 0,
      width: Math.max((leaf.x1 ?? 0) - (leaf.x0 ?? 0), 0),
      height: Math.max((leaf.y1 ?? 0) - (leaf.y0 ?? 0), 0),
      value: data.value,
    };
  });
}
