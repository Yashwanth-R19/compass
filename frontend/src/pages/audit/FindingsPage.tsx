import { useState } from "react";
import { useOutletContext } from "react-router-dom";
import { useFindings } from "../../api/hooks";
import type { FindingCategory, FindingOut, Severity } from "../../api/types";
import { Card } from "../../components/Card";
import { FindingItem } from "../../components/FindingItem";
import { StageGate } from "../../components/StageGate";
import { Button } from "../../components/ui/Button";
import { FINDING_CATEGORY_COPY } from "../../lib/copy";
import { SEVERITY_LABEL } from "../../lib/format";
import type { RepoOutletContext } from "../RepoLayout";

const CATEGORIES: FindingCategory[] = [
  "risk",
  "architecture",
  "hidden_dependency",
  "knowledge",
  "hygiene",
  "test_gap",
  "secret",
  "vulnerability",
];

const SEVERITIES: Severity[] = ["high", "med", "low"];

// THE governing constraint of this session (RULES.md sec 12, Known Hazard
// #2): the default view shows the few things that matter, never a wall of
// everything. Ten, with an explicit "show all" affordance -- never quietly
// raised.
const DEFAULT_VISIBLE = 10;
const LOW_CONFIDENCE_THRESHOLD = 0.4;

/** The audit-mode landing tab: the full, globally-ranked findings stream
 * (FindingsRankEngine's `rank`), collapsed to the top 10 by default. Every
 * filter here REMOVES rows from `data.findings` -- it never reorders them.
 * `data.findings` arrives already in the backend's one global cross-category
 * rank; re-sorting it client-side (even "helpfully," even by severity)
 * throws away the entire anti-alert-fatigue mechanism this project exists
 * to provide (Known Hazard #1). If a sort control is ever added here, it
 * must re-query the backend, not `.sort()` this array. */
export function FindingsPage() {
  const { repo, share } = useOutletContext<RepoOutletContext>();
  const [category, setCategory] = useState<FindingCategory | "">("");
  const [severity, setSeverity] = useState<Severity | "">("");
  const [showAll, setShowAll] = useState(false);
  const findings = useFindings(repo.id, category || undefined, share);

  function changeCategory(next: FindingCategory | "") {
    setCategory(next);
    setShowAll(false);
  }

  function changeSeverity(next: Severity | "") {
    setSeverity(next);
    setShowAll(false);
  }

  return (
    <Card
      title="Findings"
      subtitle="Ranked by impact across every category — the anti-alert-fatigue spine"
      action={
        <div className="flex items-center gap-2">
          <select
            aria-label="Filter findings by category"
            value={category}
            onChange={(e) => changeCategory(e.target.value as FindingCategory | "")}
            className="border border-border-interactive bg-surface px-2 py-1 text-xs text-ink-muted"
          >
            <option value="">All categories</option>
            {CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {FINDING_CATEGORY_COPY[c]()}
              </option>
            ))}
          </select>
          <select
            aria-label="Filter findings by severity"
            value={severity}
            onChange={(e) => changeSeverity(e.target.value as Severity | "")}
            className="border border-border-interactive bg-surface px-2 py-1 text-xs text-ink-muted"
          >
            <option value="">All severities</option>
            {SEVERITIES.map((s) => (
              <option key={s} value={s}>
                {SEVERITY_LABEL[s]}
              </option>
            ))}
          </select>
        </div>
      }
    >
      <StageGate
        query={findings}
        emptyTitle="No findings"
        emptyMessage="Nothing rose above the noise floor for this repo yet."
        isEmpty={(data) => data.findings.length === 0}
      >
        {(data) => (
          <FindingsList
            findings={data.findings}
            severity={severity}
            showAll={showAll}
            onToggleShowAll={() => setShowAll((v) => !v)}
            repoId={repo.id}
            repoUrl={repo.url}
          />
        )}
      </StageGate>
    </Card>
  );
}

function FindingsList({
  findings,
  severity,
  showAll,
  onToggleShowAll,
  repoId,
  repoUrl,
}: {
  findings: FindingOut[];
  severity: Severity | "";
  showAll: boolean;
  onToggleShowAll: () => void;
  repoId: string;
  repoUrl: string;
}) {
  // A pure filter (removes rows), never a sort -- see this file's own
  // docstring. `findings` arrives pre-ranked; `.filter` preserves order.
  const filtered = severity ? findings.filter((f) => f.severity === severity) : findings;
  const visible = showAll ? filtered : filtered.slice(0, DEFAULT_VISIBLE);
  const lowConfidenceCount = filtered.filter((f) => f.confidence < LOW_CONFIDENCE_THRESHOLD).length;

  if (filtered.length === 0) {
    return (
      <p className="py-8 text-center text-sm text-ink-faint">No findings match this filter.</p>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {lowConfidenceCount > 0 ? (
        <p className="border-l-2 border-conf-low py-1.5 pl-3 text-xs text-ink-muted">
          {lowConfidenceCount} of {filtered.length}{" "}
          {filtered.length === 1 ? "finding is" : "findings are"} low-confidence — this repository
          may not have enough analyzed history yet for a firm signal. Treat these as directional,
          not certain.
        </p>
      ) : null}

      <ul>
        {visible.map((f) => (
          <FindingItem key={f.id} finding={f} repoId={repoId} repoUrl={repoUrl} />
        ))}
      </ul>

      {filtered.length > DEFAULT_VISIBLE ? (
        <Button
          variant="secondary"
          size="sm"
          onClick={onToggleShowAll}
          className="w-fit self-center"
        >
          {showAll ? `Show top ${DEFAULT_VISIBLE} only` : `Show all ${filtered.length} findings`}
        </Button>
      ) : null}
    </div>
  );
}
