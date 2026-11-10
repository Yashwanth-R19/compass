import type { DiagramInfraCategory } from "../../api/types";
import type { VisibleEdge, VisibleNode } from "./visible";

export interface MermaidInput {
  repoName: string;
  grouping: string;
  aiOn: boolean;
  nodes: VisibleNode[];
  edges: VisibleEdge[];
  /** The label currently displayed for a node (AI-renamed when AI is on). */
  labelOf: (node: VisibleNode) => string;
  /** Whether that displayed label was written by the AI. */
  isAiLabel: (node: VisibleNode) => boolean;
  bands: { index: number; label: string }[];
  infraCategory: (id: string) => DiagramInfraCategory | null;
  verbOf: (edge: VisibleEdge) => string | null;
  /** Literal colour for cycle edges (Mermaid needs a colour value, not a CSS var). */
  cycleColor: string;
}

function escape(text: string): string {
  return text.replace(/"/g, "#quot;").replace(/\n/g, " ");
}

function byId<T extends { id: string }>(a: T, b: T): number {
  return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
}

/** Deterministic Mermaid flowchart of exactly what is on screen. */
export function toMermaid(input: MermaidInput): string {
  const sorted = [...input.nodes].sort(byId);
  const alias = new Map(sorted.map((n, i) => [n.id, `n${i}`]));
  const childrenOf = new Map<string | null, VisibleNode[]>();
  for (const n of sorted) {
    const list = childrenOf.get(n.parentId) ?? [];
    list.push(n);
    childrenOf.set(n.parentId, list);
  }

  const lines: string[] = [
    `%% Compass Map: ${input.repoName} (${input.grouping}), drawn from the computed import graph and commit history`,
  ];
  if (input.aiOn) {
    lines.push(
      "%% Names and verbs marked (AI) were written by an AI model; boxes and arrows are computed.",
    );
  }
  lines.push("flowchart TD");

  const label = (n: VisibleNode): string => {
    const base = input.labelOf(n);
    return escape(input.isAiLabel(n) ? `${base} (AI)` : base);
  };

  const shape = (n: VisibleNode): string => {
    const id = alias.get(n.id) as string;
    const text = label(n);
    if (n.kind === "actor" || n.kind === "more") return `${id}(["${text}"])`;
    if (n.kind === "infra") {
      return input.infraCategory(n.id) === "datastore"
        ? `${id}[("${text}")]`
        : `${id}[/"${text}"/]`;
    }
    const files =
      n.kind === "file"
        ? ""
        : ` (${n.fileIndices.length} file${n.fileIndices.length === 1 ? "" : "s"})`;
    return `${id}["${text}${files}"]`;
  };

  const emit = (n: VisibleNode, indent: string): void => {
    const kids = childrenOf.get(n.id) ?? [];
    if (n.expanded && kids.length > 0) {
      lines.push(`${indent}subgraph ${alias.get(n.id)}["${label(n)}"]`);
      for (const k of kids) emit(k, `${indent}  `);
      lines.push(`${indent}end`);
    } else {
      lines.push(`${indent}${shape(n)}`);
    }
  };

  const topLevel = childrenOf.get(null) ?? [];
  for (const band of [...input.bands].sort((a, b) => a.index - b.index)) {
    const members = topLevel.filter((n) => n.band === band.index);
    if (members.length === 0) continue;
    lines.push(`  subgraph band${band.index}["${escape(band.label)}"]`);
    for (const n of members) emit(n, "    ");
    lines.push("  end");
  }
  for (const n of topLevel.filter((t) => t.band === null)) emit(n, "  ");

  const cycleLinks: number[] = [];
  let linkIndex = 0;
  for (const e of [...input.edges].sort(byId)) {
    const s = alias.get(e.source);
    const t = alias.get(e.target);
    if (!s || !t) continue;
    if (e.kind === "hidden") {
      lines.push(`  ${s} -. "co-change ${Math.round((e.maxDegree ?? 0) * 100)}%" .- ${t}`);
    } else if (e.kind === "import") {
      const imports = `${e.count} import${e.count === 1 ? "" : "s"}`;
      const verb = input.verbOf(e);
      lines.push(`  ${s} -- "${escape(verb ? `${verb} (AI) · ${imports}` : imports)}" --> ${t}`);
    } else {
      lines.push(`  ${s} -- "${e.kind === "actor" ? "enters" : "runs"}" --> ${t}`);
    }
    if (e.inCycle) cycleLinks.push(linkIndex);
    linkIndex += 1;
  }
  for (const i of cycleLinks) {
    lines.push(`  linkStyle ${i} stroke:${input.cycleColor || "red"},stroke-width:2px`);
  }
  return `${lines.join("\n")}\n`;
}
