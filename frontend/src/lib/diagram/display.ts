import type { DiagramAiGroupOut, DiagramGroupOut, DiagramResponse } from "../../api/types";
import { colorForKey } from "../palette";
import { parseNodeId } from "./ids";
import type { VisibleEdge, VisibleNode } from "./visible";

/** A group's identity colour -- the same colour the rest of the app uses
 * for that subsystem (SubsystemBadge keys on the bare label), a namespaced
 * key for folders, and neutral grey for the catch-all buckets. */
export function groupColor(data: DiagramResponse, groupId: string | null): string {
  if (!groupId || groupId === "other" || groupId === "sub:unassigned") return colorForKey(null);
  if (data.grouping === "folder" || groupId.startsWith("dir:")) {
    return colorForKey(`folder:${groupId}`);
  }
  const group = data.groups.find((g) => g.id === groupId);
  return colorForKey(group?.label ?? groupId);
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
