import { useMemo } from "react";
import { useOutletContext } from "react-router-dom";
import { Cell, Legend, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import { useHealth, useRisk } from "../../api/hooks";
import { Card } from "../../components/Card";
import { HeuristicNote } from "../../components/HeuristicNote";
import { ScoreGauge } from "../../components/ScoreGauge";
import { StageGate } from "../../components/StageGate";
import type { RepoOutletContext } from "../RepoLayout";

// Recharts needs explicit color props -- it doesn't read CSS custom
// properties or inherit Tailwind classes (Known Hazard #7). This constant
// is the one place this page's chart colors live, so a future visual-
// identity pass (session 15) has a single spot to change them.
const LANGUAGE_COLORS = [
  "#6366f1",
  "#0ea5e9",
  "#10b981",
  "#f59e0b",
  "#ec4899",
  "#8b5cf6",
  "#64748b",
];

export function HealthPage() {
  const { repo, share } = useOutletContext<RepoOutletContext>();
  const health = useHealth(repo.id, share);
  const risk = useRisk(repo.id, share);

  const riskData = risk.data?.kind === "data" ? risk.data.data : undefined;

  const languageMix = useMemo(() => {
    if (!riskData) return [];
    const counts = new Map<string, number>();
    for (const file of riskData.files) {
      counts.set(file.language, (counts.get(file.language) ?? 0) + 1);
    }
    return [...counts.entries()]
      .map(([name, value]) => ({ name, value }))
      .sort((a, b) => b.value - a.value);
  }, [riskData]);

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
      <Card
        title="Health score"
        subtitle="Composite of risk, cycles, and hidden dependencies"
        className="lg:col-span-1"
      >
        <StageGate query={health} loadingLabel="Computing health…">
          {(data) => (
            <div className="flex flex-col items-center gap-4">
              <ScoreGauge score={data.score} />
              <HeuristicNote message="Heuristic score — not yet corpus-calibrated. Weights are documented, literature-informed defaults (see master-context.md §8.1), not a statistically fitted model." />
              <dl className="grid w-full grid-cols-3 gap-2 text-center text-xs">
                <div>
                  <dt className="text-slate-400 dark:text-slate-500">High-risk files</dt>
                  <dd className="font-medium text-slate-700 dark:text-slate-200">
                    {Math.round(data.high_risk_ratio * 100)}%
                  </dd>
                </div>
                <div>
                  <dt className="text-slate-400 dark:text-slate-500">Cycles</dt>
                  <dd className="font-medium text-slate-700 dark:text-slate-200">
                    {data.cycle_count}
                  </dd>
                </div>
                <div>
                  <dt className="text-slate-400 dark:text-slate-500">Hidden deps</dt>
                  <dd className="font-medium text-slate-700 dark:text-slate-200">
                    {data.hidden_dependency_count}
                  </dd>
                </div>
              </dl>
            </div>
          )}
        </StageGate>
      </Card>

      <Card title="Repo vitals" className="lg:col-span-2">
        <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
          <dl className="grid grid-cols-2 gap-4 text-sm">
            <div>
              <dt className="text-slate-400 dark:text-slate-500">Commits analyzed</dt>
              <dd className="text-xl font-semibold text-slate-900 dark:text-slate-100">
                {repo.commit_count}
              </dd>
            </div>
            <div>
              <dt className="text-slate-400 dark:text-slate-500">Files</dt>
              <dd className="text-xl font-semibold text-slate-900 dark:text-slate-100">
                {repo.file_count}
              </dd>
            </div>
            <div>
              <dt className="text-slate-400 dark:text-slate-500">Default branch</dt>
              <dd className="text-sm font-medium text-slate-700 dark:text-slate-200">
                {repo.default_branch ?? "—"}
              </dd>
            </div>
            <div>
              <dt className="text-slate-400 dark:text-slate-500">Last analyzed</dt>
              <dd className="text-sm font-medium text-slate-700 dark:text-slate-200">
                {repo.analyzed_at ? new Date(repo.analyzed_at).toLocaleString() : "—"}
              </dd>
            </div>
          </dl>
          <div className="h-40">
            <StageGate
              query={risk}
              loadingLabel="Loading language mix…"
              emptyTitle="No language data"
              isEmpty={() => languageMix.length === 0}
            >
              {() => (
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie
                      data={languageMix}
                      dataKey="value"
                      nameKey="name"
                      innerRadius={32}
                      outerRadius={56}
                      paddingAngle={2}
                    >
                      {languageMix.map((entry, i) => (
                        <Cell key={entry.name} fill={LANGUAGE_COLORS[i % LANGUAGE_COLORS.length]} />
                      ))}
                    </Pie>
                    <Tooltip formatter={(value, name) => [`${value} files`, String(name)]} />
                    <Legend
                      verticalAlign="middle"
                      align="right"
                      layout="vertical"
                      iconSize={8}
                      wrapperStyle={{ fontSize: 12 }}
                    />
                  </PieChart>
                </ResponsiveContainer>
              )}
            </StageGate>
          </div>
        </div>
      </Card>
    </div>
  );
}
