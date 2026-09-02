import { useOutletContext } from "react-router-dom";
import { useBenchmark } from "../../api/hooks";
import { Card } from "../../components/Card";
import { StageGate } from "../../components/StageGate";
import { formatScore } from "../../lib/format";
import type { BenchmarkResponse } from "../../api/types";
import type { RepoOutletContext } from "../RepoLayout";

const CORPUS_REPOS_URL =
  "https://github.com/search?q=repo%3Acompass+path%3Aapp%2Fbaseline%2Fcorpus_repos.yaml";
// A generic, safe fallback link (a repo-agnostic search) since this
// frontend doesn't know its own backend repository's GitHub URL at build
// time; deployments that fork this project should point this at their own
// repo's corpus_repos.yaml. Session 14, Part E: "a link to the checked-in
// corpus_repos.yaml on GitHub."

function MetricBar({ metric }: { metric: BenchmarkResponse["metrics"][number] }) {
  const pct = Math.round(metric.percentile * 100);
  return (
    <div>
      <div className="mb-1 flex items-center justify-between gap-2 text-xs">
        <span className="text-slate-700 dark:text-slate-300">{metric.metric}</span>
        <span className="flex items-center gap-2 tabular-nums text-slate-400 dark:text-slate-500">
          {formatScore(metric.value, 2)} · p{pct}
          {metric.widened ? (
            <span className="rounded-full bg-amber-100 px-1.5 py-0.5 text-[10px] font-medium text-amber-700 dark:bg-amber-500/20 dark:text-amber-400">
              widened
            </span>
          ) : null}
          <span className="text-slate-300 dark:text-slate-600">
            n={metric.n_repos} repos / {metric.n_files} files
          </span>
        </span>
      </div>
      <div className="h-2 w-full rounded-full bg-slate-100 dark:bg-slate-800">
        <div className="h-2 rounded-full bg-indigo-500" style={{ width: `${Math.max(2, pct)}%` }} />
      </div>
    </div>
  );
}

export function BenchmarkPage() {
  const { repo, share } = useOutletContext<RepoOutletContext>();
  const benchmark = useBenchmark(repo.id, share);

  return (
    <StageGate
      query={benchmark}
      loadingLabel="Comparing against the corpus…"
      emptyTitle="No corpus data yet"
      emptyMessage="No comparable repositories exist for this language/size combination yet."
      isEmpty={(data: BenchmarkResponse) => data.metrics.every((m) => m.n_repos === 0)}
    >
      {(data) => (
        <div className="flex flex-col gap-4">
          <Card
            title="Compared against the curated corpus"
            subtitle={`${data.dominant_language} · ${data.size_bucket} repositories`}
          >
            <p className="mb-4 text-xs text-slate-500 dark:text-slate-400">{data.corpus_note}</p>
            <div className="flex flex-col gap-3">
              {data.metrics.map((m) => (
                <MetricBar key={m.metric} metric={m} />
              ))}
            </div>
            <p className="mt-4 text-xs text-slate-400 dark:text-slate-500">
              A metric with <code>n_repos=0</code> has no corpus data for this language/size cell
              yet -- its bar shows a heuristic fallback position, not a real percentile. A{" "}
              <span className="rounded-full bg-amber-100 px-1.5 py-0.5 text-[10px] font-medium text-amber-700 dark:bg-amber-500/20 dark:text-amber-400">
                widened
              </span>{" "}
              badge means the comparison dropped the size bucket (or the language) because the exact
              cell had too few repositories to answer honestly.
            </p>
            <a
              href={CORPUS_REPOS_URL}
              target="_blank"
              rel="noreferrer"
              className="mt-3 inline-block text-xs text-indigo-600 hover:underline dark:text-indigo-400"
            >
              See the exact repository list this corpus comes from →
            </a>
          </Card>
        </div>
      )}
    </StageGate>
  );
}
