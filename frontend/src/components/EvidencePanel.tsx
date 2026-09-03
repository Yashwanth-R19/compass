import { Link } from "react-router-dom";
import { EvidenceLink } from "./EvidenceLink";
import { shortSha } from "../lib/format";
import type { FindingDeepLink } from "../lib/findingLinks";

/** The evidence shown when a finding row expands (Part A): the free-text
 * detail (already carries the real metrics an engine computed -- see
 * app/engines/*.py's own `detail=` f-strings, e.g. "risk_score=0.82
 * (churn_weighted=..., complexity=...)"), the evidence commit linked to
 * GitHub, the affected file(s), and a deep link into the page that
 * visualizes this category. Deliberately generic over WHICH finding
 * produced it -- FindingItem is the only caller today, but nothing here is
 * findings-specific, so a future page (e.g. a hygiene event) can reuse it. */
export function EvidencePanel({
  detail,
  evidenceSha,
  repoUrl,
  affectedFiles,
  deepLink,
}: {
  detail: string;
  evidenceSha?: string | null;
  repoUrl?: string | null;
  affectedFiles: string[];
  deepLink?: FindingDeepLink | null;
}) {
  return (
    <div className="flex flex-col gap-2.5 border-l-2 border-border-strong bg-bg-inset p-3 text-sm">
      <p className="text-text-muted">{detail}</p>

      {evidenceSha ? (
        <div className="flex items-center gap-2 text-xs text-text-muted">
          <span>Evidence commit:</span>
          {repoUrl ? (
            <EvidenceLink repoUrl={repoUrl} sha={evidenceSha} />
          ) : (
            <span className="w-fit cp-stat border border-border bg-bg-elevated px-1.5 py-0.5 text-xs text-text-muted">
              {shortSha(evidenceSha)}
            </span>
          )}
        </div>
      ) : null}

      {affectedFiles.length > 0 ? (
        <div className="flex flex-col gap-1">
          <span className="cp-label">
            {affectedFiles.length === 1 ? "Affected file" : "Affected files"}
          </span>
          <ul className="flex flex-col gap-0.5">
            {affectedFiles.map((f) => (
              <li key={f} className="truncate font-mono text-xs text-text-muted" title={f}>
                {f}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {deepLink ? (
        <Link to={deepLink.to} className="w-fit text-xs font-medium text-accent hover:underline">
          {deepLink.label} →
        </Link>
      ) : null}
    </div>
  );
}
