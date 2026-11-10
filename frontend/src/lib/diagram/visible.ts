import type { DiagramResponse } from "../../api/types";
import { ACTOR_NODE_ID, fileNodeId, groupNodeId, moreNodeId } from "./ids";
import { hasChildren, orderedChildren, type TreeChild, type TreeFolder } from "./tree";

/** "component" = one of a COLLAPSED group's key files, drawn inside the group
 * container (GitDiagram-style); "file" = a file inside an EXPANDED group. */
export type VisibleNodeKind =
  "group" | "folder" | "file" | "component" | "more" | "actor" | "infra";

export interface VisibleNode {
  id: string;
  kind: VisibleNodeKind;
  parentId: string | null;
  /** Owning group (null for actor/infra). */
  groupId: string | null;
  label: string;
  /** Every file this node stands for, recursively. */
  fileIndices: number[];
  /** For a folder node: its relPath inside the group. */
  relPath?: string;
  /** For a file node: its file index. */
  fileIndex?: number;
  /** For a "more" chip: the children it hides. */
  hiddenChildren?: TreeChild[];
  expandable: boolean;
  expanded: boolean;
  depth: number;
  /** Band index -- top-level nodes only. */
  band: number | null;
}

export type VisibleEdgeKind = "import" | "hidden" | "actor" | "runs";

export interface VisibleEdge {
  id: string;
  kind: VisibleEdgeKind;
  source: string;
  target: string;
  /** Import pairs / hidden pairs / entry points behind this edge. */
  count: number;
  maxDegree?: number;
  sharedRevs?: number;
  inCycle: boolean;
  /** Up to MAX_FILE_PAIRS underlying file pairs, for the evidence panel. */
  filePairs: [number, number][];
}

export interface VisibleGraph {
  nodes: VisibleNode[];
  byId: Map<string, VisibleNode>;
  /** file index -> id of the deepest visible node standing for it. */
  ownerOf: string[];
}

const MAX_FILE_PAIRS = 20;
/** HEURISTIC: how many key files a collapsed group shows as components. */
export const COMPONENTS_PER_GROUP = 4;
/** HEURISTIC: past this many import edges on screen, single-import edges
 * are hidden by default ("Weak links" toggle brings them back). */
export const WEAK_EDGE_THRESHOLD = 60;

