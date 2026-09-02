import { useEffect, useState } from "react";
import { useOutletContext } from "react-router-dom";
import { useCompare, useRuns } from "../api/hooks";
import type {
  AnalysisRunOut,
  CompareFindingOut,
  CompareResponse,
  ContributorChangeOut,
  CouplingChangeOut,
  RiskMoverOut,
  SubsystemChangeOut,
} from "../api/types";
import { Card } from "../components/Card";
import { EmptyState } from "../components/EmptyState";
import { ErrorState } from "../components/ErrorState";
import { LoadingState } from "../components/LoadingState";
import { SeverityChip } from "../components/SeverityChip";
import { CONTRIBUTOR_CHANGE_COPY, COUPLING_CHANGE_COPY, SUBSYSTEM_CHANGE_COPY } from "../lib/copy";
import { DIRECTION_TEXT_CLASS, formatSignedDelta, headlineDirection } from "../lib/compare";
import type { RepoOutletContext } from "./RepoLayout";

/** Session 13, Part G: diff two analysis runs of the same repository --
 * findings appeared/resolved/persisted, risk movers, contributors joined and
 * left. Defaults to the two most recent COMPLETED runs (current vs.
 * previous). "Completed" means "ready" (the current run) OR "superseded"
 * (an earlier run a later one has since replaced) -- NOT just "ready": a
 * repo's current run is the only one ever "ready" at a time (CLAUDE.md,
 * Facts/Insight split), so filtering to "ready" alone would mean no repo
 * could ever offer two runs to pick from. "running"/"failed" runs are
 * excluded -- they have no usable Insight data to diff against. */
