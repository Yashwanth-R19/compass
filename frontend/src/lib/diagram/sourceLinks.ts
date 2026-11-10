import type { DiagramSourceOut } from "../../api/types";

function encodePath(path: string): string {
  return path
    .split("/")
    .filter((segment) => segment.length > 0)
    .map(encodeURIComponent)
    .join("/");
}

/** Link to a file at the analysed commit, or null for hosts Compass can't
 * build links for. */
export function blobUrl(source: DiagramSourceOut, path: string): string | null {
  return source.blob_base_url ? `${source.blob_base_url}${encodePath(path)}` : null;
}

/** Link to a directory at the analysed commit ("" = repository root). */
export function treeUrl(source: DiagramSourceOut, dir: string): string | null {
  if (!source.tree_base_url) return null;
  return dir ? `${source.tree_base_url}${encodePath(dir)}` : source.tree_base_url;
}

export function hostLabel(source: DiagramSourceOut): string {
  return source.host === "gitlab" ? "GitLab" : "GitHub";
}