export function computeVisible(
  data: DiagramResponse,
  trees: Map<string, TreeFolder>,
  expanded: ReadonlySet<string>,
  options: { showActor: boolean },
): VisibleGraph {
  const nodes: VisibleNode[] = [];
  const cap = data.caps.max_children_visible;

  function addChildren(folder: TreeFolder, parentId: string, groupId: string, depth: number) {
    const children = orderedChildren(folder, data);
    const shown = children.slice(0, cap);
    const hidden = children.slice(cap);
    for (const child of shown) {
      if (child.kind === "folder") {
        const f = child.folder;
        const expandable = hasChildren(f);
        const isExpanded = expandable && expanded.has(f.id);
        nodes.push({
          id: f.id,
          kind: "folder",
          parentId,
          groupId,
          label: f.name,
          fileIndices: f.allFiles,
          relPath: f.relPath,
          expandable,
          expanded: isExpanded,
          depth,
          band: null,
        });
        if (isExpanded) addChildren(f, f.id, groupId, depth + 1);
      } else {
        const file = data.files[child.index];
        nodes.push({
          id: fileNodeId(file.path),
          kind: "file",
          parentId,
          groupId,
          label: file.path.split("/").pop() ?? file.path,
          fileIndices: [child.index],
          fileIndex: child.index,
          expandable: false,
          expanded: false,
          depth,
          band: null,
        });
      }
    }
    if (hidden.length > 0) {
      const indices: number[] = [];
      for (const h of hidden) {
        if (h.kind === "folder") indices.push(...h.folder.allFiles);
        else indices.push(h.index);
      }
      nodes.push({
        id: moreNodeId(parentId),
        kind: "more",
        parentId,
        groupId,
        label: `+${hidden.length} more`,
        fileIndices: indices.sort((a, b) => a - b),
        hiddenChildren: hidden,
        expandable: false,
        expanded: false,
        depth,
        band: null,
      });
    }
  }

  // A collapsed group's key files: the ones the most import edges touch
  // (so the arrows have real anchors), then centrality / size, then path.
  // Drawn top-to-bottom importer-before-imported, like a flow.
  const degree = new Map<number, number>();
  for (const [f, t] of data.imports) {
    degree.set(f, (degree.get(f) ?? 0) + 1);
    degree.set(t, (degree.get(t) ?? 0) + 1);
  }
  function keyFiles(indices: number[]): number[] {
    const ranked = [...indices].sort((a, b) => {
      const fa = data.files[a];
      const fb = data.files[b];
      return (
        (degree.get(b) ?? 0) - (degree.get(a) ?? 0) ||
        (fb.centrality ?? 0) - (fa.centrality ?? 0) ||
        fb.loc - fa.loc ||
        fa.path.localeCompare(fb.path)
      );
    });
    const chosen = ranked.slice(0, COMPONENTS_PER_GROUP);
    const inSet = new Set(chosen);
    const incoming = new Map(chosen.map((i) => [i, 0]));
    const out = new Map<number, number[]>(chosen.map((i) => [i, []]));
    for (const [f, t] of data.imports) {
      if (f !== t && inSet.has(f) && inSet.has(t)) {
        out.get(f)?.push(t);
        incoming.set(t, (incoming.get(t) ?? 0) + 1);
      }
    }
    const order: number[] = [];
    const remaining = new Set(chosen);
    while (remaining.size > 0) {
      const ready = chosen.filter((i) => remaining.has(i) && (incoming.get(i) ?? 0) === 0);
      const next = ready[0] ?? chosen.find((i) => remaining.has(i)); // cycle: fall back to rank
      if (next === undefined) break;
      remaining.delete(next);
      order.push(next);
      for (const t of out.get(next) ?? []) incoming.set(t, (incoming.get(t) ?? 0) - 1);
    }
    return order;
  }

  const actorLayer = data.layers.find((l) => l.kind === "actor");
  if (options.showActor && data.actor && actorLayer) {
    nodes.push({
      id: ACTOR_NODE_ID,
      kind: "actor",
      parentId: null,
      groupId: null,
      label: data.actor.label,
      fileIndices: [],
      expandable: false,
      expanded: false,
      depth: 0,
      band: actorLayer.index,
    });
  }

  for (const g of data.groups) {
    const tree = trees.get(g.id);
    if (!tree) continue;
    const id = groupNodeId(g.id);
    const expandable = hasChildren(tree);
    const isExpanded = expandable && expanded.has(id);
    nodes.push({
      id,
      kind: "group",
      parentId: null,
      groupId: g.id,
      label: g.label,
      fileIndices: tree.allFiles,
      expandable,
      expanded: isExpanded,
      depth: 0,
      band: g.layer,
    });
    if (isExpanded) addChildren(tree, id, g.id, 1);
    else {
      for (const index of keyFiles(tree.allFiles)) {
        const file = data.files[index];
        nodes.push({
          id: fileNodeId(file.path),
          kind: "component",
          parentId: id,
          groupId: g.id,
          label: file.path.split("/").pop() ?? file.path,
          fileIndices: [index],
          fileIndex: index,
          expandable: false,
          expanded: false,
          depth: 1,
          band: null,
        });
      }
    }
  }

  const infraLayer = data.layers.find((l) => l.kind === "infra");
  for (const item of data.infra) {
    nodes.push({
      id: item.id,
      kind: "infra",
      parentId: null,
      groupId: null,
      label: item.label,
      fileIndices: [],
      expandable: false,
      expanded: false,
      depth: 0,
      band: infraLayer?.index ?? null,
    });
  }

  // Children are always pushed after their parent, so walking in order and
  // overwriting leaves each file owned by its DEEPEST visible node.
  const ownerOf: string[] = new Array<string>(data.files.length).fill("");
  for (const node of nodes) {
    if (node.kind === "actor" || node.kind === "infra") continue;
    for (const i of node.fileIndices) ownerOf[i] = node.id;
  }

  return { nodes, byId: new Map(nodes.map((n) => [n.id, n])), ownerOf };
}

