import { useState } from "react";
import { useOutletContext } from "react-router-dom";
import { useFindings } from "../../api/hooks";
import type { FindingCategory } from "../../api/types";
import { Card } from "../../components/Card";
import { FindingItem } from "../../components/FindingItem";
import { StageGate } from "../../components/StageGate";
import { FINDING_CATEGORY_COPY } from "../../lib/copy";
import type { RepoOutletContext } from "../RepoLayout";

const CATEGORIES: FindingCategory[] = [
  "risk",
  "architecture",
  "hidden_dependency",
  "knowledge",
  "hygiene",
  "test_gap",
];

/** The audit-mode landing tab: the full, globally-ranked findings stream
 * (FindingsRankEngine's `rank`, read straight -- never re-sorted here, per
 * RULES.md sec 12). Session 06's Overview page used to show only the top 10
 * alongside health/vitals; splitting findings into its own tab means the
 * complete ranked list belongs here, with an optional category filter. */
export function FindingsPage() {
  const { repo, share } = useOutletContext<RepoOutletContext>();
  const [category, setCategory] = useState<FindingCategory | "">("");
  const findings = useFindings(repo.id, category || undefined, share);

  return (
    <Card
      title="Findings"
      subtitle="Ranked by impact across every category — the anti-alert-fatigue spine"
      action={
        <select
          value={category}
          onChange={(e) => setCategory(e.target.value as FindingCategory | "")}
          className="rounded-md border border-slate-200 bg-white px-2 py-1 text-xs text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300"
        >
          <option value="">All categories</option>
          {CATEGORIES.map((c) => (
            <option key={c} value={c}>
              {FINDING_CATEGORY_COPY[c]()}
            </option>
          ))}
        </select>
      }
    >
      <StageGate
        query={findings}
        emptyTitle="No findings"
        emptyMessage="Nothing rose above the noise floor for this repo yet."
        isEmpty={(data) => data.findings.length === 0}
      >
        {(data) => (
          <ul>
            {data.findings.map((f) => (
              <FindingItem key={f.id} finding={f} repoUrl={repo.url} />
            ))}
          </ul>
        )}
      </StageGate>
    </Card>
  );
}
