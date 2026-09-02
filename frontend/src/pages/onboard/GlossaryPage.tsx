import { useState } from "react";
import { Link, useOutletContext } from "react-router-dom";
import { useGlossary } from "../../api/hooks";
import type { GlossaryTermOut } from "../../api/types";
import { Card } from "../../components/Card";
import { StageGate } from "../../components/StageGate";
import type { RepoOutletContext } from "../RepoLayout";

/** Part F. The honesty note is the point of this page as much as the term
 * list is -- it sits above the list, unconditionally, not as a footnote
 * (Compass identifies the codebase's own vocabulary and shows where it's
 * defined; it does not claim to know what any term means). */
export function GlossaryPage() {
  const { repo, share } = useOutletContext<RepoOutletContext>();
  const glossary = useGlossary(repo.id, share);

  return (
    <StageGate
      query={glossary}
      loadingLabel="Extracting domain vocabulary…"
      emptyTitle="No terms extracted"
      emptyMessage="Not enough named symbols or file stems were found to build a glossary."
      isEmpty={(data) => data.terms.length === 0}
    >
      {(data) => (
        <div className="flex flex-col gap-4">
          <p className="rounded-md bg-amber-50 px-4 py-3 text-sm text-amber-800 dark:bg-amber-500/10 dark:text-amber-300">
            {data.limitation}
          </p>
          <Card
            title="Domain vocabulary"
            subtitle={`${data.terms.length} term${data.terms.length === 1 ? "" : "s"}, ranked by how much this codebase revolves around them`}
          >
            <ul className="flex flex-col divide-y divide-slate-100 dark:divide-slate-800">
              {data.terms.map((term) => (
                <GlossaryTermRow key={term.term} term={term} repoId={repo.id} />
              ))}
            </ul>
          </Card>
        </div>
      )}
    </StageGate>
  );
}

function GlossaryTermRow({ term, repoId }: { term: GlossaryTermOut; repoId: string }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <li className="py-2.5">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full flex-wrap items-center gap-3 text-left"
      >
        <span className="font-mono text-sm font-medium text-ink">{term.term}</span>
        <span className="text-xs text-ink-faint">
          {term.occurrences} occurrence{term.occurrences === 1 ? "" : "s"}
        </span>
        <span className="text-xs text-ink-faint">
          spans {term.subsystem_spread} subsystem{term.subsystem_spread === 1 ? "" : "s"}
        </span>
        {term.defining_paths.length > 0 ? (
          <span className="text-xs font-medium text-indigo-600 dark:text-indigo-400">
            {expanded ? "Hide" : "Show"} {term.defining_paths.length} defining file
            {term.defining_paths.length === 1 ? "" : "s"}
          </span>
        ) : null}
      </button>

      {expanded && term.defining_paths.length > 0 ? (
        <ul className="mt-1.5 ml-1 flex flex-col gap-1">
          {term.defining_paths.map((path) => (
            <li key={path}>
              <Link
                to={`/repos/${repoId}/onboard/people?path=${encodeURIComponent(path)}`}
                className="font-mono text-xs text-ink-muted hover:text-indigo-600 hover:underline dark:hover:text-indigo-400"
              >
                {path}
              </Link>
            </li>
          ))}
        </ul>
      ) : null}
    </li>
  );
}