export function ComparePage() {
  const { repo, share } = useOutletContext<RepoOutletContext>();
  const runs = useRuns(repo.id, share);

  const completedRuns = (runs.data?.runs ?? []).filter(
    (r) => r.status === "ready" || r.status === "superseded",
  );
  const [runIdBefore, setRunIdBefore] = useState<string | undefined>(undefined);
  const [runIdAfter, setRunIdAfter] = useState<string | undefined>(undefined);

  useEffect(() => {
    if (runIdBefore || runIdAfter || completedRuns.length < 2) return;
    // useRuns returns newest first -- [0] is current, [1] is previous.
    setRunIdAfter(completedRuns[0].id);
    setRunIdBefore(completedRuns[1].id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [completedRuns.length]);

  const compare = useCompare(runIdBefore, runIdAfter);

  if (runs.isPending) return <LoadingState label="Loading runs…" />;
  if (runs.isError) return <ErrorState error={runs.error} onRetry={() => void runs.refetch()} />;

  if (completedRuns.length < 2) {
    return (
      <EmptyState
        title="Nothing to compare yet"
        message="This repository needs at least two completed analysis runs before they can be compared."
      />
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <RunPicker
        runs={completedRuns}
        runIdBefore={runIdBefore}
        runIdAfter={runIdAfter}
        onChangeBefore={setRunIdBefore}
        onChangeAfter={setRunIdAfter}
      />

      {!runIdBefore || !runIdAfter || runIdBefore === runIdAfter ? (
        <EmptyState title="Pick two different runs" />
      ) : compare.isPending ? (
        <LoadingState label="Comparing runs…" />
      ) : compare.isError ? (
        <ErrorState error={compare.error} onRetry={() => void compare.refetch()} />
      ) : (
        <CompareView data={compare.data} />
      )}
    </div>
  );
}

function RunPicker({
  runs,
  runIdBefore,
  runIdAfter,
  onChangeBefore,
  onChangeAfter,
}: {
  runs: AnalysisRunOut[];
  runIdBefore: string | undefined;
  runIdAfter: string | undefined;
  onChangeBefore: (id: string) => void;
  onChangeAfter: (id: string) => void;
}) {
  const runLabel = (r: AnalysisRunOut) =>
    `${new Date(r.started_at).toLocaleDateString()} (${r.head_sha.slice(0, 7)})`;

  return (
    <Card title="Compare runs">
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <label className="flex items-center gap-2">
          <span className="text-slate-500 dark:text-slate-400">From</span>
          <select
            value={runIdBefore ?? ""}
            onChange={(e) => onChangeBefore(e.target.value)}
            className="rounded-md border border-slate-200 bg-white px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-900"
          >
            {runs.map((r) => (
              <option key={r.id} value={r.id}>
                {runLabel(r)}
              </option>
            ))}
          </select>
        </label>
        <span className="text-slate-400">→</span>
        <label className="flex items-center gap-2">
          <span className="text-slate-500 dark:text-slate-400">To</span>
          <select
            value={runIdAfter ?? ""}
            onChange={(e) => onChangeAfter(e.target.value)}
            className="rounded-md border border-slate-200 bg-white px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-900"
          >
            {runs.map((r) => (
              <option key={r.id} value={r.id}>
                {runLabel(r)}
              </option>
            ))}
          </select>
        </label>
      </div>
    </Card>
  );
}

function CompareView({ data }: { data: CompareResponse }) {
  return (
    <div className="flex flex-col gap-4">
      {data.engine_version_differs ? (
        <div className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-300">
          These two runs used different engine versions ({data.engine_version_before} →{" "}
          {data.engine_version_after}). A prior session changed how an input is measured (e.g.
          churn) -- some movement below may reflect that measurement change rather than a real
          change in the code.
        </div>
      ) : null}

      <HeadlineStrip data={data} />

      <div className="grid gap-4 lg:grid-cols-3">
        <FindingsColumn
          title="Appeared"
          findings={data.findings.appeared}
          total={data.findings.appeared_total}
          tone="worsened"
        />
        <FindingsColumn
          title="Resolved"
          findings={data.findings.resolved}
          total={data.findings.resolved_total}
          tone="improved"
        />
        <FindingsColumn
          title="Persisted"
          findings={data.findings.persisted}
          total={data.findings.persisted_total}
          tone="neutral"
        />
      </div>

      <RiskMoversTable worsened={data.risk_movers_worsened} improved={data.risk_movers_improved} />

      <div className="grid gap-4 lg:grid-cols-2">
        <SubsystemChanges changes={data.subsystem_changes} />
        <ContributorChanges changes={data.contributor_changes} />
      </div>

      <CouplingChanges changes={data.coupling_changes} />

      <SecurityDiff data={data} />
    </div>
  );
}

// --- Headline delta strip -----------------------------------------------------

function HeadlineStrip({ data }: { data: CompareResponse }) {
  return (
    <Card title="Since last run">
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
        {data.headline.map((item) => {
          const direction = headlineDirection(item);
          return (
            <div key={item.metric} className="flex flex-col gap-0.5">
              <span className="text-xs text-slate-500 dark:text-slate-400">{item.label}</span>
              <span
                className={`text-lg font-semibold tabular-nums ${DIRECTION_TEXT_CLASS[direction]}`}
              >
                {item.delta === null ? "—" : formatSignedDelta(item.delta)}
              </span>
              <span className="text-[11px] text-slate-400 dark:text-slate-500">
                {item.before?.toLocaleString() ?? "—"} → {item.after?.toLocaleString() ?? "—"}
              </span>
            </div>
          );
        })}
      </div>
    </Card>
  );
}

// --- Findings appeared / resolved / persisted ---------------------------------

function FindingsColumn({
  title,
  findings,
  total,
  tone,
}: {
  title: string;
  findings: CompareFindingOut[];
  total: number;
  tone: "improved" | "worsened" | "neutral";
}) {
  return (
    <Card
      title={`${title} (${total})`}
      className={tone === "worsened" ? "ring-1 ring-red-200 dark:ring-red-500/20" : ""}
    >
      {findings.length === 0 ? (
        <p className="text-sm text-slate-400 dark:text-slate-500">None.</p>
      ) : (
        <ul className="flex flex-col divide-y divide-slate-100 dark:divide-slate-800">
          {findings.map((f) => (
            <li key={f.signature} className="flex flex-col gap-1 py-2">
              <div className="flex items-center gap-2">
                <SeverityChip severity={f.severity} />
                <span className="truncate text-sm text-slate-700 dark:text-slate-200">
                  {f.title}
                </span>
              </div>
              {f.file_path ? (
                <span className="truncate font-mono text-xs text-slate-400 dark:text-slate-500">
                  {f.file_path}
                </span>
              ) : null}
            </li>
          ))}
        </ul>
      )}
      {total > findings.length ? (
        <p className="mt-2 text-xs text-slate-400 dark:text-slate-500">
          Showing {findings.length} of {total}.
        </p>
      ) : null}
    </Card>
  );
}

// --- Risk movers ----------------------------------------------------------------

function RiskMoversTable({
  worsened,
  improved,
}: {
  worsened: RiskMoverOut[];
  improved: RiskMoverOut[];
}) {
  const rows = [
    ...worsened.map((m) => ({ ...m, tone: "worsened" as const })),
    ...improved.map((m) => ({ ...m, tone: "improved" as const })),
  ];

  return (
    <Card
      title="Risk movers"
      subtitle="Files whose hotspot rank moved the most in either direction"
    >
      {rows.length === 0 ? (
        <p className="text-sm text-slate-400 dark:text-slate-500">
          No file's rank moved meaningfully.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="text-xs uppercase tracking-wide text-slate-400 dark:text-slate-500">
                <th className="pb-2 pr-4 font-medium">File</th>
                <th className="pb-2 pr-4 font-medium">Rank</th>
                <th className="pb-2 pr-4 font-medium">Risk score</th>
                <th className="pb-2 font-medium">Max coupling</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
              {rows.map((m) => (
                <tr key={m.file_path}>
                  <td className="max-w-[260px] truncate py-2 pr-4 font-mono text-xs text-slate-700 dark:text-slate-300">
                    {m.file_path}
                  </td>
                  <td className={`py-2 pr-4 tabular-nums ${DIRECTION_TEXT_CLASS[m.tone]}`}>
                    {m.hotspot_rank_before ?? "—"} → {m.hotspot_rank_after ?? "—"}
                  </td>
                  <td className="py-2 pr-4 tabular-nums text-slate-600 dark:text-slate-300">
                    {(m.risk_score_before ?? 0).toFixed(2)} → {(m.risk_score_after ?? 0).toFixed(2)}
                  </td>
                  <td className="py-2 tabular-nums text-slate-600 dark:text-slate-300">
                    {m.max_coupling_degree_before.toFixed(2)} →{" "}
                    {m.max_coupling_degree_after.toFixed(2)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

// --- Subsystem / contributor / coupling changes --------------------------------

function SubsystemChanges({ changes }: { changes: SubsystemChangeOut[] }) {
  return (
    <Card title="Subsystem changes" subtitle="Matched by membership overlap, not tracked identity">
      {changes.length === 0 ? (
        <p className="text-sm text-slate-400 dark:text-slate-500">
          No subsystem appeared, disappeared, merged, or split.
        </p>
      ) : (
        <ul className="flex flex-col divide-y divide-slate-100 dark:divide-slate-800">
          {changes.map((c, i) => (
            <li key={`${c.kind}-${c.label}-${i}`} className="py-2 text-sm">
              <span className="font-medium text-slate-700 dark:text-slate-200">
                {SUBSYSTEM_CHANGE_COPY[c.kind]()}:
              </span>{" "}
              <span className="text-slate-600 dark:text-slate-300">{c.label}</span>
              <p className="mt-0.5 text-xs text-slate-400 dark:text-slate-500">{c.detail}</p>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function ContributorChanges({ changes }: { changes: ContributorChangeOut[] }) {
  return (
    <Card title="Contributor changes">
      {changes.length === 0 ? (
        <p className="text-sm text-slate-400 dark:text-slate-500">
          No contributor joined, left, or went quiet.
        </p>
      ) : (
        <ul className="flex flex-col gap-1">
          {changes.map((c, i) => (
            <li
              key={`${c.kind}-${c.name}-${i}`}
              className="text-sm text-slate-600 dark:text-slate-300"
            >
              <span className="font-medium text-slate-700 dark:text-slate-200">{c.name}</span>{" "}
              {CONTRIBUTOR_CHANGE_COPY[c.kind]().toLowerCase()}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function CouplingChanges({ changes }: { changes: CouplingChangeOut[] }) {
  return (
    <Card title="Coupling changes">
      {changes.length === 0 ? (
        <p className="text-sm text-slate-400 dark:text-slate-500">
          No coupling pair appeared, strengthened, weakened, or vanished.
        </p>
      ) : (
        <ul className="flex flex-col divide-y divide-slate-100 dark:divide-slate-800">
          {changes.map((c, i) => (
            <li
              key={`${c.kind}-${c.file_a_path}-${c.file_b_path}-${i}`}
              className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm"
            >
              <span className="font-mono text-xs text-slate-600 dark:text-slate-300">
                {c.file_a_path} ↔ {c.file_b_path}
              </span>
              <span className="text-xs text-slate-500 dark:text-slate-400">
                {COUPLING_CHANGE_COPY[c.kind]()}
                {c.coupling_degree_before !== null || c.coupling_degree_after !== null
                  ? ` (${c.coupling_degree_before?.toFixed(2) ?? "—"} → ${c.coupling_degree_after?.toFixed(2) ?? "—"})`
                  : ""}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

// --- Security --------------------------------------------------------------------

function SecurityDiff({ data }: { data: CompareResponse }) {
  return (
    <Card title="Security">
      <div className="flex flex-wrap gap-x-8 gap-y-2 text-sm">
        <span>
          Vulnerabilities introduced:{" "}
          <span className="font-semibold text-red-600 dark:text-red-400">
            {data.security.vulnerabilities_introduced}
          </span>
        </span>
        <span>
          Vulnerabilities remediated:{" "}
          <span className="font-semibold text-emerald-600 dark:text-emerald-400">
            {data.security.vulnerabilities_remediated}
          </span>
        </span>
        <span>
          Secrets introduced (approximate):{" "}
          <span className="font-semibold text-red-600 dark:text-red-400">
            {data.security.secrets_introduced}
          </span>
        </span>
      </div>
      <p className="mt-2 text-xs text-slate-400 dark:text-slate-500">
        {data.security.secrets_caveat}
      </p>
    </Card>
  );
}
