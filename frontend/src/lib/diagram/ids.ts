/**
 * Node id formats for the Map. These appear in the URL (`?expanded=`,
 * `?focus=`, `?path=`), so they must stay stable across releases:
 *
 *   group   g:<groupId>              g:sub:0, g:dir:backend/app, g:other
 *   folder  f:<groupId>::<relPath>   relPath relative to the group's base_path
 *   file    file:<path>
 *   more    more:<parentNodeId>      the "+N more" chip inside an expanded node
 *   actor   actor
 *   infra   infra:<name>             the backend's own infra id
 */

export type ParsedNodeId =
  | { kind: "group"; groupId: string }
  | { kind: "folder"; groupId: string; relPath: string }
  | { kind: "file"; path: string }
  | { kind: "more"; parentId: string }
  | { kind: "actor" }
  | { kind: "infra"; infraId: string };

export const ACTOR_NODE_ID = "actor";

export function groupNodeId(groupId: string): string {
  return `g:${groupId}`;
}

export function folderNodeId(groupId: string, relPath: string): string {
  return `f:${groupId}::${relPath}`;
}

export function fileNodeId(path: string): string {
  return `file:${path}`;
}

export function moreNodeId(parentId: string): string {
  return `more:${parentId}`;
}

export function parseNodeId(id: string): ParsedNodeId | null {
  if (id === ACTOR_NODE_ID) return { kind: "actor" };
  if (id.startsWith("infra:")) return { kind: "infra", infraId: id };
  if (id.startsWith("g:")) return { kind: "group", groupId: id.slice(2) };
  if (id.startsWith("file:")) return { kind: "file", path: id.slice(5) };
  if (id.startsWith("more:")) return { kind: "more", parentId: id.slice(5) };
  if (id.startsWith("f:")) {
    const rest = id.slice(2);
    const sep = rest.indexOf("::");
    if (sep < 0) return null;
    return { kind: "folder", groupId: rest.slice(0, sep), relPath: rest.slice(sep + 2) };
  }
  return null;
}
