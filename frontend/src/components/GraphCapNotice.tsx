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
    <p className="mb-2 border-l-2 border-conf-low py-1 pl-3 text-xs text-ink-muted">
      {nodesCapped
        ? `Showing top ${shownNodes} of ${totalNodes} files by coupling strength.`
        : "Some low-weight edges are hidden to keep this graph responsive."}
    </p>
  );
}
