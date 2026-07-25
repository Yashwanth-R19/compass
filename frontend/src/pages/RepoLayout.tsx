import { NavLink, Outlet, useParams } from "react-router-dom";
import { useRepo } from "../api/hooks";
import { LoadingState } from "../components/LoadingState";
import { ErrorState } from "../components/ErrorState";
import { EmptyState } from "../components/EmptyState";
import type { RepoOut } from "../api/types";

const TABS = [
  { to: "overview", label: "Overview" },
  { to: "coupling", label: "Coupling" },
  { to: "architecture", label: "Architecture" },
  { to: "risk", label: "Risk" },
];

const STATUS_LABEL: Record<string, string> = {
  pending: "Queued",
  mining: "Mining commit history…",
  analyzing: "Running analysis…",
  ready: "Ready",
  failed: "Failed",
};

export type RepoOutletContext = { repo: RepoOut };

export function RepoLayout() {
  const { repoId } = useParams<{ repoId: string }>();
  const { data: repo, isPending, isError, error, refetch } = useRepo(repoId);

  if (isPending) return <LoadingState label="Loading repo…" />;
  if (isError) return <ErrorState error={error} onRetry={() => void refetch()} />;

  const tabClass = ({ isActive }: { isActive: boolean }) =>
    `border-b-2 px-1 py-2.5 text-sm font-medium transition-colors ${
      isActive
        ? "border-indigo-600 text-indigo-600 dark:border-indigo-400 dark:text-indigo-400"
        : "border-transparent text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200"
    }`;

  return (
    <div className="flex flex-col gap-6">
      <div>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
              {repo.owner}/{repo.name}
            </h1>
            <a
              href={repo.url}
              target="_blank"
              rel="noreferrer"
              className="text-xs text-slate-500 hover:underline dark:text-slate-400"
            >
              {repo.url}
            </a>
          </div>
          <span
            className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium ${
              repo.status === "ready"
                ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-400"
                : repo.status === "failed"
                  ? "bg-red-100 text-red-700 dark:bg-red-500/10 dark:text-red-400"
                  : "bg-indigo-100 text-indigo-700 dark:bg-indigo-500/10 dark:text-indigo-400"
            }`}
          >
            {STATUS_LABEL[repo.status] ?? repo.status}
          </span>
        </div>
        {repo.status === "ready" ? (
          <nav className="mt-4 flex gap-5 border-b border-slate-200 dark:border-slate-800">
            {TABS.map((tab) => (
              <NavLink key={tab.to} to={tab.to} className={tabClass}>
                {tab.label}
              </NavLink>
            ))}
          </nav>
        ) : null}
      </div>

      {repo.status === "ready" ? (
        <Outlet context={{ repo } satisfies RepoOutletContext} />
      ) : repo.status === "failed" ? (
        <EmptyState
          title="Analysis failed"
          message="Something went wrong while analyzing this repo. Try submitting it again from the home page."
        />
      ) : (
        <LoadingState label={STATUS_LABEL[repo.status] ?? "Working…"} />
      )}
    </div>
  );
}
