import type { FindingCategory, FindingOut } from "../api/types";
import { EvidenceLink } from "./EvidenceLink";
import { FINDING_CATEGORY_COPY } from "../lib/copy";
import { SEVERITY_CLASSES, SEVERITY_LABEL, confidenceLabel, formatPercent } from "../lib/format";

function categoryLabel(category: string): string {
  const copy = FINDING_CATEGORY_COPY[category as FindingCategory];
  return copy ? copy() : category;
}

export function FindingItem({
  finding,
  repoUrl,
}: {
  finding: FindingOut;
  repoUrl?: string | null;
}) {
  const confLabel = confidenceLabel(finding.confidence);

  return (
    <li className="flex flex-col gap-2 border-b border-slate-100 py-3 last:border-0 dark:border-slate-800">
      <div className="flex flex-wrap items-center gap-2">
        <span
          className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${SEVERITY_CLASSES[finding.severity]}`}
        >
          {SEVERITY_LABEL[finding.severity]}
        </span>
        <span className="inline-flex items-center rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600 dark:bg-slate-800 dark:text-slate-300">
          {categoryLabel(finding.category)}
        </span>
        <span
          className={`text-xs ${confLabel === "low" ? "text-amber-600 dark:text-amber-400" : "text-slate-400 dark:text-slate-500"}`}
          title="Confidence: how much history backs this finding"
        >
          {formatPercent(finding.confidence)} confidence{confLabel === "low" ? " (low)" : ""}
        </span>
      </div>
      <p className="text-sm font-medium text-slate-900 dark:text-slate-100">{finding.title}</p>
      <p className="text-sm text-slate-500 dark:text-slate-400">{finding.detail}</p>
      {finding.evidence_sha ? (
        repoUrl ? (
          <EvidenceLink repoUrl={repoUrl} sha={finding.evidence_sha} />
        ) : (
          <span className="w-fit rounded bg-slate-100 px-1.5 py-0.5 font-mono text-xs text-slate-500 dark:bg-slate-800 dark:text-slate-400">
            {finding.evidence_sha.slice(0, 7)}
          </span>
        )
      ) : null}
    </li>
  );
}
