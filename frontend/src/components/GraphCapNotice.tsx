export function GraphCapNotice({
  nodesCapped,
  edgesCapped,
  shownNodes,
  totalNodes,
}: {
  nodesCapped: boolean;
  edgesCapped: boolean;
  shownNodes: number;
  totalNodes: number;
}) {
  if (!nodesCapped && !edgesCapped) return null;

  return (
    <p className="mb-2 rounded-md bg-amber-50 px-3 py-1.5 text-xs text-amber-700 dark:bg-amber-500/10 dark:text-amber-400">
      {nodesCapped
        ? `Showing top ${shownNodes} of ${totalNodes} files by coupling strength.`
        : "Some low-weight edges are hidden to keep this graph responsive."}
    </p>
  );
}