export function projectEdges(
  data: DiagramResponse,
  graph: VisibleGraph,
  options: { showWeak: boolean; showActor: boolean },
): { edges: VisibleEdge[]; weakHiddenCount: number } {
  const { ownerOf, byId } = graph;
  const cycleEdges = new Set<string>();
  for (const c of data.cycles) {
    for (let k = 0; k < c.length; k++) cycleEdges.add(`${c[k]}>${c[(k + 1) % c.length]}`);
  }
  const groupCycle = new Set(
    data.group_edges
      .filter((e) => e.in_group_cycle || e.in_file_cycle)
      .map((e) => `${groupNodeId(e.source)}>${groupNodeId(e.target)}`),
  );

  const edges = new Map<string, VisibleEdge>();

  for (const [f, t] of data.imports) {
    const s = ownerOf[f];
    const d = ownerOf[t];
    if (!s || !d || s === d) continue;
    const id = `e:import:${s}->${d}`;
    let edge = edges.get(id);
    if (!edge) {
      edge = { id, kind: "import", source: s, target: d, count: 0, inCycle: false, filePairs: [] };
      edges.set(id, edge);
    }
    edge.count += 1;
    if (cycleEdges.has(`${f}>${t}`) || groupCycle.has(`${s}>${d}`)) edge.inCycle = true;
    if (edge.filePairs.length < MAX_FILE_PAIRS) edge.filePairs.push([f, t]);
  }

  for (const pair of data.hidden_pairs) {
    const a = ownerOf[pair.a];
    const b = ownerOf[pair.b];
    if (!a || !b || a === b) continue;
    const [s, d] = a < b ? [a, b] : [b, a];
    const id = `e:hidden:${s}->${d}`;
    let edge = edges.get(id);
    if (!edge) {
      edge = {
        id,
        kind: "hidden",
        source: s,
        target: d,
        count: 0,
        maxDegree: 0,
        sharedRevs: 0,
        inCycle: false,
        filePairs: [],
      };
      edges.set(id, edge);
    }
    edge.count += 1;
    edge.maxDegree = Math.max(edge.maxDegree ?? 0, pair.degree);
    edge.sharedRevs = (edge.sharedRevs ?? 0) + pair.shared_revs;
    if (edge.filePairs.length < MAX_FILE_PAIRS) edge.filePairs.push([pair.a, pair.b]);
  }

  if (options.showActor && data.actor && byId.has(ACTOR_NODE_ID)) {
    const kinds = new Set(data.actor.entry_kinds);
    for (const gid of data.actor.group_ids) {
      const target = groupNodeId(gid);
      if (!byId.has(target)) continue;
      const group = data.groups.find((g) => g.id === gid);
      const count = group?.entry_points.filter((ep) => kinds.has(ep.kind)).length ?? 0;
      const id = `e:actor:${ACTOR_NODE_ID}->${target}`;
      edges.set(id, {
        id,
        kind: "actor",
        source: ACTOR_NODE_ID,
        target,
        count,
        inCycle: false,
        filePairs: [],
      });
    }
  }

  for (const item of data.infra) {
    for (const gid of item.runs_group_ids) {
      const target = groupNodeId(gid);
      if (!byId.has(target) || !byId.has(item.id)) continue;
      const id = `e:runs:${item.id}->${target}`;
      edges.set(id, {
        id,
        kind: "runs",
        source: item.id,
        target,
        count: 1,
        inCycle: false,
        filePairs: [],
      });
    }
  }

  let list = dedupeAcrossCollapsedGroups([...edges.values()], graph);
  let weakHiddenCount = 0;
  const importCount = list.filter((e) => e.kind === "import").length;
  if (!options.showWeak && importCount > WEAK_EDGE_THRESHOLD) {
    const kept = list.filter((e) => !(e.kind === "import" && e.count < 2 && !e.inCycle));
    weakHiddenCount = list.length - kept.length;
    list = kept;
  }
  list.sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
  return { edges: list, weakHiddenCount };
}

function topLevelOf(graph: VisibleGraph, id: string): VisibleNode | undefined {
  let node = graph.byId.get(id);
  while (node?.parentId) node = graph.byId.get(node.parentId);
  return node;
}

/** Between two COLLAPSED groups, draw ONE arrow per direction (one dashed
 * link for co-change), anchored on the endpoints that carry the most
 * imports, labelled with the pair's TOTAL -- the GitDiagram-style "one
 * clear line per relationship" instead of a fan of thin file-level lines.
 * Edges touching an expanded group keep full detail. */
function dedupeAcrossCollapsedGroups(edges: VisibleEdge[], graph: VisibleGraph): VisibleEdge[] {
  const kept: VisibleEdge[] = [];
  const buckets = new Map<string, VisibleEdge[]>();
  for (const e of edges) {
    if (e.kind !== "import" && e.kind !== "hidden") {
      kept.push(e);
      continue;
    }
    const a = topLevelOf(graph, e.source);
    const b = topLevelOf(graph, e.target);
    const collapsedPair =
      a &&
      b &&
      a.id !== b.id &&
      a.kind === "group" &&
      b.kind === "group" &&
      !a.expanded &&
      !b.expanded;
    if (!collapsedPair) {
      kept.push(e);
      continue;
    }
    const key = e.kind === "hidden" ? `h:${[a.id, b.id].sort().join("|")}` : `i:${a.id}>${b.id}`;
    const list = buckets.get(key) ?? [];
    list.push(e);
    buckets.set(key, list);
  }
  for (const list of buckets.values()) {
    const best = [...list].sort((x, y) => y.count - x.count || (x.id < y.id ? -1 : 1))[0];
    const merged: VisibleEdge = {
      ...best,
      count: list.reduce((sum, e) => sum + e.count, 0),
      inCycle: list.some((e) => e.inCycle),
      maxDegree: list.reduce((m, e) => Math.max(m, e.maxDegree ?? 0), 0) || best.maxDegree,
      sharedRevs: list.reduce((sum, e) => sum + (e.sharedRevs ?? 0), 0) || best.sharedRevs,
      filePairs: list.flatMap((e) => e.filePairs).slice(0, MAX_FILE_PAIRS),
    };
    kept.push(merged);
  }
  return kept;
}

/** Ids of a node and every ancestor up to the top level. */
export function ancestorIds(graph: VisibleGraph, id: string): string[] {
  const result: string[] = [];
  let current = graph.byId.get(id);
  while (current) {
    result.push(current.id);
    current = current.parentId ? graph.byId.get(current.parentId) : undefined;
  }
  return result;
}
