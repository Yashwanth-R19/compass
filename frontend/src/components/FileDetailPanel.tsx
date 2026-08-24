import { Link } from "react-router-dom";
import { Card } from "./Card";
import { SubsystemBadge } from "./SubsystemBadge";
import { formatPercent } from "../lib/format";

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
  subsystemLabel,
  expertName,
  onClose,
}: {
  repoId: string;
  path: string;
  loc?: number | null;
  complexity?: number | null;
  riskScore?: number | null;
  subsystemLabel?: string | null;
  expertName?: string | null;
  onClose: () => void;
}) {
  return (
    <Card
      title="Selected file"
      subtitle={path}
      action={
        <button
          type="button"
          onClick={onClose}
          className="text-xs text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
        >
          Clear
        </button>
      }
    >
      <div className="flex flex-col gap-2 text-xs text-slate-500 dark:text-slate-400">
        <SubsystemBadge label={subsystemLabel} />
        {loc != null ? <p>{loc.toLocaleString()} LOC</p> : null}
        {complexity != null ? <p>Complexity {complexity.toFixed(1)}</p> : null}
        {riskScore != null ? <p>Risk score {formatPercent(riskScore)}</p> : null}
        {expertName ? <p>Principal author: {expertName}</p> : null}
        <Link
          to={`/repos/${repoId}/onboard/people?path=${encodeURIComponent(path)}`}
          className="w-fit font-medium text-indigo-600 hover:underline dark:text-indigo-400"
        >
          See who knows this file →
        </Link>
        <Link
          to={`/repos/${repoId}/onboard/impact?path=${encodeURIComponent(path)}`}
          className="w-fit font-medium text-indigo-600 hover:underline dark:text-indigo-400"
        >
          See its blast radius →
        </Link>
      </div>
    </Card>
  );
}
