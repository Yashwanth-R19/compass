import type { DiagramAiGroupOut, DiagramGroupOut, DiagramResponse } from "../../api/types";
import { parseNodeId } from "./ids";
import type { VisibleEdge, VisibleNode } from "./visible";

/** A group's accent colour on the Map surfaces (the stroke of its palette
 * hue, as a CSS `var()` -- use it in `style`, not an SVG attribute). */
export function groupColor(data: DiagramResponse, groupId: string | null): string {
  return groupHue(data, groupId).stroke;
}

/** The same colour resolved to a literal value, for APIs that need one
 * (React Flow's MiniMap, Mermaid export). Read at call time, so it follows
 * the current theme. */
export function resolvedGroupColor(data: DiagramResponse, groupId: string | null): string {
  const value = groupColor(data, groupId);
  const name = value.slice(4, -1); // "var(--x)" -> "--x"
  if (typeof document === "undefined") return "#888888";
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#888888";
}

export function groupById(data: DiagramResponse, groupId: string | null): DiagramGroupOut | null {
  if (!groupId) return null;
  return data.groups.find((g) => g.id === groupId) ?? null;
}

/** The name shown for a node: the AI's friendly name for a top-level group
 * when AI labels are on and one survived validation, else the computed label. */
export function displayName(
  node: VisibleNode,
  aiOn: boolean,
  aiGroups: Map<string, DiagramAiGroupOut>,
): { name: string; fromAi: boolean } {
  if (node.kind === "group" && aiOn && node.groupId) {
    const friendly = aiGroups.get(node.groupId)?.friendly_name;
    if (friendly) return { name: friendly, fromAi: true };
  }
  return { name: node.label, fromAi: false };
}

/** The AI verb for an import edge between two COLLAPSED top-level groups
 * (verbs are only ever written at group level). */
export function edgeVerb(
  edge: VisibleEdge,
  aiOn: boolean,
  aiVerbs: Map<string, string>,
): string | null {
  if (!aiOn || edge.kind !== "import") return null;
  const s = parseNodeId(edge.source);
  const t = parseNodeId(edge.target);
  if (s?.kind !== "group" || t?.kind !== "group") return null;
  return aiVerbs.get(`${s.groupId}>${t.groupId}`) ?? null;
}

export function withShare(path: string, share: string | undefined): string {
  if (!share) return path;
  return `${path}${path.includes("?") ? "&" : "?"}share=${encodeURIComponent(share)}`;
}

/** Number of hues in the Map palette (tokens.css `--map-h0..7-*`). */
const MAP_HUES = 8;

export interface HueVars {
  fill: string;
  stroke: string;
  text: string;
}

export const EXTERNAL_HUE: HueVars = {
  fill: "var(--map-ext-fill)",
  stroke: "var(--map-ext-stroke)",
  text: "var(--map-ext-text)",
};

/** A group's Map hue. Assigned by the group's position in the (already
 * deterministic) backend order rather than by hashing its label, so the
 * first eight groups are guaranteed eight different colours -- a hash would
 * happily paint two neighbouring groups the same. Catch-all buckets
 * ("Other", "Unassigned") get the neutral external palette. */
/** Palette slot (0-7) for a group, or null for the neutral palette. */
export function groupHueIndex(data: DiagramResponse, groupId: string | null): number | null {
  if (!groupId || groupId === "other" || groupId === "sub:unassigned") return null;
  const index = data.groups.findIndex((g) => g.id === groupId);
  return index < 0 ? null : index % MAP_HUES;
}

export function groupHue(data: DiagramResponse, groupId: string | null): HueVars {
  if (!groupId || groupId === "other" || groupId === "sub:unassigned") return EXTERNAL_HUE;
  const index = data.groups.findIndex((g) => g.id === groupId);
  if (index < 0) return EXTERNAL_HUE;
  const h = index % MAP_HUES;
  return {
    fill: `var(--map-h${h}-fill)`,
    stroke: `var(--map-h${h}-stroke)`,
    text: `var(--map-h${h}-text)`,
  };
}

const GENERIC_STEMS = new Set(["index", "__init__", "main", "mod", "app", "lib"]);

function humanizeWords(raw: string): string {
  const words = raw
    .replace(/[_\-.]+/g, " ")
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/([A-Z]+)([A-Z][a-z])/g, "$1 $2")
    .trim()
    .split(/\s+/)
    .filter(Boolean)
    .map((w) => w.toLowerCase());
  if (words.length === 0) return raw;
  const sentence = words.join(" ");
  return sentence.charAt(0).toUpperCase() + sentence.slice(1);
}

/** A readable, DETERMINISTIC title for a file box ("blast_radius.py" ->
 * "Blast radius", "MapSurfacePage.tsx" -> "Map surface page"). Generic
 * stems borrow their folder ("content/index.ts" -> "Content index"). The
 * exact file name is always shown underneath in [brackets]. */
export function fileTitle(path: string): string {
  const parts = path.split("/");
  const name = parts[parts.length - 1] ?? path;
  const stem = name.includes(".") ? name.slice(0, name.lastIndexOf(".")) : name;
  if (GENERIC_STEMS.has(stem) && parts.length >= 2) {
    const folder = parts[parts.length - 2];
    return humanizeWords(`${folder} ${stem === "__init__" ? "package" : stem}`);
  }
  return humanizeWords(stem);
}
