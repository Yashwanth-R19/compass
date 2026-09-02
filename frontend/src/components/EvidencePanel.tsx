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
    <div className="flex flex-col gap-2.5 rounded-lg bg-slate-50 p-3 text-sm dark:bg-slate-950/40">
      <p className="text-slate-600 dark:text-slate-300">{detail}</p>

      {evidenceSha ? (
        <div className="flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
          <span>Evidence commit:</span>
          {repoUrl ? (
            <EvidenceLink repoUrl={repoUrl} sha={evidenceSha} />
          ) : (
            <span className="w-fit rounded bg-slate-100 px-1.5 py-0.5 font-mono text-xs text-slate-500 dark:bg-slate-800 dark:text-slate-400">
              {shortSha(evidenceSha)}
            </span>
          )}
        </div>
      ) : null}

      {affectedFiles.length > 0 ? (
        <div className="flex flex-col gap-1">
          <span className="text-xs text-slate-500 dark:text-slate-400">
            {affectedFiles.length === 1 ? "Affected file" : "Affected files"}
          </span>
          <ul className="flex flex-col gap-0.5">
            {affectedFiles.map((f) => (
              <li
                key={f}
                className="truncate font-mono text-xs text-slate-700 dark:text-slate-300"
                title={f}
              >
                {f}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {deepLink ? (
        <Link
          to={deepLink.to}
          className="w-fit text-xs font-medium text-indigo-600 hover:underline dark:text-indigo-400"
        >
          {deepLink.label} →
        </Link>
      ) : null}
    </div>
  );
}
