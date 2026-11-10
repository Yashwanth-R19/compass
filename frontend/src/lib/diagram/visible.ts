import type { DiagramResponse } from "../../api/types";
import { ACTOR_NODE_ID, fileNodeId, groupNodeId, moreNodeId } from "./ids";
import { hasChildren, orderedChildren, type TreeChild, type TreeFolder } from "./tree";

export type VisibleNodeKind = "group" | "folder" | "file" | "more" | "actor" | "infra";

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

  let list = [...edges.values()];
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
