import { useState } from "react";
import type { FindingCategory, FindingOut } from "../api/types";
import { ConfidenceMeter } from "./ConfidenceMeter";
import { EvidencePanel } from "./EvidencePanel";
import { SeverityChip } from "./SeverityChip";
import { FINDING_CATEGORY_COPY } from "../lib/copy";
import { findingDeepLink, parseHiddenDependencyPair } from "../lib/findingLinks";

function categoryLabel(category: string): string {
  const copy = FINDING_CATEGORY_COPY[category as FindingCategory];
  return copy ? copy() : category;
}

/** One row in the audit findings stream (Part A). Collapsed: severity,
 * category, confidence, title, affected file -- everything needed to
 * triage without a click. Expanded (click anywhere on the row): the real
 * evidence -- detail text (already carries the metrics an engine computed),
 * the evidence commit, every affected file, and a deep link into the page
 * that visualizes this category (lib/findingLinks.ts). `repoId` is required
 * to build that deep link as an absolute `/repos/<id>/...` path -- see
 * findingDeepLink's own docstring for why it can't be relative here. */
export function FindingItem({
  finding,
  repoId,
  repoUrl,
}: {
  finding: FindingOut;
  repoId: string;
  repoUrl?: string | null;
}) {
  const [expanded, setExpanded] = useState(false);

  const affectedFiles = (() => {
    if (finding.category === "hidden_dependency") {
      const pair = parseHiddenDependencyPair(finding.title);
      if (pair) return pair;
    }
    return finding.file_path ? [finding.file_path] : [];
  })();

  const deepLink = findingDeepLink(finding, repoId);

  return (
    <li className="border-b border-border py-3 last:border-0">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
        className="flex w-full flex-col gap-2 text-left"
      >
        <div className="flex flex-wrap items-center gap-2">
          <SeverityChip severity={finding.severity} />
          <span className="cp-label border border-border px-1.5 py-0.5">
            {categoryLabel(finding.category)}
          </span>
          <ConfidenceMeter confidence={finding.confidence} size="sm" />
          <span className="ml-auto shrink-0 text-xs text-ink-faint">
            {expanded ? "Hide evidence ▲" : "Show evidence ▼"}
          </span>
        </div>
        <p className="text-sm font-medium text-ink">{finding.title}</p>
        {finding.file_path ? (
          <p className="truncate font-mono text-xs text-ink-faint" title={finding.file_path}>
            {finding.file_path}
          </p>
        ) : null}
      </button>

      {expanded ? (
        <div className="mt-2">
          <EvidencePanel
            detail={finding.detail}
            evidenceSha={finding.evidence_sha}
            repoUrl={repoUrl}
            affectedFiles={affectedFiles}
            deepLink={deepLink}
          />
        </div>
      ) : null}
    </li>
  );
}
