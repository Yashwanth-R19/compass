import { Link } from "react-router-dom";
import { Card } from "./ui/Card";
import { InfoTooltip } from "./ui/InfoTooltip";
import { SubsystemBadge } from "./SubsystemBadge";
import { formatPercent, formatScore } from "../lib/format";
import { TOOLTIPS } from "../content/explainability";

/** The one file-detail side panel every view that lets you click on a file
 * opens -- the codebase map's subsystem graph (MapPage) and the 3D code
 * city (CodeCity) both render this same component rather than each
 * building their own "selected file" card (session 09, Part F: "Reuse it;
 * do not build a second one"). Docked as a side panel rather than an
 * overlay/modal, matching the pattern every other repo-scoped page in this
 * app already uses for a "selected node" side panel (ArchitecturePage). */
export function FileDetailPanel({
  repoId,
  path,
  loc,
  complexity,
  riskScore,
  centrality,
  subsystemLabel,
  expertName,
  onClose,
}: {
  repoId: string;
  path: string;
  loc?: number | null;
  complexity?: number | null;
  riskScore?: number | null;
  /** PageRank over the combined dependency+coupling graph -- only ever
   * available on the codebase map's own subsystem-graph view (from
   * `/subsystems`' `SubsystemMemberOut.centrality`), never from `/city`,
   * so the 3D city's own calls to this component simply omit it. */
  centrality?: number | null;
  subsystemLabel?: string | null;
  expertName?: string | null;
  onClose: () => void;
}) {
  return (
    <Card
      eyebrow="Selected file"
      action={
        <button type="button" onClick={onClose} className="text-xs text-text-muted hover:text-text">
          Clear
        </button>
      }
    >
      <div className="flex flex-col gap-2 text-xs text-text-muted">
        <p className="truncate font-mono text-sm text-text" title={path}>
          {path}
        </p>
        <SubsystemBadge label={subsystemLabel} />
        {loc != null ? <p>{loc.toLocaleString()} LOC</p> : null}
        {complexity != null ? <p>Complexity {complexity.toFixed(1)}</p> : null}
        {riskScore != null ? <p>Risk score {formatPercent(riskScore)}</p> : null}
        {centrality != null ? (
          <p className="flex items-center gap-1">
            Centrality {formatScore(centrality, 3)}
            <InfoTooltip label="What is centrality?" text={TOOLTIPS.centrality} />
          </p>
        ) : null}
        {expertName ? <p>Principal author: {expertName}</p> : null}
        <Link
          to={`/repos/${repoId}/guide?view=people&path=${encodeURIComponent(path)}`}
          className="w-fit font-medium text-accent hover:underline"
        >
          See who knows this file →
        </Link>
        <Link
          to={`/repos/${repoId}/explore?view=impact&path=${encodeURIComponent(path)}`}
          className="w-fit font-medium text-accent hover:underline"
        >
          See its blast radius →
        </Link>
      </div>
    </Card>
  );
}
