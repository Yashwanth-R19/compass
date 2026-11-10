import type { DiagramResponse } from "../../api/types";
import { folderNodeId } from "./ids";

/** One folder inside a group, relative to that group's `base_path`. The
 * group itself is the virtual root (`relPath === ""`). */
export interface TreeFolder {
  id: string;
  groupId: string;
  name: string;
  relPath: string;
  folders: TreeFolder[];
  /** Files directly inside this folder (file indices). */
  files: number[];
  /** Every file under this folder, recursively (file indices, sorted). */
  allFiles: number[];
}

export type TreeChild = { kind: "folder"; folder: TreeFolder } | { kind: "file"; index: number };

function relativePath(path: string, base: string): string {
  if (!base) return path;
  return path.startsWith(`${base}/`) ? path.slice(base.length + 1) : path;
}

/** Builds one folder tree per group from the flat file list. Pure and
 * deterministic: children are sorted by `orderedChildren`, never by
 * insertion order. */
export function buildGroupTrees(data: DiagramResponse): Map<string, TreeFolder> {
  const trees = new Map<string, TreeFolder>();
  const baseOf = new Map(data.groups.map((g) => [g.id, g.base_path]));

  for (const g of data.groups) {
    trees.set(g.id, {
      id: folderNodeId(g.id, ""),
      groupId: g.id,
      name: g.label,
      relPath: "",
      folders: [],
      files: [],
      allFiles: [],
    });
  }

  const lookup = new Map<string, TreeFolder>();
  for (const file of data.files) {
    const root = trees.get(file.group_id);
    if (!root) continue;
    const segments = relativePath(file.path, baseOf.get(file.group_id) ?? "").split("/");
    let node = root;
    node.allFiles.push(file.i);
    for (let k = 0; k < segments.length - 1; k++) {
      const relPath = segments.slice(0, k + 1).join("/");
      const key = folderNodeId(file.group_id, relPath);
      let child = lookup.get(key);
      if (!child) {
        child = {
          id: folderNodeId(file.group_id, relPath),
          groupId: file.group_id,
          name: segments[k],
          relPath,
          folders: [],
          files: [],
          allFiles: [],
        };
        lookup.set(key, child);
        node.folders.push(child);
      }
      node = child;
      node.allFiles.push(file.i);
    }
    node.files.push(file.i);
  }

  return trees;
}

/** The one ordering used everywhere a node's children are listed: folders
 * first (largest first, then name), then files (most central first in
 * subsystem mode, largest first in folder mode, then path). */
export function orderedChildren(folder: TreeFolder, data: DiagramResponse): TreeChild[] {
  const folders = [...folder.folders].sort(
    (a, b) => b.allFiles.length - a.allFiles.length || a.name.localeCompare(b.name),
  );
  const files = [...folder.files].sort((a, b) => {
    const fa = data.files[a];
    const fb = data.files[b];
    const primary =
      data.grouping === "subsystem" ? (fb.centrality ?? 0) - (fa.centrality ?? 0) : fb.loc - fa.loc;
    return primary || fa.path.localeCompare(fb.path);
  });
  return [
    ...folders.map((f) => ({ kind: "folder" as const, folder: f })),
    ...files.map((index) => ({ kind: "file" as const, index })),
  ];
}

export function hasChildren(folder: TreeFolder): boolean {
  return folder.folders.length + folder.files.length > 0;
}

/** Finds a folder by its relPath inside a group's tree. */
export function findFolder(root: TreeFolder, relPath: string): TreeFolder | null {
  if (relPath === "") return root;
  let node: TreeFolder | undefined = root;
  const segments = relPath.split("/");
  for (let k = 0; k < segments.length && node; k++) {
    const target = segments.slice(0, k + 1).join("/");
    node = node.folders.find((f) => f.relPath === target);
  }
  return node ?? null;
}

/** Folder chain (relPaths, outermost first) leading to a file's parent
 * folder inside its group -- used by search to expand a file's ancestors. */
export function ancestorFolderPaths(path: string, base: string): string[] {
  const segments = relativePath(path, base).split("/");
  const result: string[] = [];
  for (let k = 0; k < segments.length - 1; k++) {
    result.push(segments.slice(0, k + 1).join("/"));
  }
  return result;
}

export function sumLoc(data: DiagramResponse, indices: number[]): number {
  let total = 0;
  for (const i of indices) total += data.files[i].loc;
  return total;
}

export function sumChurn(data: DiagramResponse, indices: number[]): number {
  let total = 0;
  for (const i of indices) total += data.files[i].churn_365d;
  return total;
}

export function maxLastChanged(data: DiagramResponse, indices: number[]): number {
  let latest = 0;
  for (const i of indices) latest = Math.max(latest, data.files[i].last_changed);
  return latest;
}
