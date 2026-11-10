import ELK from "elkjs/lib/elk.bundled.js";
import type { ElkExtendedEdge, ElkNode } from "elkjs/lib/elk-api";
import type { VisibleEdge, VisibleGraph, VisibleNode, VisibleNodeKind } from "./visible";

/** Fixed box sizes per node kind. A node's box NEVER changes size with zoom
 * (semantic zoom swaps its content, not its footprint), so a zoom change
 * never forces a relayout. Expanded group/folder boxes are sized by ELK. */
export const NODE_SIZE: Record<VisibleNodeKind, { width: number; height: number }> = {
  group: { width: 248, height: 120 },
  folder: { width: 208, height: 72 },
  file: { width: 208, height: 56 },
  more: { width: 132, height: 40 },
  actor: { width: 168, height: 56 },
  infra: { width: 196, height: 72 },
};

/** Room at the top of an expanded box for its header row. */
export const EXPANDED_HEADER = 56;

export interface LaidOutNode {
  id: string;
  parentId: string | null;
  /** Relative to the parent (absolute for top-level nodes). */
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface BandRect {
  index: number;
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface DiagramLayout {
  nodes: Map<string, LaidOutNode>;
  bands: BandRect[];
}

/** Top-level boxes per row inside one band before it wraps onto a new row. */
const MAX_PER_ROW = 5;
const GAP_X = 48;
const GAP_ROW = 40;
const GAP_BAND = 88;
const BAND_PAD_X = 40;
const BAND_PAD_TOP = 36;
const BAND_PAD_BOTTOM = 24;

const elk = new ELK();

/** ELK lays out only the INSIDE of an expanded box (its folders/files and
 * the edges between them); the bands themselves are laid out as plain rows
 * below, which keeps every band genuinely flat and its order predictable. */
const CONTAINER_OPTIONS: Record<string, string> = {
  "elk.algorithm": "layered",
  "elk.direction": "DOWN",
  "elk.hierarchyHandling": "INCLUDE_CHILDREN",
  "elk.padding": `[top=${EXPANDED_HEADER},left=16,bottom=16,right=16]`,
  "elk.spacing.nodeNode": "24",
  "elk.layered.spacing.nodeNodeBetweenLayers": "40",
  "elk.layered.nodePlacement.strategy": "BRANDES_KOEPF",
  "elk.randomSeed": "1",
};

function compareIds(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0;
}

function topAncestor(graph: VisibleGraph, id: string): string | null {
  let node = graph.byId.get(id);
  while (node?.parentId) node = graph.byId.get(node.parentId);
  return node?.id ?? null;
}

async function layoutContainer(
  graph: VisibleGraph,
  top: VisibleNode,
  childrenOf: Map<string, string[]>,
  edges: VisibleEdge[],
  out: Map<string, LaidOutNode>,
): Promise<{ width: number; height: number }> {
  const toElk = (id: string): ElkNode => {
    const node = graph.byId.get(id) as VisibleNode;
    const kids = [...(childrenOf.get(id) ?? [])].sort(compareIds);
    if (node.expanded && kids.length > 0) {
      return {
        id,
        layoutOptions: { "elk.padding": CONTAINER_OPTIONS["elk.padding"] },
        children: kids.map(toElk),
      };
    }
    return { id, width: NODE_SIZE[node.kind].width, height: NODE_SIZE[node.kind].height };
  };

  const inside = edges
    .filter(
      (e) => topAncestor(graph, e.source) === top.id && topAncestor(graph, e.target) === top.id,
    )
    .filter((e) => e.source !== top.id && e.target !== top.id)
    .sort((a, b) => compareIds(a.id, b.id))
    .map<ElkExtendedEdge>((e) => ({ id: e.id, sources: [e.source], targets: [e.target] }));

  const kids = [...(childrenOf.get(top.id) ?? [])].sort(compareIds);
  // INCLUDE_CHILDREN is only needed when a nested folder is itself expanded
  // (edges then cross hierarchy levels). Without it, ELK packs unconnected
  // children into rows by aspect ratio instead of one very long row.
  const nested = kids.some((id) => graph.byId.get(id)?.expanded);
  const options: Record<string, string> = {
    ...CONTAINER_OPTIONS,
    "elk.aspectRatio": "1.6",
  };
  if (!nested) delete options["elk.hierarchyHandling"];
  const root: ElkNode = {
    id: top.id,
    layoutOptions: options,
    children: kids.map(toElk),
    edges: inside,
  };
  const result = await elk.layout(root);

  const collect = (node: ElkNode, parentId: string) => {
    for (const child of node.children ?? []) {
      out.set(child.id, {
        id: child.id,
        parentId,
        x: child.x ?? 0,
        y: child.y ?? 0,
        width: child.width ?? 0,
        height: child.height ?? 0,
      });
      collect(child, child.id);
    }
  };
  collect(result, top.id);
  return { width: result.width ?? NODE_SIZE[top.kind].width, height: result.height ?? 0 };
}

/** Orders each band's boxes to reduce crossings: every box is placed at the
 * average position of the boxes it connects to in the bands ABOVE it
 * (a single downward barycenter sweep). Boxes with no such neighbour keep
 * their original order (largest first, as the backend sorts them) after
 * the connected ones. Deterministic: ties fall back to the original order. */
function orderBands(
  bands: Map<number, VisibleNode[]>,
  neighbours: Map<string, Set<string>>,
): Map<number, VisibleNode[]> {
  const ordered = new Map<number, VisibleNode[]>();
  const position = new Map<string, number>();
  for (const band of [...bands.keys()].sort((a, b) => a - b)) {
    const nodes = bands.get(band) ?? [];
    const keyed = nodes.map((n, original) => {
      const above = [...(neighbours.get(n.id) ?? [])].filter((id) => position.has(id));
      const bary =
        above.length > 0
          ? above.reduce((sum, id) => sum + (position.get(id) ?? 0), 0) / above.length
          : Number.POSITIVE_INFINITY;
      return { n, bary, original };
    });
    keyed.sort((a, b) => a.bary - b.bary || a.original - b.original);
    const result = keyed.map((k) => k.n);
    result.forEach((n, i) => position.set(n.id, i / Math.max(1, result.length - 1)));
    ordered.set(band, result);
  }
  return ordered;
}

/** Lays out the visible graph: bands as flat, horizontally centred rows
 * (wrapping after MAX_PER_ROW boxes), expanded boxes sized by ELK. Every
 * input is sorted first, so the same graph always lands in the same place. */
export async function layoutDiagram(
  graph: VisibleGraph,
  edges: VisibleEdge[],
): Promise<DiagramLayout> {
  const nodes = new Map<string, LaidOutNode>();
  const childrenOf = new Map<string, string[]>();
  const topLevel: VisibleNode[] = [];
  for (const node of graph.nodes) {
    if (node.parentId === null) topLevel.push(node);
    else {
      const list = childrenOf.get(node.parentId) ?? [];
      list.push(node.id);
      childrenOf.set(node.parentId, list);
    }
  }

  // 1. Size every top-level box (ELK only for expanded ones).
  const size = new Map<string, { width: number; height: number }>();
  for (const top of topLevel) {
    if (top.expanded && (childrenOf.get(top.id)?.length ?? 0) > 0) {
      size.set(top.id, await layoutContainer(graph, top, childrenOf, edges, nodes));
    } else {
      size.set(top.id, NODE_SIZE[top.kind]);
    }
  }

  // 2. Which top-level boxes touch which (for ordering within bands).
  const neighbours = new Map<string, Set<string>>();
  for (const e of edges) {
    const a = topAncestor(graph, e.source);
    const b = topAncestor(graph, e.target);
    if (!a || !b || a === b) continue;
    if (!neighbours.has(a)) neighbours.set(a, new Set());
    if (!neighbours.has(b)) neighbours.set(b, new Set());
    neighbours.get(a)?.add(b);
    neighbours.get(b)?.add(a);
  }

  const byBand = new Map<number, VisibleNode[]>();
  for (const top of topLevel) {
    const band = top.band ?? 0;
    const list = byBand.get(band) ?? [];
    list.push(top);
    byBand.set(band, list);
  }
  const ordered = orderBands(byBand, neighbours);

  // 3. Rows: chunk each band, measure, then centre every row on the widest.
  interface Row {
    band: number;
    items: VisibleNode[];
    width: number;
    height: number;
  }
  const rows: Row[] = [];
  for (const band of [...ordered.keys()].sort((a, b) => a - b)) {
    const items = ordered.get(band) ?? [];
    for (let start = 0; start < items.length; start += MAX_PER_ROW) {
      const chunk = items.slice(start, start + MAX_PER_ROW);
      const width =
        chunk.reduce((sum, n) => sum + (size.get(n.id)?.width ?? 0), 0) +
        GAP_X * Math.max(0, chunk.length - 1);
      const height = Math.max(...chunk.map((n) => size.get(n.id)?.height ?? 0));
      rows.push({ band, items: chunk, width, height });
    }
  }
  const maxWidth = Math.max(0, ...rows.map((r) => r.width));

  const bandExtent = new Map<number, { top: number; bottom: number }>();
  let y = 0;
  let previousBand: number | null = null;
  for (const row of rows) {
    if (previousBand !== null) y += row.band === previousBand ? GAP_ROW : GAP_BAND;
    if (row.band !== previousBand) y += BAND_PAD_TOP;
    let x = (maxWidth - row.width) / 2;
    for (const n of row.items) {
      const s = size.get(n.id) ?? NODE_SIZE[n.kind];
      // Shorter boxes sit vertically centred in their row.
      nodes.set(n.id, {
        id: n.id,
        parentId: null,
        x,
        y: y + (row.height - s.height) / 2,
        width: s.width,
        height: s.height,
      });
      x += s.width + GAP_X;
    }
    const extent = bandExtent.get(row.band) ?? { top: y - BAND_PAD_TOP, bottom: 0 };
    extent.bottom = y + row.height + BAND_PAD_BOTTOM;
    bandExtent.set(row.band, extent);
    y += row.height;
    previousBand = row.band;
  }

  const bands: BandRect[] = [...bandExtent.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([index, ext]) => ({
      index,
      x: -BAND_PAD_X,
      y: ext.top,
      width: maxWidth + 2 * BAND_PAD_X,
      height: ext.bottom - ext.top,
    }));

  return { nodes, bands };
}
